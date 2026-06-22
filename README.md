# Agentic Pay Zone Identification in Well Logs

A from-scratch pipeline that ingests raw, unconditioned LAS well logs and
produces a complete petrophysical suite (`VSH`, `PHIT`, `PHIE`, `SW`,
`PERM`, `PAY_FLAG`) per well, screening out "honeypot" wells whose raw
measurements contain baked-in physics violations along the way.

This is v1 of an iterative submission: the pipeline runs cleanly end to end
on all 800 wells, but the cutoffs and honeypot threshold below are
calibratable against daily leaderboard feedback (5 submissions/day x 14
days). See **Status & Next Steps** at the bottom for what's tuned vs. what's
still a reasonable first guess.

## Quick start

```bash
pip install -r requirements.txt   # numpy only
python run_pipeline.py --input-dir <raw_las_dir> --output-dir submission --report docs/qc_report.json
```

Output: one `.las` file per input well in `submission/`, containing
`DEPTH, VSH, PHIT, PHIE, SW, PERM, PAY_FLAG`, plus a JSON QC report with
per-well honeypot scores, gate scores, and curve-source provenance.

## Architecture: the agentic workflow

The pipeline is organized as a sequence of discrete, auditable decision
stages rather than one opaque model -- each stage has a clear
input/output/provenance trail, which is what "agentic" means here in
practice (see `SKILL.md` for the workflow spec an agent follows):

```
raw LAS file
   |
   v
[1] Ingest & parse        src/las_io.py     -- dependency-free LAS 2.0 reader
   |                                            handling ragged rows, mixed
   |                                            NULL conventions, etc.
   v
[2] Resolve mnemonics      src/mnemonics.py  -- maps 217 observed raw mnemonic
   |                                            variants onto canonical roles
   |                                            (GR, RHOB, NPHI, PEF, DT,
   |                                            RES_DEEP/MED/SHAL, CALI, SP),
   |                                            with full alias provenance
   |                                            and unit normalization.
   v
[3] Petrophysics calc      src/petrophysics.py -- VSH, PHIT, PHIE, SW, PERM
   |
   v
[4] Honeypot screen        src/honeypot.py   -- evaluates raw-curve physics
   |                                            violations inside the
   |                                            candidate-pay interval; if
   |                                            evidence is strong, the
   |                                            whole well's pay is zeroed.
   v
[5] Finalize PAY_FLAG      src/pay.py        -- standard clastic cutoffs,
   |                                            applied post-honeypot-screen.
   v
[6] Internal gate QC       src/gates.py      -- 25 physics/bounds/consistency
   |                                            checks restricted to the 7
   |                                            submitted columns, scored per
   |                                            well, for our own audit.
   v
[7] Export LAS             src/pipeline.py::write_result
```

`run_pipeline.py` is the CLI that drives stage 1-7 across every well in an
input directory and writes a JSON summary.

## Data audit (what we found before writing any petrophysics)

Before touching cutoffs or formulas, we surveyed all 800 raw LAS files
(`docs/qc_report.json` / the original survey script). Key findings that
shaped the design:

- **217 distinct curve mnemonics** across 800 wells, reflecting different
  acquisition vintages (e.g. gamma ray alone appears as `GR`, `SGR`,
  `ECGR`, `CGR`, `HSGR`, `GRD`, `GR1`, ... 24 variants). This is why
  `mnemonics.py` exists as its own module with explicit alias tables and
  a documented fallback heuristic, instead of hardcoding `GR`/`RHOB`/etc.
  directly in the calc code.
- **NULL convention is consistent**: `-999.25` in 799/800 wells (one used
  a different STEP but the same NULL). We rely on this but also treat
  literal NaNs defensively.
- **STEP is 0.5 ft** in 799/800 wells.
- **9-22 curves per well** (mean 13.4) -- no well has every curve type;
  the pipeline must degrade gracefully (e.g. density-derived porosity with
  a sonic fallback, deep-resistivity Rt with a shallow-resistivity
  fallback) rather than assuming a fixed curve set.
- Several wells carry **drilling/trajectory channels** (`WOB`, `TORQ`,
  `ROP`, `RPM`, `TENS`, `HAZI`, `DEVI`, `ECD`, `PRES`) mixed in with log
  curves. These are explicitly blocklisted in `mnemonics.py` so they're
  never mistaken for a petrophysical curve by a substring-matching
  fallback (e.g. `TENS` vs `DENS`).

## Petrophysical methodology

All formulas are textbook clastic-reservoir methods (no proprietary
models), matching the challenge's statement that the answer key "uses
standard petrophysical cutoffs for pay in a clastic reservoir":

| Curve | Method | Notes |
|---|---|---|
| `VSH` | Larionov (older rocks): `VSH = 0.33*(2^(2*IGR)-1)` | `IGR` normalized per-well using robust 2nd/98th percentile GR min/max (resists single-sample spikes) |
| `PHIT` | Density porosity `(RHOB_ma - RHOB)/(RHOB_ma - RHOB_fl)`, `RHOB_ma=2.65`, `RHOB_fl=1.0` | Merged **per depth sample** with Wyllie time-average sonic porosity, then raw neutron porosity, in priority order (`pp.merge_per_sample`) -- not a whole-well source choice, see below |
| `PHIE` | `PHIT * (1 - VSH)`, clipped to `<= PHIT` | Falls back to `PHIT` if no GR/VSH available |
| `SW` | Archie: `SW = (a*Rw / (PHIE^m * Rt))^(1/n)`, `a=1, m=2, n=2` | `Rw` estimated per-well via the apparent-Rw (Rwa) method on the cleanest/highest-porosity samples (no Rw catalog or SP-based salinity was provided); `Rt` merged **per depth sample** across deep/medium/shallow resistivity in priority order |
| `PERM` | Timur (1968): `k = 0.136 * PHIE^4.4 / Swirr^2`, using computed `SW` as the `Swirr` proxy | Deliberately couples PHIE, SW, and PERM through one transform, since the grading explicitly treats them as physically linked, not independent outputs |

**Pay cutoffs** (`src/pay.py`): `VSH <= 0.40`, `PHIE >= 0.08`, `SW <= 0.50`
-- standard clastic-reservoir defaults.

### Bad-hole mitigation (`pp.detect_bad_hole`, wired into `pipeline.py`)

The challenge prompt pointed to
[github.com/ttracx/oil-and-gas-claude-skills](https://github.com/ttracx/oil-and-gas-claude-skills)
for ideas. Most of that repo is a multi-domain (drilling/completions/
production/HSE) extraction-agent library that doesn't apply here, and its
petrophysics skill (`skills/well_log_interpreter`) is a spec, not runnable
code, describing the same textbook formulas we already had. The one
concrete, useful idea we adopted: that skill calls out flagging washed-out
("bad hole") intervals from caliper excursions as a data-quality issue.

We went one step further than just flagging it. No bit-size curve exists
anywhere in this dataset, so `detect_bad_hole()` uses each well's own
median `CALI` reading as a proxy nominal hole size and flags samples where
caliper exceeds it by more than 2 inches. In flagged intervals the density
tool loses pad contact, so `RHOB` (and therefore density-derived `PHIT`)
reads unreliably there specifically -- not elsewhere in the same well.
`pipeline.py` now swaps in sonic- or neutron-derived porosity *per sample*
inside those intervals instead of trusting density everywhere just because
the well has a `RHOB` curve. On the full 800-well run this corrected 2,145
samples across 27 wells; tracked per well as `bad_hole_frac` /
`phit_mitigated_samples` in `docs/qc_report.json` for auditability.

### Per-sample curve merging (`pp.merge_per_sample`, wired into `pipeline.py`)

Axis 1 fails a gate at any depth sample where the relevant curve is NaN
("if a computed curve exists but is 100% NaN, that's a failed gate" --
the same logic applies partially: a NaN sample fails every gate touching
it). The original pipeline picked **one source curve for the whole well**
for `PHIT` (density, else sonic, else neutron) and `RT` (deep, else
medium, else shallow resistivity). That's wasteful when a well's coverage
is genuinely complementary rather than redundant -- e.g. density logged
100-150ft, sonic logged 150-300ft -- because picking density for the
whole well leaves 150-300ft as NaN even though sonic could have filled it.

`pp.merge_per_sample()` instead merges every available candidate curve
**sample-by-sample** in priority order (density > sonic > neutron for
porosity; deep > medium > shallow for resistivity), falling back only at
the individual depths where the preferred curve is actually missing.
Checked across the full dataset before implementing: 566/799 wells gain
real (not fabricated) `PHIT` coverage this way (avg +4.4 points where it
helps), and 530/797 gain `RT` coverage (avg +8.0 points). On the full run
this raised mean internal gate score from 89.6 to **90.7/100**, raised
wells-with-pay from 482 to 522, and is a genuine accuracy improvement (752
of 800 output `.las` files changed) -- not just a QC-methodology change,
so `submission/` and `las_submission_v2.zip` were rebuilt. Bad-hole
mitigation (above) now runs after this merge and can still override a
density-sourced sample inside a washed-out interval with sonic/neutron,
even when density wasn't NaN there.

## Honeypot detection (`src/honeypot.py`)

The challenge plants two different kinds of "fake pay": (a) ordinary tight/
wet intervals inside otherwise-real wells that a naive cutoff might
mis-flag (handled by the cutoffs above doing their job correctly), and (b)
whole wells where the **raw measurements themselves are physically
inconsistent** ("digital potholes... physics violations baked into the raw
measurements"). Axis 3 scores (b) as a binary per-well catch/miss with a
squared penalty for misses, and flagging *zero* pay everywhere scores zero
overall (geometric mean), so naive "always reject" is not a viable
strategy -- the detector has to be evidence-based.

We score three independent evidence channels over each well's
candidate-pay interval (post-cutoff, pre-honeypot-screen):

1. **Raw bounds violations** -- fraction of samples where `RHOB`, `NPHI`,
   `PEF`, `DT`, or `CALI` sit outside what's physically possible for
   sedimentary rock (not just "unusual" -- impossible, e.g. `RHOB < 0.9`).
2. **Cross-method porosity disagreement** -- density-, neutron-, and
   sonic-derived porosity estimates for the same rock should roughly agree;
   systematic disagreement > 0.15 v/v across the interval indicates at
   least one curve was fabricated/corrupted.
3. **Pre-clip Archie blow-up** -- `SW` computed from raw `Rt`/`PHIE` before
   any clipping comes out far outside `[0,1]`, which can only happen if the
   resistivity/porosity pairing isn't physically consistent rock.

A weighted combination (`0.45/0.35/0.20`) above `0.30` flags the well as a
honeypot; its `PAY_FLAG` is zeroed everywhere, but `VSH/PHIT/PHIE/SW/PERM`
are still computed and submitted normally (zeroing those too would tank
Axis 1 gate compliance for no benefit -- "submitting only GR + DEPTH +
PAY_FLAG is not a petrophysical submission").

On the full 800-well set, this flags **202 wells (25.2%)** as honeypots --
close to the stated 25% true honeypot rate, which is an encouraging
internal signal but **not** a substitute for actual leaderboard feedback
(we have no way to confirm precision/recall against the true labels
locally).

## Scoring formulas

The exact official formulas (final score `S` and all four axes `A1-A4`,
with notation) are transcribed verbatim in `docs/scoring.md`, alongside a
note on one real ambiguity in the Axis-1 text (whether a gate's pass/fail
is per-well-binary or a continuous fraction across depth samples -- we
implement the continuous/more forgiving reading) and an open question on
whether `PERM` should be submitted as linear mD or `log10(k)` (we currently
submit linear mD; `docs/scoring.md` explains the reasoning and how to test
the alternative).

`src/scoring_sim.py` is a small reference implementation of those formulas
used to sanity-check our reading of the spec and to reason about observed
leaderboard scores. It reproduces the challenge's own worked examples
exactly (missing 3/30 honeypots -> `A3=81`, a 19-point cost; missing
10/30 -> `A3=44.4`). Run `python3 -m src.scoring_sim` to see this plus a
back-of-envelope diagnosis of any observed composite score: given our
internal `A1` estimate (90.7, see below) and an observed leaderboard score
of 21.4 from submission v1, `A2 * A3 * A4` must equal roughly `2312`, i.e.
if the three were all comparably weak, each is sitting around `~13/100` --
meaning the v1 cutoffs/Rw estimate/honeypot threshold are likely all
under-calibrated, not just one of them. The next submission should target
whichever real axis breakdown comes back weakest (the leaderboard UI did
not surface a per-axis breakdown as of this writing -- worth checking
again after clicking into the submission row, or via Discussion/support).

## Internal gate QC (`src/gates.py`)

The challenge's exact 25 gates aren't disclosed by design, but one thing
*is* certain: the real grader can only gate-check what's actually inside
the submitted LAS file. We submit exactly 7 columns -- `DEPTH, VSH, PHIT,
PHIE, SW, PERM, PAY_FLAG` -- and nothing else ever leaves the pipeline. So
`build_gates()` is now restricted to checks expressible purely in terms of
those 7 columns: per-curve bounds (`phit_0_1`, `sw_0_1`, ...), per-curve
completeness (`*_finite`), cross-curve consistency among submitted curves
(`phie_le_phit`, `sw_phie_le_phit`, `perm_zero_when_no_porosity`,
`no_pay_at_full_sw`, `no_pay_without_porosity`, `no_pay_at_near_pure_shale`,
`no_pay_with_missing_inputs`, `phie_consistent_with_vsh_phit`), and
structural integrity (`depth_monotonic`, `depth_step_consistent`,
`depth_coverage_complete`, `all_required_curves_present`) -- 25 named
gates in total.

The previous version of this file also scored raw input curves (`GR`,
`RHOB`, `NPHI`, `DT`, `CALI`, `RT`) as if they were gated, which can't be
right -- those curves are internal to our pipeline and never reach the
grader, and gating on them would unfairly penalize honeypot wells whose
raw measurements are *deliberately* broken by the challenge design (that's
Axis 3's job, not Axis 1's). Those checks are now kept separately as
`build_diagnostic_gates()` -- excluded from the A1 estimate, used only as
our own pipeline-bug detector.

Current full-dataset run with the corrected, submission-scoped gate set
*and* per-sample curve merging (see below): **mean internal gate score
90.7/100** (up from 83.3/100 under the original over-broad gate set that
also scored raw curves the grader never sees, then 89.6/100 after fixing
that scope, then 90.7/100 after closing complementary-coverage gaps in
`PHIT`/`RT`). Min 53.8/100 (worst wells are ones with very sparse logging
coverage *everywhere* -- e.g. RHOB, DT, and NPHI all simultaneously
covering <5% of the logged interval, confirmed by direct inspection to be
a genuine data-completeness ceiling, not a gates.py bug or a merge-logic
gap). The separate raw-curve diagnostic score sits at 72.6/100, expected
to run lower since honeypot wells' intentionally-corrupted raw
measurements show up here correctly (that's the diagnostic pass's job).
This remains a regression guard during iteration, not a prediction of the
actual leaderboard score.

## Reproducing results end to end

```bash
git clone <this repo>
cd "Agentic Pay Zone Identification in Well Logs"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_pipeline.py \
    --input-dir /path/to/raw_las_wells \
    --output-dir submission \
    --report docs/qc_report.json
```

No training step, no model checkpoints, no GPU -- the pipeline is a
deterministic, rule-based petrophysical workflow, so "reproduction" is
just re-running it. Runtime: ~6 seconds for all 800 wells on a single CPU
core.

## Repository layout

```
src/
  las_io.py        LAS 2.0 reader/writer (no external deps)
  mnemonics.py      raw-mnemonic -> canonical-curve resolver
  petrophysics.py   VSH / PHIT / PHIE / SW / PERM formulas
  gates.py          25 submission-scoped gates (A1 proxy) + raw-curve diagnostics
  honeypot.py       raw-curve physics-violation detector
  pay.py            cutoff-based PAY_FLAG logic
  pipeline.py        per-well orchestration + LAS export
  scoring_sim.py     reference impl of official scoring formulas (diagnostic)
run_pipeline.py      CLI entrypoint (batch driver)
docs/
  qc_report.json     full per-well QC summary from the latest run
  scoring.md          official scoring formulas, transcribed verbatim
SKILL.md             agent-workflow skill spec used to drive this build
requirements.txt
LICENSE
```

## Model / harness disclosure

This pipeline itself is pure deterministic Python (numpy) -- no LLM is
called at inference time. The pipeline's *design and code* were produced
by Claude (Claude Sonnet 4.6) operating in Anthropic's Cowork agent
harness, working from the raw LAS files directly (data survey -> module
design -> implementation -> full-dataset validation), per the workflow
documented in `SKILL.md`.

## Status & next steps

What's implemented and validated:
- End-to-end run across all 800 wells with zero crashes/exceptions.
- Every well has all 6 required curves populated (no well submits a fully-
  NaN curve or skips a curve entirely).
- Honeypot rejection rate (25.2% as of the latest run) tracks the
  disclosed true rate (25%) reasonably closely as an internal sanity
  check.
- Bad-hole (washed-out caliper) intervals no longer feed unreliable density
  porosity into PHIT/PHIE/SW/PERM -- per-sample sonic/neutron fallback
  added, idea adapted from the linked `oil-and-gas-claude-skills` repo (see
  "Bad-hole mitigation" above). ~2,100 samples across 27 wells affected.
- `src/gates.py` rewritten to score only the 7 columns we actually submit
  (the real grader can't check curves that never leave the pipeline);
  raw-curve checks moved to a separate, excluded-from-A1 diagnostic pass.
  This alone raised the mean internal gate score 83.3 -> 89.6/100 (output
  curves unchanged -- a QC-methodology fix, not a petrophysics change).
- `PHIT` and `RT` now merge every available candidate curve **per depth
  sample** in priority order (`pp.merge_per_sample`) instead of picking
  one source curve for the whole well -- closes genuinely complementary
  (not redundant) coverage gaps, since a NaN sample fails every Axis-1
  gate that touches it. This is a real accuracy change (752/800 output
  files differ, wells-with-pay 482 -> 522), raising mean internal gate
  score 89.6 -> **90.7/100**. `submission/` and `las_submission_v2.zip`
  were rebuilt to reflect it.

What's a reasonable first guess but **not yet calibrated against actual
leaderboard feedback** (the only ground truth available):
- The honeypot threshold (`0.30`) and channel weights (`0.45/0.35/0.20`)
  in `honeypot.py` -- precision/recall against true honeypot labels is
  unknown until we see Axis 3 score.
- The `Rw` estimation method (`estimate_rw` in `petrophysics.py`) is a
  field heuristic (Rwa on the cleanest interval), not validated against
  any water-resistivity ground truth -- this is the single biggest lever
  on `SW` (and therefore `PERM`) accuracy (Axis 4).
- Matrix/fluid constants (`RHO_MATRIX=2.65`, `DT_MATRIX=55.5`, etc.) assume
  a clean sandstone matrix; if any wells are actually carbonate-dominated
  this will bias `PHIT` for those wells specifically.
- Pay cutoffs (`VSH<=0.40, PHIE>=0.08, SW<=0.50`) are standard defaults,
  not fit to this dataset's answer key.

Recommended iteration loop for the remaining submissions: submit this v1,
read back the four axis sub-scores, and prioritize whichever axis is
weakest (Axis 3 -> retune honeypot thresholds; Axis 4 -> retune Rw/PERM
transform; Axis 2 -> retune pay cutoffs; Axis 1 -> check `docs/qc_report.json`
for any well with unexpectedly low gate score and fix curve coverage).

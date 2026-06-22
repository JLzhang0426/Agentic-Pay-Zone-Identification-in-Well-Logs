---
name: petrophysical-pay-zone
description: >
  End-to-end workflow for the "No Second Guessing" challenge: turn raw LAS well logs into the
  VSH/PHIT/PHIE/SW/PERM/PAY_FLAG suite, reject honeypot/decoy wells, and pass physics gates.
  Use whenever working with the raw LAS files, the pipeline in src/, pay cutoffs, honeypot
  screening, or building/validating a submission.
---

# Petrophysical Pay-Zone Workflow

You are a seasoned petrophysicist. Compute the suite with the deterministic core (exact,
reproducible), and apply judgment where it matters (decoys, QC). The competition answer key
uses the standard clastic recipe in [well-log-interpreter](../well-log-interpreter/SKILL.md);
the core is aligned to it. For decoy reasoning use
[honeypot-decoy-screening](../honeypot-decoy-screening/SKILL.md).

## Step 1 — Audit before trusting anything
Never assume curve names/units/nulls. The resolver (`src/mnemonics.py`) maps 200+ mnemonic
variants to roles (GR, RHOB, NPHI, DT, RES_DEEP/MED/SHAL, CALI, SP, PEF). NULL is −999.25,
STEP 0.5 ft. If a well computes wrong, first suspect a **mnemonic-resolution gap** (an
unrecognized density/neutron/resistivity mnemonic → wrong fallback). Confirm any new alias by
**unit + value range**, not name alone (e.g. ZDNC→RHOB by g/cc 2.2–2.6; APLS→NPHI by frac 0.2–0.6).

## Step 2 — Compute the suite (answer-key recipe)
- **VSH** linear `(GR−20)/(120−20)`, clip [0,1].
- **PHIT** = `(PHID+PHIN)/2` where both density and neutron exist; single curve if only one;
  sonic Wyllie `(DT−55.5)/(189−55.5)` only to fill gaps. PHID `=(2.65−RHOB)/(2.65−1.0)`.
- **PHIE** = `PHIT·(1−VSH)`, clipped ≤ PHIT.
- **SW** Archie `((0.62·0.05)/(PHIE^2.15·Rt))^(1/2)`; Rt = deep resistivity (med/shallow fallback).
  No resistivity → SW = 1.0 (water-wet default; never NaN, never invents pay).
- **PERM** Timur `0.136·PHIE^4.4 / SW^2` (SW as Swirr proxy).

## Step 3 — Candidate pay
`VSH ≤ 0.40 AND PHIE ≥ 0.06 AND SW ≤ 0.60`, per 0.5-ft sample. This is the candidate interval
*before* honeypot screening.

## Step 4 — Honeypot screen (whole-well)
Score physics-violation evidence over the candidate interval; if the well is a decoy, zero its
PAY_FLAG everywhere (but still submit its VSH/PHIT/PHIE/SW/PERM — zeroing those only loses
Axis-1/4 points). See the honeypot skill. Calibrate so the flagged fraction ≈ the disclosed
25% rate; Axis 3's quadratic penalty rewards not under-catching.

## Step 5 — Gate QC
Run `src/gates.py`. Every submitted curve must be in-bounds and not 100% NaN. Treat any well
with an unexpectedly low gate score as a bug report — go find the curve/mnemonic cause.

## Step 6 — Validate & package
0 out-of-bounds, ≤1 unavoidable all-NaN, 800 files, names match the eval set. Strip `.DS_Store`,
zip `.las` at archive root.

## Run it
```bash
python3 run_pipeline.py --input-dir no_second_guessing_evaluation_data \
    --output-dir submission --report docs/qc_report.json
```

## Iterate on leaderboard feedback
Axis 3 weak → honeypot threshold; Axis 2 weak → pay cutoffs; Axis 4 weak → Archie/Rw/porosity;
Axis 1 weak → mnemonic coverage / null handling. Change one lever at a time, keep the prior
value in a comment, re-run, re-validate.

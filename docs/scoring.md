# Official Scoring Formulas ("No Second Guessing" -- Evaluation page)

Transcribed verbatim from the challenge's Evaluation page so the exact math
is preserved alongside the code, not just paraphrased in the README. Symbol
definitions are repeated at point of use.

## Final score

```
S = (A1 * A2 * A3 * A4) ^ (1/4)
```

Geometric mean of four axes, each scored 0-100, equally weighted. A zero on
any single axis zeros the entire score `S`.

Notation used throughout:

| Symbol | Definition |
|---|---|
| `N` | Total number of wells |
| `N_r` | Number of real wells |
| `N_h` | Number of honeypot wells |
| `G` | Number of physics gates per well (= 25) |
| `g_i` | Number of gates passed by well `i` |
| `F_i^pred` | Predicted net pay footage for well `i` (total feet where `PAY_FLAG=1`) |
| `F_i^true` | Answer-key net pay footage for well `i` |
| `P_i^pred` | Set of depth samples where the submission flags pay for well `i` |
| `P_i^true` | Set of depth samples where the answer key flags pay for well `i` |
| `tau_c` | Scoring tolerance for curve `c` |

## Axis 1: Gate Compliance

Every well is evaluated against `G = 25` physics-based logic gates (hard
physical constraints, e.g. porosity in `[0,1]`, `Sw` in `[0,1]`, `k >= 0`).
Each gate returns a binary pass/fail **for every depth sample** in the well.
"A well's gate score is the fraction of gates passed."

```
A1 = (1/N) * sum_{i=1}^{N} (g_i / G) * 100
```

Rules called out explicitly:
- Skipping a gate by not computing a curve does not help.
- A computed curve that is 100% NaN counts as a **failed gate**.
- Zero valid computed curves for a well -> that well's gate score is zero.
- "Submitting only GR + DEPTH + PAY_FLAG is not a petrophysical submission."

**Interpretation note (our assumption, not disclosed by the challenge):**
the text is ambiguous about whether `g_i` is an integer count of gates the
well passes *outright* (i.e. a gate "passes" only if it passes at every
depth sample, 0 or 1 per gate) or whether each gate contributes its
*fraction of depth samples passed* (a real number in `[0,1]` per gate,
summed over the 25 gates). Our `src/gates.py::gate_score()` implements the
**continuous fractional interpretation**: for each gate, compute the
fraction of depth samples that pass it, then average that fraction across
all 25 gates. This is the more forgiving of the two readings -- if the
real grader uses the strict "all-or-nothing per gate" interpretation
instead, our internal QC number will be an *overestimate* of the true A1.
This is the single most important unresolved ambiguity to watch for when
the next leaderboard score comes back.

## Axis 2: Pay Accuracy

On the `N_r` real wells only. `PAY_FLAG` must be 0 or 1 (non-binary values
rounded to nearest integer before scoring). Two equally-weighted
components per well:

**Footage error (50%)**
```
f_i = |F_i^pred - F_i^true| / F_i^true
```

**Jaccard overlap (50%)** -- depth-sample overlap between predicted and
true pay intervals:
```
J_i = |P_i^pred ∩ P_i^true| / |P_i^pred ∪ P_i^true|
```

Combined per-well error:
```
e_i = (1/2) * f_i + (1/2) * (1 - J_i)
```

Axis score:
```
A2 = (1/N_r) * sum_{i=1}^{N_r} max(0, 1 - e_i) * 100
```

Notes: overpredicting pay is penalized exactly as heavily as
underpredicting it (it's `|pred-true|`, not a one-sided penalty). If the
submission doesn't cover the full depth range, "a coverage penalty kicks
in" (mechanism not fully specified, but the practical implication is:
never truncate output depth range, even for honeypot wells -- pad with the
full depth range and PAY_FLAG=0 rather than omitting samples).

## Axis 3: Honeypot Rejection

Per-honeypot-well binary catch indicator:
```
c_i = 1  if F_i^pred = 0
c_i = 0  if F_i^pred > 0
```

Axis score applies a **squared** penalty to the miss fraction (not linear):
```
A3 = 100 * ( (1/N_h) * sum_{i=1}^{N_h} c_i ) ^ 2
```

Worked examples from the challenge text (confirmed by us below):
- Catch all: `A3 = 100`
- Miss 3 of 30 (catch 90%): `A3 = 100 * 0.9^2 = 81`, i.e. "costs you 19" points
  (the text says missing 3/30 costs 19 points -- matches `100-81=19`)
- Miss 10 of 30 (catch 66.7%): `A3 = 100 * (0.667)^2 = 44.4`
- Flag zero pay on every well -> all wells "caught" including real ones,
  but then `A2 = 0` for every real well (footage error 100%, Jaccard 0),
  so `S = 0` regardless of `A3`.

`A3` is computed only over the `N_h` true honeypot wells; we never get
told `N_h` directly but the challenge states ~25% of the 800 wells (i.e.
roughly `N_h ~= 200`).

## Axis 4: Petrophysical Accuracy

On the `N_r` real wells, three curves are compared to the answer key, but
**only at depth samples within the true pay interval `P_i^true`**:

| LAS mnemonic | Symbol | Curve `c` | Tolerance `tau_c` |
|---|---|---|---|
| `PHIE` | phi_e (effective porosity) | 1 | 0.03 v/v |
| `SW` | S_w (water saturation) | 2 | 0.10 v/v |
| `PERM` | log10(k) (log-permeability) | 3 | 0.50 log-decades |

For each real well `i` and curve `c`, RMSE is computed over all depth
samples in `P_i^true`:
```
s_{i,c} = max(0, 1 - RMSE_{i,c} / tau_c)
```

Per-well score is the **geometric mean** of the three curve scores (a zero
on any one curve zeroes the whole well's Axis-4 contribution):
```
s_i = (s_{i,1} * s_{i,2} * s_{i,3}) ^ (1/3)
```

Axis score:
```
A4 = (100 / N_r) * sum_{i=1}^{N_r} s_i
```

Hard-zero conditions called out explicitly:
- Less than 50% of the pay interval covered by the submission -> well
  hard-zeroed.
- More than 50% of a curve's values NaN within the pay zone -> that curve
  hard-zeroed.
- Physically impossible values (negative porosity, `Sw > 1`) penalized
  multiplicatively; >50% out-of-bounds samples zeroes the curve entirely.
- Missing samples treated as maximum error (do not omit depth rows).

**Open question on `PERM` units (worth testing, not yet confirmed):** the
table's "Symbol" column maps the `PERM` mnemonic to `log10 k`, and the
tolerance is given in "log-decades" with the explicit gloss "your perm can
be off by ~3x" (`10^0.5 ≈ 3.16`). Two readings are consistent with that
text:
  (a) We submit `PERM` in ordinary linear mD (as `src/petrophysics.py`
      currently does), and the grader takes `log10()` of our submitted
      value internally before computing RMSE against `log10(k_true)`.
      This reading is also the one consistent with Axis 1's explicit gate
      example "permeability must be non-negative" -- a constraint that
      only makes sense stated about linear `k`, since `log10(k)` is
      negative for any `k < 1 mD` (common in tight, non-pay rock) and
      would otherwise fail that gate on totally normal low-permeability
      samples.
  (b) We submit `log10(k)` directly as the `PERM` curve values.
We currently implement (a), which we believe is the better-supported
reading given the Axis-1 gate language, but it is not confirmed by the
challenge text. If Axis 4 (or the geometric-mean per-well `s_i`, which
zeroes if any one of the three curves scores zero) comes back
suspiciously low on the next submission, this is the first thing to test
by submitting a variant with `PERM = log10(k)` instead and comparing.
`src/petrophysics.py::compute_log10_perm()` already exists for this swap.

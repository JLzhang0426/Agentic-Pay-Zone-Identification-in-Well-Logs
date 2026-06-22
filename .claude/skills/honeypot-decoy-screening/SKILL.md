---
name: honeypot-decoy-screening
description: >
  How to decide whether a well is a planted "honeypot"/decoy (raw measurements with baked-in
  physics violations → correct net pay = 0) versus a real well with merely tight/wet or
  bad-hole intervals. Use when adjudicating honeypot flags, reviewing the borderline band in
  docs/qc_report.json, or tuning HONEYPOT_THRESHOLD.
---

# Honeypot / Decoy Screening

~25% of the 800 wells are honeypots: their **raw** curves contain physics that is impossible
for real sedimentary rock, engineered so a naive cutoff pipeline reports spurious pay. Your
job is to catch them from the physics — like a petrophysicist who distrusts the data, not just
the answer. A whole-well call: if it's a decoy, net pay must be **0** everywhere.

## Why this is the highest-leverage judgment
Axis 3 = (fraction of honeypots caught)². Quadratic: miss 3 of 30 → lose 19 pts, miss 10 → 44/100.
So **under-catching is far costlier than slightly over-flagging**. BUT flagging *every* well
zeroes Axis 2 (pay accuracy) and geometric-means the whole score to 0. So be evidence-based,
and when uncertain on a well that shows real violations, lean toward flagging.

## Evidence channels (computed in `src/honeypot.py`, surfaced in qc_report.json)
1. **raw_bounds_violation_rate** — fraction of candidate-pay samples where a raw curve sits
   outside what's physically possible for rock (not merely unusual): RHOB < 0.9 or > 3.4 g/cc,
   NPHI < −0.10 or > 0.55, PEF < 0.5 or > 7, DT < 35 or > 160 µs/ft, CALI < 3.5 or > 30 in.
2. **porosity_disagreement_rate** — density-, neutron-, sonic-derived porosity for the same
   rock disagree by > 0.15 v/v. Independent tools measuring the same property shouldn't
   systematically disagree; systematic disagreement ⇒ at least one curve is fabricated.
3. **sw_blowup_rate** — Archie SW from raw Rt/PHIE, *before clipping*, lands far outside [0,1].
   Only possible if the resistivity/porosity pairing isn't physically consistent rock.

Combined score = 0.45·bounds + 0.35·disagreement + 0.20·blowup. Flag if ≥ `HONEYPOT_THRESHOLD`.

## Adjudicating a single well (the judgment)
Decoy (flag, pay→0) when evidence is **systematic across the interval**:
- A large fraction of candidate-pay samples violate hard bounds, OR
- Persistent cross-tool porosity disagreement spanning the interval, OR
- SW blow-up that can't be explained by a few bad samples.

NOT a decoy — explain and keep the pay — when the anomaly is **localized or explainable**:
- **Bad hole / washout** (CALI ≫ well median): density reads low there → looks like a
  violation but it's an environmental artifact over a short interval, not a planted decoy.
- **A single spike / cycle-skip** (one or two samples) rather than a sustained pattern.
- **Vintage/tool quirk** (e.g. neutron in limestone units reading offset) that shifts a curve
  uniformly without making it physically impossible.
- Genuinely tight or wet rock (low PHIE / high SW) — that's correctly handled by the cutoffs as
  non-pay; it is **not** a honeypot and must not zero an otherwise-real well.

## Calibration
On the full 800-well set, set `HONEYPOT_THRESHOLD` so the flagged fraction tracks the disclosed
**~25%** (≈200 wells). After a leaderboard read of Axis 3: if it lags, lower the threshold
(catch more); if Axis 2 is dropping from over-flagging real wells, raise it. Change in small
steps and record the prior value.

## What to record per adjudicated well
`well_id, decision (honeypot|real), combined_score, dominant_channel, one-line reason`. This
trail is the interpretability the competition scores, and your regression guard for next round.

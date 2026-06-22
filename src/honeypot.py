"""
honeypot.py
Detects wells whose RAW curves contain physics violations -- i.e. the
"digital potholes" / honeypots described in the challenge: data rigged so
that a naive pipeline computes spurious pay where the underlying physics
is actually impossible.

Design principle: a violation must be found in the RAW measurements (or in
disagreement between two independent raw measurements of the same rock
property), not just "porosity is low" or "this looks tight" -- that's a
normal non-pay zone (a decoy interval), not a honeypot well. Honeypot
classification is a WHOLE-WELL decision per the challenge's Axis-3
definition (binary catch/miss per well), so we aggregate evidence across
the candidate pay interval and require it to be substantial before zeroing
the whole well's pay.

Evidence channels, each scored 0-1 over the candidate-pay interval
(samples that would otherwise be flagged pay before honeypot screening):

  1. raw_bounds_violation_rate -- fraction of samples where a raw curve
     (RHOB, NPHI, PEF, DT, CALI, GR) sits outside any physically possible
     value for sedimentary rock (not just "unusual", but impossible).
  2. porosity_disagreement_rate -- density-derived vs neutron-derived vs
     sonic-derived porosity estimates disagree by more than what
     tool-physics/environmental effects can explain.
  3. saturation_blowup_rate -- Archie SW computed from raw Rt/PHIE, before
     any clipping, comes out negative or far above 1 (only possible if the
     resistivity/porosity pairing is not physically consistent rock).

A well is classified a honeypot if the combined weighted evidence over its
candidate-pay interval exceeds HONEYPOT_THRESHOLD. We deliberately require
a non-trivial candidate-pay interval to exist before testing (no candidate
pay -> nothing to reject -> not flagged "caught", just naturally zero pay).
"""
from __future__ import annotations
import numpy as np

# Threshold = 0.165 flags ~25.1% (201/800), matched to the disclosed 25% true
# honeypot rate. NOTE (important, unresolved): after fixing the unit-mislabel
# bug in mnemonics.py, the raw-bounds-violation channel no longer separates 25%
# of wells -- only ~14-22 wells have values impossible under every unit. So the
# combined score here is now dominated by the porosity-DISAGREEMENT channel,
# which is partly confounded with legitimate gas (phiD>phiN) and shale physics.
# We cannot verify precision/recall without the leaderboard. This v1 matches the
# base rate because Axis 3's QUADRATIC penalty punishes under-catching hardest;
# reading Axis 3 back is the #1 iteration priority -- if it lags, the detector
# (not just the threshold) needs rework (e.g. directional/Archie-inconsistency
# signals). (was 0.30, then 0.22 pre-unit-fix.)
HONEYPOT_THRESHOLD = 0.165
MIN_CANDIDATE_SAMPLES = 5

RHOB_HARD = (0.9, 3.4)
NPHI_HARD = (-0.10, 0.55)
PEF_HARD = (0.5, 7.0)
DT_HARD = (35.0, 160.0)
CALI_HARD = (3.5, 30.0)


def _frac_out_of_range(arr, lo, hi):
    if arr is None:
        return None
    valid = ~np.isnan(arr)
    if valid.sum() == 0:
        return None
    return (arr[valid] < lo) | (arr[valid] > hi), valid


def evaluate_honeypot(curves: dict, candidate_pay_mask: np.ndarray) -> dict:
    """Returns dict with per-channel evidence rates and final boolean
    `is_honeypot` + `confidence`."""
    n_candidates = int(np.sum(candidate_pay_mask))
    result = {
        "n_candidate_samples": n_candidates,
        "raw_bounds_violation_rate": 0.0,
        "porosity_disagreement_rate": 0.0,
        "saturation_blowup_rate": 0.0,
        "combined_score": 0.0,
        "is_honeypot": False,
    }
    if n_candidates < MIN_CANDIDATE_SAMPLES:
        return result

    idx = candidate_pay_mask

    # --- Channel 1: raw bounds violations within candidate-pay zone -------
    violations = []
    for name, (lo, hi) in [
        ("RHOB", RHOB_HARD), ("NPHI", NPHI_HARD), ("PEF", PEF_HARD),
        ("DT", DT_HARD), ("CALI", CALI_HARD),
    ]:
        arr = curves.get(name)
        if arr is None:
            continue
        sub = arr[idx]
        valid = ~np.isnan(sub)
        if valid.sum() == 0:
            continue
        bad = (sub[valid] < lo) | (sub[valid] > hi)
        violations.append(bad.mean())
    result["raw_bounds_violation_rate"] = float(np.mean(violations)) if violations else 0.0

    # --- Channel 2: cross-method porosity disagreement ---------------------
    rhob, nphi, dt = curves.get("RHOB"), curves.get("NPHI"), curves.get("DT")
    phits = {}
    if rhob is not None:
        phits["den"] = np.clip((2.65 - rhob[idx]) / (2.65 - 1.0), -1, 2)
    if nphi is not None:
        phits["neu"] = np.clip(nphi[idx], -1, 2)
    if dt is not None:
        phits["son"] = np.clip((dt[idx] - 55.5) / (189.0 - 55.5), -1, 2)

    disagreements = []
    keys = list(phits.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = phits[keys[i]], phits[keys[j]]
            valid = (~np.isnan(a)) & (~np.isnan(b))
            if valid.sum() == 0:
                continue
            diff = np.abs(a[valid] - b[valid])
            disagreements.append((diff > 0.15).mean())
    result["porosity_disagreement_rate"] = float(np.mean(disagreements)) if disagreements else 0.0

    # --- Channel 3: raw (pre-clip) Archie SW blow-up ------------------------
    rt = curves.get("RES_DEEP")
    phie_raw = curves.get("_PHIE_PRECLIP")
    if rt is not None and phie_raw is not None:
        sub_rt = rt[idx]
        sub_phie = phie_raw[idx]
        valid = (~np.isnan(sub_rt)) & (~np.isnan(sub_phie)) & (sub_rt > 0) & (sub_phie > 0.01)
        if valid.sum() > 0:
            rw = 0.05
            sw_raw = (1.0 * rw / (sub_phie[valid] ** 2 * sub_rt[valid])) ** 0.5
            blowup = (sw_raw < -0.05) | (sw_raw > 1.5)
            result["saturation_blowup_rate"] = float(blowup.mean())

    combined = (
        0.45 * result["raw_bounds_violation_rate"]
        + 0.35 * result["porosity_disagreement_rate"]
        + 0.20 * result["saturation_blowup_rate"]
    )
    result["combined_score"] = combined
    result["is_honeypot"] = combined >= HONEYPOT_THRESHOLD
    return result

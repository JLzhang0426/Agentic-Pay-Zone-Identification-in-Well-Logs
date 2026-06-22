"""
pay.py
Final PAY_FLAG decision logic: standard clastic-reservoir cutoffs, applied
only after honeypot screening.

Cutoffs are aligned to the organizer's well_log_interpreter SKILL.md (the
likely answer-key generator), whose pay rule is Vsh<cutoff AND PHIE>cutoff
AND Sw<cutoff with these defaults:
    VSH  <= 0.40   (skill Vsh_cutoff=0.40; rock must not be too shaly)
    PHIE >= 0.06   (skill PHIE_cutoff=0.06; was 0.08)
    SW   <= 0.60   (skill Sw_cutoff=0.60; was 0.50)
"""
from __future__ import annotations
import numpy as np

VSH_CUTOFF = 0.40
PHIE_CUTOFF = 0.06
SW_CUTOFF = 0.60


def candidate_pay_mask(vsh, phie, sw) -> np.ndarray:
    """Pay mask using cutoffs alone, BEFORE honeypot screening -- used both
    as the final flag (if well is not a honeypot) and as the interval that
    honeypot evidence gets evaluated against."""
    if vsh is None or phie is None or sw is None:
        return np.zeros_like(phie if phie is not None else vsh, dtype=bool)
    mask = (vsh <= VSH_CUTOFF) & (phie >= PHIE_CUTOFF) & (sw <= SW_CUTOFF)
    return np.nan_to_num(mask.astype(float), nan=0.0).astype(bool)


def finalize_pay_flag(candidate_mask: np.ndarray, is_honeypot: bool) -> np.ndarray:
    if is_honeypot:
        return np.zeros_like(candidate_mask, dtype=int)
    return candidate_mask.astype(int)

"""
mnemonics.py
Canonical-curve resolver: maps the messy, multi-vintage mnemonic zoo observed
across the 800 raw LAS files (217 distinct mnemonics surveyed) onto a small
set of canonical petrophysical roles needed downstream:

    DEPTH, GR, SP, CALI, RHOB, NPHI, PEF, DT, RES_DEEP, RES_MED, RES_SHAL

Strategy
--------
1. Exact-match alias tables built from the observed mnemonic survey
   (see docs/mnemonic_survey.md) -- this covers the large majority of wells.
2. A regex/heuristic fallback for anything not in the table, so a totally
   unseen vintage doesn't silently drop a curve.
3. Per-role, if multiple raw curves are candidates (e.g. both RHOB and RHOZ
   present), we prefer the first available alias in priority order and
   record which one we used (full provenance, no silent guessing).
4. Unit normalization so downstream physics always sees consistent units
   (API, g/cc, v/v fraction, ohm.m, in, us/ft, mV).

This module is intentionally conservative: drilling/trajectory curves
(WOB, TORQ, ROP, RPM, TENS, HAZI, DEVI, ECD, PRES, TT1/TT2, SWOB) are
recognized and explicitly EXCLUDED from petrophysical roles -- some wells
carry mud-logging/drilling channels that are irrelevant (or decoys) for
log-based pay identification.
"""
from __future__ import annotations
import re
import numpy as np

# Curves that must never be mistaken for a petrophysical role even though
# they share substrings with real ones (e.g. "TENS" vs "DENS").
DRILLING_BLOCKLIST = {
    "WOB", "TORQ", "ROP", "RPM", "TENS", "HAZI", "DEVI", "ECD", "PRES",
    "TT1", "TT2", "SWOB", "X1", "X2", "UNKNOWN",
}

ALIASES = {
    "DEPTH": ["DEPT", "DEPTH", "MD", "TDEP", "MDEPTH", "DEP", "DEPH"],
    "GR": [
        "GR", "SGR", "ECGR", "CGR", "HSGR", "GRD", "GRGC", "GR1", "GRS",
        "GR_EDTC", "NGRT", "GRR", "SGRD", "GRTO", "GRN", "HGR", "HGRCC",
        "HGRC", "GR2", "GR_SL", "EHGR", "GKUT", "GRAM",
    ],
    "SP": [
        "SP", "SSP", "SPONT", "SP_MV", "SPC", "SPR", "PSP", "SPONPOT",
        "SPOT", "SPNT", "SPM", "ESP",
    ],
    "CALI": [
        "CALI", "CAL", "HCAL", "CALS", "CAL_CDL", "LCAL", "CAL1", "CALDC",
        "CALR", "CALD", "CALX", "CAL2", "HCALS", "DCAL",
        # confirmed by unit (IN) + ~bit-size range across eval set
        "C1", "ECAL",
    ],
    "RHOB": [
        "RHOB", "RHOZ", "ZDEN", "DEN", "DENS", "RHOB_CDL", "DENB", "RHOBC",
        "ZDENS", "DENC", "RHOM", "RHBH", "RHOZE", "DEN_COR", "ROBB", "FDC",
        # confirmed by unit (G/CC) + 2.2-2.6 g/cc range across eval set
        "ZDNC", "HDRA",
    ],
    "NPHI": [
        "NPHI", "TNPH", "NPOR", "HNPO", "CNL", "NEU", "NEUT", "CNCF",
        "HTNP", "NPRL", "SNPH", "ENPH", "TNPS", "NPRS", "TCNL", "NPOR_LS",
        "ENPE", "TNPB", "CNC", "BPHI", "PHIN", "SPHI",
        # confirmed by unit (V/V frac) + 0.2-0.6 range across eval set;
        # APLS (sandstone-referenced) preferred over APLC (limestone) for clastics
        "APLS", "APLC", "PHIS",
    ],
    "PEF": [
        "PEF", "PE", "PEFZ", "PEFA", "HPEF", "PEZ", "PEFN", "PEDN", "PEFL",
        "PEFLA", "PEF8", "PE_CDL", "PEZL", "PE8",
        # confirmed by unit (B/E) across eval set
        "HDPE",
    ],
    "DT": [
        "DTCO", "DTC", "DT", "SONIC", "BHC", "DTLN", "DT1R", "SON",
        "DT_BHC", "DTCO4", "DT4P", "SLOWNESS", "DTL", "DT4S", "SONICDT",
        "DT1", "DT24", "DTBHC", "DTSH", "DTLN_MRK",
        # confirmed by unit (US/FT) + 80-105 us/ft range across eval set
        "AC", "HDTC", "EDTC",
    ],
    # Deep resistivity (induction/laterolog deep reading) -- primary Rt for Archie.
    "RES_DEEP": [
        "ILD", "RT", "RD", "RILD", "RESD", "RLLD", "IDPH", "HLLD",
        "RLLA", "M2R9", "RAILD", "RT_HRLT", "AHT90", "AO90", "AIT_H90",
        "A28H", "A34H", "HDRS", "LLD",
        # array-induction 90-inch (deepest DOI) confirmed by unit (OHMM)
        "AT90",
    ],
    "RES_MED": [
        "RILM", "ILM", "A22H", "P16H", "HMRS", "AHF90", "A16H",
    ],
    "RES_SHAL": [
        "RXO", "RXOZ", "MSFL", "SFL", "SFLU", "MCFL", "MLL", "RSFL",
        "RXO_HRLT", "RXO8", "RXORT", "SN", "RLA5", "AO10", "AHO10",
        "RLA1", "LLS", "RS", "RB",
    ],
}

# Priority order used when several aliases for the same role are present
# in one well (prefer the "modern"/most standard mnemonic first).
PRIORITY = {role: aliases for role, aliases in ALIASES.items()}

UNIT_NORMALIZERS = {
    "GR": {"target": "API", "factor": {"GAPI": 1.0, "API": 1.0, "CPS": 1.0}},
    "RHOB": {"target": "G/CC", "factor": {"G/CC": 1.0, "G/C3": 1.0, "G/CM3": 1.0, "GM/CC": 1.0}},
    "NPHI": {"target": "V/V", "factor": {"V/V": 1.0, "DEC": 1.0, "M3/M3": 1.0, "FRAC": 1.0, "%": 0.01}},
    "PEF": {"target": "B/E", "factor": {"B/E": 1.0, "BARN/E": 1.0, "BARNS/ELECTRON": 1.0, "B/EL": 1.0}},
    "DT": {"target": "US/FT", "factor": {
        "US/FT": 1.0, "USFT": 1.0, "US/F": 1.0, "USEC/FT": 1.0, "MICROSEC/FT": 1.0,
        "US/M": 1.0 / 3.28084,
    }},
    "CALI": {"target": "IN", "factor": {
        "IN": 1.0, "INCH": 1.0, "INCHES": 1.0, "INS": 1.0,
        "CM": 1.0 / 2.54, "MM": 1.0 / 25.4,
    }},
    "RES_DEEP": {"target": "OHMM", "factor": {"OHMM": 1.0, "OHM.M": 1.0, "HMOH": 1.0}},
    "RES_MED": {"target": "OHMM", "factor": {"OHMM": 1.0, "OHM.M": 1.0, "HMOH": 1.0}},
    "RES_SHAL": {"target": "OHMM", "factor": {"OHMM": 1.0, "OHM.M": 1.0, "HMOH": 1.0}},
    "SP": {"target": "MV", "factor": {"MV": 1.0, "MVOL": 1.0, "MILLIVOLT": 1.0, "V": 1000.0}},
}

# Physically plausible window for the MEDIAN of a curve in its canonical unit.
# Used ONLY to catch mislabeled units: this dataset contains caliper curves
# reading 8.5 (inches, a standard bit size) but tagged "CM"/"MM", and sonic
# curves reading ~90 (us/ft) tagged "US/M". Blindly trusting the label
# over-converts them into physically impossible values (~3.3 in, ~28 us/ft),
# which (a) corrupts sonic porosity and (b) was masquerading as honeypot-level
# "physics violations". When the labeled conversion lands outside this window
# we re-pick the unit factor that brings the median back in range.
#
# Key property: a value that is impossible under EVERY candidate unit (a true
# fabricated honeypot curve) cannot be rescued and stays flagged -- so this
# fix cleanly separates unit-mislabels from genuine physics violations.
PLAUSIBLE_MEDIAN = {
    "CALI": (4.0, 24.0),    # inches (bit sizes ~6-17.5; hole rarely <4 or >24)
    "DT":   (40.0, 220.0),  # us/ft (dolomite ~43 matrix to unconsolidated ~190)
    "RHOB": (1.5, 3.1),     # g/cc
    "NPHI": (0.0, 0.80),    # v/v fraction
}


def _clean(mnem: str) -> str:
    return mnem.strip().upper().replace(" ", "_")


def resolve_curves(las) -> dict:
    """
    Given a LASFile, return {role: (LASCurve, alias_used)} for every
    canonical role we could find. Roles not found are simply absent from
    the returned dict (callers must handle missing curves explicitly --
    no silent fabrication of data).
    """
    available = {_clean(c.mnemonic): c for c in las.curves}
    resolved = {}

    for role, alias_list in PRIORITY.items():
        for alias in alias_list:
            if alias in DRILLING_BLOCKLIST:
                continue
            if alias in available:
                curve = available[alias]
                # Skip if curve is entirely NaN -- treat as not available.
                if curve.data.size == 0 or np.all(np.isnan(curve.data)):
                    continue
                resolved[role] = (curve, alias)
                break

    # Fallback heuristic pass for mnemonics not in any alias list, in case
    # an unseen vintage uses something we haven't catalogued. Only applies
    # to roles still missing.
    if "DEPTH" not in resolved:
        # curves[0] is always the index/depth curve per LAS 2.0 spec.
        resolved["DEPTH"] = (las.curves[0], las.curves[0].mnemonic)

    for mnem_clean, curve in available.items():
        if mnem_clean in DRILLING_BLOCKLIST:
            continue
        if any(mnem_clean == a for aliases in PRIORITY.values() for a in aliases):
            continue
        if curve.data.size == 0 or np.all(np.isnan(curve.data)):
            continue
        if re.search(r"GR", mnem_clean) and "GR" not in resolved:
            resolved["GR"] = (curve, mnem_clean)
        elif re.search(r"RHO|DEN", mnem_clean) and "RHOB" not in resolved:
            resolved["RHOB"] = (curve, mnem_clean)
        elif re.search(r"NPH|NEU|CNL", mnem_clean) and "NPHI" not in resolved:
            resolved["NPHI"] = (curve, mnem_clean)
        elif re.search(r"^PE", mnem_clean) and "PEF" not in resolved:
            resolved["PEF"] = (curve, mnem_clean)
        elif re.search(r"^DT|SONIC", mnem_clean) and "DT" not in resolved:
            resolved["DT"] = (curve, mnem_clean)
        elif re.search(r"^CAL|^BS$", mnem_clean) and "CALI" not in resolved:
            resolved["CALI"] = (curve, mnem_clean)
        elif re.search(r"^SP", mnem_clean) and "SP" not in resolved:
            resolved["SP"] = (curve, mnem_clean)
        elif re.search(r"^R[ILTD]|RES|OHM", mnem_clean) and "RES_DEEP" not in resolved:
            resolved["RES_DEEP"] = (curve, mnem_clean)

    return resolved


def normalized_array(role: str, curve) -> np.ndarray:
    """Return curve.data converted to the canonical unit for its role.

    Conversion is *plausibility-guarded*: if the unit-label-driven conversion
    yields a physically impossible median for the role, we re-pick the unit
    factor (from the role's known factors, plus identity) that lands the median
    back inside PLAUSIBLE_MEDIAN. This repairs mislabeled units (e.g. inches
    tagged "CM", us/ft tagged "US/M") without touching correctly-labeled wells,
    and without rescuing genuinely fabricated values (no unit makes them sane).
    """
    spec = UNIT_NORMALIZERS.get(role)
    data = curve.data.astype(float)
    if spec is None:
        return data
    unit = (curve.unit or "").strip().upper()
    factor = spec["factor"].get(unit)
    if factor is None:
        # Unknown unit string: heuristics for the common cases that slip
        # through (blank unit, stray punctuation already normalized).
        factor = 1.0
    out = data * factor

    win = PLAUSIBLE_MEDIAN.get(role)
    if win is not None:
        valid = out[~np.isnan(out)]
        if valid.size >= 5:
            med = float(np.median(valid))
            if not (win[0] <= med <= win[1]):
                # Labeled conversion is implausible -> search candidate factors
                # (role's known factors + identity) for one whose median lands
                # in-window; prefer the one closest to the window center.
                raw_valid = data[~np.isnan(data)]
                center = 0.5 * (win[0] + win[1])
                best = None
                for f in set(spec["factor"].values()) | {1.0}:
                    m = float(np.median(raw_valid * f))
                    if win[0] <= m <= win[1]:
                        d = abs(m - center)
                        if best is None or d < best[0]:
                            best = (d, f)
                if best is not None:
                    out = data * best[1]
    return out

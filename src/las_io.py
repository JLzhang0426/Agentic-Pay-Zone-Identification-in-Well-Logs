"""
las_io.py
Minimal, dependency-free LAS 2.0 reader/writer.

We don't rely on third-party LAS libraries (lasio, welly, etc.) because the
sandbox this pipeline was built in has no outbound package-index access, and
because writing our own parser forces us to handle the messy header
variability we actually observed across the 800 wells (inconsistent
delimiters, missing colons, unit-string variants, CPS vs API gamma units,
multiple depth-curve aliases, etc.) rather than trusting a library's
assumptions about "well-formed" LAS files.

Only the subset of LAS 2.0 needed for this challenge is implemented:
~VERSION, ~WELL, ~CURVE, ~PARAMETER, ~OTHER, ~ASCII sections, one line per
depth step (WRAP NO), space-delimited data.
"""
from __future__ import annotations
import re
import numpy as np
from dataclasses import dataclass, field


HEADER_LINE_RE = re.compile(
    r"^\s*([A-Za-z0-9_\-\s]+?)\.([A-Za-z0-9/%\.\*\^\-]*)\s+([^:]*?)\s*:?\s*(.*)$"
)


@dataclass
class LASCurve:
    mnemonic: str
    unit: str
    data: np.ndarray
    descr: str = ""


@dataclass
class LASFile:
    well_params: dict = field(default_factory=dict)   # mnemonic -> (unit, value, descr)
    version_params: dict = field(default_factory=dict)
    other_params: dict = field(default_factory=dict)
    curves: list = field(default_factory=list)          # list[LASCurve], curves[0] is depth/index
    null_value: float = -999.25
    source_path: str = ""

    @property
    def depth(self) -> np.ndarray:
        return self.curves[0].data

    def curve_names(self):
        return [c.mnemonic for c in self.curves]

    def get(self, mnemonic):
        for c in self.curves:
            if c.mnemonic.upper() == mnemonic.upper():
                return c
        return None

    def __contains__(self, mnemonic):
        return self.get(mnemonic) is not None


def _parse_header_line(line: str):
    m = HEADER_LINE_RE.match(line)
    if not m:
        return None
    mnem, unit, val, descr = m.groups()
    return mnem.strip(), unit.strip(), val.strip(), descr.strip()


def read_las(path: str) -> LASFile:
    las = LASFile(source_path=path)
    section = None
    ascii_lines = []

    with open(path, "r", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("~"):
                section = stripped[1:].strip().split()[0].upper()[0]  # V/W/C/P/O/A
                continue
            if stripped.startswith("#"):
                continue

            if section == "A":  # ASCII data section
                ascii_lines.append(stripped)
                continue

            parsed = _parse_header_line(line)
            if parsed is None:
                continue
            mnem, unit, val, descr = parsed

            if section == "W":
                las.well_params[mnem.upper()] = (unit, val, descr)
                if mnem.upper() == "NULL":
                    try:
                        las.null_value = float(val)
                    except ValueError:
                        pass
            elif section == "V":
                las.version_params[mnem.upper()] = (unit, val, descr)
            elif section == "C":
                las.curves.append(LASCurve(mnemonic=mnem, unit=unit, data=None, descr=descr))
            elif section == "P":
                las.other_params[mnem.upper()] = (unit, val, descr)
            elif section == "O":
                las.other_params.setdefault("_OTHER_TEXT", ("", "", ""))

    n_curves = len(las.curves)
    rows = []
    for line in ascii_lines:
        parts = line.split()
        if len(parts) != n_curves:
            # Tolerate ragged rows (rare OCR/typo artifacts): pad or truncate.
            if len(parts) > n_curves:
                parts = parts[:n_curves]
            else:
                parts = parts + ["nan"] * (n_curves - len(parts))
        try:
            rows.append([float(p) for p in parts])
        except ValueError:
            rows.append([float("nan")] * n_curves)

    if rows:
        arr = np.array(rows, dtype=float)
    else:
        arr = np.zeros((0, n_curves))

    null = las.null_value
    arr_masked = np.where(np.isclose(arr, null, atol=1e-3) | np.isnan(arr), np.nan, arr)

    for i, c in enumerate(las.curves):
        c.data = arr_masked[:, i] if arr_masked.size else np.array([])

    return las


def write_las(las: LASFile, path: str, null_value: float = -999.25):
    """Write a LAS 2.0 file (WRAP NO, space-delimited)."""
    lines = []
    lines.append("~VERSION INFORMATION")
    lines.append("VERS.                 2.0 : CWLS log ASCII Standard -VERSION 2.0")
    lines.append("WRAP.                  NO : One line per depth step")
    lines.append("~WELL INFORMATION")

    depth = las.curves[0].data
    strt = np.nanmin(depth) if depth.size else 0.0
    stop = np.nanmax(depth) if depth.size else 0.0
    step = float(np.nanmedian(np.diff(depth))) if depth.size > 1 else 0.5

    wp = dict(las.well_params)
    wp["STRT"] = ("", f"{strt:.5f}", "")
    wp["STOP"] = ("", f"{stop:.5f}", "")
    wp["STEP"] = ("", f"{step:.5f}", "")
    wp["NULL"] = ("", f"{null_value:.4f}", "")

    for mnem in ["STRT", "STOP", "STEP", "NULL", "COMP", "WELL", "FLD", "LOC", "PROV",
                 "CNTY", "STAT", "CTRY", "SRVC", "DATE", "UWI", "API"]:
        if mnem in wp:
            unit, val, descr = wp[mnem]
            lines.append(f"{mnem:<5s}.{unit:<8s} {val:<28s}: {descr}")

    lines.append("~CURVE INFORMATION")
    for c in las.curves:
        lines.append(f"{c.mnemonic:<8s}.{c.unit:<8s}     : {c.descr}")

    lines.append("~PARAMETER INFORMATION")
    for mnem, (unit, val, descr) in las.other_params.items():
        if mnem.startswith("_"):
            continue
        lines.append(f"{mnem:<8s}.{unit:<8s} {val:<16s}: {descr}")

    lines.append("~OTHER")
    lines.append("Processed by agentic pay-zone identification pipeline.")

    lines.append("~ASCII")
    n = len(depth)
    cols = [c.data for c in las.curves]
    for i in range(n):
        row_vals = []
        for col in cols:
            v = col[i] if i < len(col) else np.nan
            if v is None or (isinstance(v, float) and np.isnan(v)):
                v = null_value
            row_vals.append(f"{v:12.5f}")
        lines.append(" ".join(row_vals))

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")

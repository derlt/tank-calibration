"""Raw data, step cells, corrections and intervals (§1, §2, §3.9, §5.1).

The raw file is never written by this package.  Every correction produces a
new row object and is recorded in ``*_corrected.csv`` with a flag, the rule
that authorised it, and its magnitude (§1.1).
"""

from __future__ import annotations

import copy
import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Step cells (§3.9): a number, "?" (whole pour unknown), or "N+?" (N litres
# plus an unknown extra).  Legacy "x1"/"x2" cells are read as unknown pours.
# ---------------------------------------------------------------------------

_NUM = r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)"
_PARTIAL_RE = re.compile(rf"^\s*({_NUM})\s*\+\s*(?:\?|x\d*)\s*$", re.IGNORECASE)
_UNKNOWN_RE = re.compile(r"^\s*(?:\?|x\d*)\s*$", re.IGNORECASE)


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


@dataclass
class Step:
    kind: str  # "known" | "unknown" | "partial"
    value: float | None = None
    base: float = 0.0
    raw: str = ""

    @property
    def known(self) -> bool:
        return self.kind == "known"


def parse_step(cell: str) -> Step:
    """Parse one ``step_volume`` cell."""
    text = "" if cell is None else str(cell).strip()
    if text == "":
        return Step("unknown", raw=text)
    m = _PARTIAL_RE.match(text)
    if m:
        return Step("partial", value=None, base=_to_float(m.group(1)), raw=text)
    if _UNKNOWN_RE.match(text):
        return Step("unknown", raw=text)
    try:
        return Step("known", value=_to_float(text), raw=text)
    except ValueError as exc:
        raise ValueError(f"cannot parse step_volume cell {text!r}") from exc


@dataclass
class Row:
    index: int  # 0-based position in the file
    step: Step
    height: float
    note: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def line(self) -> int:
        return self.index + 1


@dataclass
class Correction:
    """One flagged correction (§1.1, §6.1)."""

    row: int  # 1-based data row, header excluded
    field: str  # "height" or "step"
    value: float
    rule: str
    magnitude: float
    note: str = ""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

_ALIASES = {
    "step": ("step_volume", "step", "pour", "volume", "pour_l", "litres", "l"),
    "height": ("measured_height", "height", "level", "dip", "h", "mm"),
    "note": ("note", "notes", "comment", "remark"),
}


def _pick(fieldnames, kind):
    lowered = {str(n).strip().lower(): n for n in fieldnames if n}
    for alias in _ALIASES[kind]:
        if alias in lowered:
            return lowered[alias]
    for name, original in lowered.items():
        if kind == "height" and ("height" in name or "level" in name or "dip" in name):
            return original
        if kind == "step" and ("step" in name or "pour" in name or "volume" in name):
            return original
    return None


def read_raw(path: str | Path) -> list[Row]:
    """Read a raw campaign file.  Accepts comma or semicolon delimiters."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError(f"{path}: no header row")
    step_col = _pick(reader.fieldnames, "step")
    height_col = _pick(reader.fieldnames, "height")
    note_col = _pick(reader.fieldnames, "note")
    if step_col is None or height_col is None:
        raise ValueError(
            f"{path}: header needs a step/pour column and a height/level column; "
            f"found {reader.fieldnames}"
        )
    rows: list[Row] = []
    for i, rec in enumerate(reader):
        raw_h = (rec.get(height_col) or "").strip()
        if raw_h == "":
            continue
        try:
            height = _to_float(raw_h)
        except ValueError as exc:
            raise ValueError(f"{path}: row {i + 1}: bad height {raw_h!r}") from exc
        rows.append(
            Row(
                index=len(rows),
                step=parse_step(rec.get(step_col)),
                height=height,
                note=(rec.get(note_col) or "").strip() if note_col else "",
            )
        )
    if len(rows) < 2:
        raise ValueError(f"{path}: need at least two rows")
    return rows


# ---------------------------------------------------------------------------
# Corrections and the corrected file
# ---------------------------------------------------------------------------

def apply_corrections(rows: list[Row], corrections: list[Correction]) -> list[Row]:
    """Return a corrected copy.  The input rows are not modified."""
    out = copy.deepcopy(rows)
    for c in corrections:
        if not 1 <= c.row <= len(out):
            raise ValueError(f"correction for row {c.row}: file has {len(out)} rows")
        row = out[c.row - 1]
        if c.field == "height":
            row.flags.append(
                f"dip corrected {row.height:g}->{c.value:g} mm "
                f"({c.rule}, {c.magnitude:+g} mm)"
            )
            row.height = float(c.value)
        elif c.field == "step":
            row.flags.append(
                f"pour corrected {row.step.raw or row.step.value}->{c.value:g} L "
                f"({c.rule}, {c.magnitude:+g} L)"
            )
            row.step = Step("known", value=float(c.value), raw=f"{c.value:g}")
        else:
            raise ValueError(f"correction field must be 'height' or 'step', got {c.field!r}")
        if c.note:
            row.flags.append(c.note)
    return out


def write_corrected(path: str | Path, rows: list[Row]) -> None:
    """Write the derived table.  One flag per row, raw value kept in the note."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["step_volume", "measured_height", "note", "flag"])
        for row in rows:
            step = (
                f"{row.step.value:g}"
                if row.step.kind == "known"
                else (row.step.raw or "?")
            )
            writer.writerow(
                [step, f"{row.height:g}", row.note, "; ".join(row.flags)]
            )


# ---------------------------------------------------------------------------
# Intervals (§2, §5.1)
# ---------------------------------------------------------------------------

@dataclass
class Interval:
    idx: int  # 1-based interval number
    row: int  # 0-based index of the ending row
    s: float | None
    known: bool
    base: float
    h_prev: float
    h_cur: float
    trusted: bool = True
    reason: str = ""
    # filled by the model
    pred: float = 0.0
    resid: float = 0.0
    m: float = 0.0
    mm_equiv: float = 0.0
    sigma: float = 0.0
    z: float = 0.0
    flag: str = ""
    drift: float = 0.0

    @property
    def rise(self) -> float:
        return self.h_cur - self.h_prev


def build_intervals(rows: list[Row]) -> list[Interval]:
    """One interval per pour: from the previous dip to this dip."""
    out: list[Interval] = []
    for i in range(1, len(rows)):
        step = rows[i].step
        out.append(
            Interval(
                idx=i,
                row=i,
                s=step.value if step.kind == "known" else None,
                known=step.kind == "known",
                base=step.base,
                h_prev=rows[i - 1].height,
                h_cur=rows[i].height,
            )
        )
    return out


def mark_trusted(
    intervals: list[Interval],
    *,
    brim: float,
    object_bands: list[dict] | None = None,
    excluded_rows: set[int] | None = None,
) -> None:
    """Apply the trusted-set rules of §5.1.

    Excluded: unknown/partial pours, overflow intervals, non-positive rises,
    declared object bands, and explicit row exclusions.
    """
    bands = object_bands or []
    excluded_rows = excluded_rows or set()
    for iv in intervals:
        iv.trusted, iv.reason = True, ""
        if not iv.known:
            iv.trusted, iv.reason = False, "unknown pour"
            continue
        if iv.h_cur > brim:
            iv.trusted, iv.reason = False, "overflow interval"
            continue
        if iv.rise <= 0:
            iv.trusted, iv.reason = False, "non-positive rise"
            continue
        if iv.row in excluded_rows:
            iv.trusted, iv.reason = False, "excluded row"
            continue
        for band in bands:
            lo, hi = float(band["low"]), float(band["high"])
            if iv.h_cur >= lo and iv.h_prev <= hi:
                iv.trusted, iv.reason = False, f"object band {lo:g}-{hi:g} mm"
                break


def trusted(intervals: list[Interval]) -> list[Interval]:
    return [iv for iv in intervals if iv.trusted]

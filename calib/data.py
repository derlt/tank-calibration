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
from itertools import pairwise
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
    index: int  # 0-based position among the kept rows
    step: Step
    height: float
    note: str = ""
    flags: list[str] = field(default_factory=list)
    file_line: int = 0  # 1-based line in the file; 0 = same as index + 1

    @property
    def line(self) -> int:
        return self.file_line or self.index + 1


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
            step = parse_step(rec.get(step_col) if step_col else "")
            if step.known or step.base:
                raise ValueError(
                    f"{path}: row {i + 1}: pour {step.raw!r} is recorded without a height"
                )
            continue  # a blank line, not a lost pour
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
                file_line=i + 1,
            )
        )
    if len(rows) < 2:
        raise ValueError(f"{path}: need at least two rows")
    return rows


def books_start(rows: list[Row], shell) -> float:
    """Liquid on the books at the first recorded level (§9.3).

    The first row's pour filled the tank to its first level.  A known pour
    enters the books at its recorded value; an unknown one enters at the
    back-predicted ``F(H_0)`` (§8.1).  Without this term the closure identity
    is short by exactly the first pour.
    """
    if not rows:
        return 0.0
    first = rows[0]
    if first.step.known:
        return float(first.step.value)
    return float(shell.volume(first.height))


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
#
# A campaign has one direction (§3.11).  FILL: pour in, the level rises.
# DRAIN: pump out, the level falls.  The step volume is always positive
# litres, and ``h_prev`` / ``h_cur`` stay in time order.  The predicted step
# is the shell volume between the two levels, so the residual keeps the one
# convention of §2 in both directions:
#
#     pred = direction * (F(h_cur) - F(h_prev)) = F(h_hi) - F(h_lo)
#     resid = s - pred
# ---------------------------------------------------------------------------

FILL = 1
DRAIN = -1
DIRECTIONS = {"fill": FILL, "drain": DRAIN}


def direction_sign(direction: str | int | None) -> int:
    """+1 for a fill campaign, -1 for a drain campaign."""
    if direction is None:
        return FILL
    if isinstance(direction, int) and direction in (FILL, DRAIN):
        return direction
    key = str(direction).strip().lower()
    if key not in DIRECTIONS:
        raise ValueError(f"direction must be 'fill' or 'drain', got {direction!r}")
    return DIRECTIONS[key]


def direction_name(sign: int) -> str:
    return "drain" if sign == DRAIN else "fill"


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
    direction: int = FILL  # +1 fill (level rises), -1 drain (level falls)
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
    def travel(self) -> float:
        """Level change in the campaign direction: the rise of a fill, the fall of a drain."""
        return self.direction * (self.h_cur - self.h_prev)

    @property
    def rise(self) -> float:
        """Alias of ``travel``.  For a drain it is the fall, positive."""
        return self.travel

    @property
    def h_lo(self) -> float:
        return min(self.h_prev, self.h_cur)

    @property
    def h_hi(self) -> float:
        return max(self.h_prev, self.h_cur)

    def predicted(self, shell) -> float:
        """Shell volume moved by this step: ``direction * (F(h_cur) - F(h_prev))``."""
        return self.direction * float(shell.volume(self.h_cur) - shell.volume(self.h_prev))


def infer_direction(rows: list[Row]) -> int:
    """The campaign direction the heights show: most steps rise or most fall.

    A first-row note that says ``drain`` decides it when the heights do not.
    """
    ups = sum(1 for a, b in pairwise(rows) if b.height > a.height)
    downs = sum(1 for a, b in pairwise(rows) if b.height < a.height)
    if downs > ups:
        return DRAIN
    if ups > downs:
        return FILL
    return DRAIN if rows and "drain" in rows[0].note.lower() else FILL


def build_intervals(rows: list[Row], direction: int | str = FILL) -> list[Interval]:
    """One interval per step: from the previous dip to this dip."""
    sign = direction_sign(direction)
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
                direction=sign,
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

    Excluded: unknown/partial steps, intervals that touch the neck (the
    overflow interval of a fill, the neck interval of a drain), non-positive
    travel, declared object bands, and explicit row exclusions.
    """
    bands = object_bands or []
    excluded_rows = excluded_rows or set()
    for iv in intervals:
        iv.trusted, iv.reason = True, ""
        drain = iv.direction == DRAIN
        if not iv.known:
            iv.trusted, iv.reason = False, "unknown drain" if drain else "unknown pour"
            continue
        if iv.h_hi > brim:
            iv.trusted, iv.reason = False, "neck interval" if drain else "overflow interval"
            continue
        if iv.travel <= 0:
            iv.trusted, iv.reason = False, "non-positive fall" if drain else "non-positive rise"
            continue
        if iv.row in excluded_rows:
            iv.trusted, iv.reason = False, "excluded row"
            continue
        for band in bands:
            lo, hi = float(band["low"]), float(band["high"])
            if iv.h_hi >= lo and iv.h_lo <= hi:
                iv.trusted, iv.reason = False, f"object band {lo:g}-{hi:g} mm"
                break


def trusted(intervals: list[Interval]) -> list[Interval]:
    return [iv for iv in intervals if iv.trusted]

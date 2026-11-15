"""Campaign JSON scaffold and preflight.

``calib init`` writes a campaign file from the raw CSV.  It infers what the
data knows and asks only for the tank record.  ``calib check`` resolves an
existing file without running the fit.
"""

from __future__ import annotations

import json
import math
import os
from itertools import pairwise
from pathlib import Path

from .config import load_config
from .data import (
    DRAIN,
    Row,
    apply_corrections,
    build_intervals,
    direction_name,
    direction_sign,
    infer_direction,
    mark_trusted,
    read_raw,
)
from .geometry import Shell

_SUFFIXES = ("_raw", "_data")


def tank_stem(raw_path: str | Path) -> str:
    """The tank name a raw file suggests: ``run1_raw.csv`` -> ``run1``."""
    stem = Path(raw_path).stem
    for suffix in _SUFFIXES:
        if stem.lower().endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _nominal_brim(r: float) -> float:
    return 2.0 * r


def infer_pour_unit(rows: list[Row], r: float) -> float | None:
    """The largest increment that divides the known, non-overflow pours."""
    brim = _nominal_brim(r)
    values = []
    for row in rows:
        if not row.step.known:
            continue
        note = row.note.lower()
        if row.height > brim or "overflow" in note or "neck" in note:
            continue
        values.append(float(row.step.value))
    if len(values) < 2:
        return None
    ints = [round(v) for v in values]
    if any(abs(v - i) > 0.01 for v, i in zip(values, ints)):
        return None
    unit = 0
    for value in ints:
        unit = math.gcd(unit, value)
    if unit <= 0:
        return None
    smallest = min(ints)
    if unit * 2 <= smallest:
        return float(smallest)
    return float(unit)


def infer_overflow(rows: list[Row], r: float) -> float | None:
    """The pour of the last row that overflowed, if the data says so."""
    for row in reversed(rows):
        if row.step.known and "overflow" in row.note.lower():
            return float(row.step.value)
    last = rows[-1]
    if last.step.known and last.height > _nominal_brim(r):
        return float(last.step.value)
    return None


def infer_neck_drain(rows: list[Row], r: float) -> float | None:
    """The drain out of the neck into the shell, if the data says so (§5.3a).

    The site marks the first shell level after a neck start with
    ``neck interval``.  Without the note: the first known drain that ends
    at or below the nominal brim after a row above it.
    """
    for row in rows:
        if row.step.known and "neck interval" in row.note.lower():
            return float(row.step.value)
    brim = _nominal_brim(r)
    for prev, row in pairwise(rows):
        if prev.height > brim >= row.height:
            return float(row.step.value) if row.step.known else None
    return None


def infer_neck_entrance(rows: list[Row]) -> float | None:
    """The brim reading of a drain that starts at the neck entrance."""
    first = rows[0]
    if "neck entrance" in first.note.lower():
        return float(first.height)
    return None


def infer_heel(rows: list[Row], r: float, L: float) -> bool:
    """True when the first pour is far below the volume at the first dip."""
    first = rows[0]
    if not first.step.known or first.height <= 0:
        return False
    volume = float(Shell(r, L, 0.0).volume(first.height))
    return float(first.step.value) < 0.5 * volume


def unknown_pours(rows: list[Row]) -> list[dict]:
    """The 1-based rows whose pour is unknown or partial."""
    return [
        {"row": i, "raw": row.step.raw or "?"}
        for i, row in enumerate(rows, start=1)
        if not row.step.known
    ]


def scan_rows(rows: list[Row], r: float, L: float, direction: int | str = 1) -> list[str]:
    """Structural warnings a reader should see before the first fit."""
    warnings: list[str] = []
    drain = direction_sign(direction) == DRAIN
    for i, row in enumerate(rows, start=1):
        if i == 1:
            continue
        prev = rows[i - 2].height
        if drain and row.height >= prev:
            warnings.append(
                f"row {i}: height {row.height:g} mm does not fall below row {i - 1}"
            )
        elif not drain and row.height <= prev:
            warnings.append(
                f"row {i}: height {row.height:g} mm does not rise above row {i - 1}"
            )
    seen: dict[float, int] = {}
    for i, row in enumerate(rows, start=1):
        if row.height in seen:
            warnings.append(
                f"row {i}: height {row.height:g} mm repeats row {seen[row.height]}"
            )
        else:
            seen[row.height] = i
    if drain:
        first = rows[0]
        if first.height > _nominal_brim(r):
            warnings.append(
                f"row 1: height {first.height:g} mm is above the nominal brim "
                f"{_nominal_brim(r):g} mm: the drain starts in the neck; check "
                "brim.neck_drain"
            )
        return warnings
    last = rows[-1]
    if last.height > _nominal_brim(r):
        warnings.append(
            f"row {len(rows)}: height {last.height:g} mm is above the nominal "
            f"brim {_nominal_brim(r):g} mm; check brim.reading and "
            "brim.overflow_pour"
        )
    if infer_heel(rows, r, L):
        warnings.append(
            "the first pour is far below the volume at the first dip; the tank "
            "may start with a heel (set heel_row true)"
        )
    return warnings


def infer_config(
    raw_path: str | Path,
    *,
    r: float,
    L: float,
    tank: str | None = None,
    site: str = "",
    sigma_h: float = 1.5,
    pour_unit: float | None = None,
    brim: float | None = None,
    overflow_pour: float | None = None,
    heel_row: bool | None = None,
    direction: str | None = None,
) -> tuple[dict, list[str]]:
    """Build a campaign dict from the raw CSV and the tank record.

    ``None`` for ``pour_unit``, ``overflow_pour``, ``heel_row`` or
    ``direction`` means: infer it from the data.  A fill never infers
    ``brim``; a missing brim is refined by the fit from the shell.  A drain
    whose first row says ``at neck entrance`` reads the brim there (§3.11).
    """
    raw_path = Path(raw_path)
    rows = read_raw(raw_path)
    if r <= 0 or L <= 0:
        raise ValueError("r and L must be positive")
    if sigma_h <= 0:
        raise ValueError("sigma_h must be positive")

    sign = infer_direction(rows) if direction is None else direction_sign(direction)
    drain = sign == DRAIN
    inferred_unit = infer_pour_unit(rows, r)
    inferred_overflow = infer_neck_drain(rows, r) if drain else infer_overflow(rows, r)
    inferred_heel = False if drain else infer_heel(rows, r, L)

    unit = inferred_unit if pour_unit is None else float(pour_unit)
    overflow = inferred_overflow if overflow_pour is None else float(overflow_pour)
    heel = inferred_heel if heel_row is None else bool(heel_row)
    neck_entrance = infer_neck_entrance(rows) if drain else None
    if drain and brim is None and neck_entrance is not None:
        brim = neck_entrance

    data: dict = {
        "tank": tank or tank_stem(raw_path),
        "site": site,
        "table_version": "v1",
        "supersedes": "none",
        "raw": raw_path.name,
        "direction": direction_name(sign),
        "nominal": {"r": float(r), "L": float(L)},
        "sigma_h": float(sigma_h),
        "pour_noise": {"rel": 0.005, "abs": 3.0},
        "h0": {"mode": "fit"},
        "heel_row": heel,
        "object_bands": [],
        "corrections": [],
        "exclude": [],
        "strapping": {"step_mm": 10.0, "start_mm": 0.0},
        "bootstrap_n": 200,
        "seed": 0,
    }
    if unit is not None:
        data["pour_unit"] = float(unit)
    brim_data: dict = {}
    if brim is not None:
        brim_data["reading"] = float(brim)
    if overflow is not None:
        brim_data["neck_drain" if drain else "overflow_pour"] = float(overflow)
    if drain and neck_entrance is not None and brim == neck_entrance:
        # The start reading at the neck entrance is the shell crown (§5.3a).
        brim_data["neck_equality"] = True
    if brim_data:
        data["brim"] = brim_data

    warnings = scan_rows(rows, r, L, sign)
    if drain and direction is None:
        warnings.insert(0, "direction: drain (the heights fall); give --direction to override")
    for item in unknown_pours(rows):
        warnings.insert(0, f"row {item['row']}: pour is unknown ({item['raw']})")
    if inferred_unit is not None and unit != inferred_unit:
        warnings.append(
            f"pour_unit {unit:g} L overrides the inferred {inferred_unit:g} L"
        )
    return data, warnings


def _relative_raw(base: Path, raw: Path) -> str:
    try:
        rel = os.path.relpath(raw.resolve(), base.resolve())
    except ValueError:  # different drives on Windows
        return str(raw.resolve())
    return rel.replace(os.sep, "/")


def write_config(
    path: str | Path,
    data: dict,
    *,
    force: bool = False,
    raw_path: str | Path | None = None,
) -> Path:
    """Write a campaign file.  Refuse to replace one without ``force``."""
    path = Path(path)
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists; use --force to replace it")
    payload = dict(data)
    if raw_path is not None:
        payload["raw"] = _relative_raw(path.parent, Path(raw_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def preflight(config_path: str | Path) -> dict:
    """Resolve a campaign file and report what the fit will trust."""
    cfg = load_config(config_path)
    rows = read_raw(cfg.raw)
    corrected = apply_corrections(rows, cfg.corrections)
    intervals = build_intervals(corrected, cfg.sign)
    brim = (
        cfg.brim_reading
        if cfg.brim_reading is not None
        else cfg.h0_value + 2.0 * cfg.nominal_r
    )
    mark_trusted(
        intervals,
        brim=brim,
        object_bands=cfg.object_bands,
        excluded_rows=cfg.excluded_interval_rows,
    )
    untrusted = [
        {"row": iv.row + 1, "reason": iv.reason}
        for iv in intervals
        if not iv.trusted
    ]
    corrections = [
        {
            "row": c.row,
            "field": c.field,
            "value": c.value,
            "rule": c.rule,
            "magnitude": c.magnitude,
        }
        for c in cfg.corrections
    ]
    warnings = scan_rows(corrected, cfg.nominal_r, cfg.nominal_L, cfg.sign)
    if cfg.heel_row:
        warnings = [w for w in warnings if "heel_row true" not in w]
    if cfg.brim_reading is not None and cfg.overflow_pour is not None:
        warnings = [w for w in warnings if "above the nominal brim" not in w]
    if cfg.drain and cfg.overflow_pour is not None:
        warnings = [w for w in warnings if "starts in the neck" not in w]
    return {
        "config": cfg,
        "rows": len(rows),
        "intervals": len(intervals),
        "trusted": sum(1 for iv in intervals if iv.trusted),
        "untrusted": untrusted,
        "unknown_pours": unknown_pours(corrected),
        "corrections": corrections,
        "warnings": warnings,
        "brim": brim,
    }

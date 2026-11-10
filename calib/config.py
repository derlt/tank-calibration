"""Campaign configuration: one JSON file per tank."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .data import Correction


@dataclass
class Config:
    tank: str
    raw: str
    nominal_r: float
    nominal_L: float
    sigma_h: float = 1.5
    pour_rel: float = 0.005
    pour_abs: float = 3.0
    pour_unit: float | None = None
    h0_mode: str = "fit"  # "fit" | "locked"
    h0_value: float = 0.0
    heel_row: bool = False
    brim_reading: float | None = None
    overflow_pour: float | None = None
    vent_volume: float = 0.0
    neck_equality: bool = False
    object_bands: list[dict] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)
    excluded_rows: set[int] = field(default_factory=set)
    blocking: dict = field(default_factory=dict)
    tilt_test: bool = False
    joint: dict | None = None
    strapping: dict = field(default_factory=dict)
    bootstrap_n: int = 200
    seed: int = 0
    lag_checks: list[dict] = field(default_factory=list)
    notes: str = ""

    @property
    def nominal(self) -> dict:
        return {"r": self.nominal_r, "L": self.nominal_L}

    @property
    def excluded_interval_rows(self) -> set[int]:
        """0-based Interval.row values from the 1-based config rows."""
        return {int(r) - 1 for r in self.excluded_rows}

    def validate(self) -> None:
        if self.nominal_r <= 0 or self.nominal_L <= 0:
            raise ValueError("nominal r and L must be positive")
        if self.sigma_h <= 0:
            raise ValueError("sigma_h must be positive")
        if self.h0_mode not in ("fit", "locked"):
            raise ValueError("h0 mode must be 'fit' or 'locked'")
        if self.pour_rel < 0 or self.pour_abs < 0:
            raise ValueError("pour noise must be non-negative")
        for band in self.object_bands:
            if "low" not in band or "high" not in band:
                raise ValueError("object band needs 'low' and 'high' (mm)")
            if band["high"] <= band["low"]:
                raise ValueError("object band high must exceed low")
        if any(int(r) < 1 for r in self.excluded_rows):
            raise ValueError("exclude rows are 1-based data rows")


def _get(d, *keys, default=None):
    for key in keys:
        if isinstance(d, dict) and key in d:
            return d[key]
    return default


def load_config(path: str | Path) -> Config:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent

    raw = _get(data, "raw", "data", default="")
    if not raw:
        raise ValueError(f"{path}: 'raw' is required")
    raw_path = Path(raw)
    if not raw_path.is_absolute():
        raw_path = (base / raw_path).resolve()

    nominal = _get(data, "nominal", default={}) or {}
    r_nom = _get(nominal, "r", "radius", default=_get(data, "nominal_r"))
    l_nom = _get(nominal, "L", "length", default=_get(data, "nominal_L"))
    if r_nom is None or l_nom is None:
        raise ValueError(f"{path}: nominal r and L are required")

    h0 = _get(data, "h0", default={}) or {}
    if isinstance(h0, (int, float)):
        h0 = {"mode": "locked", "value": float(h0)}

    brim = _get(data, "brim", default={}) or {}
    if isinstance(brim, (int, float)):
        brim = {"reading": float(brim)}

    pour = _get(data, "pour_noise", "pour", default={}) or {}

    corrections = []
    for item in _get(data, "corrections", default=[]) or []:
        corrections.append(
            Correction(
                row=int(item["row"]),
                field=item.get("field", "height"),
                value=float(item["value"]),
                rule=item.get("rule", ""),
                magnitude=float(item.get("magnitude", 0.0)),
                note=item.get("note", ""),
            )
        )

    excluded = set()
    for item in _get(data, "exclude", "excluded_rows", default=[]) or []:
        excluded.add(int(item["row"] if isinstance(item, dict) else item))

    cfg = Config(
        tank=_get(data, "tank", "id", default=path.stem),
        raw=str(raw_path),
        nominal_r=float(r_nom),
        nominal_L=float(l_nom),
        sigma_h=float(_get(data, "sigma_h", default=1.5)),
        pour_rel=float(_get(pour, "rel", default=0.005)),
        pour_abs=float(_get(pour, "abs", default=3.0)),
        pour_unit=(
            float(_get(data, "pour_unit"))
            if _get(data, "pour_unit") is not None
            else None
        ),
        h0_mode=str(_get(h0, "mode", default="fit")),
        h0_value=float(_get(h0, "value", default=0.0)),
        heel_row=bool(_get(data, "heel_row", default=False)),
        brim_reading=(
            float(_get(brim, "reading"))
            if _get(brim, "reading") is not None
            else None
        ),
        overflow_pour=(
            float(_get(brim, "overflow_pour"))
            if _get(brim, "overflow_pour") is not None
            else None
        ),
        vent_volume=float(_get(brim, "vent_volume", default=0.0)),
        neck_equality=bool(_get(brim, "neck_equality", default=False)),
        object_bands=list(_get(data, "object_bands", default=[]) or []),
        corrections=corrections,
        excluded_rows=excluded,
        blocking=dict(_get(data, "blocking", default={}) or {}),
        tilt_test=bool(_get(data, "tilt_test", default=False)),
        joint=_get(data, "joint"),
        strapping=dict(_get(data, "strapping", default={}) or {}),
        bootstrap_n=int(_get(data, "bootstrap_n", default=200)),
        seed=int(_get(data, "seed", default=0)),
        lag_checks=list(_get(data, "lag_checks", default=[]) or []),
        notes=_get(data, "notes", default=""),
    )
    cfg.validate()
    return cfg

#!/usr/bin/env python3
"""Generate a synthetic DRAIN demo campaign with known truth (§3.11).

The tank starts full, with liquid standing in the neck.  A pump draws the
water out into cans; each row is the litres of one batch and the level
after it.  The campaign exercises the drain path of the whole method: a
start in the neck (the first drain bounds the brim gap, §5.3a), a declared
object band, a misread dip, an unknown drain, and a part can at the end.
The truth is written to ``demo_drain_truth.json``.

    uv run python examples/make_demo_drain.py
    uv run python -m calib fit examples/demo_drain.json -o out/demo_drain
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from calib.geometry import Shell  # noqa: E402

TRUE_R = 900.0
TRUE_L = 3000.0
TRUE_H0 = -5.0
SIGMA_H = 1.0
POUR_REL = 0.003
POUR_ABS = 1.0
OBJECT_L = 30.0
OBJECT_AT_MM = 1000.0  # the solid fills the band 990-1000 mm
NECK_L = 25.0  # liquid above the crown at the start (unknown to the fit)
NECK_MM = 40.0  # neck reading above the brim
NECK_DRAIN = 150.0  # first drain: out of the neck into the shell

DRAINS = [
    50, 50, 100, 100, 150, 150, 200, 200, 300, 300,
    400, 400, 500, 500, 600, 600, 700, 600, 500, 400, 300, 200,
]
MISREAD_ROW = 12  # 1-based data row
MISREAD_MM = 4.0
UNKNOWN_ROW = 16  # 1-based data row
PART_CAN = 37.0  # the pump loses suction during the last can


def height_for(shell: Shell, liquid: float, displacement: float) -> float:
    brim = shell.brim()

    def residual(h):
        return float(shell.volume(h)) - displacement - liquid

    return brentq(residual, 0.0, brim - 1e-6)


def liquid_height(shell: Shell, liquid: float) -> float:
    """Level of ``liquid`` litres, with the solid in its band."""
    h = height_for(shell, liquid, OBJECT_L)
    if h < OBJECT_AT_MM:
        # Below the solid's top: the band is only part blocked.  Search with
        # the band volume taken out where the level crosses it.
        def residual(x):
            blocked = OBJECT_L * min(max((x - (OBJECT_AT_MM - 10.0)) / 10.0, 0.0), 1.0)
            return float(shell.volume(x)) - blocked - liquid

        h = brentq(residual, 0.0, shell.brim() - 1e-6)
    return h


def campaign(seed: int = 7) -> tuple[list[list[str]], dict]:
    shell = Shell(TRUE_R, TRUE_L, TRUE_H0)
    brim = shell.brim()
    rng = np.random.default_rng(seed)
    # Every solid lies below a full tank: the liquid is the shell less it.
    liquid = shell.capacity() - OBJECT_L + NECK_L
    rows = [["?", f"{brim + NECK_MM + rng.normal(0.0, SIGMA_H):.1f}", "drain campaign; neck level"]]

    liquid -= NECK_DRAIN
    h = liquid_height(shell, liquid)
    rows.append([f"{NECK_DRAIN:g}", f"{h + rng.normal(0.0, SIGMA_H):.1f}", "neck interval"])

    for i, drain in enumerate(DRAINS, start=3):
        actual = drain + rng.normal(0.0, POUR_REL * drain + POUR_ABS) * 0.6
        liquid -= actual
        h = liquid_height(shell, liquid)
        h_rec = h + rng.normal(0.0, SIGMA_H)
        note = ""
        if i == MISREAD_ROW:
            h_rec += MISREAD_MM
            note = "dip read once"
        cell = f"{drain:g}"
        if i == UNKNOWN_ROW:
            cell = "?"
            note = (note + "; " if note else "") + "can count lost"
        rows.append([cell, f"{h_rec:.1f}", note])

    # The pump loses suction: 100 L of full cans, then a part can.
    liquid -= 100.0 + PART_CAN
    h = liquid_height(shell, liquid)
    rows.append(["100+?", f"{h + rng.normal(0.0, SIGMA_H):.1f}", "pump lost suction: last can part"])

    misread_true = float(rows[MISREAD_ROW - 1][1]) - MISREAD_MM
    truth = {
        "r": TRUE_R, "L": TRUE_L, "h0": TRUE_H0, "brim": brim,
        "capacity": shell.capacity(), "object_l": OBJECT_L,
        "object_band_mm": [OBJECT_AT_MM - 10.0, OBJECT_AT_MM],
        "neck_l": NECK_L, "neck_drain": NECK_DRAIN,
        "misread_row": MISREAD_ROW, "misread_mm": MISREAD_MM,
        "misread_true_mm": round(misread_true, 1),
        "unknown_row": UNKNOWN_ROW, "unknown_l": DRAINS[UNKNOWN_ROW - 3],
        "part_can_l": PART_CAN, "end_liquid_l": liquid,
        "sigma_h": SIGMA_H, "pour_rel": POUR_REL, "pour_abs": POUR_ABS,
    }
    return rows, truth


def config(raw_name: str, truth: dict) -> dict:
    return {
        "tank": "demo_drain",
        "raw": raw_name,
        "direction": "drain",
        "nominal": {"r": 880.0, "L": 2950.0},
        "sigma_h": SIGMA_H,
        "pour_noise": {"rel": POUR_REL, "abs": POUR_ABS},
        "pour_unit": 50.0,
        "h0": {"mode": "fit"},
        "heel_row": False,
        "brim": {"neck_drain": NECK_DRAIN},
        "object_bands": [
            {
                "low": OBJECT_AT_MM - 10.0,
                "high": OBJECT_AT_MM,
                "litres": OBJECT_L,
                "label": "demo solid",
                "test": "inspect the empty tank",
            }
        ],
        "corrections": [
            {
                "row": MISREAD_ROW,
                "field": "height",
                "value": truth["misread_true_mm"],
                "rule": "6.1",
                "magnitude": -MISREAD_MM,
                "note": "demo: dip misread by +4 mm",
            }
        ],
        "strapping": {"step_mm": 10.0, "start_mm": 0.0},
        "bootstrap_n": 150,
        "seed": 11,
        "notes": "Synthetic drain campaign with known truth. See demo_drain_truth.json.",
    }


def write(outdir: Path, *, seed: int = 7) -> Path:
    """Write the raw CSV, the campaign JSON and the truth; return the JSON path."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    rows, truth = campaign(seed)
    raw = outdir / "demo_drain_raw.csv"
    with raw.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["step_volume", "measured_height", "note"])
        writer.writerows(rows)
    cfg_path = outdir / "demo_drain.json"
    cfg_path.write_text(json.dumps(config(raw.name, truth), indent=2) + "\n", encoding="utf-8")
    (outdir / "demo_drain_truth.json").write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    return cfg_path


def main() -> None:
    path = write(HERE)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

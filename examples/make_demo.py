#!/usr/bin/env python3
"""Generate a synthetic demo campaign with known truth.

The campaign exercises the whole method: a misread dip, a declared object
band, an unknown pour, and an overflow pour.  The truth is written to
``demo_truth.json`` so a reader can check what the fit recovers.
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
OBJECT_AT_MM = 1000.0
OVERFLOW_POUR = 120.0

POURS = [
    50, 50, 100, 100, 150, 150, 200, 200, 300, 300,
    400, 400, 500, 500, 600, 600, 700, 700, 800, 700, 50,
]
MISREAD_ROW = 12  # 1-based data row
MISREAD_MM = 4.0
UNKNOWN_ROW = 16  # 1-based data row


def height_for(shell: Shell, liquid: float, displacement: float) -> float:
    brim = shell.brim()

    def residual(h):
        return float(shell.volume(h)) - displacement - liquid

    return brentq(residual, 0.0, brim - 1e-6)


def main() -> None:
    shell = Shell(TRUE_R, TRUE_L, TRUE_H0)
    brim = shell.brim()
    rng = np.random.default_rng(7)

    rows = []
    cumulative = 0.0
    for i, pour in enumerate(POURS, start=1):
        cumulative += pour
        h = height_for(shell, cumulative, 0.0)
        if h >= OBJECT_AT_MM:
            h = height_for(shell, cumulative, OBJECT_L)
        h_rec = h + rng.normal(0.0, SIGMA_H)
        note = ""
        if i == MISREAD_ROW:
            h_rec += MISREAD_MM
            note = "dip read once"
        step_cell = "?" if i == UNKNOWN_ROW else f"{pour:g}"
        if i == UNKNOWN_ROW:
            note = (note + "; " if note else "") + "can count lost"
        rows.append([step_cell, f"{h_rec:.1f}", note])

    # Overflow pour: the field reached the vent.
    rows.append([f"{OVERFLOW_POUR:g}", f"{brim + 45.0:.1f}", "overflow: vent liquid"])

    raw = HERE / "demo_raw.csv"
    with raw.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["step_volume", "measured_height", "note"])
        writer.writerows(rows)

    config = {
        "tank": "demo",
        "raw": "demo_raw.csv",
        "nominal": {"r": 880.0, "L": 2950.0},
        "sigma_h": SIGMA_H,
        "pour_noise": {"rel": POUR_REL, "abs": POUR_ABS},
        "pour_unit": 50.0,
        "h0": {"mode": "fit"},
        "heel_row": False,
        "brim": {"reading": round(brim, 1), "overflow_pour": OVERFLOW_POUR},
        "object_bands": [
            {
                "low": OBJECT_AT_MM - 10.0,
                "high": OBJECT_AT_MM,
                "litres": OBJECT_L,
                "label": "demo solid",
                "test": "repeat pour into the band",
            }
        ],
        "corrections": [
            {
                "row": MISREAD_ROW,
                "field": "height",
                "value": round(float(rows[MISREAD_ROW - 1][1]) - MISREAD_MM, 1),
                "rule": "6.1",
                "magnitude": -MISREAD_MM,
                "note": "demo: dip misread by +4 mm",
            }
        ],
        "strapping": {"step_mm": 10.0, "start_mm": 0.0},
        "bootstrap_n": 150,
        "seed": 11,
        "notes": "Synthetic campaign with known truth. See demo_truth.json.",
    }
    (HERE / "demo.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    truth = {
        "r": TRUE_R,
        "L": TRUE_L,
        "h0": TRUE_H0,
        "capacity": shell.capacity(),
        "brim": brim,
        "object_l": OBJECT_L,
        "object_at_mm": OBJECT_AT_MM,
        "misread_row": MISREAD_ROW,
        "misread_mm": MISREAD_MM,
        "unknown_row": UNKNOWN_ROW,
        "overflow_pour": OVERFLOW_POUR,
        "sigma_h": SIGMA_H,
        "pour_rel": POUR_REL,
        "pour_abs": POUR_ABS,
    }
    (HERE / "demo_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(f"wrote {raw} and demo.json; truth: r={TRUE_R} L={TRUE_L} h0={TRUE_H0}")
    print(f"capacity {shell.capacity():.1f} L, brim {brim:.1f} mm")


if __name__ == "__main__":
    main()

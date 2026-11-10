# Tank calibration

Calibrate a horizontal, flat-ended cylindrical tank from pour and level data.
The package implements [CALIBRATION_METHODOLOGY.md](CALIBRATION_METHODOLOGY.md) end to end.

**Python owns the numbers. Excel shows them.** The fit, the uncertainty, the
anomaly register and the charts come from Python. The workbook is a
values-only delivery layer, plus an optional live-formula audit sheet.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Python 3.10 or newer. Dependencies: numpy, scipy, matplotlib, openpyxl.

## Quick start

```bash
# 1. Generate the synthetic demo campaign (known truth).
python examples/make_demo.py

# 2. Fit, diagnose, and write every deliverable.
python -m calib fit examples/demo.json -o out/demo

# 3. Check the workbook formulas.
python -m calib gate out/demo/demo_workbook.xlsx

# 4. Validate a new field run against the adopted shell.
python -m calib field out/demo/demo_presets.json examples/demo_raw.csv
```

The fit prints the adopted shell record and the six acceptance checks. It
exits with code 2 if any check fails.

## Commands

| Command | Purpose |
|---|---|
| `calib fit CONFIG -o DIR` | Run the full pipeline for one tank. |
| `calib field PRESETS CSV` | Per-pour z-test against an adopted shell (§10). |
| `calib field PRESETS --interactive` | Type pours one at a time. |
| `calib joint CONFIG...` | One common `r`, separate lengths (§5.4). |
| `calib gate WORKBOOK` | Formula gate over every cell (§11). |

## What the fit writes

For tank `X` in the output directory:

| File | Content |
|---|---|
| `X_raw.csv` | Byte copy of the source. The source is never edited. |
| `X_corrected.csv` | Corrections flagged with rule and magnitude. |
| `X_strapping.csv` | Authoritative table: level, liquid, ±σ, flag. |
| `X_commercial.csv` | Fixed interval, whole litres, extrapolated region labelled. |
| `X_anomaly_register.csv` | Object bands, dip pairs, single-sided events, watch items, unknowns. |
| `X_shell_record.txt` | The adopted-shell record of §11. |
| `X_presets.json` | The adopted shell for the field tool. One source of truth. |
| `X_workbook.xlsx` | Values-only workbook, plus the optional Audit sheet. The Audit objective sums the trusted set only. |
| `X_report.md` | Shell record, acceptance table, register, limitations. |
| `charts/` | The seven views of §6.6, plus the `r` profile. |

## Configuration

One JSON file per tank. Paths are relative to the JSON file.

```json
{
  "tank": "tankA",
  "raw": "tankA_raw.csv",
  "nominal": {"r": 948.0, "L": 2517.0},
  "sigma_h": 1.5,
  "pour_noise": {"rel": 0.005, "abs": 3.0},
  "pour_unit": 50,
  "h0": {"mode": "fit"},
  "heel_row": true,
  "brim": {"reading": 1896.0, "overflow_pour": 50.0},
  "object_bands": [
    {"low": 1397, "high": 1444, "litres": 44.0, "label": "solid"}
  ],
  "corrections": [
    {"row": 12, "field": "height", "value": 853.0,
     "rule": "6.1", "magnitude": -4.0, "note": "dip misread"}
  ],
  "exclude": [{"row": 30}],
  "blocking": {"enabled": false, "target_rise_mm": 30.0},
  "tilt_test": false,
  "lag_checks": [
    {"at_mm": 1200, "readings": [[1, 1201.0], [10, 1202.5]]}
  ],
  "strapping": {"step_mm": 10.0, "start_mm": 0.0},
  "bootstrap_n": 200,
  "seed": 0
}
```

Notes:

- `raw` is read-only. Corrections live in `corrections`, never in the raw file.
- `corrections` and `exclude` use 1-based data rows (the header is not a row).
- A step cell may be a number, `?` (whole pour unknown), or `200+?`
  (200 L plus an unknown extra). `x1`/`x2` are read as unknown pours.
- `object_bands` are level ranges. `litres` is the displacement in that band.
  If omitted, the net residual over the band estimates it.
- `brim.reading` is the tape reading at the shell crown. `overflow_pour` is the
  pour that overflowed. The fit then enforces `G <= P` inside the fit.
- `h0.mode` is `fit` or `locked`. A locked datum reports its cost.
- `tilt_test` adds the tilt parameter of §5.5 and keeps it only if the F-test
  and plausibility both pass.

## How the pieces map to the method

See `FEATURES.md` for a section-by-section map.

Short version:

- `calib/geometry.py` — §4 geometry, optional tilt.
- `calib/data.py` — raw reading, step cells, corrections, trusted set.
- `calib/fit.py` — difference fit, multi-start, Huber, brim constraint, joint
  fit, profiles, lock cost, tilt test, bootstrap, GLS.
- `calib/diagnostics.py` — action bar, pair rule, object bookkeeping, closure,
  noise split, telescoping blocks, multiple comparisons, detector views.
- `calib/quantized.py` — pour-unit grid search for superposed errors.
- `calib/blocking.py` — interval blocking for small pours.
- `calib/unknowns.py` — back-prediction, one σ formula, sensitivity battery.
- `calib/field.py` — live per-pour protocol.
- `calib/report.py` — strapping table, commercial chart, register, shell record.
- `calib/charts.py` — the seven views.
- `calib/workbook.py` — values-only workbook and audit sheet.
- `calib/formula_gate.py` — parenthesis balance, formula parse, single-sheet ranges.
- `calib/pipeline.py` — orchestration and acceptance checks.

## Examples

| Config | What it exercises |
|---|---|
| `examples/demo.json` | Known truth: misread dip, object band, unknown pour, overflow. |

`examples/demo_truth.json` holds the truth for the synthetic campaign. The fit
recovers it within the quoted uncertainty.

## Tests

```bash
python -m unittest discover -s tests -v
```

48 tests cover geometry, step parsing, corrections, the trusted set, fit
recovery, the pair rule, object bookkeeping, noise split, telescoping blocks,
blocking, unknowns, the field protocol, the formula gate, a locked datum
(with and without an overflow), the audit objective, and an end-to-end run
with the workbook gate.

## Limits

The method states its own limits in §12. The package records them; it does not
hide them. In particular:

- Tape scale is unidentifiable from pour and level data.
- Object versus pour error is not separable from one pass.
- A static tilt is tested only when `tilt_test` is true.
- `r` is an effective mean; ovality is not modelled.

A fit is adopted only when all six checks of §5.7 pass. The workbook and the
commercial chart say so when they do not.

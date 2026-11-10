# Tank calibration

Calibrate a horizontal, flat-ended cylindrical tank from pour and level data.
The package implements [CALIBRATION_METHODOLOGY.md](CALIBRATION_METHODOLOGY.md) end to end.

**Python owns the numbers. Excel shows them.** The fit, the uncertainty, the
anomaly register and the charts come from Python. The workbook is a
values-only delivery layer, plus an optional live-formula audit sheet.

## Install

On Windows, install Git and uv first:

```powershell
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
```

If `winget` is not available, install uv with:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Clone the repository, then install:

```bash
git clone https://github.com/derlt/tank-calibration.git
cd tank-calibration
uv sync
```

`uv` creates `.venv` and installs the runtime and development dependencies
pinned in `uv.lock`. Use `uv sync --no-dev` for the runtime only.
Python 3.10 or newer. Runtime dependencies: numpy, scipy, matplotlib, openpyxl.

## Quick start

```bash
# 1. Generate the synthetic demo campaign (known truth).
uv run python examples/make_demo.py

# 2. Fit, diagnose, and write every deliverable.
uv run python -m calib fit examples/demo.json -o out/demo

# 3. Check the workbook formulas.
uv run python -m calib gate out/demo/demo_workbook.xlsx

# 4. Validate a new field run against the adopted shell.
uv run python -m calib field out/demo/demo_presets.json examples/demo_raw.csv
```

`uv run` uses the project environment, so you do not need to activate it.

The fit prints the adopted shell record and the six acceptance checks. It
exits with code 2 if any check fails.

## Real data

The demo shows the shape of a run. A real tank needs one folder with one CSV
and one JSON file:

```text
C:\tank-data\run1\
    run1_raw.csv
    run1.json
```

The examples use Windows paths. On Linux or macOS, use the same commands with
your own paths.

The CSV holds the pours and dips:

```csv
step_volume,measured_height,note
50,62,
50,90,
100,134,
100,166,
150,205,
```

- `step_volume` is the pour since the previous dip, in litres. It is not
  cumulative.
- `measured_height` is the dip reading in mm.
- The first row is the datum. If the tank was not empty, set `heel_row` to
  `true` and record the heel.
- A whole unknown pour is `?`. A partial unknown is `200+?`.
- The raw file is never edited. Corrections go in the JSON.

The JSON names the tank, the raw file and the decisions:

```json
{
  "tank": "run1",
  "raw": "run1_raw.csv",
  "nominal": {"r": 948.0, "L": 2517.0},
  "sigma_h": 1.5,
  "pour_unit": 50,
  "h0": {"mode": "fit"},
  "heel_row": false,
  "brim": {"reading": 1896.0, "overflow_pour": 50.0},
  "object_bands": [],
  "strapping": {"step_mm": 10.0, "start_mm": 0.0},
  "bootstrap_n": 200,
  "seed": 0
}
```

Fill the values from the tank record. [Configuration](#configuration) explains
every field.

Run the fit from the repo root:

```powershell
uv run python -m calib fit C:\tank-data\run1\run1.json -o C:\tank-data\run1\out
```

Or from any folder, with `--project`:

```powershell
uv run --project C:\src\tank-calibration python -m calib fit C:\tank-data\run1\run1.json -o C:\tank-data\run1\out
```

The fit prints the adopted shell and the six acceptance checks. It exits with
code 2 if any check fails. [What the fit writes](#what-the-fit-writes) lists
the files.

Gate the workbook and check the field data:

```powershell
uv run --project C:\src\tank-calibration python -m calib gate C:\tank-data\run1\out\run1_workbook.xlsx
uv run --project C:\src\tank-calibration python -m calib field C:\tank-data\run1\out\run1_presets.json C:\tank-data\run1\run1_raw.csv
```

Add `--interactive` to `calib field` to type each pour as `step,height`.

### Windows notes

- `make` is not installed by default. Use the `uv run` commands above. If you
  install make, run it from Git Bash, because `make clean` uses `rm -rf`.
- Use forward slashes or double backslashes in JSON paths.
- Save the CSV as UTF-8. Excel's "CSV UTF-8" works; a BOM is accepted.
- Use a dot for decimals. Do not mix comma decimals with a comma delimiter.
- Close the workbook in Excel before a run. Windows locks open files.
- Keep `out\` out of OneDrive. Sync can lock files during a run.
- Clone to a short path such as `C:\src\tank-calibration` to avoid long-path
  problems.

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
| `X_strapping.csv` | Authoritative table with a generated certificate header: level, liquid, ±σ, flag. |
| `X_commercial.csv` | Fixed interval, whole litres, extrapolated region labelled, with the same certificate header. |
| `X_anomaly_register.csv` | Object bands, dip pairs, single-sided events, watch items, unknowns. |
| `X_shell_record.txt` | The adopted-shell record of §11. |
| `X_presets.json` | The adopted shell for the field tool. One source of truth. |
| `X_workbook.xlsx` | Values-only workbook, a Certificate header sheet, plus the optional Audit sheet. The Audit objective sums the trusted set only. |
| `X_report.md` | Shell record, acceptance table, register, limitations. |
| `charts/` | The seven views of §6.6, the `r` profile, and the three composites (`pour_fit`, `pour_fit_views`, `anomaly_detector`). |

## Configuration

One JSON file per tank. Paths are relative to the JSON file.

```json
{
  "tank": "tankA",
  "site": "Tank farm A",
  "table_version": "v1",
  "supersedes": "none",
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
- `site`, `table_version` and `supersedes` fill the generated certificate
  header. The header is written to the top of both tables, the workbook
  `Certificate` sheet and the report.
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

## Charts

The chart specification is in [CHARTS.md](CHARTS.md): visual grammar, the
seven diagnostic views, the synthetic reference panel, Excel wiring and the
inline equivalents.

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
uv run python -m unittest discover -s tests -v
```

50 tests cover geometry, step parsing, corrections, the trusted set, fit
recovery, the pair rule, object bookkeeping, noise split, telescoping blocks,
blocking, unknowns, the field protocol, the formula gate, a locked datum
(with and without an overflow), the audit objective, and an end-to-end run
with the workbook gate.

## Development

```bash
uv run ruff check .
uv run python -m coverage run -m unittest discover -s tests
uv run python -m coverage report -m
```

`make test`, `make lint` and `make coverage` run the same commands.

## Makefile

`make` is a short command menu over the same `uv run` commands:

| Command | Runs |
|---|---|
| `make` | `test` |
| `make test` | the 50 tests |
| `make lint` | `ruff check .` |
| `make coverage` | tests with a coverage report |
| `make demo` | generate, fit and gate the demo |
| `make gate` | gate the demo workbook |
| `make clean` | remove `out/` |

`PY ?= uv run python` sets the Python command. Override it with
`make test PY=python3`. The targets are `.PHONY`, so they always run.

## License

MIT. See [LICENSE](LICENSE).

## Limits

The method states its own limits in §12. The package records them; it does not
hide them. In particular:

- Tape scale is unidentifiable from pour and level data.
- Object versus pour error is not separable from one pass.
- A static tilt is tested only when `tilt_test` is true.
- `r` is an effective mean; ovality is not modelled.

A fit is adopted only when all six checks of §5.7 pass. The workbook and the
commercial chart say so when they do not.

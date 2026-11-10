# Method coverage

Every section and rule of `CALIBRATION_METHODOLOGY.md`, and where it lives.

## §1 Products and authority

| Rule | Implementation | How to see it |
|---|---|---|
| 1.1 Raw never edited | `data.read_raw` only reads; `pipeline._write_artifacts` copies the raw file; corrections live in `Correction` objects | `X_raw.csv` is a byte copy; `X_corrected.csv` carries the flag |
| 1.2 A gap is a finding | `report.anomaly_register`; residuals are never averaged away | `X_anomaly_register.csv`, workbook `AnomalyLog` |
| 1.3 One authoritative table | One `X_strapping.csv` per run | `X_shell_record.txt` names it |
| 1.4 No extrapolation | `report.strapping_table` flags every row below the lowest verified dip | `flag = extrapolated` |

## §2 Conventions

| Item | Implementation |
|---|---|
| Units mm and litres | Whole package |
| `resid = s - pred` | `diagnostics.apply_model` |
| Sign meaning | `diagnostics.residual_meaning` |
| Drift `D_k` | `Interval.drift`, `diagnostics.classify_drift` |
| Pair signs | `diagnostics.find_pairs` |

## §3 Campaign design

| Rule | Implementation |
|---|---|
| 3.1 Can calibration | `pour_noise.rel` / `.abs` in the config |
| 3.4 Pour sizing | `FieldValidator.advisor` (30 mm target, 10σ floor, 100 mm ceiling) |
| 3.9 Unknown cells | `data.parse_step` (`?`, `N+?`, `x1`) |
| 3.10 Pour unit grid | `pour_unit`; `quantized.quantized_pour_search` |

## §4 Geometry

`geometry.py`: `area`, `volume`, `capacity`, `brim_reading`, `slope`,
`volume_tilted`, `Shell`.

## §5 Fitting

| Rule | Implementation |
|---|---|
| 5.1 Difference fit | `fit.fit_difference` |
| 5.2 TRF, multi-start, Huber | `fit_difference` (`loss="huber"`, `f_scale`) |
| 5.3a Brim constraint | `fit_constrained` (SLSQP, penalty fallback); `overflow_direction` |
| 5.3a Neck equality | `fit_constrained(neck=True)`; `brim.neck_equality` |
| 5.3b Empty start | `fit.empty_start_check` |
| 5.3c Monotonic levels | `data.mark_trusted` |
| 5.4 Joint fit | `fit.fit_joint`; `calib joint` |
| 5.5 `r` profile | `fit.profile_param` / `profile_r` |
| 5.5 `h0` lock cost | `fit.lock_cost` (F-test) |
| 5.5 Tilt test | `fit.tilt_test`; `tilt_test: true` |
| 5.5 Bootstrap | `fit.parametric_bootstrap` |
| 5.5 GLS per-dip covariance | `fit.gls_fit` |
| 5.6 Spreadsheet reproduction | Workbook `Audit` sheet with live formulas and Solver steps |
| 5.7 Six acceptance checks | `pipeline._acceptance` |

## §6 Anomaly classification

| Rule | Implementation |
|---|---|
| Action bar | `diagnostics.classify` |
| 6.1 Pair rule | `diagnostics.find_pairs` (four conditions, net balance) |
| 6.1 Correction arithmetic | `PairFinding.delta_mm`, `corrected_dip` |
| 6.2 Single-sided rule | `diagnostics.single_sided` |
| 6.2 Quantized pour search | `quantized.quantized_pour_search` |
| 6.3 Object bookkeeping | `band_displacement`, `blocked_below`, `liquid_volume`, `to_brim`, `max_liquid` |
| 6.4 Void, leak, lag | `diagnostics.lag_check`; net residual over a band |
| 6.5 Watch items | `diagnostics.watch_items` |
| 6.6 Seven views | `charts.all_charts`; `pair_scatter`; `classify_drift` |

## §7 Small pours and grouping

`blocking.block_intervals`: merges adjacent trusted intervals, keeps unknown
rows solo, keeps block boundaries as fit points. The pipeline fits the blocked
set and reports the geometry delta. RMSE is labelled not comparable.

## §8 Unknown pours

| Rule | Implementation |
|---|---|
| 8.1 Back-prediction | `unknowns.back_predict` (subtracts blocked volume crossed) |
| 8.2 One σ formula | `unknowns.sigma_x` |
| 8.3 Sensitivity battery | `unknowns.sensitivity_battery` (loss × h0 × r × exclusions) |
| Widen by fit spread | `unknowns.widen_unknowns` |

## §9 Uncertainty budget

| Rule | Implementation |
|---|---|
| 9.1 One set of numbers | Config `sigma_h`, `pour_noise`; used everywhere |
| 9.2 Per-interval σ | `diagnostics.interval_sigma` |
| 9.3 Closure | `diagnostics.closure` (includes unknown estimates, excludes overflow) |
| 9.4 Sanity | `diagnostics.sanity_rmse` |
| 9.5 Noise split | `diagnostics.noise_split` (lag-1 covariance) |
| 9.6 Telescoping blocks | `diagnostics.telescoping_blocks` (per contiguous run) |
| 9.7 Multiple comparisons | `diagnostics.multiple_comparisons` |

## §10 Field protocol

`field.FieldValidator`: OK, CHECK, ALARM, DIP-PAIR, DETECTOR, BRIM-WARN,
OVERFLOW, DRIFT, unknown pours with ±2σ, pour-size advisor, closure line.
`calib field` runs a CSV or an interactive session. The presets file is the
adopted shell, so the tool cannot drift from the fit.

## §11 Deliverables

| Deliverable | Where |
|---|---|
| `*_raw.csv` | Byte copy, immutable |
| `*_corrected.csv` | Flag, rule, magnitude, raw value in the note |
| Strapping table | `X_strapping.csv`, workbook `Strapping` |
| Shell record | `X_shell_record.txt` |
| Anomaly register | `X_anomaly_register.csv`, workbook `AnomalyLog` |
| Fit script | This package |
| Empty-start residual | `Diagnostics` sheet, `result["empty_start"]` |
| Unknown pours, one formula | `unknowns.estimate_unknowns` |
| Closure number | `Diagnostics` sheet, shell record |
| Commercial chart | `X_commercial.csv`, workbook `Commercial` |
| Datum statement | Shell record, `report.datum_statement` |
| Formula gate | `calib gate`, `formula_gate.gate_workbook` |

The commercial chart carries a note. It says `SHELL NOT ACCEPTED — do not use
for custody` when any §5.7 check fails.

## §12 Limitations

`pipeline._markdown` writes the limitation list. The shell record states the
datum cause. The tilt test reports "not kept" when it does not pass.

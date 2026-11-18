# Method coverage

Every section and rule of [CALIBRATION_METHODOLOGY.md](CALIBRATION_METHODOLOGY.md), and where it lives.

## §1 Products and authority

| Rule | Implementation | How to see it |
|---|---|---|
| 1.1 Raw never edited | `data.read_raw` only reads; `pipeline._write_artifacts` copies the raw file; corrections live in `Correction` objects | `X_raw.csv` is a byte copy; `X_corrected.csv` carries the flag |
| 1.2 A gap is a finding | `report.anomaly_register`; residuals are never averaged away | `X_anomaly_register.csv`, workbook `AnomalyLog` |
| 1.3 One authoritative table | One `X_strapping.csv` per run | `X_shell_record.txt` names it |
| 1.4 No extrapolation | `report.strapping_table` flags every row below the lowest verified dip and every row above the highest verified dip | `flag = extrapolated` or `brim-anchored` |

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
| 3.11 Reverse strapping (drain) | `direction` in the config; `Interval.direction`, `travel`, `h_lo`/`h_hi`, `predicted`; every module takes the sign; `fit.end_heel`; `scaffold.infer_neck_drain` / `infer_neck_entrance`; `fit_constrained(gap_pour=None)` for the equality of a start at the brim; site `direction: "drain"`. Mirror test: `tests/test_drain.py` |
| 3.12 Transfer strapping (two tanks) | site `TransferSession` (`site_core.js`): one can tally shared by a drain session and a fill session, one level per tank per batch, paired residuals that decompose a shared pour error from a transfer loss from a one-tank cause. Tests: `tests/test_site.py::TestSiteTransfer` |

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
| 5.3a Declared brim | `brim.declared` / `declared_pm` (`scaffold.infer_declared_brim` reads the row 1 note `brim X ± Y mm`); `pipeline._declared_check`, `FitResult.brim_sigma`: compared and reported, never enforced; site: `cfg.brim` / `brimPm` as the running-fit prior (`makePrior`), `Session.brimConflict`, setup and *Settings → This campaign* fields; `tests/test_brim.py`, `tests/test_site.py::TestSiteBrim` |
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
| 6.6 Seven views | `charts.all_charts`; `pair_scatter`; `classify_drift`; see [CHARTS.md](CHARTS.md) |

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
A drain (`direction="drain"`, from the presets) uses NECK and BOTTOM-WARN
instead of OVERFLOW and BRIM-WARN, and the drain cause texts.
`calib field` runs a CSV or an interactive session. The presets file is the
adopted shell, so the tool cannot drift from the fit.

## §10a Live campaign check

| Rule | Implementation |
|---|---|
| 10a.1 Running shell with priors | `site_core.js` `fitShell` (Levenberg–Marquardt, one residual per prior); `Session._refit` on accepted intervals only |
| 10a.2 Prediction and its σ | `predictLevel`, `Session.preview` (shared by `Session._predict` and the Now line); noise scale in `Session._refit` |
| 10a.4–10a.5 First-reading decision, sharpness | `Session._evaluate` |
| 10a.6 Blind repeat | `verdict.hidden`; the page hides earlier readings and the check's prediction while a level is pending. The Now line shows the expected level before the dip, so the operator must not read it before dipping |
| 10a.7 Repeat test, creep | `adopt`, `UNSETTLED` in `Session._evaluate` |
| 10a.8 LEARNING, WATCH, ALARM, pair pattern | `Session._evaluate` |
| 10a.9 Record | `Session.toRawCsv` (reads back with `data.read_raw`), `Session.toJSON` |
| 10a.10 Performance | `site/simulate.js`; `tests/test_site.py` |
| Offline page | `site/page.html` + core + `site/i18n.js` → `calib site-page` → `site/calib_site.html` |
| Page language | `site/i18n.js`: English and Vietnamese, chosen in Settings; the exported files stay English; `tests/test_i18n.py` checks a key for every text |
| Header live indicator | `site/page.html` `liveState` / `tickLive`: fill, close-valve, full (fill timer) and drain (drain time after the last tap); `tests/test_site.py` |
| Tank tiles | `site/page.html` `renderTiles` / `tileHtml` / `tileLive`, `site_core.js` `Session.tileView` / `TransferSession.tiles`: the third frozen row, the last dip and the batch-end prediction, the plan/tapped/typed rule, the waiting-reading ring, the result mark (`tileMark`, a tap shows the reading card: `showVerdict`), the brim / floor / dry limit marks (`tileEdge`), the litres past a limit (`past`, `beyond`), the way left to the brim or the suction floor (`left`), the wave arrow with its bob and flowing wave; `tests/test_site.py::TestSiteTiles` |
| Finished tank | `site_core.js` `Session.finish` / `reopen` / `canReopen` / `closeTally`, `TransferSession.liveKeys` / `liveKey` / `_afterFinish`; `site/page.html` `renderFinish` / `toggleFinish`, the `finished` tile reason; `tests/test_site.py::TestSiteFinish` |
| Now card | `site/page.html` `renderNowPrediction` / `renderTransferPrediction` / `panelInput`, `site_core.js` `tileOne` with `leftOf`: the same view as the tile, the limit after ≥ or ≤, the expected dip for the first reading only, the way left now and after the batch, the one-line simple mode; `tests/test_site.py::TestSiteTiles`, `test_page_now_previews_the_pour_input` |
| Pour card foot | `site/page.html` `renderTally`: one action bar `#t-act` (*↶* `#t-undo` → +1 can `#t-plus` → *✓* `#p-go`, ↶ and ✓ the same width) → *Options*; `#p-go` quiet / ok / over by the batch's cans, asks below them (`tallyCans`), green with no can and a typed or unknown pour, disabled until a can or litres; `#p-opts` folds the can size first, then `#p-opts-rest` (the ticks, the note and typed litres; hidden in next-can mode) (`prefs.optsOpen`); `renderPlanLive` writes the batch line (`Batch 800 L · 3/8`, `Batch ≈ 400 L`) and `volumeWarn` the chip `#t-warn` and the limit line on `#t-bar`; the Now card follows the pour card (`placePourCard`); `Session.closeTally` option `volume` replaces the batch volume and sets `cans.typed`, and the count hint is skipped; `tests/test_site.py::TestSitePage` |
| Next can while the dip waits | `site/page.html` `earlyTimer` (fill; transfer once A is decided or finished; never a drain), `nextCanMode` / `placePourCard` (the pour card under the dip card, the count and the batch locked), `T.pour.early` (no fill start on the tap), `stopPumpForA` / `undoOpensA` / `dropStaleTimer`, the `fill` alarm kind over the settle alarm; `tests/test_site.py::TestSiteEarlyTimer` |
| iPhone timer (Shortcuts) | `site/page.html` `isIOS` / `iosTimerUrl` / `iosTimer`, started by *Start fill timer*; device prefs `iosTimer`, `iosShortcut`; `tests/test_site.py` |
| Swipe between tabs | `site/page.html` touch handlers on `main`, `goTab`; `tests/test_site.py` |
| Settings tab | `site/page.html`; `Session.setCampaign` refits the running shell after a change of the tank record, the priors or the noise |
| Batch plan (§3.4, §3.10) | `checkPlan`, `canMix` (fewest, then largest cans), `planState` (past the mid-dip the batches still to come are recounted; finished groups are closed; a count holds within ¾ batch of the last one, `L.plan.counts`) in `site_core.js`; `Session.planNow`, the plan group on each level (`L.plan`), the plan's batch as the advice target, `fillPlan` over the plan's batches; the page's setup rows and the pour card's group tally. Tests: `tests/test_site.py::TestSitePlan` |
| Time trend of the cans | `Session.timeTrend` / `timerSuggestion` in `site_core.js`: fill from the fill-timer starts, drain from *+1 can* to the next start, recency-weighted (a can 3 back weighs half; each held to ⅓–3× the median); the time estimate follows the trend, the typed times count where no can was timed; *Use the trend* adopts it for the timers; the fill alarm keeps the typed time. Tests: `tests/test_site.py::TestSiteTimeTrend` |
| Suction floor (drain) | `cfg.suctionFloor` (a tape reading, 65 mm default, Settings → Noise and limits): `floorVolume`; the drain's room, plan room, advice watch and time-to-the-suction-floor all end there. Tests: `tests/test_site.py::TestSiteTimeTrend` |
| Transfer, two tanks (§3.12) | `TransferSession` in `site_core.js` + the page's transfer mode: shared tally, one dip field and button per tank (`dipBoth`), tinted field cards with tank pictograms and a same-batch header, per-tank verdicts, the pair view after both dips, per-tank raw files, the frozen tank tiles as the tank switch (`↑ alpha`, `↓ beta`) |

## §11 Deliverables

| Deliverable | Where |
|---|---|
| `*_raw.csv` | Byte copy, immutable |
| `*_corrected.csv` | Flag, rule, magnitude, raw value in the note |
| Strapping table | `X_strapping.csv` with a generated certificate header; workbook `Certificate` and `Strapping` |
| Customer header | `report.table_header` → CSV comment block, workbook `Certificate`, report section |
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

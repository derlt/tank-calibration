# Chart specification

Every chart the package produces, with its data contract, encodings, style
tokens and implementation. Use this when you reuse the look or rebuild a view.

The seven diagnostic views are the catalogue of §6.6. The `r` profile is the
extra view of §5.5. The Excel workbook carries live versions of the seven;
the PNGs carry the reference lines.

---

## 1. Shared style system

### 1.1 Palette

| Token | Hex | Role |
|---|---|---|
| `INK` | `#1f2933` | Titles, zero lines, primary text |
| `MUTED` | `#7b8794` | Axis labels, ticks, reference lines, secondary marks |
| `GRID` | `#e4e7eb` | Grid lines, spines, zero guides on the pair scatter |
| `BLUE` | `#2563eb` | The adopted shell, the data points, the profile curve |
| `RED` | `#dc2626` | Cumulative books, drift, candidate residuals, ±3 lines |
| `AMBER` | `#d97706` | Watch items, object bands, ±2 lines, profile threshold |
| `GREEN` | `#059669` | Reserved; not used by the current views |

One palette for every chart. Do not add a colour without giving it a role in
this table.

### 1.2 Typography and axes

| Element | Setting |
|---|---|
| Title | 11 pt, `INK`, left-aligned (`loc="left"`), `pad=8` |
| Axis labels | 9 pt, `MUTED` |
| Tick labels | 8 pt, `MUTED` |
| Legend | 8 pt, frameless (`frameon=False`) |
| Grid | `GRID`, line width 0.7 |
| Spines | top and right hidden; left and bottom `GRID` |
| Background | white |

Titles are sentence case and carry no units. Units live in the axis labels.

### 1.3 Figure sizes and output

| View | Figure (inches) | File |
|---|---|---|
| Strapping vs books | 7.0 × 4.2 | `01_strapping.png` |
| Interval residuals | 7.0 × 4.2 | `02_residuals.png` |
| Predicted vs recorded | 5.2 × 4.6 | `03_predicted_vs_recorded.png` |
| Slope profile | 7.0 × 4.2 | `04_slope_profile.png` |
| Drift | 7.0 × 4.2 | `05_drift.png` |
| z alarms | 7.0 × 4.2 | `06_z_alarms.png` |
| Adjacent-pair scatter | 5.4 × 5.0 | `07_pair_scatter.png` |
| `r` profile | 6.0 × 4.0 | `08_r_profile.png` |
| Combined sheet | 16.0 × 8.0 | `00_all_views.png` |

PNGs save at 150 dpi, white face, after `tight_layout()`. The combined sheet
saves at 110 dpi.

### 1.4 Units and conventions

| Quantity | Unit | Where |
|---|---|---|
| Tape reading `H` | mm | Every x-axis |
| Residual | mm-equivalent (`resid / m`) | Interval residuals |
| Residual | litres | Drift, books, predicted-vs-recorded |
| Volume | litres | Strapping, slope is L/mm |
| Slope `m` | L/mm | Slope profile |
| Significance | z (dimensionless) | z alarms, pair scatter |
| Radius `r` | mm | Profile |
| RMSE | L/step | Profile |

Residual sign follows §2: negative means the rise came too cheap (object or
under-recorded pour); positive means the rise came too small (loss or
over-recorded pour). The charts never mirror it.

### 1.5 Data filters

| View | Rows used |
|---|---|
| Strapping vs books | All rows; books skip unknown pours |
| Interval residuals | `known` and finite `resid` |
| Predicted vs recorded | `known` and finite `resid` |
| Slope profile | `known` and `rise > 0` |
| Drift | finite `drift` (unknown pours break the chain) |
| z alarms | `known` and finite `z` |
| Pair scatter | `trusted` and finite `z` |
| `r` profile | The profile grid from the fit |

Gaps matter. An unknown pour or an excluded object band leaves a hole in a
series. Do not interpolate across it: the hole is information.

---

## 2. Strapping vs books

**Question.** Where does the ledger leave the tank? Every step between the
shell curve and the books is mis-accounted litres.

**Data.**

- Shell curve: 400 points from `H = 0` to `H = shell.brim()`, `F(H) = shell.volume(H)`.
- Books: `heel + Σ step` for known pours, in file order, plotted at each row's `measured_height`.
- Object bands: `low`/`high` in mm.

**Marks.**

| Mark | Encoding |
|---|---|
| Shell | `BLUE` line, width 2.0 |
| Books | `RED` circles, marker size 3.5, no line |
| Object bands | `AMBER` vertical span, alpha 0.15 |

**Axes.** x = tape reading `H` (mm); y = volume (L). Legend: "adopted shell
F(H)" and "cumulative books", 8 pt, frameless.

**What it reveals.** A vertical step between the curve and the points is a
mis-accounted volume. A drift away from the curve is a systematic effect. The
bands mark where an object is expected, so a step there is not a surprise.

**Implementation.** `charts.chart_strapping`. Excel: `Charts` sheet, anchor
`A4`, 15 × 9. Series 1 is `Curve!B` vs `Curve!A` (shell line, `2563EB`,
22000 EMU). Series 2 is `Model!M` vs `Model!C` (books, circle markers size 4,
no line). Excel shows the default legend.

**Reuse notes.** This is a shell-versus-books diagnostic, not the commercial
liquid table. It plots `F(H)`, not `F(H) − blocked`. The object bands are the
warning that raw `F` is not liquid. The PNG skips unknown pours in the books
line; the Excel `Model!M` column uses the back-predicted total, so the two
differ across an unknown pour.

---

## 3. Interval residuals

**Question.** Where is each disagreement, and how large is it?

**Data.** One bar per interval: x = `h_cur`, y = `mm_equiv = resid / m`.

**Marks.**

| Mark | Encoding |
|---|---|
| Candidate | `RED` bar |
| Watch | `AMBER` bar |
| Noise | `MUTED` bar |
| Bar width | 8 mm |
| Zero line | `INK`, 0.8 |
| ±3 mm | `MUTED` dashed, 0.8 |
| ±1.5 mm | `MUTED` dotted, 0.8 |

**Axes.** x = level `H` (mm); y = residual (mm-equivalent).

**What it reveals.** Adjacent bars of opposite sign that clear the bar are a
shared-dip misread. A lone bar is an object or a pour error. The bar height is
the size of the finding, not its significance; use the z chart for that.

**Implementation.** `charts.chart_residuals`. Excel: `Charts` sheet, anchor
`A22`, 15 × 9. `BarChart` (column), `Model!H` with categories `Model!C`. No
reference lines in Excel.

**Reuse notes.** Keep mm-equivalent on the y-axis. Litres hide the structure
at the top and bottom of the tank, where the slope changes by an order of
magnitude.

---

## 4. Predicted vs recorded

**Question.** Is the pour record or the dip record wrong?

**Data.** One point per interval: x = `pred` (model pour), y = `s` (recorded
pour).

**Marks.**

| Mark | Encoding |
|---|---|
| Identity | `MUTED` line, width 1.0, `y = x` from 0 to `1.05 × max` |
| Points | `BLUE` circles, size 3.5 |

**Axes.** x = predicted pour (L); y = recorded pour (L). Equal visual scale
matters more than equal limits.

**What it reveals.** Points off the identity line are a bad pour record or a
bad pair of dips. A point above the line means more was recorded than the
rise supports; below means less.

**Implementation.** `charts.chart_predicted_vs_recorded`. Excel: `Charts`
sheet, anchor `A40`, 12 × 9. Scatter, `Model!D` (y) vs `Model!E` (x). No
identity line in Excel.

**Reuse notes.** The identity line is essential. Without it the eye reads a
trend that is not there.

---

## 5. Slope profile

**Question.** Which rows are physically impossible?

**Data.**

- Shell slope: 400 points from 0 to brim, `m(H) = 2L√(2rh−h²)/1e6`.
- Pour/rise points: `s / rise` at `h_cur`, for known intervals with `rise > 0`.

**Marks.**

| Mark | Encoding |
|---|---|
| Shell slope | `BLUE` line, width 2.0 |
| Pour / rise | `RED` circles, size 3.5 |

**Axes.** x = level `H` (mm); y = slope (L/mm). Legend: "shell slope m(H)" and
"pour / rise", 8 pt, frameless.

**What it reveals.** A pour/rise point that jumps off the smooth curve is
physically impossible for that geometry. It points at a dip error, a pour
error, or an object in that band.

**Implementation.** `charts.chart_slope_profile`. Excel: `Charts` sheet,
anchor `A58`, 15 × 9. Series 1 `Curve!C` vs `Curve!A` (shell, `2563EB`,
22000 EMU); series 2 `Model!N` vs `Model!C` (pour/rise, circle size 4, no
line). Excel shows the default legend.

**Reuse notes.** `Model!N` is blank for unknown pours and for non-positive
rises. The blank is correct; do not fill it.

---

## 6. Drift

**Question.** What is the running disagreement, and what shape does it have?

**Data.** `D_k = Σ resid_i` at each `h_cur`, for intervals with a finite
drift. Unknown pours break the chain and leave a gap.

**Marks.**

| Mark | Encoding |
|---|---|
| Drift | `RED` line, width 1.8 |
| Zero | `INK` line, 0.8 |

**Axes.** x = level `H` (mm); y = cumulative residual (L).

**What it reveals.** The shape names the cause:

| Shape | Reading |
|---|---|
| Flat wobble | Honest noise |
| One-point spike that returns | One misread dip |
| Single step then flat | One-off event: up = loss / over-record, down = object / under-record |
| Ramp that never returns | Persistent effect: audit, do not refit |
| Dip then return | Settling lag, net ≈ 0 |

**Implementation.** `charts.chart_drift`. Excel: `Charts` sheet, anchor
`A76`, 15 × 9. `LineChart`, `Model!K` with categories `Model!C`. No zero line
in Excel.

**Reuse notes.** The residual locates; the drift remembers. Do not smooth the
drift line.

---

## 7. z alarms

**Question.** Which intervals are significant against the action bar?

**Data.** One point per interval: x = `h_cur`, y = `z = resid / sigma`.

**Marks.**

| Mark | Encoding |
|---|---|
| Points | `BLUE` circles, size 3.5 |
| ±2 | `AMBER` dashed, 0.9 |
| ±3 | `RED` solid, 0.9 |

**Axes.** x = level `H` (mm); y = z.

**What it reveals.** The action bar in one view. Points beyond ±2 are CHECK;
beyond ±3 and at least 3 mm-equivalent are candidates. The chart shows
significance; pair it with the residual chart for size.

**Implementation.** `charts.chart_z_alarms`. Excel: `Charts` sheet, anchor
`A94`, 15 × 9. Scatter, `Model!J` vs `Model!C`. No threshold lines in Excel.

**Reuse notes.** The ±2 and ±3 lines are the point of the chart. If you port
this to another tool, add them as constant series.

---

## 8. Adjacent-pair scatter

**Question.** Which failure mode is present? This is the compass.

**Data.** Every adjacent pair of trusted intervals as one point
`(z_i, z_{i+1})`.

**Marks.**

| Mark | Encoding |
|---|---|
| Points | `BLUE` circles, area 18 |
| Anti-diagonal | `MUTED` dashed, 0.8 (`z_i = −z_{i+1}`) |
| Main diagonal | `MUTED` dotted, 0.8 (`z_i = z_{i+1}`) |
| Zero guides | `GRID`, 0.8 |
| Limits | Symmetric, `max(4, 1.15 × max|z|)` |

**Axes.** x = `z(i)`; y = `z(i+1)`. Equal limits on both axes.

**What it reveals.**

| Position | Reading |
|---|---|
| Central cloud inside ±2 | Honest noise |
| Anti-diagonal | Shared-dip misread |
| On an axis | Single-sided event |
| Main diagonal, same sign | Persistent effect |
| Off both diagonals | Superposed errors: decompose before correcting |

**Implementation.** `charts.chart_pair_scatter`. Excel: `Charts` sheet, anchor
`A112`, 12 × 10. Scatter, `Pairs!C` vs `Pairs!B`. No diagonals in Excel.

**Reuse notes.** Consult this view last. It is the view that forbids a hasty
correction. Keep the equal limits; unequal limits destroy the diagonal
reading.

---

## 9. `r` profile

**Question.** How well does the data identify the radius?

**Data.** `profile_param` returns `grid` (r in mm), `rmse` (L/step),
`threshold`, `lo`, `hi`.

**Marks.**

| Mark | Encoding |
|---|---|
| Profile | `BLUE` line, width 1.8 |
| Threshold | `AMBER` dashed, 0.9 |
| One-sigma band | `BLUE` span, alpha 0.08 |

**Axes.** x = `r` (mm); y = RMSE (L/step).

**What it reveals.** A flat profile means the data cannot pin `r`; quote the
profile interval, not the covariance. The threshold is
`√(best² + s²/n)`, the delta-SSE rule on the RMSE scale.

**Implementation.** `charts.chart_profile`. PNG only; the Excel workbook does
not carry this view. The `L` profile is computed by the pipeline but not
charted.

**Reuse notes.** The band is the honest interval. Do not draw a vertical line
at the fitted value alone; it implies a precision the profile does not have.

---

## 10. Combined sheet

**Question.** One page for the report and the review.

**Data.** The seven PNGs, in catalogue order.

**Layout.** 2 rows × 4 columns, 16 × 8 inches, 110 dpi, white. The first seven
cells hold the views; the eighth is blank. Each image is placed with
`imshow` and its axes switched off.

**Order.**

```
row 1: strapping | residuals | predicted | slope
row 2: drift     | z         | pair      | (blank)
```

**Implementation.** `charts.all_charts`, after the individual saves.

**Reuse notes.** Keep the pair scatter last in reading order. Do not add the
profile to this sheet; it is a method view, not a diagnostic one.

---

## 11. Excel parity

The workbook carries live versions of the seven. They read the `Model`,
`Curve` and `Pairs` sheets, so they update when the data changes.

| View | Excel chart | Data | Anchor | Size |
|---|---|---|---|---|
| Strapping vs books | Scatter, 2 series | shell y=`Curve!B`, x=`Curve!A`; books y=`Model!M`, x=`Model!C` | `A4` | 15 × 9 |
| Interval residuals | Column | `Model!H`, categories `C` | `A22` | 15 × 9 |
| Predicted vs recorded | Scatter | y=`Model!D`, x=`Model!E` | `A40` | 12 × 9 |
| Slope profile | Scatter, 2 series | shell y=`Curve!C`, x=`Curve!A`; points y=`Model!N`, x=`Model!C` | `A58` | 15 × 9 |
| Drift | Line | `Model!K`, categories `C` | `A76` | 15 × 9 |
| z alarms | Scatter | y=`Model!J`, x=`Model!C` | `A94` | 15 × 9 |
| Pair scatter | Scatter | y=`Pairs!C`, x=`Pairs!B` | `A112` | 12 × 10 |

**Parity gaps.** The Excel charts show the data and the series, but they do
not carry the reference lines, the object-band shading, the identity line or
the diagonals. The PNGs do. If the workbook must stand alone for a reviewer,
add those as constant series:

- z chart: two series at `+2`, `-2`, `+3`, `-3`.
- predicted chart: a series of `x` against `x`.
- pair scatter: two series over `[-lim, lim]`.
- strapping: a shaded band is not native; use a filled area series or leave
  the band to the `AnomalyLog` sheet.

**Style in Excel.** Header `1F3864` with white 9 pt bold; body 9 pt `1F2933`;
thin borders `D9DEE5`; band `EEF2F7`; warning `FDE68A`; bad `FECACA`; good
`BBF7D0`. Shell lines use `2563EB` at 22000 EMU. Point series use circle
markers, size 4–5, no connecting line.

---

## 12. Data contract

Every view reads the same objects. Keep these fields stable when you reuse
the code.

**`Interval`**

| Field | Meaning |
|---|---|
| `idx` | 1-based interval number |
| `row` | 0-based index of the ending row |
| `s` | pour volume in litres, or `None` |
| `known` | pour is recorded |
| `h_prev`, `h_cur` | bounding tape readings, mm |
| `pred` | `F(h_cur) − F(h_prev)`, L |
| `resid` | `s − pred`, L |
| `m` | slope at `h_cur`, L/mm |
| `mm_equiv` | `resid / m` |
| `sigma` | per-interval sigma, L |
| `z` | `resid / sigma` |
| `flag` | `candidate`, `watch`, `ok`, or an exclusion reason |
| `drift` | running residual, L |
| `trusted` | in the fit's trusted set |

**`Row`**: `height` (mm), `step` (`Step` with `kind`, `value`, `base`, `raw`),
`note`, `flags`.

**`Shell`**: `volume(H)`, `slope(H)`, `brim()`, `capacity()`.

**Bands**: `low`, `high` in mm; `displacement` or `litres` in L.

---

## 13. Reuse checklist

1. Use the palette and type scale above; do not introduce a new colour
   without a role.
2. Put units in the axis labels, not the title.
3. Keep titles left-aligned and sentence case.
4. Keep the residual sign convention and the mm-equivalent axis.
5. Keep the reference lines: zero, ±1.5, ±3, ±2, ±3, identity, diagonals.
6. Keep equal limits on the pair scatter.
7. Do not interpolate across a gap.
8. Put the pair scatter last in any layout.
9. If you add a view, add it to `all_charts`, to the combined sheet, and to
   the Excel `Charts` sheet with its source columns.
10. Run the workbook formula gate after any Excel change.

---

## 14. File map

| What | Where |
|---|---|
| Matplotlib views | `calib/charts.py` |
| Excel live charts | `calib/workbook.py` (`_charts`, `_curve`, `_pairs`) |
| Chart data on the Model sheet | `calib/workbook.py` (`_model`) |
| Output folder | `out/<tank>/charts/` |
| Combined sheet | `out/<tank>/charts/00_all_views.png` |
| Workbook charts | `out/<tank>/<tank>_workbook.xlsx`, sheet `Charts` |

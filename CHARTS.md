# Chart specification — tank calibration diagnostics

**Purpose.** A reusable specification for the seven diagnostic charts built in this
project, plus the synthetic reference panel. Use it to reproduce the same visual
language on any tank: same colours, same marker vocabulary, same reference lines,
same annotation style, same reading rules.

**Scope.** These charts are diagnostic and presentational. They do not replace the
strapping table; they explain it. The authoritative numbers live in the corrected
CSV and the adopted-shell record.

**Implementation.** Python 3.12 + matplotlib (Agg backend), `dpi=160`.
The same seven charts exist as live native charts in `test/tank_calculator.xlsx`
(wiring table in §7). Line-only charts also render inline as `openui-lang`
`LineChart` blocks (§8); scatter charts cannot, so they stay as images.

---

## 1. The visual grammar (the part that must never change)

Every chart answers the same question in the same way: **raw data, corrected data,
and the fitted model on one canvas.** The reader must be able to see, without
reading a caption, what was wrong and what the fix did.

### 1.1 Colour roles

| Colour | Hex | Role | Never used for |
|---|---|---|---|
| Model blue | `#1a6fa8` | fitted shell curve, shell slope, diagonals, fix arrows | data points |
| Raw red | `#d62728` | raw recorded data, ALARM threshold | corrected data |
| Corrected green | `#2ca02c` | corrected data, clean end state | raw data |
| Excluded purple | `#9467bd` | overflow / excluded rows, anti-diagonal guide | fitted data |
| Check orange | `#ff9f1c` | CHECK threshold (±2), ±2 noise box | data |
| Object orange | `#ff7f0e` | simulated object signature | real data |
| Loss blue | `#1f77b4` | simulated loss / short-pour signature | real data |
| Leak brown | `#8c564b` | simulated leak signature | real data |
| Neutral grey | `0.3`–`0.7` | zero line, y = x line, brim line, arrow shafts | series |

Rule: **red is always "as recorded", green is always "after correction", blue is
always "the model".** A reader who learns this once can read every chart.

### 1.2 Marker vocabulary

| Marker | Style | Meaning |
|---|---|---|
| Open circle | `"o"`, `mfc="none"`, `mec="#d62728"`, `mew=1.2–1.4`, `ms=5–6` | raw recorded point |
| Filled square | `"s"`, `color="#2ca02c"`, `ms=4–5` | corrected point |
| Cross | `"x"`, `color="#9467bd"`, `ms=8`, `mew=2` | excluded / overflow row |
| Diamond | `"D"`, filled accent | simulated single-sided signature (object, short pour) |
| Triangle up / down | `"^"` / `"v"`, `#9467bd` | simulated dip misread, positive / negative |
| Star | `"*"`, `#8c564b` | simulated continuing leak |

Rule: **open markers are observations; filled markers are conclusions.** The raw
series is always open so overlapping corrected points remain visible.

### 1.3 Line vocabulary

| Line | Style | Meaning |
|---|---|---|
| Model curve | solid, `#1a6fa8`, `lw=2–2.2` | fitted `V(H)` or `dV/dH` |
| Reference | solid, `0.6` grey, `lw=1` | y = x, zero line |
| Brim | dashed, `0.5` grey, `lw=1` | brim / neck reading |
| CHECK | dashed, `#ff9f1c`, `lw=1` | ±2σ |
| ALARM | dotted, `#d62728`, `lw=1.2` | ±3σ |
| Diagonal guide | solid, `#1a6fa8`, `lw=1`, `alpha=0.6` | detector axes |
| Raw path | solid, red, `lw=1`, open markers | drift / cumulative raw |
| Corrected path | solid, green, `lw=1`, filled markers | drift / cumulative corrected |

### 1.4 Reference elements

- **Zero line** on every residual / drift / z chart: `axhline(0, color="0.3", lw=1)`.
- **Noise band** on residual charts: `fill_between(mid, -σ, +σ, color="#1a6fa8", alpha=0.12)`,
  labelled `±1σ (dip + pour noise)`.
- **Brim line**: vertical, with a rotated label `brim 2475` at `color="0.4"`.
- **Threshold pairs**: always drawn symmetric (±2, ±3), even when only one side fires.
- **Diagonal guides** on the detector: both diagonals, plus a dashed ±2 box at the origin.

### 1.5 Annotation style

```python
ann = dict(fontsize=9, arrowprops=dict(arrowstyle="->", color="0.3"))
```

- Text sits in empty space, never on a series; an arrow points to the datum.
- Numbers carry sign and unit: `-145 L`, `+122 L`, `12.7 L/mm`, `z = -10.7`.
- Arrows use the accent colour when they explain a fix (`#1a6fa8` for raw→corrected).
- One annotation per anomaly, maximum; the chart is not a report.
- Long notes use `\n` and stay under ~40 characters per line.

### 1.6 Layout and export

| Figure | Size (in) | Grid | Export |
|---|---|---|---|
| Main pair (`pour_fit.png`) | `11.5 × 9.5`, height ratio `1.5 : 1` | 1 × 2 vertical | `dpi=160` |
| Gallery (`pour_fit_views.png`) | `14.5 × 11` | 2 × 2 | `dpi=160` |
| Detector (`anomaly_detector.png`) | `15 × 7.2` | 1 × 2 horizontal | `dpi=160` |

- `fig.suptitle(..., fontsize=12)`; panels carry numbered titles (`1.`, `2.`, …).
- `fig.tight_layout(rect=(0, 0, 1, 0.96))` when a suptitle is present, else `tight_layout()`.
- `ax.grid(alpha=0.25–0.3)`; legends `fontsize=8–9`, placed to avoid the data.
- Axis labels always carry units: `Tape reading H (mm)`, `Residual (L)`, `z`.
- No chartjam: one idea per panel.

---

## 2. Data contract — what every chart needs

| Symbol | Meaning | Source |
|---|---|---|
| `H[i]` | tape reading after row `i` (mm) | raw CSV |
| `s[i]` | pour for interval `i` (L) | raw CSV |
| `F(H)` | fitted shell volume (L) | adopted shell |
| `m(H)` | local slope `dF/dH` (L/mm) | derivative of `F` |
| `pred[i]` | `F(H[i]) − F(H[i−1])` (L) | model |
| `d[i]` | `pred[i] − s[i]` (L) — **figure convention** | derived |
| `σ[i]` | `√((m_i σh)² + (m_{i+1} σh)² + (rel·s + abs)²)` | noise model |
| `z[i]` | `d[i] / σ[i]` | derived |
| `books[i]` | heel + cumulative pours (L) | ledger |
| `drift[i]` | `F(H[i]) − books[i]` (L) | derived |
| `mid[i]` | `(H[i−1] + H[i]) / 2` (mm) | derived |

**Sign convention — read this before reusing the figures.** The figures in this
project plot `d = pred − obs` (positive = the level rose less than the shell
predicts). The methodology text uses `resid = obs − pred = −d`. They are exact
mirrors. Every axis label says which one it is. For new charts, prefer the
methodology convention `resid = obs − pred` and label the axis
`resid = obs − pred`; if you reuse these images unchanged, keep `pred − obs`.

---

## 3. Chart catalogue

### C1 — Strapping curve vs cumulative books

- **File:** `test/pour_fit.png`, top panel.
- **Question:** does the tank agree with the ledger in absolute volume, and where
  does it stop agreeing?
- **Axes:** x = tape reading `H` (mm); y = cumulative volume (L).
- **Series:**
  1. fitted `V(H)` — solid blue, 500 points from 0 to brim, `lw=2.2`;
  2. raw cumulative books — open red circles at each dip;
  3. corrected cumulative books — filled green squares.
- **Reference:** dashed vertical brim line + rotated label.
- **Annotations:** heel guess vs fitted heel; the phantom-pour step; the final
  dip at the brim.
- **Reading rule:** a vertical step between red and blue = mis-accounted litres
  at that level. A parallel offset = a wrong heel. The corrected series should lie
  on the curve within the noise band.
- **Why it works:** it is the only chart in absolute volume, so it catches a
  wrong starting volume, which every difference-based chart is blind to.

### C2 — Residual per interval

- **File:** `test/pour_fit.png`, bottom panel.
- **Question:** where, and by how much, do data and model disagree?
- **Axes:** x = interval midpoint (mm); y = `pred − obs` (L).
- **Series:**
  1. raw residuals — open red circles;
  2. corrected residuals — filled green squares (last point omitted);
  3. `±1σ` band — blue fill, `alpha=0.12`.
- **Reference:** zero line.
- **Special marker:** excluded overflow row as a purple `x`.
- **Annotations:** the single-sided anomaly, the shared-dip pair, the overflow row.
- **Reading rule:** inside the band = noise; a lone spike = single-sided event
  (object / pour error); an adjacent opposite-sign pair = shared-dip misread;
  a run of same-sign points = systematic (datum, leak).
- **y-limits:** fixed symmetric (`±165 L` here) so raw and corrected are comparable
  across figures; do not autoscale per panel.

### C3 — Predicted vs recorded pour

- **File:** `test/pour_fit_views.png`, panel 1.
- **Question:** which rows have a pour record that the shell cannot reproduce?
- **Axes:** x = recorded pour (L); y = predicted pour from the shell (L).
- **Series:**
  1. raw — open red circles;
  2. corrected — filled green squares;
  3. `y = x` — solid grey `0.6`, `lw=1`.
- **Fix arrows:** blue arrows from each raw point to its corrected position.
- **Reading rule:** distance from the diagonal = the size of the record error.
  Points above the line were under-recorded; below, over-recorded. A point far
  off the line with a neighbour also off = a dip error, not a pour error.
- **Why it works:** it separates "the number in the ledger is wrong" from "the
  level reading is wrong" better than any other single view.

### C4 — Slope profile (litres per mm)

- **File:** `test/pour_fit_views.png`, panel 2.
- **Question:** is the tank's shape physically plausible at every level?
- **Axes:** x = level midpoint (mm); y = slope (L per mm).
- **Series:**
  1. shell slope `dV/dH` — solid blue, smooth curve;
  2. raw `pour / rise` — open red circles;
  3. corrected `pour / rise` — filled green squares.
- **Reading rule:** the shell curve is smooth and zero at both ends. Any point
  that jumps off it is physically impossible: too high = a phantom pour crammed
  into a small rise; too low = a nominal pour spread over a large rise.
- **Why it works:** it is the most intuitive view for non-specialists, because
  "litres per millimetre" is a physical property they can reason about.

### C5 — Drift chart

- **File:** `test/pour_fit_views.png`, panel 3.
- **Question:** how much have the books and the tank diverged, in total?
- **Axes:** x = tape reading (mm); y = `V(H) − books` (L).
- **Series:**
  1. raw — open red circles joined by a thin red line;
  2. corrected — filled green squares joined by a thin green line.
- **Reference:** zero line.
- **Annotations:** the starting offset (heel), each step, the final step, the
  corrected end value.
- **Reading rule (the shape names the cause):**
  - flat wobble inside `±3σ√k` → honest noise;
  - one-point spike that returns → misread dip;
  - single step then flat → one-off event (up = loss / over-record,
    down = object / under-record);
  - ramp that never returns → persistent effect (leak, continuing over-record) —
    audit, do not refit;
  - dip then return → settling lag.
- **Why it works:** it is cumulative, so it remembers every past error. A slow
  leak invisible per interval becomes a visible ramp.

### C6 — z-alarm chart

- **File:** `test/pour_fit_views.png`, panel 4.
- **Question:** which residuals are significant against the action bar?
- **Axes:** x = level (mm); y = `z = d / σ`.
- **Series:**
  1. raw — open red circles;
  2. corrected — filled green squares.
- **Reference:** `±2` dashed orange (CHECK), `±3` dotted red (ALARM), zero line.
- **Reading rule:** `|z| < 2` OK; `2 ≤ |z| < 3` CHECK (re-dip); `|z| ≥ 3` ALARM
  (stop, re-dip, classify). Expect ~5 % of good points beyond 2σ by chance; a
  chart with no points beyond 2σ in 45 tries is suspicious, not perfect.
- **Why it works:** it converts litres into a common significance scale, so a
  13 L residual in a shallow band and a 13 L residual mid-tank are not confused.

### C7 — Adjacent-pair detector

- **File:** `test/anomaly_detector.png`, panel A.
- **Question:** which failure mode produced the residual pattern?
- **Axes:** x = `z[i]`; y = `z[i+1]`; both in σ units, fixed `±15`.
- **Series:**
  1. real raw pairs — open red circles;
  2. real corrected pairs — filled green squares;
  3. simulated signatures — one marker each: dip +5 mm (up triangle), dip −5 mm
     (down triangle), object 120 L (diamond, orange), short pour 200 L (diamond,
     blue), leak 60 L/interval (star, brown).
- **Guides:** main diagonal, anti-diagonal, dashed ±2 box at the origin.
- **Reading rule (the failure-mode compass):**
  - central cloud inside the box → honest noise;
  - anti-diagonal (`z_i ≈ −z_{i+1}`) → one shared dip misread;
  - axis, single-sided → object (sign per convention) or pour error;
  - main-diagonal chain → persistent effect (leak / continuing over-record);
  - **off both diagonals → superposed errors: decompose before correcting.**
- **Why it works:** it is the only view that distinguishes one bad dip from two
  independent bad rows, because a shared dip *must* produce opposite signs.

### C8 — Drift-shape reference panel

- **File:** `test/anomaly_detector.png`, panel B.
- **Question:** what does each failure mode look like on a drift chart?
- **Axes:** x = interval number (1–40); y = drift (L).
- **Series (six synthetic curves, teaching aid only):**
  1. honest noise — random walk;
  2. misread dip — one-point spike, returns;
  3. one-off loss — step down, flat;
  4. object — step up, flat;
  5. active leak — ramp down;
  6. settling lag — dip, then return.
- **Reading rule:** match the shape of the real drift chart (C5) to this panel.
- **Why it works:** it turns an abstract residual pattern into six named pictures;
  the reader classifies by recognition, not by calculation.

---

## 4. Composition rules

1. **Always show raw and corrected together.** One without the other is a claim
   without evidence.
2. **Model first, data second.** The fitted curve is the reference; data points
   are read against it.
3. **One anomaly, one annotation.** If a chart needs five arrows, split it.
4. **Fixed limits across the raw/corrected pair.** Never autoscale one panel and
   not the other; the comparison is the point.
5. **The gallery order is a story:** shape (C4) → location (C2) → record (C3) →
   running total (C5) → significance (C6) → cause (C7). Do not present C7 first;
   it is the view that forbids a hasty correction.
6. **Every chart must survive a caption-free reading** by someone who knows the
   colour grammar. If it does not, the encoding is wrong, not the reader.

---

## 5. Reproduction skeleton

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# --- style constants (copy verbatim) ---
MODEL, RAW, COR, EXCL = "#1a6fa8", "#d62728", "#2ca02c", "#9467bd"
CHECK, ZERO, GREY = "#ff9f1c", "0.3", "0.6"
ANN = dict(fontsize=9, arrowprops=dict(arrowstyle="->", color="0.3"))

def raw_pts(ax, x, y, label=None, ms=5):
    ax.plot(x, y, "o", ms=ms, mfc="none", mec=RAW, mew=1.3, label=label)

def cor_pts(ax, x, y, label=None, ms=4):
    ax.plot(x, y, "s", ms=ms, color=COR, label=label)

def model_line(ax, x, y, label=None, lw=2.2):
    ax.plot(x, y, "-", color=MODEL, lw=lw, label=label)

def finish(ax, xlabel, ylabel, title, legend="upper left", grid=0.3):
    ax.axhline(0, color=ZERO, lw=1)
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title)
    if legend: ax.legend(loc=legend, fontsize=9)
    ax.grid(alpha=grid)

# --- C1 + C2 (main pair) ---
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.5, 9.5), sharex=True,
                               gridspec_kw={"height_ratios": [1.5, 1]})
model_line(ax1, Hg, V(Hg), "Fitted shell V(H)")
raw_pts(ax1, H, cum_raw, "Raw data")
cor_pts(ax1, Hc, cum_cor, "Corrected data")
ax1.axvline(BRIM, color="0.5", ls="--", lw=1)
ax1.set_ylabel("Cumulative volume (L)")
ax1.legend(loc="upper left", fontsize=9); ax1.grid(alpha=0.3)

ax2.fill_between(mid, -sig, sig, color=MODEL, alpha=0.12, label="±1σ")
raw_pts(ax2, mid, d_raw, "Raw table")
cor_pts(ax2, mid[:-1], d_cor[:-1], "Corrected")
ax2.plot(mid[-1], d_raw[-1], "x", ms=8, color=EXCL, mew=2)
ax2.set_ylim(-165, 165)
finish(ax2, "Tape reading H (mm)", "Residual, pred − obs (L)", "")
fig.tight_layout(); fig.savefig("pour_fit.png", dpi=160)
```

For C3–C7 use the same helpers; the only new primitives are:

```python
# y = x reference (C3)
ax.plot(lim, lim, "-", color=GREY, lw=1, label="y = x")
# fix arrows (C3)
ax.annotate("", xy=(x_fix, y_fix), xytext=(x_raw, y_raw),
            arrowprops=dict(arrowstyle="->", color=MODEL, lw=1.6))
# thresholds (C6)
ax.axhline(2, color=CHECK, ls="--", lw=1);  ax.axhline(-2, color=CHECK, ls="--", lw=1)
ax.axhline(3, color=RAW, ls=":", lw=1.2);   ax.axhline(-3, color=RAW, ls=":", lw=1.2)
# detector guides (C7)
ax.plot([-L, L], [-L, L], "-", color=MODEL, lw=1, alpha=0.6)
ax.plot([-L, L], [L, -L], "-", color=MODEL, lw=1, alpha=0.6)
ax.add_patch(plt.Rectangle((-2, -2), 4, 4, fill=False, ls="--", ec=CHECK))
```

---

## 6. Reading guide — one table

| Pattern | C2 residuals | C5 drift | C7 pairs | Verdict | Action |
|---|---|---|---|---|---|
| scatter inside band | noise | flat wobble | central cloud | honest | none |
| single spike | lone point | spike, returns | — | misread dip | re-dip; correct by pair arithmetic |
| adjacent ± pair | opposite signs, net ≈ 0 | spike, returns | anti-diagonal | shared dip | correct the shared level |
| single-sided | lone point | step, flat | axis | object or pour error | discriminate: repeat pour / inspect / tally |
| persistent | same-sign run | ramp | main diagonal | leak / continuing over-record | audit; do not refit |
| mixed | large, no partner | step + offset | off both diagonals | superposed errors | decompose before correcting |

---

## 7. Excel workbook wiring (`test/tank_calculator.xlsx`)

Seven native `ScatterChart` objects on the `Charts` sheet, all fed by `Calc`
formulas (200-row capacity). Ranges are `(min_col, min_row, max_col, max_row)`.

| # | Chart | x range | y range(s) | Type |
|---|---|---|---|---|
| 1 | Strapping vs books | `Calc X2:X102` | `Calc Y2:Y102` (line), `Calc F2:F201` (markers) | line + scatter |
| 2 | Residuals | `Calc I2:I200` | `Calc L2:L200` | scatter |
| 3 | Pred vs recorded | `Calc J2:J200` | `Calc K2:K200`; `Fit B14:B15`→`C14:C15` (y = x) | scatter + line |
| 4 | Slope profile | `Calc I2:I200` | `Calc R2:R200` (line), `Calc Q2:Q200` (markers) | line + scatter |
| 5 | Drift | `Calc A2:A201` | `Calc G2:G201` | scatter |
| 6 | z-alarms | `Calc I2:I200` | `Calc P2:P200`; `S/T/U/V` (±2, ±3 lines) | scatter + lines |
| 7 | Pair detector | `Calc P2:P200` | `Calc W2:W200`; `Fit B22:B23`→`C22:C23` (main diag); `Fit B24:B25`→`C24:C25` (anti-diag) | scatter + lines |

`Calc` column map: `A` H, `B` pour, `C` clipped depth, `D` V(H), `E` slope,
`F` books, `G` drift, `I` mid level, `J` pour, `K` pred, `L` resid, `M` include,
`N` SSE, `O` σ, `P` z, `Q` pour/rise, `R` shell slope, `S–V` threshold lines,
`W` z-next, `X` curve H grid, `Y` curve V.

Rules for the workbook charts:
- `x_axis.delete = False`, `y_axis.delete = False` (openpyxl hides axes by default);
- markers: `Marker(symbol="circle", size=6)`, line `noFill` for scatter series;
- model lines: `line.width = 20000`, `smooth = True`;
- threshold lines: `dashStyle = "dash"`, `smooth = False`;
- every generated workbook passes the formula gate (paren balance + parse).

---

## 8. Inline `openui-lang` equivalents

`LineChart` only — it cannot draw scatter, so C3 and C7 stay as images.

| Chart | Inline form |
|---|---|
| C1 | `LineChart(labels=H, series=[Fitted, Raw, Corrected])` |
| C2 | `LineChart(labels=mid, series=[Raw resid, Corrected resid])` |
| C4 | `LineChart(labels=mid, series=[Shell slope, Raw, Corrected])` |
| C5 | `LineChart(labels=H, series=[Raw drift, Corrected drift])` |
| C8 | `LineChart(labels=1..40, series=[six synthetic shapes])` |

Use `null` for missing points (the corrected series ends one row early).
Units go in the `LineChart` third argument (`"L"`, `"L/mm"`).

---

## 9. Checklist for a new tank

- [ ] Adopted shell fixed; `F`, `m`, `σ`, `z`, `books`, `drift` computed.
- [ ] Raw and corrected tables both available, with flags.
- [ ] C1 and C2 rendered first; confirm the corrected series lies inside the band.
- [ ] C3: every off-diagonal point explained or flagged.
- [ ] C4: no point off the shell curve without a cause.
- [ ] C5: no unexplained step or ramp; corrected drift ends inside `±3σ√n`.
- [ ] C6: observed vs expected counts at 2σ and 3σ reported.
- [ ] C7: every point off both diagonals decomposed.
- [ ] Fixed limits, same colours, same marker grammar as this document.
- [ ] Caption-free reading test passed.

---

## 10. Files produced in this project

| File | Contents |
|---|---|
| `test/pour_fit.png` | C1 + C2 (main pair) |
| `test/pour_fit_views.png` | C3 + C4 + C5 + C6 (gallery) |
| `test/anomaly_detector.png` | C7 + C8 (detector) |
| `test/tank_calculator.xlsx` | all seven as live native charts |
| `test/pour_corrected.csv` | corrected table behind every chart |

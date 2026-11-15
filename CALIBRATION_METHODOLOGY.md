# Calibration of horizontal cylindrical tanks — general methodology

**Scope.** This method straps any horizontal, near-circular, flat-ended cylindrical tank from pour/level data: pour a known volume, read the level, repeat. A tank that is already full is strapped the other way: pump a known volume out, read the level, repeat (drain, §3.11). It produces four artifacts: a strapping table, a fitted shell model, an anomaly register, and a live field protocol. It is distilled from four tank campaigns; every rule below was forced by a lesson from one of them (Appendix A).

**Methods used, in one line each:** pour-and-dip strapping at controlled rise increments; bound-constrained nonlinear least squares (trust-region reflective) with multi-start; robust-loss comparison (Huber); grid profiling for parameter uncertainty; constrained refit (SLSQP or penalty) for the brim and neck constraints; residual-signature analysis (pair rule, single-sided rule); adjacent-pair detector scatter with drift-shape taxonomy; quantized-pour grid search; interval blocking; telescoping block sums; back-prediction with propagated uncertainty; sensitivity battery; parametric bootstrap with per-dip covariance; closure audit; per-pour z-test validation in the field; one-step-ahead prediction from a prior-regularized running fit with a blind repeat reading (live check, before any shell is adopted); spreadsheet formula gate.

---

## 1. Products and authority

| Artifact | Role | Authority |
|---|---|---|
| Raw data file | The measurements, exactly as taken | Immutable |
| Empirical strapping table | Level → liquid volume, from cumulative pours | Authoritative record of what happened |
| Shell model `F(H)` | Smooth geometry for interpolation, prediction, checks | A tool. Never a replacement |
| Anomaly register | Objects, corrected dips, watch items | The explanation of every data↔model gap |

**Rule 1.1** — The raw file is never edited. Corrections live in derived files, one flag per row, with the rule and the magnitude.

**Rule 1.2** — When model and data disagree, the disagreement is a finding. Classify it (§6) or carry it as a watch item. Never average it away. Never fit it away silently.

**Rule 1.3** — One authoritative table per tank at any time. Superseded tables are marked, not deleted.

**Rule 1.4** — Between anchored levels, interpolate liquid volume with the adopted shell (§6.3). Never extrapolate past the last trusted dip, except in OVERFLOW mode (§10).

## 2. Conventions — one set, used everywhere

- **Units:** millimetres and litres. Nothing else in the tables.
- **Symbols:** `H` tape reading; `h = H − h0` true depth; `h0` datum offset; `r` radius; `L` shell length; `F(H)` model volume; `Vcap` shell capacity; `B = h0 + 2r` brim reading; `m(H)` local slope `dF/dH`.
- **Interval `i`:** pour `s_i` from `H_{i−1}` to `H_i`; `pred_i = F(H_i) − F(H_{i−1})`.
- **Residual convention (used everywhere, never its mirror):**

```
resid_i = s_i − pred_i          # litres; mm-equivalent = resid / m(H_i)
```

  - `resid < 0` → the rise came too cheap: a solid displaced liquid, or the pour was under-recorded (more liquid entered than the record claims).
  - `resid > 0` → the rise came too small: liquid went somewhere (leak, film, trapped air), or the pour was over-recorded (less entered than the record claims).
  - Read residuals in mm-equivalent first, litres second.
  - **Drain campaigns (§3.11)** keep this convention: `s_i` is the positive litres pumped out, and `pred_i = F(H_{i−1}) − F(H_i)`. The object and record signs stay the same. A leak flips to `resid < 0`. One new cause gives `resid > 0`: liquid that comes back (hose, wall film).
- **Dip-misread signs** (the whole pair rule in two lines): if the dip shared by two intervals is misread by `δ` (recorded − true = `δ`), then `r_first = −m·δ` and `r_second = +m·δ`. The net is exactly zero for a pure dip error.
- **Drift:** `D_k = Σ_{i≤k} resid_i` — the running books-versus-tank disagreement (equivalently `books_k − F(H_k)` up to the heel constant). The drift remembers every past error; the residual locates it. Its shape is a diagnostic (§6.6).

## 3. Campaign design

**Method: pour-and-dip strapping at controlled rise increments.**

- **3.1** Calibrate every can by mass, once. Read one meniscus edge, always. The pour noise you assume later (§9) must be a measurement, not a hope.
- **3.2** One tape, verified against a standard. One convention: innage or ullage — never mixed. Clean the datum plate each dip.
- **3.3** Sound the bottom before the first pour. Record the heel as a row. Never assume an empty start.
- **3.4** Size pours to the slope. Target rise ≈ `20·σh` (≈30 mm at σh = 1.5 mm). Floor ≈ `10·σh` (≈15 mm): below it, dip noise dominates (§7). Ceiling 100 mm: above it, shape detail is lost. Before the slope is known, estimate from nominal `D` and `L`; adapt from the third pour.
- **3.5** Settle ≥ 5 min after each pour; dip twice, 5 min apart. A creeping level means not settled — waves, foam, or a weep-hole lag (§6.4).
- **3.6** Log temperature every ~5 pours if the liquid expands (diesel ≈ 0.08 %/°C ≈ 8 L per 10 kL per °C). Correct to a reference temperature (VCF) if volumes are custody-grade.
- **3.7** Plan the final pour to overflow on purpose, and record the above-brim level. The overflow pour gives the strongest capacity constraint you will get (§5.3a).
- **3.8** Vent open; fill slowly at the start; trapped air lies.
- **3.9** File format: `step_volume,measured_height,note`. Unknown pours are legal cells: `?` (whole pour unknown) or `N+?` (N litres plus an unknown extra).
- **3.10** Record the pouring unit (drum size, meter increment, can count). Pours live on that grid; when a pour is later suspect, the grid is a discriminating constraint (§6.2), not a rounding detail.
- **3.11** Reverse strapping (drain). Use this for a tank that is already full. A pump draws the liquid out into calibrated cans. Each batch is one step, and the level falls from the top to the bottom. One file has one direction. A refill of the same tank is a new campaign.
  - **Same mathematics, mirrored.** Write the step as positive litres. Then `pred = F(H_{i−1}) − F(H_i)` and `resid = s − pred` (§2). A drain gives the same fit, residuals and corrections as the same steps poured in the reverse order. The slope of an interval is taken at its upper level, in both directions. Drift stays `D_k = Σ resid`; for a drain that is `F(H_k) − books_k` plus a constant.
  - **Sign changes.** There are two. A leak gives `resid < 0`, because liquid leaves another way and the fall is too large. In the pair rule, `δ = (r1 − r2)/(2m)`: the earlier interval falls too little (`r1 = +m·δ`) and the later one too much.
  - **Leak test first.** A full tank allows a static test. Take two readings at least 15 min apart before the first drain. A falling level is a leak; find it before you start.
  - **Start at the neck entrance (recommended).** Pump the neck down until the level reaches the shell crown. The neck is narrow, so there the level falls fast; in the shell it slows down a lot. That reading is the brim `B`: enforce `2r + h0 = B` (§5.3a) from the first level. A start in the neck is also correct: the reading is vent-column height, the drain out of the neck is the mirror of the overflow pour, and the same inequality `G = Vcap − F(H*) ≤ P` holds, with `H*` the first level in the shell.
  - **Hose state.** This is a new error source. The hose must be in the same state at every dip: always full (with a check valve), or always drained back into the tank. If the state changes between batches, each dip carries ± the hose volume. A hose that drains back gives a positive bias per batch; the telescoping block test (§9.6) finds it.
  - **Prime the pump before the start reading.** Priming liquid leaves the tank.
  - **Fill each can to its calibrated mark**, never until it overflows. A spill is litres that left the tank but are not on the record (`resid < 0`).
  - **Pour size** follows §3.4 (`≈ 30 mm` of fall). Near the crown the slope is small, so the first drains are small. The halving rule of §10 BRIM-WARN does not apply. Near the bottom the pump may lose suction: record a part can as `N+?`, or measure it.
  - **Settling.** After pumping, wall film drains down, and the level can creep up a little. §3.5 applies.
  - **The end.** The pump leaves a heel. Report it as the shell liquid at the last dip, and label it a shell value. Then use the empty tank: sound the bottom (this measures the datum, §12), and inspect for objects (the §6.2 discriminating test).
  - **File.** The same three columns. The heights fall. The first row holds the volume at the first level: a number when the prefill was metered, else `?`. The config sets `direction: drain`. The drain out of the neck is `brim.neck_drain`, and a start at the neck entrance sets `brim.reading` with `neck_equality`.

**3.12 Transfer strapping (two tanks, one water).** Calibrate two tanks with one water: a pump draws known volumes out of a full tank into calibrated cans, and the same cans are emptied into the other tank. Each batch is one step for both tanks: the first tank is a drain (§3.11), the second a fill. The litres are shared; the tanks are not. Each tank keeps its own raw file, its own fit and its own register, and the two files are fitted independently (`calib init`, `calib fit` on each; §5.4's joint fit applies when the tanks share fabrication).
  - **Paired residuals.** One batch gives two interval residuals, `resid_A = s − pred_A` and `resid_B = s − pred_B`, each in the §2 convention of its own direction. Because the cans are shared, a pour error (a miscount, a can not filled to its mark) enters both residuals with the same litres: `resid_A ≈ resid_B`. A loss on the way (a spill at the carry) enters only the receiving tank: `resid_B − resid_A` = the lost litres. A cause inside one tank (object, dip, hose) enters only that tank. The pour noise is common to both residuals and cancels in the difference, so `σ(resid_B − resid_A)` holds only the two dip noises (and, while a running shell is still weak, that shell's own error): the difference is a sharper test than either residual alone. A wide check on one side can confirm nothing — say so, do not guess.
  - **Reading the pair.** Same litres, both at the action bar → the cans, not a tank: recount; one recount corrects both raw files. Difference beyond the noise with the drain tank clean → litres lost on the way: the receiving tank's interval goes to the register (LOSS?), the drain tank's is good. Difference with one tank at the bar and the other clean → the cause is on the one side: the drain tank alone (hose, pump seal, spill at the can: LEAK? / RETURN?) or the fill tank alone (OBJECT?). Both at the bar with different litres → superposed causes: decompose (§6.2) before correcting either.
  - **Campaign rules.** Both first levels are dipped before the first batch: the drain tank per §3.11, the fill tank with its heel per §3.3. The batch size follows the tighter of the two 30 mm targets (§3.4), with the drain tank's bottom watch and the fill tank's brim watch. The campaign ends when the drain tank is empty or the fill tank reaches its brim, whichever comes first; plan the final batch to overflow the fill tank on purpose (§3.7) when the water allows it. The §3.11 hose rule applies to the drain tank's hose; the carry between the tanks is a new loss path — a can set down and spilled shows only in the receiving tank.

## 4. Geometry model

**Method: horizontal circular cylinder, flat ends, one datum offset.**

```
A(h)  = r²·acos((r−h)/r) − (r−h)·√(2rh−h²)     0 ≤ h ≤ 2r    [mm²]
F(H)  = L·A(clip(H−h0, 0, 2r)) / 1e6                         [L]
Vcap  = π·r²·L / 1e6                                          [L]
B     = h0 + 2r                                               [mm]
m(H)  = 2L·√(2rh−h²)/1e6   at h = H−h0                        [L/mm]
```

Assumption tests — run all four, record the results:
- **flat ends** → closure identity, §9.3;
- **circular section** → measure circumference at 3+ heights; treat fitted `r` as an effective mean;
- **no static tilt** → tilt test §5.5, or a recorded limitation §12;
- **known bottom shape** → `h0` absorbs part of it; the heel row is an estimate unless the bottom was sounded.

## 5. Fitting

**Method: bound-constrained nonlinear least squares on interval differences; multi-start; robust loss compared; physical constraints enforced inside the fit.**

### 5.1 Difference fit (default)

Unknowns `(r, L, h0)`. Residuals over the trusted set: `resid_i = s_i − (F(H_i) − F(H_{i−1}))`.

- **Trusted set** = every interval except: unknown pours, overflow intervals, declared object bands (§6.3), and non-positive rises.
- Why differences: a wrong first pour or an unknown start volume cancels exactly. The cumulative fit (`Vcum = F + C`) needs an extra offset `C` and inherits any first-pour error; use it only as a cross-check.

### 5.2 Optimizer

Trust-region reflective least squares, bounded (e.g. `r ∈ [0.6, 1.4]×` nominal, `L ∈ [0.7, 1.3]×` nominal, `h0 ∈ [−80, 80]` mm). Multi-start over a grid of `(r0, L0, h0)`; keep the best SSE. Run both linear loss and Huber loss (`f_scale ≈` one interval's σ). Adopt the linear fit unless Huber moves a parameter by more than its profile uncertainty.

### 5.3 Physical constraints — inside the fit, not after it

- **a. Brim constraint.** If a pour of volume `P` overflowed the shell from last level `H*`, then the shell-top gap obeys `G = Vcap − F(H*) ≤ P`. A pour cannot fill a gap larger than its own volume. Tighten to `G ≤ P − V_vent` if the vent volume is known. Fit with this as an inequality constraint (SLSQP or penalty). If the constraint binds, adopt the constrained fit and report both fits. **An unconstrained fit that violates the constraint is not a result — it is a bug.** The dip taken when liquid first reaches the neck or brim reads `B` itself (neck entrance = shell crown): add the equality `2r + h0 = B` and report the free fit's agreement with it. Both directions carry information: `G ≤ P` — the pour filled the shell and continued into the vent; adopt the constrained fit. `G > P` while the field confirms the tank reached the brim — the recorded pour is nominal: treat that row's pour as an unknown (§8), back-predict `x = G`, exclude the row from the fit. **An overflow row's height is data; its pour is a claim.** A drain that starts in the neck uses the same constraint (§3.11): the litres pumped from the neck reading to the first level in the shell must cover `G` at that level. A drain that starts at the neck entrance has the equality and no inequality.
- **b. Empty-start check.** Always report the first row's residual: `s_1 − F(H_1)` (empty start) or `s_1 − (F(H_1) − F(H_heel))` (heel present). A silent first interval is an unchecked assumption.
- **c. Monotonic levels.** `H` must strictly increase. A non-positive rise is a data error: excluded and flagged.

### 5.4 Joint fits

If tanks share fabrication (same shell diameter), fit one common `r` with separate lengths: `p = (r, L1, L2, …)`, one `h0` policy for all (all locked, or all free). Adopt only if a common-`r` scan shows a negligible RMSE penalty. This stabilizes `r`, which single-tank data identifies weakly.

### 5.5 Identifiability — state what the data cannot tell you

- **Tape scale** (tilted or stretched tape): exact degeneracy `(r, L, h0) → (r/s, s²L, h0/s)` leaves every volume prediction unchanged. The table is invariant; only the physical dimensions carry the error. Never fit `s`. If dimensions matter, measure the tape independently (plumb it, or dip one true level at two tape angles).
- **r–L tradeoff:** profile `r` on a grid (±10 mm in 1 mm steps), record the RMSE profile, quote `r ±` from the profile. Never quote `r` to 0.1 mm when the profile is flat over millimetres. (A bootstrap over intervals gives formal intervals if needed; the profile is usually enough. For deliverable-grade intervals, bootstrap parametrically — fresh dip and pour noise on the recorded chain — and note that naive (JᵀJ)⁻¹ errors run ~40 % large because adjacent residuals share a dip; a GLS with per-dip covariance reproduces the bootstrap.)
- **Datum offset `h0`:** lock `h0 = 0` when the datum is physically set (tape zero = tank bottom) and the lock costs ≤ ~0.05 L/step; otherwise fit it. Report the cost either way. When the cost is material (≳ 0.5 L/step, or an F-test on the lock rejects), diagnose the cause with the telescoping block test (§9.6): a deficit concentrated in the bottom block is a datum/bottom-shape effect; one proportional to pour size is pour bias. A brim equality (§5.3a) removes most of the r–h0 trade — quote the tightened intervals.
- **Static tank tilt:** NOT absorbed by `r` — it bends the shape of `V(H)` asymmetrically. Test by adding one tilt parameter `ε` (volume by numerical integration of `A(h(x))` along the axis, `h(x)` linear in `x`). Keep `ε` only if RMSE drops materially and `ε` is physically plausible. If untested, record it as a limitation (§12).

### 5.6 Spreadsheet reproduction (fallback)

A Solver (GRG) sheet can reproduce the cumulative fit, but it must include: a `C` offset cell when the start volume is unknown; exclusion of flagged rows from the objective; and the brim constraint as a Solver constraint. Prefer the shipped script; the sheet is an audit aid.

### 5.7 Fit acceptance — a fit is adopted only when all six hold

1. RMSE in mm-equivalent ≈ `√2·σh` (§9.4) — no missing error term;
2. no unexplained residual at or above the action bar (§6);
3. every physical constraint satisfied, with binding status reported;
4. closure identity (§9.3) within `3σ√n`;
5. the sensitivity battery (§8.3) moves no conclusion;
6. linear and Huber losses agree within the parameter uncertainty.

## 6. Anomaly classification — the decision tree

**Method: residual-signature analysis with one fixed action bar.**

**Action bar (one bar for every tank, no exceptions):**
- candidate: `|resid| ≥ 3 mm`-equivalent **and** `|z| ≥ 3`;
- watch: `|resid| ≥ 1.5 mm`-equivalent or `|z| ≥ 2`;
- below watch: noise.

### 6.1 Pair rule — shared dip misread

Four conditions, all required:
1. two adjacent intervals, residuals of opposite sign;
2. each at or above the action bar;
3. **net balance:** `|r1 + r2| ≤ 0.15 × (|r1| + |r2|)`. A pure dip error nets exactly zero. Genuine pairs in the source campaigns ran ≤ 10 %; the one false correction ran 23 %. The net is invariant under the correction — a large net means the dip cannot explain the pair, and correcting it bakes in half of something else;
4. confirmation: live — re-dip the shared level; retrospective — the refit after correction moves no conclusion (§5.7-5).

Correction and bookkeeping:

```
δ = (r2 − r1) / (2·m)        # m = local slope at the shared dip
true dip = recorded − δ
```

For a drain (§3.11) the two signs swap, so `δ = (r1 − r2) / (2·m)`. The net-balance test does not change.

Apply in the corrected table; flag the row; keep the raw value in the note. If the net balance is marginal (0.15–0.25), do not correct: mark the dip suspect and decide with a re-dip or a grouped refit (§7).

### 6.2 Single-sided rule — object or pour error

`|resid|` at or above the action bar, no partner. Two live hypotheses — **one pass of pour/level data cannot separate them:**
- **OBJECT:** a solid in that band (`resid < 0` — the rise came too cheap);
- **POUR:** a mis-recorded pour volume (either sign), or a loss (`resid > 0`: leak, film, trapped air).

Discriminating tests — name at least one in the register:
- repeat a known pour into the same band (an object reproduces the residual; a pour error does not);
- if pours are quantized (§3.10): grid-search the suspect pour(s) on the unit grid, letting the shared dips move under a dip-noise prior, ranked by penalized χ² — a superposed pour + dip error decomposes decisively where the pair rule alone misfires (§6.6);
- inspect the tank;
- pump-out audit.

Until discriminated: exclude the band from the fit; keep it in the empirical table; flag it; treat every cumulative volume above the band as `±|resid|`.

### 6.3 Object bookkeeping

This is where naive calibrations go wrong.
- While the level crosses the object, one interval carries the displaced volume `d`.
- Once the object is fully submerged, the displacement is **constant**. Difference residuals return to zero. The object vanishes from the fit — but not from the liquid.
- Therefore:

```
liquid(H)      = F(H) − Σ blocked volumes below H      (objects + permanent voids)
to-brim(H)     = Vcap − F(H) − Σ blocked volumes above H
max liquid     = Vcap − Σ all blocked volumes
closure: books_0 + Σ poured + Σ blocked below H ≈ F(H)    (§9.3)
```

- Read liquid volumes from the empirical cumulative table, or subtract blocked volumes from `F`. Never quote raw `F(H)` as "liquid in tank" where objects are declared.
- `d` is the displacement **in that band**, not necessarily the object's total volume: a vertical member crossing the band shows in every band it crosses. Look for partners before declaring a volume.

### 6.4 Void, leak, lag

- **Permanent void or leak:** over the enclosing band, the net residual equals the hidden volume. Net ≈ 0 → no permanent loss.
- **Transient lag** (stilling well, weep hole): repeat static dips 1 min and 10 min apart. Creep ≈ the pair's mm-equivalent confirms lag. Correct the reading time, not the level.

### 6.5 Watch items

1.5–3 mm-equivalent, isolated: recorded, never corrected, never excluded. They are the audit trail of "almost".

### 6.6 Detector views — locate the failure mode before touching data

- **Adjacent-pair scatter.** Plot every adjacent interval pair as one point `(z_i, z_{i+1})`. Honest noise → central cloud inside ±2. Shared-dip misread → anti-diagonal (`z_i ≈ −z_{i+1}`). Single-sided event → the axes, sign per §2 (object/under-record toward −, loss/over-record toward +). A persistent effect → a chain on the main diagonal, sign per §2: (+,+) continuing loss / over-record, (−,−) continuing displacement / under-record. **Off both diagonals → superposed errors: decompose (§6.1 arithmetic, §6.2 grid) before correcting anything** — a correction applied to a superposition bakes in half of each cause.
- **Drift shapes.** The drift chart (`D_k`, §2) remembers every past error; its shape names the cause — the residual locates, the drift remembers. Flat wobble = honest noise. One-point spike that returns (either sign) = one misread dip. Single step then flat = one-off event: up = loss / over-record, down = object / under-record. Ramp that never returns = persistent effect — audit, do not refit. Dip then return = settling lag (§6.4), net ≈ 0.
- **Chart catalog** — seven views; each catches a failure mode first. Type and purpose:

| Chart | Type | Purpose |
|---|---|---|
| Strapping vs books | fitted `V(H)` line + cumulative-books points | where the ledger leaves the tank; every step is mis-accounted litres |
| Interval residuals | resid vs level | location and size of every disagreement; adjacent ± pairs and single-sided events |
| Predicted vs recorded | recorded pour vs predicted pour, with y = x line | off-diagonal points = bad pour record or bad dips |
| Slope profile | pour/rise points vs shell-slope curve | rows jumping off the smooth curve are physically impossible |
| Drift | `D_k` vs level | the running total; shape names the failure mode (above) |
| z-alarms | z vs level, with ±2 and ±3 threshold lines | significance against the action bar (§6, §10) |
| Adjacent-pair scatter | `(z_i, z_{i+1})` points | the failure-mode compass (above) |

The shipped workbook implements all seven as live charts. Consult the pair scatter last: it is the view that forbids a hasty correction.

## 7. Small pours and grouping

**Method: interval blocking to raise signal over dip noise.**

- **7.1 Noise floor.** An interval carries level noise `√2·σh`. If the planned rise is below `10·σh` (≈15 mm at σh = 1.5), the interval adds more noise than shape.
- **7.2 Blocking.** Merge adjacent trusted intervals into one block (sum the steps, keep the boundary dips) for fitting only. Rules:
  - block only across trusted, fully known pours;
  - accident/unknown rows stay solo, at their native rise, so nothing leaks into their back-prediction;
  - **block boundaries are fit points** — a misread at a boundary still matters; grouping "dissolves" only the interior dips;
  - the empirical table keeps every raw row, with the merge documented in the note;
  - RMSE is not comparable across grouped vs ungrouped fits (different weights). Compare geometry and predictions instead.

## 8. Unknown pours

**Method: back-prediction from the adopted shell; never fitted.**

- **8.1** `x = F(H_i) − F(H_{i−1}) − known_base`. The unknown never enters the fit, so it cannot pull the geometry.
- **8.2** One uncertainty formula for all unknowns:

```
σ_x = √( (√2·m·σh)² + (rel·known_base + abs)² )
```

  widened by the fit-shape spread from 8.3. Quote `x ± 2σ_x`. Never hand out different formulas per row.
- **8.3 Sensitivity battery.** Refit under `{linear, Huber} × {h0 locked, free} × {r free, common-r} × {suspect exclusions on/off}`. Report the range of `x`. Adopt the value from the final adopted (constrained) shell. If the range exceeds the level-noise term, the shell is not settled — fix the shell before quoting `x`.

## 9. Uncertainty budget — one set of numbers, everywhere

**Method: explicit propagation of dip and pour noise; closure audit.**

- **9.1** Choose `σh` per campaign and use it in the document, the tables, and the tool alike: careful dipping 1.0 mm; field conditions 1.5 mm. Choose pour noise from the can calibration: `rel` (e.g. 0.5 %) + `abs` (e.g. 3 L).
- **9.2** Per interval: `σ² = (m·σh·√2)² + (rel·s + abs)²`; `z = resid/σ`.
- **9.3 Closure identity:** `books₀ + Σ poured + Σ blocked volumes below H ≈ F(H)`, within `3σ√n`. `books₀` is the liquid on the books at the first recorded level: the first row's pour when known, `F(H₀)` when the first pour is unknown. Without that term the identity is short by exactly the first pour. Report it with every fit and every field run. A drifting closure is the best single live alarm.
- **9.4 Sanity:** `RMSE / m` should land near `√2·σh`. Much larger → find the structure (pairs, singles, drift) before quoting anything. Much smaller → `σh` is over-conservative; say so.
- **9.5 Noise split from the data.** Adjacent residuals share a dip, so their lag-1 autocorrelation is negative, ≈ `−(m·σh)²/σ²` when dip noise dominates. Method-of-moments on the residuals splits the interval σ into dip and pour parts; the implied RMSE must equal the observed (§9.4). Prefer the measured split when quoting unknowns (§8.2) and z-scores.
- **9.6 Telescoping block test.** In a block sum of residuals every interior dip appears twice with opposite signs and cancels; only the two boundary dips and the pour noise remain: `σ_block = √((m₁² + m₂²)·σh² + Σ(rel·s + abs)²)` — far smaller than `√n·σ`. Run bottom/middle/top thirds at every adoption: a block sum beyond `3·σ_block` is a systematic effect (datum offset, pour bias, slow leak) even when no single interval clears the watch bar.
- **9.7 Multiple comparisons.** With `n` intervals, chance alone puts ≈ `0.05·n` residuals beyond |z| = 2 and ≈ `0.003·n` beyond |z| = 3. Report observed versus expected counts with every scan: a clean scan that expected two flags, and a noisy one that found ten, are both findings.

## 10. Field protocol (live validation)

**Method: per-pour z-test against the adopted shell, with a fixed flag taxonomy.**

- **OK:** `|z| < 2`.
- **CHECK:** `|z| ≥ 2` → re-dip both endpoints after settling.
- **ALARM:** `|z| ≥ 3` and ≥ 3 mm-equivalent → stop; re-dip; if confirmed: `OBJECT?` (`resid < 0`) / `POUR?` or `LOSS?` (`resid > 0`); run a discriminating test (§6.2) before believing either.
- **DIP-PAIR:** evaluate §6.1's four conditions live; print the estimated correction with direction; re-dip that one level.
- **DETECTOR:** after the run, plot the adjacent-pair scatter (§6.6); a point off both diagonals means superposed errors — decompose (§6.2) before correcting.
- **BRIM-WARN:** gap < 5 % of `Vcap` or within 60 mm of brim → halve the pour.
- **BOTTOM-WARN (drain):** liquid < 5 % of `Vcap` or within 60 mm of the bottom → the pump may lose suction; record a part can as `N+?`. No halving.
- **NECK (drain):** a level above the brim, or the first drain out of the neck → vent-column height; record it for the brim constraint, keep it out of the test.
- **OVERFLOW:** `H` above brim → vent mode: the reading is vent-column height, not shell level. Record it; it feeds the brim constraint.
- **DRIFT:** `|Σ resid| > 3σ√n` → stop and audit (tilt? can size? leak?).
- **Unknown pours:** estimated with ±2σ bands; never fitted.
- **POUR-SIZE advisor:** next pour ≈ `m × 30 mm`; warn below the §7.1 floor and above 100 mm of rise.
- Print the closure line every run.

## 10a. Live campaign check (no adopted shell yet)

**Method: one-step-ahead prediction from a prior-regularized running fit; blind repeat reading on demand.**

§10 needs an adopted shell. A first campaign has none. The question on site is narrower: *is this dip good, or must I dip again?* It must be answered **before the next pour**. After that pour the level is gone, and the pair rule (§6.1) can only point at a dip that nobody can re-read.

- **10a.1 Running shell.** After every decided level, refit `(r, L, h0)` by the difference fit (§5.1) on the **accepted intervals only**, plus one residual per prior: `r = D/2`, `L`, `h0 = 0`, each with the on-site ± taken as 2σ. Weak priors are harmless: the data take over within a few pours. The level under test never enters the fit that judges it.
- **10a.2 Prediction.** For pour `s` from accepted level `H_a`: `Ĥ = F⁻¹(F(H_a) + s)`. Its σ in mm combines the anchor reading `σr·m_a/m`, the new reading `σr`, the pour `(rel·s + abs)/m`, and the shell `∇Ĥᵀ·Cov·∇Ĥ`. Multiply by a noise scale `c = max(1, median|z|/0.6745)` taken from earlier one-step misses, shrunk toward 1 while they are few.
- **10a.3 Reading noise is a measurement.** `σr` is the repeatability of one reading: many dips at one still level, no pouring. It is smaller than the interval noise of §9 (0.2–0.4 mm against 0.8–1.2 mm-equivalent in the source campaigns): most interval scatter is pour noise and settling, not the tape.
- **10a.4 Decision on the first reading.** Accept when `|z| < 2`, the miss is `< 3 mm`, **and** the test is sharp (`2σ ≤ 3 mm`). Otherwise ask for a second reading. A blunt test cannot catch a 3 mm slip, so it does not get to accept one.
- **10a.5 Always two readings** where no prediction exists: the first level, an unknown pour (`?`, `N+?`), and a blunt prediction.
- **10a.6 Blind repeat.** Hide the earlier readings and the prediction until the new reading is in. A reader who knows the expected number tends to read it.
- **10a.7 Repeat test.** Two readings agree when they differ by `≤ max(1 mm, 2.5·√2·σr)`. Adopt their mean. No agreeing pair → read again; readings that move in one direction → not settled (§3.5, §6.4): wait.
- **10a.8 Confirmed miss.** Two agreeing readings that still miss the prediction make the **dip good**, so the cause is the pour or the tank:
  - fewer than 3 fit intervals → LEARNING: the bottom shape and the datum are not known yet; keep the level in the fit;
  - below the action bar (§6) → WATCH: keep it in the fit (§6.5);
  - at or above the action bar → ALARM: recount the pour; if the count stands, `OBJECT?` (`resid < 0`) or `LOSS?` (`resid > 0`), exclude the interval from the running fit, keep the level as the next anchor, register it (§6.2);
  - a previous interval of opposite sign with net ≤ 15 % → the earlier level was the misread one; mark it suspect for §6.1 in the final fit.
- **10a.9 The record.** One raw row per level with the adopted reading; every reading and the live state go in the note. The running shell is a tool for the live check, never the deliverable: the campaign file goes through `calib init` and `calib fit` (§5–§9) as usual.
- **10a.10 Expected performance.** On synthetic campaigns like the source tanks (σr = 0.4 mm, pours 0.5 % + 3 L, D known to ±200 mm): one reading slipped by 3 mm is caught 92 % of the time, 4 mm or more every time; an honest reading triggers an extra dip 3–6 % of the time; a false ALARM ≤ 0.3 %.

## 11. Deliverables (per tank)

- [ ] `*_raw.csv` — immutable, notes only.
- [ ] `*_corrected.csv` — every correction flagged with rule and magnitude.
- [ ] Authoritative strapping table — level, liquid volume (blocked-volume corrected, §6.3), `±σ`, flags. One per tank.
- [ ] Adopted shell record (template below).
- [ ] Anomaly register: object bands (band, displacement, discriminating test, status), corrected dips, watch items.
- [ ] Fit script shipped in the repository; tool presets identical to the adopted shell — one source of truth.
- [ ] Empty-start/heel residual reported.
- [ ] Unknown pours with one formula.
- [ ] Closure number, last run.
- [ ] Commercial chart (when required): generated from the adopted shell at a fixed dip interval, whole litres, valid from the lowest verified dip to the brim; the region below the lowest dip labelled "extrapolated". The shell curve carries the chart only where §5.7 passes and every object band is patched (§6.3); state the QA agreement number (max |books − F| over corrected rows); the corrected empirical table ships with the chart as the record.
- [ ] Datum statement in the table header: `h0` value, locked|fitted, lock cost, and `V(0)` when ≠ 0. Shift to "volume above tape zero" only on request, with the excluded heel stated. Datum measured (plumb, or dip near empty) before custody grade.
- [ ] Generated spreadsheets pass a formula gate: parenthesis balance and a formula parse over every cell; ranges in canonical single-sheet form.

Adopted shell record template:

```
Tank X — adopted shell
  r = ____ ± ____ mm    L = ____ ± ____ mm    h0 = ____ mm (locked|fitted, lock cost ____ L/step)
  brim reading ____ mm    Vcap ____ L    max liquid ____ L
  heel ____ L (sounded | fitted ± ____ L)    datum cause: measured | unresolved (§12)
  brim constraint: ____ (binding at G = ____ | slack)
  RMSE ____ L/step = ____ mm-equiv    σh = ____ mm
  blocked volumes: ____    corrected dips: ____    watch items: ____
  unknown pours: ____ ± ____ L
  authoritative file: ____
```

## 12. Limitations — state them, never hide them

- **Static tilt:** untested unless §5.5's test ran.
- **Tape scale:** unidentifiable from pour/level data; the volume table is invariant; the physical dimensions carry it.
- **Object vs pour error:** not separable from one pass; needs a repeat pour, an inspection, or a pump-out audit.
- **Ovality and bulging:** `r` is an effective mean; measure circumference at 3+ heights for custody grade.
- **Bottom shape:** `h0` absorbs part of it; the heel is an estimate unless the bottom was sounded. A raised datum and a wide bottom produce the same residuals — pour/level data cannot separate them; measure the datum to close it.

---

## Appendix A — Provenance (rule ← lesson)

- **Brim constraint (5.3a):** an unconstrained fit wanted a 66 L top gap; the last pour was 50 L and the tank overflowed. Impossible.
- **Net balance (6.1-3):** one dip was corrected on a pair with a 23 % net; a grouped refit later showed the dip was fine. Genuine pairs ran ≤ 10 %.
- **Net invariance (6.1-3):** that same "corrected" pair landed at −9/−9 L afterwards — the correction had baked in half of a pour error, not a dip error.
- **Object bookkeeping (6.3):** a report quoted "usable 7065 L" while the tank held 7023 L; a declared 44 L object had not been subtracted, and the empirical table said so all along.
- **One residual convention (§2):** the same object appeared as +44.4 in one section and −34.4 in the next, because two sections used opposite signs.
- **One σh, one error formula (8.2, 9.1):** two unknown pours got ±10 L and ±15 L from the same mathematics.
- **Blocking rules (7.2):** 200 L pours bought 20 mm of rise — pure dip noise; 800 L blocks bought 80 mm. But a block-boundary dip stayed a fit point, and the "dissolved" correction there was the false one.
- **Uniform action bar (§6):** a 13.6 L residual became a watch item on one tank; −24 L and −23 L residuals on another were never mentioned.
- **Empty-start always reported (5.3b):** a −7 L first-fill residual sat in every fit and was never printed.
- **Presets = adopted shell (§11):** the field tool shipped the unconstrained shell after a constrained fit had been adopted.
- **Immutable raw, flagged corrections (1.1):** three rounds of dip corrections were needed; only flagged, reversible edits kept the record trustworthy.
- **Refit-invariance check (6.1-4):** after corrections, geometry and back-predicted unknowns did not move — the proof that they were gauge errors, not shape information.
- **Pour-unit grid (3.10, 6.2):** a |z| = 10.7 pour anomaly hid two superposed errors — a phantom 200 L unit and a 3 mm dip slip. The pair rule alone mis-corrected a neighbour dip; the unit-grid search (χ² 39 vs 201 runner-up, 291 as recorded) decomposed both in one pass.
- **Neck reading = brim (5.3a):** the last dip read 2475 mm as water reached the neck; the free fit put the shell top at 2472 [2462–2485] — the reading anchored the r–h0 trade. The recorded 100 L pour could not fill the 222 L gap: the height was data, the pour a claim, back-predicted at 222 ± 8 L.
- **Telescoping block test (9.6):** the bottom third of a campaign summed to 164 L against ± 39 L of block noise while no single interval cleared the watch bar — a real datum offset (h0 ≈ −34 mm, lock cost 2.4 L/step, F-test p = 0.001) that per-interval scanning never saw.
- **Noise split (9.5):** lag-1 autocorrelation −0.29 split interval noise into σ_dip ≈ 0.6 mm and pour σ ≈ 8.5 L; implied RMSE = observed. The σ you assume becomes a measurement.
- **Detector scatter (6.6):** the superposed pour + dip error landed off both diagonals of the pair scatter — the signature that forces decomposition instead of a pair-rule correction.
- **Chart backbone + QA (§11):** corrected books tracked the fitted curve to 23 L max (mean 8 L) over 45 intervals — the agreement number that lets the smooth curve carry the commercial table, with the empirical record attached.
- **Datum in the deliverable (§11):** the fitted datum put 67 L below tape zero and 1.3 % of capacity below the lowest dip — the honest table starts at the verified dip and labels the rest extrapolated.
- **Formula gate (§11):** Excel 365 rejected a shipped workbook: one extra parenthesis in 101 generated formulas, plus 200 non-canonical double-sheet ranges. A parenthesis + parse gate now runs before any spreadsheet ships.
- **Live check before the next pour (§10a):** replayed live, two campaigns flagged their known faults at the level where they happened: a shared-dip pair (+3.4 / −3.5 mm) at its first dip, and the superposed phantom unit + dip slip at z = −10. Both called for a re-dip of a level that was still there. The pair rule found them only after the level was gone.
- **Learning phase (§10a.8):** the first three replayed pours missed the prediction by up to 10 mm. The datum was −30 mm and the shell did not know it yet. Confirmed early misses teach the shape; they are not anomalies.
- **Reading σ ≠ interval σ (§10a.3):** 25 repeat dips at one level scattered 0.36 mm, while the fitted interval noise ran 0.8–1.2 mm-equivalent. Using the interval σ for the repeat test would have passed 3 mm slips as agreement.
- **Reverse strapping (§3.11):** not yet forced by a field lesson. It is derived from the mirror symmetry and proved on synthetic campaigns: the drain fit equals the reversed fill fit to the optimizer tolerance. The hose rule comes from the physics of a pump line; take it as a rule to test on the first real drain campaign.
- **Sign check (§2):** an over-recorded pour produced `resid > 0` in the §2 convention, exposing swapped pour labels in the draft — the exact bug class the single-convention rule exists for.

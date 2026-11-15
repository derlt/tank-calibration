/* calib site core — live dip check for a campaign in progress (§10a).
 *
 * One source for the browser page and the Node tests.  No DOM, no I/O.
 * Units: millimetres and litres.  Residual convention of §2:
 *   resid = s − pred   (litres); mm-equivalent = resid / m(H)
 *
 * The shell is not known yet.  After every accepted level the core refits
 * (r, L, h0) on the accepted intervals only, with the on-site estimates as
 * priors, and predicts the level that the next pour must give.  The new dip
 * is compared with that prediction before the next pour, while the liquid
 * still stands at that level and a re-dip is still possible.
 *
 * Two directions.  A FILL campaign pours known volumes in and the level
 * rises from the bottom to the brim.  A DRAIN campaign (reverse strapping)
 * starts with a full tank and pumps known volumes out into calibrated cans;
 * the level falls from the brim or the neck to the bottom.  Step volumes are
 * always positive litres, heights are chronological, and dir = +1 (fill) or
 * −1 (drain):
 *   travel = dir·(H − H_anchor) > 0,   pred = dir·(F(H) − F(H_anchor)),
 *   resid  = s − pred  (the §2 sign, the same in both directions).
 *
 * A TRANSFER campaign (§3.12) calibrates two tanks with one water: it wraps
 * one drain session (tank A, pump out) and one fill session (tank B, pour in)
 * around a shared can tally, and compares the two residuals of each batch.
 * See TransferSession below.
 */
(function (root) {
  "use strict";

  // ---------------------------------------------------------------- geometry (§4)
  function area(h, r) {
    const hc = Math.min(Math.max(h, 0), 2 * r);
    const c = Math.min(Math.max((r - hc) / r, -1), 1);
    return r * r * Math.acos(c) - (r - hc) * Math.sqrt(Math.max(2 * r * hc - hc * hc, 0));
  }
  function volume(H, p) { return p.L * area(H - p.h0, p.r) / 1e6; }
  function slope(H, p) {
    const h = Math.min(Math.max(H - p.h0, 0), 2 * p.r);
    return 2 * p.L * Math.sqrt(Math.max(2 * p.r * h - h * h, 0)) / 1e6;
  }
  function capacity(p) { return Math.PI * p.r * p.r * p.L / 1e6; }
  function brim(p) { return p.h0 + 2 * p.r; }
  /** Tape reading at which the shell holds V litres (bisection). */
  function levelFor(V, p) {
    let lo = p.h0, hi = p.h0 + 2 * p.r;
    if (V <= 0) return lo;
    if (V >= capacity(p)) return hi;
    for (let i = 0; i < 80; i++) {
      const mid = 0.5 * (lo + hi);
      if (volume(mid, p) < V) lo = mid; else hi = mid;
    }
    return 0.5 * (lo + hi);
  }

  // ---------------------------------------------------------------- small linear algebra
  function solve3(A, b) {
    // Gaussian elimination with partial pivoting, n = A.length (3 here).
    const n = b.length;
    const M = A.map((row, i) => row.concat([b[i]]));
    for (let c = 0; c < n; c++) {
      let piv = c;
      for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[piv][c])) piv = r;
      if (Math.abs(M[piv][c]) < 1e-300) return null;
      [M[c], M[piv]] = [M[piv], M[c]];
      for (let r = 0; r < n; r++) {
        if (r === c) continue;
        const f = M[r][c] / M[c][c];
        for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k];
      }
    }
    return M.map((row, i) => row[n] / row[i]);
  }
  function inverse3(A) {
    const n = A.length, out = [];
    for (let j = 0; j < n; j++) {
      const e = new Array(n).fill(0); e[j] = 1;
      const col = solve3(A, e);
      if (!col) return null;
      out.push(col);
    }
    return out[0].map((_, i) => out.map((col) => col[i])); // transpose of columns
  }
  function jtj(J) {
    const p = J[0].length, out = [];
    for (let a = 0; a < p; a++) {
      out.push([]);
      for (let b = 0; b < p; b++) {
        let s = 0;
        for (const row of J) s += row[a] * row[b];
        out[a].push(s);
      }
    }
    return out;
  }
  function quad(g, C) {
    let s = 0;
    for (let a = 0; a < g.length; a++) for (let b = 0; b < g.length; b++) s += g[a] * C[a][b] * g[b];
    return s;
  }

  // ---------------------------------------------------------------- prior fit
  const NAMES = ["r", "L", "h0"];
  const toP = (x) => ({ r: x[0], L: x[1], h0: x[2] });

  /** Pour noise of §9.1, litres. */
  function pourSigma(s, cfg) { return cfg.pourRel * Math.abs(s) + cfg.pourAbs; }

  /** The noise a scored check was made with.  A change of it makes the old z stale. */
  function noiseOf(cfg) { return { sr: cfg.sigmaRead, rel: cfg.pourRel, abs: cfg.pourAbs }; }
  function sameNoise(a, b) {
    return !!a && a.sr === b.sr && a.rel === b.rel && a.abs === b.abs;
  }

  /**
   * Maximum a posteriori fit of (r, L, h0): the difference fit of §5.1 plus
   * one residual per prior.  Levenberg–Marquardt with a numerical Jacobian.
   * ivs: [{H1, H2, s, n1, n2}]  (n = number of dips averaged at the level)
   * H1 is the lower level and H2 the upper one in both directions.
   * prior.B (optional): a brim reading B with its σ prior.sB, one more
   * residual ((2r + h0) − B)/σB — the neck-entrance dip of a drain (§5.3a).
   */
  function fitShell(ivs, prior, cfg, start) {
    const pr = [prior.r, prior.L, prior.h0];
    const ps = [prior.sr, prior.sL, prior.sh0];
    const lo = [0.5 * prior.r, 0.5 * prior.L, -400];
    const hi = [1.5 * prior.r, 1.5 * prior.L, 400];
    const clamp = (x) => x.map((v, i) => Math.min(Math.max(v, lo[i]), hi[i]));
    const hasB = prior.B != null && isFinite(prior.B) && prior.sB > 0;
    function f(x) {
      const p = toP(x), out = [];
      for (const iv of ivs) {
        const m = Math.max(slope(iv.H2, p), 1e-3);
        const sd = Math.sqrt(m * m * cfg.sigmaRead * cfg.sigmaRead * (1 / iv.n1 + 1 / iv.n2)
          + Math.pow(pourSigma(iv.s, cfg), 2));
        out.push((iv.s - (volume(iv.H2, p) - volume(iv.H1, p))) / sd);
      }
      for (let i = 0; i < 3; i++) out.push((x[i] - pr[i]) / ps[i]);
      if (hasB) out.push((2 * x[0] + x[2] - prior.B) / prior.sB);
      return out;
    }
    function jac(x, f0) {
      const J = f0.map(() => [0, 0, 0]);
      for (let j = 0; j < 3; j++) {
        const d = 1e-4 * Math.max(1, Math.abs(x[j]));
        const xp = x.slice(), xm = x.slice();
        xp[j] += d; xm[j] -= d;
        const fp = f(xp), fm = f(xm);
        for (let i = 0; i < f0.length; i++) J[i][j] = (fp[i] - fm[i]) / (2 * d);
      }
      return J;
    }
    const cost = (v) => v.reduce((s, e) => s + e * e, 0);
    function run(x0) {
      let x = clamp(x0.slice()), fx = f(x), c = cost(fx), lam = 1e-3;
      for (let it = 0; it < 200; it++) {
        const J = jac(x, fx), A = jtj(J);
        const g = [0, 1, 2].map((j) => J.reduce((s, row, i) => s + row[j] * fx[i], 0));
        let improved = false;
        for (let k = 0; k < 12; k++) {
          const Ad = A.map((row, i) => row.map((v, j) => (i === j ? v * (1 + lam) + 1e-12 : v)));
          const step = solve3(Ad, g.map((v) => -v));
          if (!step) { lam *= 10; continue; }
          const xn = clamp(x.map((v, i) => v + step[i]));
          const fn = f(xn), cn = cost(fn);
          if (cn < c) {
            const rel = (c - cn) / Math.max(c, 1e-12);
            x = xn; fx = fn; c = cn; lam = Math.max(lam / 3, 1e-9); improved = true;
            if (rel < 1e-10) it = 1e9;
            break;
          }
          lam *= 4;
        }
        if (!improved) break;
      }
      return { x, c, fx };
    }
    let best = run(pr);
    if (hasB) {
      // The brim reading pins 2r + h0: start the search on it too.
      const alt = run([pr[0], pr[1], prior.B - 2 * pr[0]]);
      if (alt.c < best.c) best = alt;
    }
    if (start) {
      const alt = run([start.r, start.L, start.h0]);
      if (alt.c < best.c) best = alt;
    }
    const J = jac(best.x, best.fx);
    const cov = inverse3(jtj(J));
    const p = toP(best.x);
    const sd = cov ? cov.map((row, i) => Math.sqrt(Math.max(row[i], 0))) : [NaN, NaN, NaN];
    return { p, cov, cost: best.c, n: ivs.length, sd: { r: sd[0], L: sd[1], h0: sd[2] } };
  }

  /**
   * Level a step s from H1 must give, and its spread from the parameter
   * covariance.  dir = +1 pours s in (default), −1 drains s out.  overflow:
   * a pour larger than the shell gap; empty: a drain larger than the liquid.
   */
  function predictLevel(H1, s, fit, dir) {
    const p = fit.p, d = dir < 0 ? -1 : 1;
    const target = volume(H1, p) + d * s;
    const Hp = levelFor(target, p);
    const over = d > 0 && target > capacity(p);
    const empty = d < 0 && target < 0;
    let sdModel = 0;
    if (fit.cov) {
      const x = [p.r, p.L, p.h0], g = [];
      for (let j = 0; j < 3; j++) {
        const h = 1e-3 * Math.max(1, Math.abs(x[j]));
        const xp = x.slice(), xm = x.slice();
        xp[j] += h; xm[j] -= h;
        const P = toP(xp), M = toP(xm);
        g.push((levelFor(volume(H1, P) + d * s, P) - levelFor(volume(H1, M) + d * s, M)) / (2 * h));
      }
      sdModel = Math.sqrt(Math.max(quad(g, fit.cov), 0));
    }
    return { H: Hp, sdModel, overflow: over, empty };
  }

  // ---------------------------------------------------------------- configuration
  const DEFAULTS = {
    tank: "tank",
    D: null, Dpm: 200,          // diameter estimate and its ± (taken as 2σ)
    Lest: null, Lpm: null,      // length estimate and its ± (2σ); default ±3 %
    h0pm: 80,                   // datum: 0 ± 80 mm (2σ) unless sounded
    pourUnit: null,
    sigmaRead: 0.4,             // repeatability of one reading, mm (repeat study)
    pourRel: 0.005, pourAbs: 3.0,
    zCheck: 2.0,                // re-dip when |z| ≥ 2 …
    mmCheck: 3.0,               // … or when the reading is ≥ 3 mm off
    zAlarm: 3.0, mmAlarm: 3.0,  // action bar of §6
    sharpMm: 3.0,               // prediction counts only if 2σ ≤ this
    repeatTol: null,            // default 2.5·√2·σread, at least 1 mm
    tapGap: 20,                 // s: a faster second tap is asked "same can?"
    settleSeconds: 300,         // s: idle time after a batch before the dip (§3.5)
    dipSeconds: 60,             // s: one dip and its entry, for the time estimate
    fillSeconds: null,          // { "200": 90, … }: fill one can by the pump, s
    alarmLead: 15,              // s before the can is full: close the valve
    learnN: 3,                  // intervals before a confirmed miss is an anomaly
    scalePrior: 4,              // pseudo-count for the noise scale estimate
    direction: "fill",          // "fill": pour in, level rises; "drain": pump out, level falls
    brimPm: 6,                  // drain: the neck-entrance reading is the brim B ± this (2σ), mm
    brimStart: null,            // drain: B, the adopted neck-entrance reading (set by the core)
  };

  /** Priors of the running fit (§10a.1); the brim prior only with a neck-entrance start. */
  function makePrior(cfg) {
    const pr = {
      r: cfg.D / 2, sr: cfg.Dpm / 4,
      L: cfg.Lest, sL: cfg.Lpm / 2,
      h0: 0, sh0: cfg.h0pm / 2,
    };
    if (cfg.brimStart != null && isFinite(cfg.brimStart) && cfg.brimPm > 0) {
      pr.B = cfg.brimStart; pr.sB = cfg.brimPm / 2;
    }
    return pr;
  }

  function resolveConfig(c) {
    const cfg = Object.assign({}, DEFAULTS, c || {});
    if (!(cfg.D > 0)) throw new Error("diameter estimate D is required");
    if (!(cfg.Lest > 0)) throw new Error("length estimate L is required");
    if (!(cfg.Lpm > 0)) cfg.Lpm = 0.03 * cfg.Lest;
    if (!(cfg.repeatTol > 0)) cfg.repeatTol = Math.max(1.0, 2.5 * Math.SQRT2 * cfg.sigmaRead);
    // Older sessions kept the fill time under "pourSeconds".
    if (cfg.pourSeconds && !cfg.fillSeconds) cfg.fillSeconds = cfg.pourSeconds;
    delete cfg.pourSeconds;
    cfg.fillSeconds = Object.assign({}, cfg.fillSeconds || {});
    if (cfg.direction == null || cfg.direction === "") cfg.direction = "fill";
    if (cfg.direction !== "fill" && cfg.direction !== "drain") throw new Error(`direction must be "fill" or "drain", not ${JSON.stringify(cfg.direction)}`);
    cfg.dir = cfg.direction === "drain" ? -1 : 1;
    if (!(cfg.brimPm > 0)) cfg.brimPm = DEFAULTS.brimPm;
    if (cfg.brimStart != null && !isFinite(cfg.brimStart)) cfg.brimStart = null;
    cfg.prior = makePrior(cfg);
    return cfg;
  }

  // ---------------------------------------------------------------- step cells (§3.9)
  function parseStep(text) {
    const t = String(text == null ? "" : text).trim().replace(",", ".");
    if (t === "" || t === "?" || /^x\d*$/i.test(t)) return { kind: "unknown", value: null, base: 0, text: t || "?" };
    const m = t.match(/^([0-9.]+)\s*\+\s*\?$/);
    if (m) return { kind: "partial", value: null, base: parseFloat(m[1]), text: t };
    const v = parseFloat(t);
    if (!isFinite(v) || !/^[-+]?[0-9.]+(e[-+]?\d+)?$/i.test(t)) throw new Error(`cannot read pour ${JSON.stringify(text)}`);
    if (v <= 0) throw new Error("a pour must be positive");
    return { kind: "known", value: v, base: 0, text: t };
  }

  // ---------------------------------------------------------------- session
  /*
   * A level is one row of the raw file: the pour into it and the dips at it.
   *   state: "pending"  dips are still being taken
   *          "accepted" the adopted reading is good and the interval is fit data
   *          "learning" good reading, prediction missed while the shape is learnt
   *          "anomaly"  good reading, the pour or the tank is off: interval out of the fit
   *          "unknown"  good reading after an unknown pour: back-predicted, not fit
   *          "overflow" reading is vent-column height (§5.3a): out of the fit
   *          "override" accepted by the operator against the check: out of the fit
   *          "start"    the first level
   *          "neck"     drain: a level in the neck, or the first shell level
   *                     after one; the interval spans the neck (§5.3a): out of
   *                     the running fit, kept as an anchor
   */
  const GOOD = new Set(["accepted", "learning", "anomaly", "unknown", "override", "start", "neck"]);
  const FIT = new Set(["accepted", "learning"]);
  // Levels whose residual the pair view may compare (§3.12): decided by the
  // prediction test, for it or against it.
  const PAIR = new Set(["accepted", "anomaly"]);

  function Session(config, saved) {
    this.cfg = resolveConfig(config);
    this.levels = [];
    this.fit = null;
    this.batch = null;          // open can tally: { unit, cans: [{ t, u }, …] }
    if (saved && saved.batch) {
      const b = saved.batch;
      // Older pages saved one unit and a list of tap times.
      const cans = b.cans ? b.cans.map((c) => ({ t: c.t, u: c.u }))
        : (b.taps || []).map((time) => ({ t: time, u: b.unit }));
      this.batch = { unit: b.unit, cans };
    }
    if (saved) {
      this.levels = saved.levels.map((l) => {
        const L = Object.assign({}, l, { dips: l.dips.slice(), times: (l.times || []).slice(), tags: (l.tags || []).slice() });
        // Older pages saved a closed batch with one unit and no per-can sizes.
        if (L.cans && !L.cans.units) L.cans.units = (L.cans.taps || []).map(() => L.cans.unit);
        return L;
      });
    }
    this._refit();
  }

  Session.prototype.toJSON = function () {
    const c = {};
    for (const k of Object.keys(DEFAULTS)) c[k] = this.cfg[k];
    return { version: 1, config: c, levels: this.levels, batch: this.batch };
  };
  Session.fromJSON = function (obj) { return new Session(obj.config, obj); };

  Session.prototype.current = function () { return this.levels[this.levels.length - 1] || null; };
  Session.prototype.lastGood = function (before) {
    const end = before == null ? this.levels.length : before;
    for (let i = end - 1; i >= 0; i--) if (GOOD.has(this.levels[i].state)) return i;
    return -1;
  };

  /** Value adopted at a level: mean of the closest agreeing pair, or the dip. */
  function adopt(dips, tol) {
    if (dips.length === 0) return null;
    if (dips.length === 1) return { H: dips[0], n: 1, agree: null };
    let best = null;
    for (let i = 0; i < dips.length; i++) for (let j = i + 1; j < dips.length; j++) {
      const d = Math.abs(dips[i] - dips[j]);
      if (!best || d < best.d || (d === best.d && j > best.j)) best = { i, j, d };
    }
    if (best.d <= tol) return { H: 0.5 * (dips[best.i] + dips[best.j]), n: 2, agree: true, spread: best.d };
    return { H: dips[dips.length - 1], n: 1, agree: false, spread: best.d };
  }

  /**
   * Fit data: every accepted interval with a known step and a positive
   * travel dir·(H − H_anchor).  H1 is the lower level, H2 the upper one, so
   * fitShell needs no direction (n follows its level).  An interval that
   * touches the neck is never fit data.
   */
  Session.prototype._fitIntervals = function (upto) {
    const ivs = [];
    const dir = this.cfg.dir;
    const end = upto == null ? this.levels.length : upto;
    for (let i = 1; i < end; i++) {
      const L = this.levels[i];
      if (!FIT.has(L.state) || L.step.kind !== "known" || L.neck) continue;
      const j = L.from;
      if (j == null || j < 0) continue;
      const A = this.levels[j];
      if (!GOOD.has(A.state) || A.suspect || A.neck) continue;
      if (!(dir * (L.H - A.H) > 0)) continue;
      if (dir > 0) ivs.push({ H1: A.H, H2: L.H, s: L.step.value, n1: A.n, n2: L.n, row: i });
      else ivs.push({ H1: L.H, H2: A.H, s: L.step.value, n1: L.n, n2: A.n, row: i });
    }
    return ivs;
  };

  /** Drain: the adopted neck-entrance reading is the brim B (§5.3a); null otherwise. */
  Session.prototype._syncBrim = function () {
    const cfg = this.cfg, L0 = this.levels[0];
    const B = cfg.dir < 0 && L0 && L0.entrance && L0.state === "start" && L0.H != null ? L0.H : null;
    if (B !== cfg.brimStart || (B != null) !== (cfg.prior.B != null)) {
      cfg.brimStart = B;
      cfg.prior = makePrior(cfg);
    }
  };

  Session.prototype._refit = function () {
    this._syncBrim();
    const ivs = this._fitIntervals();
    this.fit = fitShell(ivs, this.cfg.prior, this.cfg, this.fit && this.fit.p);
    // Noise scale from the earlier one-step-ahead misses: robust (median), so
    // that real anomalies do not inflate it, and shrunk toward 1 while few.
    // Only checks made with the current noise count: an old z was formed with
    // the old sigma, so reusing it after a change would count the change twice.
    const zs = [];
    const noise = noiseOf(this.cfg);
    for (const L of this.levels) {
      // The level under test never sets the scale that judges it: its own
      // first-dip miss would inflate the scale for its second reading, and
      // a confirmed miss would shrink below the action bar.
      if (L.state === "pending") continue;
      if (L.check && L.check.scored && L.check.zRaw != null && L.dips.length
        && (!L.check.noise || sameNoise(L.check.noise, noise))) zs.push(Math.abs(L.check.zRaw));
    }
    const k = zs.length, nu = this.cfg.scalePrior;
    let s2 = 1;
    if (k) {
      zs.sort((a, b) => a - b);
      const med = k % 2 ? zs[(k - 1) / 2] : 0.5 * (zs[k / 2 - 1] + zs[k / 2]);
      s2 = Math.pow(med / 0.6745, 2);
    }
    this.scale = Math.max(1, Math.sqrt((nu + k * s2) / (nu + k)));
    this.scaleN = k;
    return this.fit;
  };

  /**
   * Start the campaign: first row of the raw file (heel or first pour).
   * opts.at (drain only) is where the first level stands:
   *   "entrance"  the neck was pumped down until the level just reaches the
   *               shell crown: the reading is the brim B (recommended)
   *   "neck"      the level is in the neck: vent-column height, not shell level
   *   "shell"     the level is in the shell, below the brim (default)
   */
  Session.prototype.start = function (stepText, dip, note, time, opts) {
    if (this.levels.length) throw new Error("the session has already started");
    const at = (opts && opts.at) || "shell";
    if (["entrance", "neck", "shell"].indexOf(at) < 0) throw new Error(`the start level is "entrance", "neck" or "shell", not ${JSON.stringify(at)}`);
    if (at !== "shell" && this.cfg.dir > 0) throw new Error("a start at the neck is for a drain campaign");
    const step = parseStep(stepText);
    const L = { row: 1, step, dips: [], state: "pending", from: null, note: note || "", tags: [], H: null, n: 0, start: true };
    if (at === "entrance") { L.entrance = true; addTag(L, "at neck entrance"); }
    if (at === "neck") L.neck = true;
    this.levels.push(L);
    return this.dip(dip, time);
  };

  /**
   * A new pour (fill) or drain.  The dip follows with dip().
   * opts.overflow (fill only): the pour reached the neck or overflowed.
   * opts.neck (drain only): the level is still in the neck after this drain.
   */
  Session.prototype.pour = function (stepText, opts) {
    const o = opts || {};
    const cur = this.current();
    if (!cur) throw new Error("start the session first");
    if (cur.state === "pending") throw new Error("finish the dips at the current level first");
    if (o.overflow && this.cfg.dir < 0) throw new Error("a drain cannot overflow: tick 'level still in the neck' for a level in the neck");
    if (o.neck && this.cfg.dir > 0) throw new Error("the neck tick is for a drain campaign: a fill uses 'overflow'");
    const from = this.lastGood();
    if (o.neck && !(from >= 0 && this.levels[from].neck)) {
      throw new Error("a neck level must follow a neck level: in a drain the level only falls");
    }
    const step = parseStep(stepText);
    const L = {
      row: this.levels.length + 1, step, dips: [], state: "pending", from,
      note: o.note || "", tags: [], overflow: !!o.overflow, H: null, n: 0,
    };
    if (o.neck) L.neck = true;
    this.levels.push(L);
    return L;
  };

  // ---- batch: several cans, then one dip (§3.10).  One tap per can, so the
  // count is a record made can by can, not a number remembered at the dip.
  Session.prototype.cans = function () { return this.batch ? this.batch.cans.length : 0; };
  Session.prototype.canList = function () { return this.batch ? this.batch.cans.slice() : []; };

  /** Litres in the open batch: each can keeps its own size. */
  Session.prototype.batchVolume = function () {
    return this.batch ? this.batch.cans.reduce((a, c) => a + c.u, 0) : 0;
  };

  /** The sizes used in the open batch, largest first: [{unit, count}, …]. */
  Session.prototype.canUnits = function () {
    const by = {};
    for (const c of this.canList()) by[c.u] = (by[c.u] || 0) + 1;
    return Object.keys(by).map(Number).sort((a, b) => b - a).map((unit) => ({ unit, count: by[unit] }));
  };

  /** True when a tap now would follow the last one too fast to be a new can. */
  Session.prototype.quickTap = function (time) {
    const n = this.cans();
    return n > 0 && time != null && time - this.batch.cans[n - 1].t < this.cfg.tapGap * 1000;
  };

  /** One can is empty.  unit is that can's size; the batch default is the fallback. */
  Session.prototype.tap = function (time, unit) {
    const cur = this.current();
    const u = unit == null ? (this.batch && this.batch.unit) || this.cfg.pourUnit : unit;
    if (!(u > 0)) throw new Error("set the can size in litres to count cans");
    if (!cur) throw new Error("start the session first");
    if (cur.state === "pending") throw new Error("finish the dips at the current level first");
    if (!this.batch) this.batch = { unit: u, cans: [] };
    this.batch.cans.push({ t: time == null ? null : time, u });
    return { count: this.cans(), volume: this.batchVolume(), unit: u };
  };

  Session.prototype.untap = function () {
    if (!this.cans()) return 0;
    this.batch.cans.pop();
    if (!this.batch.cans.length) this.batch = null;
    return this.cans();
  };

  /** Close the batch: the tally becomes the pour of a new level. */
  Session.prototype.closeBatch = function (opts) {
    const n = this.cans();
    if (!n) throw new Error("no can is counted yet");
    const o = opts || {}, b = this.batch, cans = b.cans;
    // A part can is an unknown extra: the full cans are known, the shell
    // estimates the rest (§3.9 N+?).
    const kept = o.partial ? cans.slice(0, -1) : cans;
    const full = kept.reduce((a, c) => a + c.u, 0);
    const text = o.partial ? (full ? `${round(full, 3)}+?` : "?") : String(round(full, 3));
    const L = this.pour(text, o);
    const sizes = this.canUnits();
    L.cans = {
      tapped: n, unit: sizes.length === 1 ? sizes[0].unit : null, partial: !!o.partial,
      taps: cans.map((c) => c.t), units: cans.map((c) => c.u),
    };
    this.batch = null;
    return L;
  };

  /** Add a site marker to a level.  Markers stay apart from the operator note. */
  function addTag(L, text) {
    if (!L.tags) L.tags = [];
    L.tags.push(text);
  }

  /** Change the pour of the pending (or last) level after a recount. */
  Session.prototype.editPour = function (stepText) {
    const L = this.current();
    if (!L || L.start) throw new Error("no pour to edit");
    L.step = parseStep(stepText);
    addTag(L, "pour edited on site");
    return this._evaluate(L);
  };

  /** Replace the operator note of a level.  row is 1-based, as in the raw file. */
  Session.prototype.editNote = function (row, text) {
    const L = this.levels.find((l) => l.row === row);
    if (!L) throw new Error(`no row ${row}`);
    L.note = String(text == null ? "" : text).trim();
    return L;
  };

  /** Record one dip reading at the current level and judge it. */
  Session.prototype.dip = function (value, time) {
    const L = this.current();
    if (!L) throw new Error("start the session first");
    const v = typeof value === "number" ? value : parseFloat(String(value).replace(",", "."));
    if (!isFinite(v)) throw new Error(`cannot read dip ${JSON.stringify(value)}`);
    if (L.state !== "pending") {
      // An extra reading on a decided level re-opens it.
      L.state = "pending";
    }
    L.dips.push(v);
    if (!L.times) L.times = [];
    L.times.push(time == null ? null : time);
    return this._evaluate(L);
  };

  /** Accept the current level against the check (operator decision). */
  Session.prototype.override = function (why) {
    const L = this.current();
    if (!L || !L.dips.length) throw new Error("nothing to accept");
    const a = adopt(L.dips, this.cfg.repeatTol);
    L.H = a.H; L.n = a.n; L.state = "override";
    addTag(L, "accepted against the check" + (why ? ": " + why : ""));
    L.verdict = { status: "OVERRIDE", color: "warn", title: "Accepted by the operator", message: "This level is kept as an anchor. Its interval stays out of the running fit.", advice: "" };
    this._refit();
    return L.verdict;
  };

  /** Remove the last dip, or the last level when it has no dips. */
  Session.prototype.undo = function () {
    const L = this.current();
    if (!L) return null;
    if (this.cans()) { this.untap(); return L; }
    if (L.dips.length > 0) {
      L.dips.pop();
      if (L.times) L.times.pop();
      if (L.dips.length === 0) { L.state = "pending"; L.verdict = null; L.H = null; L.n = 0; }
      else this._evaluate(L);
    } else {
      this.levels.pop();
      // A batch that was closed too early opens again with its cans.
      if (L.cans) {
        this.batch = {
          unit: L.cans.unit || L.cans.units[0],
          cans: L.cans.taps.map((time, i) => ({ t: time, u: L.cans.units[i] })),
        };
      }
    }
    this._refit();
    return this.current();
  };

  Session.prototype.learning = function () {
    return this._fitIntervals().length < this.cfg.learnN;
  };

  /**
   * Prediction for a pour s from level H1 with the running shell (§10a.2).
   * nAnchor is the number of readings at H1; nNew is the number of readings
   * the new level will get.  The check uses it, and so does the page's
   * preview of the pour now in the pour panel.
   */
  Session.prototype.preview = function (H1, s, nAnchor, nNew) {
    const fit = this.fit, p = fit.p;
    const pr = predictLevel(H1, s, fit, this.cfg.dir);
    const m1 = Math.max(slope(H1, p), 1e-3), m2 = Math.max(slope(pr.H, p), 1e-3);
    const sr = this.cfg.sigmaRead;
    const noise2 = sr * sr * (m1 / m2) * (m1 / m2) / Math.max(nAnchor || 1, 1)
      + sr * sr / Math.max(nNew || 1, 1)
      + Math.pow(pourSigma(s, this.cfg) / m2, 2);
    const sdNoise = Math.sqrt(noise2);
    const sd = this.scale * Math.sqrt(noise2 + pr.sdModel * pr.sdModel);
    return { H: pr.H, sd, sdNoise, sdModel: pr.sdModel, scale: this.scale, overflow: pr.overflow, empty: pr.empty, m: m2, anchor: H1 };
  };

  /** Prediction for level L (index i) from its anchor, or null. */
  Session.prototype._predict = function (L, nNew) {
    if (L.start || L.step.kind !== "known" || L.from == null || L.from < 0) return null;
    const A = this.levels[L.from];
    return this.preview(A.H, L.step.value, A.n, nNew);
  };

  /** Interval residual in the §2 convention with the running fit (pred > 0 in both directions). */
  Session.prototype._resid = function (L, H) {
    const A = this.levels[L.from], p = this.fit.p;
    const pred = this.cfg.dir * (volume(H, p) - volume(A.H, p));
    const resid = L.step.value - pred;
    const m = Math.max(slope(H, p), 1e-3);
    return { resid, mm: resid / m, pred };
  };

  Session.prototype._evaluate = function (L) {
    const cfg = this.cfg;
    if (!L.dips.length) { L.state = "pending"; L.verdict = null; L.H = null; L.n = 0; this._refit(); return null; }
    // The fit must not see the level under test: refit without it.
    const keep = L.state;
    L.state = "pending";
    this._refit();
    L.state = keep;

    const a = adopt(L.dips, cfg.repeatTol);
    L.H = a.H; L.n = a.n;
    const nd = L.dips.length;
    const verdict = { dips: nd, H: a.H, spread: a.spread == null ? null : a.spread };
    const setState = (s) => { L.state = s; };

    // Repeat test first: readings that disagree decide nothing yet.
    if (nd >= 2 && !a.agree) {
      const creeping = nd >= 3 && isMonotonic(L.dips) && Math.abs(L.dips[nd - 1] - L.dips[0]) > cfg.repeatTol;
      Object.assign(verdict, {
        status: nd >= 3 ? "UNSETTLED" : "REDIP", color: "warn",
        title: nd >= 3 ? "Readings do not agree" : "Second reading differs",
        message: `The readings do not agree within ${fmt(cfg.repeatTol, 1)} mm.`
          + (creeping ? " The level moves in one direction: it is not settled (waves, foam, weep hole lag)." : ""),
        advice: creeping ? "Wait 5 minutes and dip again." : "Dip again. Do not look at the earlier readings.",
      });
      setState("pending"); L.verdict = verdict; return verdict;
    }

    // Drain through the neck: a level in the neck, and the first shell level
    // after it, have no prediction.  The interval spans the neck: it feeds
    // the brim constraint of the final fit (§5.3a), never the running fit.
    const anchor = L.from != null && L.from >= 0 ? this.levels[L.from] : null;
    if (cfg.dir < 0 && (L.neck || (anchor && anchor.neck))) {
      const why = L.neck ? "a level in the neck" : "the first shell level below the neck";
      if (nd < 2) {
        Object.assign(verdict, {
          status: "REDIP", color: "warn", title: "Second reading needed",
          message: `No prediction can test ${why}. Only a repeat reading can.`,
          advice: "Dip again. Do not look at the first reading.",
        });
        setState("pending"); L.verdict = verdict; return verdict;
      }
      let gapText = "";
      if (!L.neck && this.fit) {
        const p = this.fit.p, gap = capacity(p) - volume(a.H, p);
        verdict.neckGap = gap;
        gapText = ` Running shell: the shell gap Vcap − F(H) ≈ ${fmt(gap, 0)} L`
          + (L.step.kind === "known" ? `; the drain was ${fmt(L.step.value, 0)} L, so the constraint reads ${fmt(gap, 0)} ≤ ${fmt(L.step.value, 0)} L.` : ".");
      }
      Object.assign(verdict, {
        status: "NECK", color: "info",
        title: L.neck ? "Neck reading recorded" : "Neck interval recorded",
        message: `Two readings agree within ${fmt(a.spread, 1)} mm. Adopted ${fmt(a.H, 1)} mm. `
          + (L.neck ? "The reading is vent-column height, not shell level. " : "The level is back in the shell. ")
          + "The interval spans the neck, so it feeds the brim constraint Vcap − F(H) ≤ P of the final fit (§5.3a) and stays out of the running fit."
          + gapText,
        advice: L.neck ? "Drain the next batch. Tick 'level still in the neck' while the level is in the neck."
          : "Drain the next batch. The next level is checked against this one.",
      });
      setState("neck"); L.verdict = verdict; this._refit(); this._advise(verdict, L); return verdict;
    }

    // First level, unknown pour, overflow: no prediction can test the reading.
    if (L.start || L.step.kind !== "known" || L.overflow) {
      const why = L.start ? "the first level" : L.overflow ? "an overflow reading" : "an unknown pour";
      if (L.overflow) {
        Object.assign(verdict, {
          status: "OVERFLOW", color: "info", title: "Overflow reading recorded",
          message: "The reading is vent-column height, not shell level. It feeds the brim constraint of the fit (§5.3a). An overflow row's height is data; its pour is a claim.",
          advice: "Record the pour that overflowed. The campaign is complete.",
        });
        setState("overflow"); L.verdict = verdict; this._refit(); return verdict;
      }
      if (nd < 2) {
        Object.assign(verdict, {
          status: "REDIP", color: "warn", title: "Second reading needed",
          message: `No prediction can test ${why}. Only a repeat reading can.`,
          advice: "Dip again. Do not look at the first reading.",
        });
        setState("pending"); L.verdict = verdict; return verdict;
      }
      Object.assign(verdict, {
        status: "ACCEPT", color: "ok", title: "Reading confirmed",
        message: `Two readings agree within ${fmt(a.spread, 1)} mm. Adopted ${fmt(a.H, 1)} mm.`,
        advice: nextStep(cfg),
      });
      if (L.start && L.entrance) {
        verdict.message += ` This is the brim B (the shell crown at the neck entrance): the running shell takes 2r + h0 = ${fmt(a.H, 1)} ± ${fmt(cfg.brimPm, 0)} mm (2σ).`;
      }
      if (!L.start && L.step.kind !== "known" && this.fit) {
        const A = this.levels[L.from], p = this.fit.p, m = Math.max(slope(a.H, p), 1e-3);
        const x = cfg.dir * (volume(a.H, p) - volume(A.H, p)) - L.step.base;
        const sr = cfg.sigmaRead;
        const sx = this.scale * Math.sqrt(m * m * sr * sr * (1 / Math.max(A.n, 1) + 1 / a.n)
          + Math.pow(cfg.pourRel * L.step.base + cfg.pourAbs, 2));
        verdict.unknown = { x, sigma: sx, base: L.step.base };
        verdict.message += ` Back-predicted ${cfg.dir < 0 ? "drain" : "pour"}: ${L.step.base ? fmt(L.step.base, 0) + " + " : ""}${fmt(x, 1)} ± ${fmt(2 * sx, 1)} L (running shell, refined by the final fit).`;
      }
      setState(L.start ? "start" : "unknown");
      L.verdict = verdict; this._refit(); this._advise(verdict, L); return verdict;
    }

    // Prediction test.
    const pr = this._predict(L, a.n);
    const e = a.H - pr.H;                       // reading minus predicted level, mm
    const res = this._resid(L, a.H);
    const zRaw = res.mm / (pr.sd / pr.scale);   // before the noise scale
    const z = res.mm / pr.sd;
    const sharp = 2 * pr.sd <= cfg.sharpMm;
    const learning = this.learning();
    Object.assign(verdict, {
      predicted: pr.H, sd: pr.sd, sdModel: pr.sdModel, sdNoise: pr.sdNoise, scale: pr.scale,
      e, resid: res.resid, mm: res.mm, z, sharp, learning,
    });
    L.check = { predicted: pr.H, sd: pr.sd, e, z, zRaw, resid: res.resid, mm: res.mm, sharp, learning, scored: sharp && !learning, noise: noiseOf(cfg) };
    const miss = Math.abs(z) >= cfg.zCheck || Math.abs(res.mm) >= cfg.mmCheck;
    const off = `Reading ${fmt(a.H, 1)} mm, predicted ${fmt(pr.H, 1)} ± ${fmt(2 * pr.sd, 1)} mm (2σ): `
      + `${fmt(Math.abs(e), 1)} mm ${e >= 0 ? "above" : "below"}. resid ${sgn(res.resid, 1)} L = ${sgn(res.mm, 1)} mm-equiv, z ${sgn(z, 1)}.`;

    if (!miss && (sharp || nd >= 2)) {
      Object.assign(verdict, {
        status: "ACCEPT", color: "ok", title: nd >= 2 ? "Reading confirmed" : "Reading good",
        message: off, advice: nextStep(cfg),
      });
      setState("accepted"); L.verdict = verdict; this._refit(); this._advise(verdict, L); return verdict;
    }
    if (nd < 2) {
      Object.assign(verdict, miss ? {
        status: "REDIP", color: "warn", title: "Check this reading",
        message: "The reading misses the prediction. Hidden until the second reading.",
        advice: "Dip again. Do not look at the first reading.",
      } : {
        status: "REDIP", color: "warn", title: "Second reading needed",
        message: `The prediction is still too wide to catch a ${fmt(cfg.sharpMm, 0)} mm slip (2σ = ${fmt(2 * pr.sd, 1)} mm). Only a repeat reading can test this level.`,
        advice: "Dip again. Do not look at the first reading.",
      });
      verdict.hidden = true;
      setState("pending"); L.verdict = verdict; return verdict;
    }

    // Two readings agree, and the level still misses: the reading is good.
    if (learning) {
      Object.assign(verdict, {
        status: "LEARNING", color: "info", title: "Reading confirmed, shape still unknown",
        message: off + " Two readings agree, so the dip is good. The running shell has fewer than "
          + `${cfg.learnN} intervals, so the miss is most likely the shape (bottom, datum), not the ${cfg.dir < 0 ? "drain" : "pour"}.`,
        advice: nextStep(cfg) + " The level is kept and used by the fit.",
      });
      setState("learning"); L.verdict = verdict; this._refit(); this._advise(verdict, L); return verdict;
    }
    const big = Math.abs(z) >= cfg.zAlarm && Math.abs(res.mm) >= cfg.mmAlarm;
    if (!big) {
      Object.assign(verdict, {
        status: "WATCH", color: "info", title: "Reading confirmed: watch item",
        message: off + " Two readings agree, so the dip is good. The miss is below the action bar "
          + `(|z| ≥ ${fmt(cfg.zAlarm, 0)} and ≥ ${fmt(cfg.mmAlarm, 0)} mm): a watch item (§6.5), kept in the fit.`,
        advice: nextStep(cfg),
      });
      L.watch = true;
      setState("accepted"); L.verdict = verdict; this._refit(); this._advise(verdict, L); return verdict;
    }
    const drain = cfg.dir < 0;
    const cause = drain
      ? (res.resid < 0
        ? "OBJECT? or LEAK? or the drain was under-recorded: the fall came too large — a solid was exposed in this band, liquid left another way, or more left than the count says (a spill at the can counts here)"
        : "RETURN? or the drain was over-recorded: the fall came too small — liquid came back (hose drained back into the tank, wall film) or less left than the count says")
      : (res.resid < 0
        ? "OBJECT? or the pour was under-recorded: the rise came too cheap, more liquid went in than recorded or a solid displaced it"
        : "LOSS? or the pour was over-recorded: the rise came too small, less liquid went in than recorded, or liquid went somewhere (leak, film, trapped air)");
    Object.assign(verdict, {
      status: "ALARM", color: "bad",
      title: drain ? "Reading confirmed: the drain or the tank is off" : "Reading confirmed: the pour or the tank is off",
      message: off + ` Two readings agree, so the dip is good. ${cause}.`,
      advice: drain
        ? "Count the full cans (or read the meter) of this drain again. If the count was wrong, edit the drain. "
          + "If it was right, keep it: this interval stays out of the running fit and goes to the anomaly register (§6.2). "
          + "Check the hose and the cans for a spill or a drain-back. Drain the next batch."
        : "Count the cans (or read the meter) of this pour again. If the count was wrong, edit the pour. "
          + "If it was right, keep it: this interval stays out of the running fit and goes to the anomaly register (§6.2). "
          + "A repeat pour of the same size into this band tells an object from a pour error. Pour the next can.",
      cause: drain ? (res.resid < 0 ? "OBJECT?" : "RETURN?") : (res.resid < 0 ? "OBJECT?" : "LOSS?"),
    });
    // Pours live on the unit grid (§3.10, §6.2): a miss of a whole number of
    // cans that a changed count explains is a count error before anything else.
    const counts = L.cans && L.cans.units
      ? L.cans.units.reduce((a, u) => { a[u] = (a[u] || 0) + 1; return a; }, {}) : null;
    const hint = canHint(res.resid, z, L.step.value, cfg, L.cans && L.cans.units, counts);
    if (hint) {
      const k = Math.abs(hint.extra), total = L.step.value + hint.extra * hint.unit;
      // A plain pour has no can record; the setup unit still gives the count.
      const single = L.cans ? L.cans.unit === hint.unit : hint.unit === cfg.pourUnit;
      const was = single ? L.step.value / hint.unit : null;
      verdict.cans = hint;
      verdict.message += ` The miss is ${fmt(Math.abs(hint.exact), 2)} can${k > 1 || Math.abs(hint.exact) > 1 ? "s" : ""} of ${fmt(hint.unit, 0)} L: `
        + `${k} can${k > 1 ? "s" : ""} ${hint.extra > 0 ? "more" : "fewer"} than the count `
        + (single ? `(${fmt(was + hint.extra, 0)}, not ${fmt(was, 0)})` : `(${fmt(total, 0)} L, not ${fmt(L.step.value, 0)} L)`)
        + ` explains it: z ${sgn(z, 1)} becomes ${sgn(hint.zAfter, 1)}.`;
      const what = drain ? "drain" : "pour";
      verdict.advice = (drain ? "Count the full cans now, before the next drain. " : "Count the empty cans now, before the next pour. ")
        + (single ? `If you count ${fmt(was + hint.extra, 0)} cans, edit the ${what} to ${fmt(total, 0)} L. `
          : `If the recount gives ${fmt(total, 0)} L, edit the ${what} to match it. `)
        + verdict.advice;
    }
    // Pair pattern with the previous interval: the previous level may be the misread one.
    const prev = this.levels[L.from];
    if (prev && prev.check && prev.check.resid != null && prev.check.resid * res.resid < 0) {
      const r1 = prev.check.resid, r2 = res.resid;
      const net = Math.abs(r1 + r2) / (Math.abs(r1) + Math.abs(r2));
      if (net <= 0.15) {
        // §6.1: δ = (r2 − r1)/(2m) for a fill.  A drain reverses the travel,
        // so the same misread flips both residuals: δ = dir·(r2 − r1)/(2m).
        const delta = cfg.dir * (r2 - r1) / (2 * Math.max(slope(prev.H, this.fit.p), 1e-3));
        verdict.pair = { level: prev.H, delta, net };
        verdict.message += ` With the previous interval this is the pattern of a misread at ${fmt(prev.H, 0)} mm `
          + `(δ ≈ ${sgn(delta, 1)} mm, net ${fmt(100 * net, 0)} %).`;
        verdict.advice = `That level is gone and cannot be dipped again. Record it: the final fit corrects it with the pair rule (§6.1). ` + verdict.advice;
        prev.suspect = true;
      }
    }
    setState("anomaly"); L.verdict = verdict; this._refit(); this._advise(verdict, L); return verdict;
  };

  /** The advice line after a good level. */
  function nextStep(cfg) { return cfg.dir < 0 ? "Drain the next batch." : "Pour the next can."; }

  /**
   * Can-count hypothesis for a confirmed miss.  resid < 0 means more liquid
   * went in than recorded (§2), so extra = −resid / unit cans.  A hint needs a
   * whole number of cans (within a quarter can) that brings z below the check.
   */
  function canHint(resid, z, value, cfg, units, counts) {
    if (!z) return null;
    const list = (units && units.length ? units : [cfg.pourUnit]).filter((u) => u > 0);
    let best = null;
    for (const unit of list) {
      const exact = -resid / unit, extra = Math.round(exact);
      if (!extra || Math.abs(exact - extra) > 0.25 || value + extra * unit <= 0) continue;
      // Do not remove more cans of this size than the batch holds.
      if (extra < 0 && counts && counts[unit] != null && -extra > counts[unit]) continue;
      const zAfter = (resid + extra * unit) / (resid / z);
      if (Math.abs(zAfter) >= cfg.zCheck) continue;
      const score = Math.abs(exact - extra);
      if (!best || score < best.score) best = { extra, exact, unit, zAfter, score };
    }
    if (!best) return null;
    delete best.score;
    return best;
  }

  // ---- campaign settings.  The tank record, the priors and the noise are
  // assumptions, not data: a change refits the running shell, and a changed
  // sigma moves the z of every new check (§9.1).  The levels themselves never
  // change, and an old z is not reused in the noise scale.

  /**
   * Change the campaign settings after the first level.  Only the keys given
   * change; the running shell is refitted on the levels already accepted.
   * `pourRel` is a fraction (0.005 = 0.5 %); `Lpm` null means ±3 % of L.
   */
  Session.prototype.setCampaign = function (o) {
    const cfg = this.cfg;
    const has = (k) => Object.prototype.hasOwnProperty.call(o, k);
    // Validate into a copy first: a bad field must change nothing.
    const next = {
      tank: cfg.tank, D: cfg.D, Dpm: cfg.Dpm, Lest: cfg.Lest, Lpm: cfg.Lpm,
      pourUnit: cfg.pourUnit, sigmaRead: cfg.sigmaRead, pourRel: cfg.pourRel,
      pourAbs: cfg.pourAbs, h0pm: cfg.h0pm, brimPm: cfg.brimPm,
    };
    if (has("direction") && o.direction != null && o.direction !== cfg.direction) {
      throw new Error("the direction (fill or drain) is fixed at the start of the campaign");
    }
    if (has("tank")) {
      const t = String(o.tank == null ? "" : o.tank).trim();
      if (t) next.tank = t;
    }
    if (has("D")) {
      if (!(o.D > 0)) throw new Error("the diameter estimate D must be more than 0 mm");
      next.D = o.D;
    }
    if (has("Dpm")) {
      if (o.Dpm == null || o.Dpm === "") next.Dpm = 200;
      else if (!(o.Dpm > 0)) throw new Error("the diameter limit ± must be more than 0 mm");
      else next.Dpm = o.Dpm;
    }
    if (has("Lest")) {
      if (!(o.Lest > 0)) throw new Error("the length estimate L must be more than 0 mm");
      next.Lest = o.Lest;
    }
    if (has("Lpm")) {
      if (o.Lpm == null || o.Lpm === "") next.Lpm = 0.03 * next.Lest;
      else if (!(o.Lpm > 0)) throw new Error("the length limit ± must be more than 0 mm");
      else next.Lpm = o.Lpm;
    }
    if (has("pourUnit")) {
      if (o.pourUnit == null || o.pourUnit === "") next.pourUnit = null;
      else if (!(o.pourUnit > 0)) throw new Error("the pour unit must be more than 0 L");
      else next.pourUnit = o.pourUnit;
    }
    if (has("sigmaRead")) {
      if (!(o.sigmaRead > 0)) throw new Error("the reading sigma must be more than 0 mm");
      next.sigmaRead = o.sigmaRead;
    }
    if (has("pourRel")) {
      if (!(o.pourRel >= 0)) throw new Error("the pour noise must be 0 % or more");
      next.pourRel = o.pourRel;
    }
    if (has("pourAbs")) {
      if (!(o.pourAbs >= 0)) throw new Error("the fixed pour noise must be 0 L or more");
      next.pourAbs = o.pourAbs;
    }
    if (has("h0pm")) {
      if (!(o.h0pm > 0)) throw new Error("the datum limit ± must be more than 0 mm");
      next.h0pm = o.h0pm;
    }
    if (has("brimPm")) {
      if (o.brimPm == null || o.brimPm === "") next.brimPm = DEFAULTS.brimPm;
      else if (!(o.brimPm > 0)) throw new Error("the brim limit ± must be more than 0 mm");
      else next.brimPm = o.brimPm;
    }
    // The repeat limit follows the reading noise unless it was set by hand.
    // "By hand" means it differs from the default made from the old sigma.
    const oldTol = Math.max(1.0, 2.5 * Math.SQRT2 * cfg.sigmaRead);
    const tolIsDefault = !(cfg.repeatTol > 0) || Math.abs(cfg.repeatTol - oldTol) < 1e-9;
    Object.assign(cfg, next);
    if (has("sigmaRead") && tolIsDefault) cfg.repeatTol = Math.max(1.0, 2.5 * Math.SQRT2 * cfg.sigmaRead);
    cfg.prior = makePrior(cfg);
    this._refit();
    return cfg;
  };

  // ---- timers and the fill estimate.  Durations are operator settings, not
  // data: they never enter the fit or the raw file.

  /** Set the timer durations.  fillSeconds merges per can size; null clears one size. */
  Session.prototype.setTimers = function (o) {
    const cfg = this.cfg;
    if (o.settleSeconds != null) {
      if (!(o.settleSeconds >= 0)) throw new Error("the settle time must be 0 s or more");
      cfg.settleSeconds = o.settleSeconds;
    }
    if (o.dipSeconds != null) {
      if (!(o.dipSeconds >= 0)) throw new Error("the dip time must be 0 s or more");
      cfg.dipSeconds = o.dipSeconds;
    }
    if (o.alarmLead != null) {
      if (!(o.alarmLead >= 0 && o.alarmLead <= 120)) throw new Error("the alarm lead must be 0 to 120 s");
      cfg.alarmLead = o.alarmLead;
    }
    for (const k of Object.keys(o.fillSeconds || {})) {
      const v = o.fillSeconds[k];
      if (v == null || v === "") { delete cfg.fillSeconds[sizeKey(k)]; continue; }
      if (!(v > 0)) throw new Error("a fill time must be more than 0 s");
      cfg.fillSeconds[sizeKey(k)] = v;
    }
    return cfg;
  };

  /**
   * Cycle time per can, measured from the taps: the median gap between two
   * taps of the same size in one batch.  The gap holds the fill by the pump,
   * the carry and the drain, which is what the estimate needs.  It cannot
   * give the fill time alone, so it never feeds the timer.
   */
  Session.prototype.measuredPourSeconds = function (size) {
    const gaps = [];
    const scan = (taps, units) => {
      for (let i = 1; i < taps.length; i++) {
        if (taps[i] == null || taps[i - 1] == null || units[i] !== size || units[i - 1] !== size) continue;
        const g = (taps[i] - taps[i - 1]) / 1000;
        if (g >= 5 && g <= 1800) gaps.push(g);
      }
    };
    for (const L of this.levels) if (L.cans && L.cans.taps) scan(L.cans.taps, L.cans.units || L.cans.taps.map(() => L.cans.unit));
    if (this.batch) scan(this.batch.cans.map((c) => c.t), this.batch.cans.map((c) => c.u));
    if (!gaps.length) return null;
    gaps.sort((a, b) => a - b);
    const k = gaps.length;
    return { seconds: k % 2 ? gaps[(k - 1) / 2] : 0.5 * (gaps[k / 2 - 1] + gaps[k / 2]), n: k };
  };

  /** Fill time of one can by the pump: the setting only.  The timer needs it. */
  Session.prototype.fillSecondsFor = function (size) {
    const set = this.cfg.fillSeconds[sizeKey(size)];
    return set > 0 ? { seconds: set, source: "set" } : null;
  };

  /** Time one can costs the campaign: the measured cycle, else the fill time. */
  Session.prototype.cycleSecondsFor = function (size) {
    const m = this.measuredPourSeconds(size);
    if (m) return { seconds: m.seconds, source: "measured", n: m.n };
    const f = this.fillSecondsFor(size);
    return f ? { seconds: f.seconds, source: "fill" } : null;
  };

  /**
   * Time to fill to half and to the brim with one can size (§3.4 advisor).
   * Each step is one level: the advised number of cans, the settle time and
   * one dip.  The steps follow the running shell, so near the brim they get
   * smaller as the advisor halves the pour.  A milestone is reached when the
   * first level at or above it is dipped.  The last step to the brim takes
   * only the cans the gap needs (the planned overflow pour, §3.7).
   *
   * A drain counts the volume down: half, then the end (`end`): the first
   * level in the bottom zone (within 60 mm of the bottom, or less than 5 %
   * of the capacity left), where the pump may lose suction.
   *
   * o = { size, cycleSeconds, settleSeconds, dipSeconds, now, pourElapsed }
   *   cycleSeconds  time one can costs: fill, carry and drain
   *   now           ms, for the settle time already spent at a pending level
   *   pourElapsed   s spent on the can that is filling now (fill timer)
   */
  Session.prototype.fillPlan = function (o) {
    const cfg = this.cfg, p = this.fit.p, size = o && o.size, dir = cfg.dir;
    const pourS = o && o.cycleSeconds, settle = o.settleSeconds != null ? o.settleSeconds : cfg.settleSeconds;
    const dipS = o.dipSeconds != null ? o.dipSeconds : cfg.dipSeconds;
    if (!(size > 0) || !(pourS > 0)) return null;
    const gi = this.lastGood();
    if (gi < 0) return null;
    const cap = capacity(p), half = 0.5 * cap;
    let V = volume(this.levels[gi].H, p), t = 0, open = 0;
    const cur = this.current();
    if (cur && cur.state === "pending" && !cur.start) {
      // The pour is in; the settle and the dip are still to come.
      if (cur.step.kind === "known") V = volume(this.levels[cur.from].H, p) + dir * cur.step.value;
      else if (cur.step.kind === "partial") V = volume(this.levels[cur.from].H, p) + dir * cur.step.base;
      const spent = cur.pourTime && o.now ? (o.now - cur.pourTime) / 1000 : 0;
      t = Math.max(0, settle - spent) + dipS;
    } else if (this.batch || o.open) {
      // A transfer keeps the open tally on the drain session; the fill
      // session sees the same litres through o.open.
      V += dir * (this.batch ? this.batchVolume() : o.open.volume);
      open = this.batch ? this.cans() : o.open.cans;
    }
    t -= Math.min(Math.max(o.pourElapsed || 0, 0), pourS);
    const start = { volume: V, seconds: t };
    const mark = (levels, cans) => ({ seconds: Math.max(0, t), levels, cans, volume: V });
    let levels = 0, cans = 0;
    const base = { size, cycleSeconds: pourS, settleSeconds: settle, dipSeconds: dipS, start, capacity: cap };
    if (dir < 0) {
      const endV = Math.max(0.05 * cap, volume(p.h0 + 60, p));
      let atHalf = V <= half ? Object.assign(mark(0, 0), { done: true }) : null;
      let atEnd = V <= endV + 1e-6 ? Object.assign(mark(0, 0), { done: true }) : null;
      for (let guard = 0; !atEnd && guard < 100000 && V > 0; guard++) {
        const H = levelFor(Math.max(V, 0), p);
        const a = this.advice(H);
        let n = Math.max(1, Math.round(a.target / size)) - open;
        if (n < 0) n = 0;
        open = 0;
        // The pump cannot draw more than is left: the last can is a part can.
        if (n * size > V) n = Math.max(1, Math.ceil(V / size - 1e-9));
        V -= n * size; cans += n; levels++;
        t += n * pourS + settle + dipS;
        if (!atHalf && V <= half) atHalf = mark(levels, cans);
        if (V <= endV + 1e-6) atEnd = mark(levels, cans);
      }
      return Object.assign(base, { half: atHalf, end: atEnd, brim: null, endVolume: endV });
    }
    let atHalf = V >= half ? Object.assign(mark(0, 0), { done: true }) : null;
    let atBrim = V >= cap - 1e-6 ? Object.assign(mark(0, 0), { done: true }) : null;
    for (let guard = 0; !atBrim && guard < 100000; guard++) {
      const H = levelFor(Math.min(V, cap), p);
      const a = this.advice(H);
      let n = Math.max(1, Math.round(a.target / size)) - open;
      if (n < 0) n = 0;
      open = 0;
      const gap = cap - V;
      if (n * size > gap) n = Math.max(1, Math.ceil(gap / size - 1e-9));
      if (n === 0 && levels === 0 && gap <= 0) break;
      V += n * size; cans += n; levels++;
      t += n * pourS + settle + dipS;
      if (!atHalf && V >= half) atHalf = mark(levels, cans);
      if (V >= cap - 1e-6) atBrim = mark(levels, cans);
    }
    return Object.assign(base, { half: atHalf, brim: atBrim });
  };

  /** Pour advisor and brim watch (§3.4, §10). */
  Session.prototype._advise = function (verdict, L) {
    const a = this.advice(L.H);
    verdict.next = a;
    return verdict;
  };

  Session.prototype.advice = function (H) {
    const p = this.fit.p, cfg = this.cfg;
    const m = slope(H, p);
    const gap = capacity(p) - volume(H, p);
    const toBrim = brim(p) - H;
    if (cfg.dir < 0) return this._adviceDrain(H, m, gap, toBrim);
    let target = 30 * m;
    const halve = gap < 0.05 * capacity(p) || toBrim < 60;
    if (halve) target /= 2;
    let units = null;
    if (cfg.pourUnit) { units = Math.max(1, Math.round(target / cfg.pourUnit)); target = units * cfg.pourUnit; }
    const sdB = Math.sqrt(Math.max(this.fit.cov ? 4 * this.fit.cov[0][0] + 4 * this.fit.cov[0][2] + this.fit.cov[2][2] : 0, 0));
    return {
      slope: m, target, units, floor: 15 * m, ceiling: 100 * m, halve,
      gap, toBrim, brim: brim(p), brimSd: sdB, capacity: capacity(p),
      text: (halve ? `Near the brim (≈ ${fmt(toBrim, 0)} mm, gap ≈ ${fmt(gap, 0)} L): halve the pour. ` : "")
        + `Next pour ≈ ${fmt(target, 0)} L` + (units ? ` = ${units} × ${cfg.pourUnit} L` : "")
        + ` (≈ ${fmt(target / Math.max(m, 1e-3), 0)} mm rise).`,
    };
  };

  /**
   * Drain advisor: the same 30 mm target, no halving (the brim is behind
   * us), and a bottom watch: the pump may lose suction near the bottom.
   */
  Session.prototype._adviceDrain = function (H, m, gap, toBrim) {
    const p = this.fit.p, cfg = this.cfg, cap = capacity(p);
    const left = volume(H, p), toBottom = H - p.h0;
    let target = 30 * m;
    let units = null;
    if (cfg.pourUnit) { units = Math.max(1, Math.round(target / cfg.pourUnit)); target = units * cfg.pourUnit; }
    const after = levelFor(left - target, p);
    const bottom = after - p.h0 < 60 || left < 0.05 * cap;
    const sdB = Math.sqrt(Math.max(this.fit.cov ? 4 * this.fit.cov[0][0] + 4 * this.fit.cov[0][2] + this.fit.cov[2][2] : 0, 0));
    return {
      slope: m, target, units, floor: 15 * m, ceiling: 100 * m, halve: false, bottom,
      gap, toBrim, brim: brim(p), brimSd: sdB, capacity: cap, left, toBottom,
      text: (bottom ? `Near the bottom (≈ ${fmt(toBottom, 0)} mm, ≈ ${fmt(left, 0)} L left): the pump may lose suction; a part can is fine (N+?). ` : "")
        + `Next drain ≈ ${fmt(target, 0)} L` + (units ? ` = ${units} × ${cfg.pourUnit} L` : "")
        + ` (≈ ${fmt(target / Math.max(m, 1e-3), 0)} mm fall).`,
    };
  };

  /** Drift and closure with the running fit (§2, §9.3). */
  Session.prototype.status = function () {
    const ivs = this._fitIntervals(), p = this.fit.p;
    let drift = 0, s2 = 0;
    for (const iv of ivs) {
      drift += iv.s - (volume(iv.H2, p) - volume(iv.H1, p));
      const m = slope(iv.H2, p);
      s2 += m * m * this.cfg.sigmaRead * this.cfg.sigmaRead * 2 + Math.pow(pourSigma(iv.s, this.cfg), 2);
    }
    const limit = 3 * Math.sqrt(s2);
    const counts = {};
    for (const L of this.levels) counts[L.state] = (counts[L.state] || 0) + 1;
    let redips = 0;
    for (const L of this.levels) redips += Math.max(0, L.dips.length - 1);
    return {
      fit: this.fit, scale: this.scale, scaleN: this.scaleN, learning: this.learning(), intervals: ivs.length,
      drift, driftLimit: limit, driftAlarm: ivs.length > 2 && Math.abs(drift) > limit,
      counts, redips, levels: this.levels.length,
      brim: brim(p), capacity: capacity(p), direction: this.cfg.direction,
    };
  };

  /**
   * Chart series against the running shell as it is now (§6.6): one entry per
   * decided interval with a known pour.  resid = s - pred (§2), z = resid / σ,
   * drift D_k = Σ resid, with its 3σ√n limit (§10 DRIFT).  Pending levels stay
   * blind; overflow readings, neck intervals and unknown pours carry no
   * residual.  `rise` is the travel dir·(H − H1): positive in both directions.
   */
  Session.prototype.series = function () {
    const p = this.fit.p, cfg = this.cfg, top = brim(p), out = [], dir = cfg.dir;
    let drift = 0, s2 = 0;
    for (const L of this.levels) {
      if (L.start || L.H == null || L.state === "pending" || L.overflow) continue;
      if (L.step.kind !== "known" || L.from == null || L.from < 0) continue;
      const A = this.levels[L.from];
      if (L.neck || A.neck || L.state === "neck") continue;
      const H1 = A.H, rise = dir * (L.H - H1);
      if (!(rise > 0) || L.H > top) continue;
      const s = L.step.value, pred = dir * (volume(L.H, p) - volume(H1, p)), resid = s - pred;
      const m = Math.max(slope(L.H, p), 1e-3);
      const v = 2 * m * m * cfg.sigmaRead * cfg.sigmaRead + Math.pow(pourSigma(s, cfg), 2);
      const sigma = this.scale * Math.sqrt(v);
      drift += resid; s2 += v;
      out.push({
        row: L.row, H: L.H, H1, mid: 0.5 * (H1 + L.H), rise, travel: rise, s, pred, resid, m, mm: resid / m,
        sigma, z: resid / sigma, drift, limit: 3 * Math.sqrt(s2), state: L.state, watch: !!L.watch,
      });
    }
    return out;
  };

  /**
   * Raw file for calib init / calib fit (§3.9).  One row per level, adopted
   * reading.  A drain keeps the same three columns and positive volumes; row
   * 1 carries "drain campaign" first, then "at neck entrance" or "neck
   * level"; a neck level carries "neck level" and the first shell level
   * after the neck "neck interval".
   */
  Session.prototype.toRawCsv = function () {
    const out = ["step_volume,measured_height,note"];
    const drain = this.cfg.dir < 0;
    for (const L of this.levels) {
      if (L.H == null) continue;
      const bits = [];
      if (drain) {
        if (L.start) bits.push("drain campaign");
        if (L.entrance) bits.push("at neck entrance");
        if (L.neck) bits.push("neck level");
        else if (L.from != null && L.from >= 0 && this.levels[L.from].neck) bits.push("neck interval");
      }
      if (L.dips.length > 1) bits.push("dips " + L.dips.map((d) => fmt(d, 1)).join("/"));
      bits.push("site " + L.state);
      if (L.verdict && L.verdict.cause && L.state === "anomaly") bits.push(L.verdict.cause);
      if (L.watch) bits.push("watch");
      if (L.suspect) bits.push("suspect dip (pair pattern)");
      if (L.overflow) bits.push("overflow");
      if (L.cans) {
        const ts = L.cans.taps.filter((x) => x != null), by = {};
        for (const u of L.cans.units) by[u] = (by[u] || 0) + 1;
        const spec = Object.keys(by).map(Number).sort((a, b) => b - a)
          .map((u) => `${by[u]}x${fmt(u, 0)}`).join("+");
        bits.push(`cans ${spec} L` + (L.cans.partial ? (drain ? " pump lost suction: last can part" : " last can part") : "")
          + (ts.length ? ` ${clock(ts[0])}-${clock(ts[ts.length - 1])}` : ""));
      }
      if (L.tags) for (const t of L.tags) if (!(drain && L.entrance && t === "at neck entrance")) bits.push(t);
      if (L.note) bits.push(L.note);
      const note = bits.join("; ").replace(/[",\r\n]/g, " ");
      out.push(`${L.step.text},${round(L.H, 2)},${note}`);
    }
    return out.join("\n") + "\n";
  };

  // ---------------------------------------------------------------- transfer (§3.12)
  /*
   * A transfer campaign calibrates two tanks with one water: a pump draws
   * known volumes out of tank A (a drain, §3.11) into calibrated cans, and
   * the same cans are emptied into tank B (a fill).  One batch of cans is
   * one step for both tanks; each tank keeps its own levels, dips, running
   * shell and raw file.  The wrapper owns the shared can tally (it lives on
   * the drain session) and the paired-residual view of the current batch:
   *
   *   resid_A ≈ resid_B      one shared cause: the cans (a miscount, a can
   *                          not filled to its mark), not a tank;
   *   resid_B − resid_A > 0  litres lost on the way (a spill at the carry),
   *                          or a cause on the A side alone (a leak);
   *   resid_B − resid_A < 0  liquid returned to A, or a cause on the B side
   *                          alone (an object in B shows only in B).
   *
   * The pour noise is common to both residuals and cancels in the
   * difference: only the two dip noises remain, so the difference is a
   * sharper test than either residual alone.  The single-tank views (log,
   * charts, shell, settings) read the active tank; the page switches it.
   */
  function TransferSession(configOut, configIn, saved) {
    this.isTransfer = true;
    this.out = new Session(Object.assign({}, configOut || {}, { direction: "drain" }), saved && saved.out);
    this.in = new Session(Object.assign({}, configIn || {}, { direction: "fill" }), saved && saved.in);
    this.active = saved && saved.active === "in" ? "in" : "out";
    this.lastDip = saved && saved.lastDip === "in" ? "in" : "out";
    this.pair = null;
    this._pair();
  }

  TransferSession.fromJSON = function (obj) { return new TransferSession(obj.out.config, obj.in.config, obj); };
  TransferSession.prototype.toJSON = function () {
    return {
      version: 1, kind: "transfer", active: this.active, lastDip: this.lastDip,
      out: this.out.toJSON(), in: this.in.toJSON(),
    };
  };

  TransferSession.prototype.tank = function (k) { return this[k === "in" ? "in" : "out"]; };
  /** The tank whose level is still being dipped: A first, then B. */
  TransferSession.prototype.pendingTank = function () {
    for (const k of ["out", "in"]) {
      const cur = this[k].current();
      if (cur && cur.state === "pending") return k;
    }
    return null;
  };
  TransferSession.prototype.pendingLevel = function () {
    const k = this.pendingTank();
    return k ? this[k].current() : null;
  };
  TransferSession.prototype._guard = function () {
    const k = this.pendingTank();
    if (k) throw new Error(`finish the dips at tank ${this[k].cfg.tank} first`);
  };

  /** Start both tanks: row 1 of two raw files, dipped before the first batch. */
  TransferSession.prototype.start = function (stepOut, dipOut, stepIn, dipIn, note, time, opts) {
    if (this.out.levels.length || this.in.levels.length) throw new Error("the session has already started");
    this.out.start(stepOut, dipOut, note, time, opts);
    this.in.start(stepIn, dipIn, note, time);
    this.lastDip = "in";   // B's reading is the later one: undo takes it back first
    this._pair();
    return this.out.current();
  };

  /** One reading at the tank whose level is open. */
  TransferSession.prototype.dip = function (value, time) {
    const k = this.pendingTank();
    if (!k) throw new Error("both tanks are decided: pour the next batch");
    this.lastDip = k;
    const v = this[k].dip(value, time);
    this._pair();
    return v;
  };

  /** The tanks whose level still waits for a reading, A first. */
  TransferSession.prototype.pendingTanks = function () {
    const out = [];
    for (const k of ["out", "in"]) {
      const cur = this[k].current();
      if (cur && cur.state === "pending") out.push(k);
    }
    return out;
  };

  /**
   * One reading per tank, entered together (§3.12): the two dips of a batch
   * can be typed in one go.  A tank left blank keeps waiting; a value for a
   * decided tank is refused before either reading is recorded, so a stale
   * field cannot re-open a level by accident.
   */
  TransferSession.prototype.dipBoth = function (a, b, time) {
    const vals = { out: a, in: b }, got = {};
    for (const k of ["out", "in"]) {
      const v = vals[k];
      if (v == null || (typeof v === "string" && v.trim() === "")) continue;
      const cur = this[k].current();
      if (!cur || cur.state !== "pending") {
        throw new Error(`tank ${this[k].cfg.tank} is decided: take another reading to re-open it`);
      }
      // Both readings are checked before either is recorded: a typo in one
      // field must not leave the other tank's reading behind.
      const n = typeof v === "number" ? v : parseFloat(String(v).replace(",", "."));
      if (!isFinite(n)) throw new Error(`cannot read dip ${JSON.stringify(v)}`);
      got[k] = v;
    }
    if (!Object.keys(got).length) throw new Error("enter at least one reading");
    const res = {};
    for (const k of ["out", "in"]) {
      if (!Object.prototype.hasOwnProperty.call(got, k)) continue;
      res[k] = this[k].dip(got[k], time);
      this.lastDip = k;
    }
    this._pair();
    return res;
  };

  /** A new batch opens one level on both tanks with the same step. */
  TransferSession.prototype.pour = function (stepText, opts) {
    this._guard();
    const o = opts || {};
    const Lo = this.out.pour(stepText, { neck: !!o.neck, note: o.note });
    const Li = this.in.pour(stepText, { overflow: !!o.overflow, note: o.note });
    this._pair();
    return Lo;
  };

  // The shared can tally lives on the drain session (the pump fills the cans).
  TransferSession.prototype.cans = function () { return this.out.cans(); };
  TransferSession.prototype.canList = function () { return this.out.canList(); };
  TransferSession.prototype.batchVolume = function () { return this.out.batchVolume(); };
  TransferSession.prototype.canUnits = function () { return this.out.canUnits(); };
  TransferSession.prototype.quickTap = function (time) { return this.out.quickTap(time); };
  TransferSession.prototype.tap = function (time, unit) { this._guard(); return this.out.tap(time, unit); };
  TransferSession.prototype.untap = function () { return this.out.untap(); };

  /** Close the batch: the tally becomes the step of a level on both tanks. */
  TransferSession.prototype.closeBatch = function (opts) {
    this._guard();
    const o = opts || {};
    const Lo = this.out.closeBatch({ partial: o.partial, neck: o.neck, note: o.note });
    const Li = this.in.pour(Lo.step.text, { overflow: !!o.overflow, note: o.note });
    Li.cans = {
      tapped: Lo.cans.tapped, unit: Lo.cans.unit, partial: Lo.cans.partial,
      taps: Lo.cans.taps.slice(), units: Lo.cans.units.slice(),
    };
    this._pair();
    return Lo;
  };

  /**
   * Undo one entry: a can of the open batch, else the last reading (the
   * tank dipped last first), else the last batch, removed from both tanks.
   */
  TransferSession.prototype.undo = function () {
    if (this.cans()) { this.out.untap(); return this.current(); }
    const order = this.lastDip === "in" ? ["in", "out"] : ["out", "in"];
    for (const k of order) {
      const s = this[k], L = s.current();
      if (L && L.dips.length) {
        L.dips.pop();
        if (L.times && L.times.length) L.times.pop();
        if (!L.dips.length) { L.state = "pending"; L.verdict = null; L.H = null; L.n = 0; }
        else s._evaluate(L);
        s._refit();
        this._pair();
        return this.current();
      }
    }
    // No reading anywhere: remove the last batch from both tanks.
    if (this.out.levels.length > 1 && this.in.levels.length > 1) {
      const Lo = this.out.levels.pop(), Li = this.in.levels.pop();
      if (Lo.cans) {
        this.out.batch = {
          unit: Lo.cans.unit || Lo.cans.units[0],
          cans: Lo.cans.taps.map((t, i) => ({ t, u: Lo.cans.units[i] })),
        };
      }
      this.out._refit();
      this.in._refit();
      this._pair();
    }
    return this.current();
  };

  /** Accept the pending level against the check (operator decision). */
  TransferSession.prototype.override = function (why) {
    const k = this.pendingTank() || this.active;
    const v = this[k].override(why);
    this._pair();   // an override is not a prediction test: the pair leaves with it
    return v;
  };

  /** One recount edits the batch on both tanks: the step is one number. */
  TransferSession.prototype.editPour = function (stepText) {
    const Lo = this.out.current(), Li = this.in.current();
    if (!Lo || Lo.start || !Li || Li.start) throw new Error("no pour to edit");
    const step = parseStep(stepText);
    for (const side of [[this.out, Lo], [this.in, Li]]) {
      side[1].step = step;
      addTag(side[1], "pour edited on site");
      side[0]._evaluate(side[1]);
    }
    this._pair();
    return Lo.verdict;
  };

  TransferSession.prototype.editNote = function (row, text) { return this[this.active].editNote(row, text); };

  /**
   * Campaign settings.  The tank record belongs to the active tank; the
   * noise and the pour unit are one set for both (§9.1).  The direction is
   * fixed at the start.
   */
  TransferSession.prototype.setCampaign = function (o) {
    const has = (k) => Object.prototype.hasOwnProperty.call(o || {}, k);
    if (has("direction")) throw new Error("the direction (fill or drain) is fixed at the start of the campaign");
    const pick = (keys) => { const x = {}; for (const k of keys) if (has(k)) x[k] = o[k]; return x; };
    const shared = pick(["pourUnit", "sigmaRead", "pourRel", "pourAbs", "h0pm", "brimPm"]);
    const geo = pick(["tank", "D", "Dpm", "Lest", "Lpm"]);
    if (!Object.keys(shared).length && !Object.keys(geo).length) return this.cfg;
    // A bad field must change nothing on either tank: one Session.setCampaign
    // checks before it changes, but two saves in a row do not.  Keep each cfg
    // and put it back if a save fails partway.
    const back = {};
    for (const k of ["out", "in"]) back[k] = Object.assign({}, this[k].cfg);
    try {
      if (Object.keys(geo).length) this[this.active].setCampaign(geo);
      if (Object.keys(shared).length) for (const k of ["out", "in"]) this[k].setCampaign(shared);
    } catch (e) {
      for (const k of ["out", "in"]) {
        Object.assign(this[k].cfg, back[k]);
        this[k].cfg.prior = makePrior(this[k].cfg);
        this[k]._refit();
      }
      throw e;
    }
    return this.cfg;
  };

  /** Timers and alarms are operator settings, shared by both tanks. */
  TransferSession.prototype.setTimers = function (o) {
    this.out.setTimers(o);
    this.in.setTimers(o);
    return this.out.cfg;
  };

  /** The active tank supplies the single-tank views. */
  Object.defineProperties(TransferSession.prototype, {
    cfg: { get: function () { return this[this.active].cfg; } },
    levels: { get: function () { return this[this.active].levels; } },
    fit: { get: function () { return this[this.active].fit; } },
    scale: { get: function () { return this[this.active].scale; } },
  });
  for (const name of ["current", "lastGood", "advice", "preview", "status", "series",
    "learning", "fillPlan", "measuredPourSeconds", "fillSecondsFor", "cycleSecondsFor",
    "toRawCsv"]) {
    TransferSession.prototype[name] = function (name) {
      return function () { const s = this[this.active]; return s[name].apply(s, arguments); };
    }(name);
  }

  /**
   * The advice for the shared batch: the tighter of the two 30 mm targets
   * (§3.4), with the bottom watch of the drain tank and the brim watch of
   * the fill tank (§10 BOTTOM-WARN, BRIM-WARN).
   */
  TransferSession.prototype.adviceBatch = function () {
    const giO = this.out.lastGood(), giI = this.in.lastGood();
    if (giO < 0 || giI < 0) return null;
    const aO = this.out.advice(this.out.levels[giO].H);
    const aI = this.in.advice(this.in.levels[giI].H);
    const unit = this.out.cfg.pourUnit;
    let target = Math.min(aO.target, aI.target), units = null;
    if (unit) { units = Math.max(1, Math.round(target / unit)); target = units * unit; }
    return {
      target, units, out: aO, in: aI, halve: aI.halve, bottom: aO.bottom,
      text: (aI.halve ? `Tank B near the brim (≈ ${fmt(aI.toBrim, 0)} mm): small batches. ` : "")
        + (aO.bottom ? `Tank A near the bottom (≈ ${fmt(aO.toBottom, 0)} mm): the pump may lose suction; a part can is fine. ` : "")
        + `Next batch ≈ ${fmt(target, 0)} L` + (units ? ` = ${units} × ${fmt(unit, 0)} L` : "")
        + ` (≈ ${fmt(target / Math.max(aO.slope, 1e-3), 0)} mm out of A, ≈ ${fmt(target / Math.max(aI.slope, 1e-3), 0)} mm into B).`,
    };
  };

  /** One transfer tag per level; a recompute replaces it. */
  function setTransferTag(L, text) {
    if (!L.tags) L.tags = [];
    L.tags = L.tags.filter((t) => !/^transfer:/.test(t));
    if (text) L.tags.push(text);
  }

  /**
   * The paired-residual view of the current batch (§3.12).  Both tanks saw
   * the same cans, so their interval residuals share the pour error and
   * cancel it in the difference.  Only prediction-tested levels carry it: a
   * learning, unknown, override, neck or overflow level has no comparable
   * residual (its stored check is stale), and while a level is pending
   * there is no pair.
   */
  TransferSession.prototype._pair = function () {
    const Lo = this.out.current(), Li = this.in.current();
    if (Lo) { Lo.transfer = null; setTransferTag(Lo, null); }
    if (Li) { Li.transfer = null; setTransferTag(Li, null); }
    this.pair = null;
    if (this.pendingTank() || !Lo || !Li || Lo.start || Li.start) return this.pair;
    if (!PAIR.has(Lo.state) || !PAIR.has(Li.state)) return this.pair;
    const co = Lo.check, ci = Li.check;
    if (!co || !ci || co.learning || ci.learning) return this.pair;

    const cfg = this.out.cfg;
    const barO = Math.abs(co.z) >= cfg.zAlarm && Math.abs(co.mm) >= cfg.mmAlarm;
    const barI = Math.abs(ci.z) >= cfg.zAlarm && Math.abs(ci.mm) >= cfg.mmAlarm;
    const watchO = Math.abs(co.z) >= cfg.zCheck || Math.abs(co.mm) >= 1.5;
    const watchI = Math.abs(ci.z) >= cfg.zCheck || Math.abs(ci.mm) >= 1.5;
    if (!barO && !barI && !watchO && !watchI) return this.pair;

    // The noise of the difference.  The pour noise is common to both
    // residuals and cancels; the dip noise and each shell's own error add.
    // A wide check (an early or weakly identified shell) widens the test
    // honestly: a blunt side can confirm nothing.
    const mO = Math.max(slope(Lo.H, this.out.fit.p), 1e-3);
    const mI = Math.max(slope(Li.H, this.in.fit.p), 1e-3);
    const pour2 = Math.pow(pourSigma(Lo.step.value, cfg), 2);
    const sd = Math.sqrt(Math.max(
      Math.pow(co.sd * mO, 2) + Math.pow(ci.sd * mI, 2) - 2 * pour2, 1e-9));
    const ro = co.resid, ri = ci.resid;
    const diff = ri - ro, z = diff / sd;
    const off = `Tank A resid ${sgn(ro, 1)} L, tank B ${sgn(ri, 1)} L; difference ${sgn(diff, 1)} L = ${sgn(z, 1)} σ of the two checks.`;
    const wideO = co.sharp ? "" : ` Tank A's band is wide here (2σ = ${fmt(2 * co.sd * mO, 0)} L); it can confirm nothing.`;
    const wideI = ci.sharp ? "" : ` Tank B's band is wide here (2σ = ${fmt(2 * ci.sd * mI, 0)} L); it can confirm nothing.`;
    const MIXED = {
      status: "MIXED", color: "bad", title: "the tanks disagree",
      message: `Both tanks are at the action bar with different litres. ${off} Superposed causes (§6.6).`,
      advice: "Decompose before correcting either tank: recount the cans, and re-dip any level that is still there.",
      tag: "transfer: tanks disagree",
    };
    const DIFF_WATCH = {
      status: "WATCH", color: "info", title: "the tanks differ (watch)",
      message: `Tank A ${sgn(ro, 1)} L, tank B ${sgn(ri, 1)} L; neither check clears its own action bar, but the tanks differ by ${sgn(diff, 1)} L = ${sgn(z, 1)} σ. ${off} A wide band can hide a large miss in mm; watch item (§6.5).`,
      advice: "Pour the next batch. Recount the cans if a miscount could explain it.",
      tag: null,
    };
    let p = null;
    if (Math.abs(z) < 2) {
      if (barO || barI) {
        if (watchO && watchI) {
          p = {
            status: "POUR", color: "bad", title: "the same litres",
            message: `Both tanks missed by the same litres. ${off} One shared cause: the can count or the can fill (§3.10), not a tank.`,
            advice: "Count the cans of this batch again. If the count was wrong, Recount edits both tanks at once. If it stands, both intervals go to the register: a can not filled to its mark does this.",
            tag: "transfer: shared pour error",
          };
        } else {
          // One tank at the bar, the other clean but too wide to confirm.
          const barIsI = barI;
          const clean = barIsI ? "A" : "B", flagged = barIsI ? "B" : "A";
          const resid = barIsI ? ri : ro;
          const cause = barIsI
            ? (resid > 0 ? "a loss on the way (a spill at the carry)" : "an object in B in this band")
            : (resid < 0 ? "a leak or a spill at A (§3.11)" : "liquid returned to A (the hose drained back)");
          p = {
            status: "UNSURE", color: "warn", title: `only tank ${flagged} shows it`,
            message: `Tank ${flagged} missed ${fmt(Math.abs(resid), 1)} L and tank ${clean} shows nothing (${sgn(barIsI ? ro : ri, 1)} L), but its band is wide: a shared can error and ${cause} both fit. ${off}`,
            advice: `Recount the cans of this batch first: one edit fixes both tanks. If the count stands, the litres belong to tank ${flagged}: its interval goes to the register.`,
            tag: `transfer: ${flagged}-side only`,
          };
        }
      } else {
        p = {
          status: "WATCH", color: "info", title: "the same litres (watch)",
          message: `Both tanks show the same litres, below the action bar. ${off} A shared cause would show in both; a watch item (§6.5).`,
          advice: "Pour the next batch.",
          tag: null,
        };
      }
    } else if (z >= 2) {
      if (barI && !barO) {
        p = {
          status: "LOSS", color: "bad", title: "litres lost on the way",
          message: `Tank A is clean, but tank B missed ${fmt(diff, 1)} L: liquid left A and did not reach B — a spill at the carry, or a can not emptied. ${off}${wideO}`,
          advice: "Check the carry path and the cans. B's interval goes to the register as LOSS? (§6.2); A's stays in its fit.",
          tag: "transfer: loss on the way",
        };
      } else if (barO && !barI) {
        p = {
          status: "ALEAK", color: "bad", title: "only tank A shows it",
          message: `Tank A missed ${fmt(diff, 1)} L that tank B does not show: liquid left A off the record — the hose, the pump seal, or a spill at the can (§3.11). ${off}${wideI}`,
          advice: "Check the hose state and the pump. A's interval goes to the register (LEAK?); B's stays in its fit.",
          tag: "transfer: A-side only",
        };
      } else if (barO && barI) p = MIXED;
      else p = DIFF_WATCH;
    } else {
      if (barO && !barI) {
        p = {
          status: "ARETURN", color: "bad", title: "only tank A shows it",
          message: `Tank A's fall came ${fmt(-diff, 1)} L too small and tank B is clean: liquid returned to A (the hose drained back) or less left A than the count says (§3.11). ${off}${wideI}`,
          advice: "Check the hose state. A's interval goes to the register (RETURN?); B's stays in its fit.",
          tag: "transfer: A-side only",
        };
      } else if (barI && !barO) {
        p = {
          status: "BOBJECT", color: "bad", title: "only tank B shows it",
          message: `Tank B's rise came ${fmt(-diff, 1)} L too cheap and tank A is clean: an object in B in this band, or liquid diverted before B. ${off}${wideO}`,
          advice: "A's interval is good. B's goes to the register (OBJECT?): inspect B in this band, or repeat a pour into it (§6.2).",
          tag: "transfer: B-side only",
        };
      } else if (barO && barI) p = MIXED;
      else p = DIFF_WATCH;
    }
    p.ro = ro; p.ri = ri; p.diff = diff; p.z = z;
    this.pair = p;
    Lo.transfer = p;
    Li.transfer = p;
    if (p.tag) { setTransferTag(Lo, p.tag); setTransferTag(Li, p.tag); }
    return this.pair;
  };

  // ---------------------------------------------------------------- replay
  /**
   * Feed raw rows [{step, H}] through the check, as if each were dipped now.
   * When the check asks for another dip, second(i, k) gives it; by default the
   * recorded reading again: the answer a correct reading gives.
   * A drain (config.direction = "drain") takes opts.neckRows (a Set of
   * 1-based rows that are neck levels) and opts.neckEntrance (row 1 is the
   * neck-entrance reading, the brim B).
   */
  function replayRows(rows, config, opts) {
    const o = opts || {};
    const s = new Session(config);
    const drain = s.cfg.dir < 0;
    const second = o.second || ((i) => rows[i].H);
    const overflow = o.overflowRows || new Set();
    const neck = o.neckRows || new Set();
    const out = [];
    const settle = (i, v) => {
      let d = 1;
      while ((v.status === "REDIP" || v.status === "UNSETTLED") && d < 4) { v = s.dip(second(i, d)); d++; }
      return { v, d };
    };
    for (let i = 0; i < rows.length; i++) {
      let v;
      if (i === 0) {
        v = drain ? s.start(rows[0].step, rows[0].H, "", null, { at: o.neckEntrance ? "entrance" : neck.has(1) ? "neck" : "shell" })
          : s.start(rows[0].step, rows[0].H);
      } else {
        s.pour(rows[i].step, drain ? { neck: neck.has(i + 1) } : { overflow: overflow.has(i + 1) });
        v = s.dip(o.first ? o.first(i) : rows[i].H);
      }
      const firstStatus = i === 0 ? "" : v.status;
      const r = settle(i, v);
      out.push({
        row: i + 1, H: rows[i].H, step: rows[i].step, dips: r.d, firstStatus, status: r.v.status,
        predicted: r.v.predicted, sd: r.v.sd, e: r.v.e, z: r.v.z, mm: r.v.mm, resid: r.v.resid,
        sharp: r.v.sharp, learning: r.v.learning, pair: r.v.pair || null,
      });
    }
    return { session: s, out, status: s.status() };
  }

  /** "drain" when the heights of the rows mostly fall, else "fill". */
  function detectDirection(rows) {
    let up = 0, down = 0;
    for (let i = 1; i < rows.length; i++) {
      if (rows[i].H > rows[i - 1].H) up++;
      else if (rows[i].H < rows[i - 1].H) down++;
    }
    return down > up ? "drain" : "fill";
  }

  /** Read a raw CSV text (§3.9): comma or semicolon, '#' comments, BOM. */
  function readRawText(text) {
    const lines = String(text).replace(/^\uFEFF/, "").split(/\r?\n/).filter((l) => l.trim() && !l.trim().startsWith("#"));
    if (!lines.length) return [];
    const delim = lines[0].includes(";") ? ";" : ",";
    const rows = [];
    for (const line of lines.slice(1)) {
      const cells = line.split(delim);
      if (cells.length < 2 || !cells[1].trim()) continue;
      const H = parseFloat(cells[1].trim().replace(",", "."));
      if (!isFinite(H)) continue;
      rows.push({ step: cells[0].trim(), H, note: (cells[2] || "").trim() });
    }
    return rows;
  }

  // ---------------------------------------------------------------- helpers
  function isMonotonic(a) {
    let up = true, down = true;
    for (let i = 1; i < a.length; i++) { if (a[i] < a[i - 1]) up = false; if (a[i] > a[i - 1]) down = false; }
    return up || down;
  }
  function round(x, d) { const f = Math.pow(10, d); return Math.round(x * f) / f; }
  function sizeKey(u) { return String(round(Number(u), 3)); }
  function clock(t) { const d = new Date(t); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; }
  function fmt(x, d) { return x == null || !isFinite(x) ? "—" : Number(x).toFixed(d); }
  function sgn(x, d) { return (x >= 0 ? "+" : "−") + fmt(Math.abs(x), d); }

  const api = {
    area, volume, slope, capacity, brim, levelFor, fitShell, predictLevel, parseStep,
    resolveConfig, Session, TransferSession, DEFAULTS, adopt, canHint, NAMES, replayRows,
    readRawText, detectDirection, makePrior,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CalibSite = api;
})(typeof globalThis !== "undefined" ? globalThis : this);

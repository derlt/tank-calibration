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

  /**
   * Maximum a posteriori fit of (r, L, h0): the difference fit of §5.1 plus
   * one residual per prior.  Levenberg–Marquardt with a numerical Jacobian.
   * ivs: [{H1, H2, s, n1, n2}]  (n = number of dips averaged at the level)
   */
  function fitShell(ivs, prior, cfg, start) {
    const pr = [prior.r, prior.L, prior.h0];
    const ps = [prior.sr, prior.sL, prior.sh0];
    const lo = [0.5 * prior.r, 0.5 * prior.L, -400];
    const hi = [1.5 * prior.r, 1.5 * prior.L, 400];
    const clamp = (x) => x.map((v, i) => Math.min(Math.max(v, lo[i]), hi[i]));
    function f(x) {
      const p = toP(x), out = [];
      for (const iv of ivs) {
        const m = Math.max(slope(iv.H2, p), 1e-3);
        const sd = Math.sqrt(m * m * cfg.sigmaRead * cfg.sigmaRead * (1 / iv.n1 + 1 / iv.n2)
          + Math.pow(pourSigma(iv.s, cfg), 2));
        out.push((iv.s - (volume(iv.H2, p) - volume(iv.H1, p))) / sd);
      }
      for (let i = 0; i < 3; i++) out.push((x[i] - pr[i]) / ps[i]);
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

  /** Level a pour s from H1 must give, and its spread from the parameter covariance. */
  function predictLevel(H1, s, fit) {
    const p = fit.p;
    const target = volume(H1, p) + s;
    const Hp = levelFor(target, p);
    const over = target > capacity(p);
    let sdModel = 0;
    if (fit.cov) {
      const x = [p.r, p.L, p.h0], g = [];
      for (let j = 0; j < 3; j++) {
        const d = 1e-3 * Math.max(1, Math.abs(x[j]));
        const xp = x.slice(), xm = x.slice();
        xp[j] += d; xm[j] -= d;
        const P = toP(xp), M = toP(xm);
        g.push((levelFor(volume(H1, P) + s, P) - levelFor(volume(H1, M) + s, M)) / (2 * d));
      }
      sdModel = Math.sqrt(Math.max(quad(g, fit.cov), 0));
    }
    return { H: Hp, sdModel, overflow: over };
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
  };

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
    cfg.prior = {
      r: cfg.D / 2, sr: cfg.Dpm / 4,
      L: cfg.Lest, sL: cfg.Lpm / 2,
      h0: 0, sh0: cfg.h0pm / 2,
    };
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
   */
  const GOOD = new Set(["accepted", "learning", "anomaly", "unknown", "override", "start"]);
  const FIT = new Set(["accepted", "learning"]);

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

  Session.prototype._fitIntervals = function (upto) {
    const ivs = [];
    const end = upto == null ? this.levels.length : upto;
    for (let i = 1; i < end; i++) {
      const L = this.levels[i];
      if (!FIT.has(L.state) || L.step.kind !== "known") continue;
      const j = L.from;
      if (j == null || j < 0 || !GOOD.has(this.levels[j].state) || this.levels[j].suspect) continue;
      if (!(L.H > this.levels[j].H)) continue;
      ivs.push({ H1: this.levels[j].H, H2: L.H, s: L.step.value, n1: this.levels[j].n, n2: L.n, row: i });
    }
    return ivs;
  };

  Session.prototype._refit = function () {
    const ivs = this._fitIntervals();
    this.fit = fitShell(ivs, this.cfg.prior, this.cfg, this.fit && this.fit.p);
    // Noise scale from the earlier one-step-ahead misses: robust (median), so
    // that real anomalies do not inflate it, and shrunk toward 1 while few.
    const zs = [];
    for (const L of this.levels) {
      if (L.check && L.check.scored && L.check.zRaw != null && L.dips.length) zs.push(Math.abs(L.check.zRaw));
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

  /** Start the campaign: first row of the raw file (heel or first pour). */
  Session.prototype.start = function (stepText, dip, note, time) {
    if (this.levels.length) throw new Error("the session has already started");
    const step = parseStep(stepText);
    const L = { row: 1, step, dips: [], state: "pending", from: null, note: note || "", tags: [], H: null, n: 0, start: true };
    this.levels.push(L);
    return this.dip(dip, time);
  };

  /** A new pour.  The dip follows with dip(). */
  Session.prototype.pour = function (stepText, opts) {
    const cur = this.current();
    if (!cur) throw new Error("start the session first");
    if (cur.state === "pending") throw new Error("finish the dips at the current level first");
    const from = this.lastGood();
    const step = parseStep(stepText);
    const L = {
      row: this.levels.length + 1, step, dips: [], state: "pending", from,
      note: (opts && opts.note) || "", tags: [], overflow: !!(opts && opts.overflow), H: null, n: 0,
    };
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

  /** Prediction for level L (index i) from its anchor, or null. */
  Session.prototype._predict = function (L, nNew) {
    if (L.start || L.step.kind !== "known" || L.from == null || L.from < 0) return null;
    const A = this.levels[L.from];
    const fit = this.fit;
    const pr = predictLevel(A.H, L.step.value, fit);
    const p = fit.p;
    const m1 = Math.max(slope(A.H, p), 1e-3), m2 = Math.max(slope(pr.H, p), 1e-3);
    const sr = this.cfg.sigmaRead;
    const noise2 = sr * sr * (m1 / m2) * (m1 / m2) / Math.max(A.n, 1) + sr * sr / nNew
      + Math.pow(pourSigma(L.step.value, this.cfg) / m2, 2);
    const sdNoise = Math.sqrt(noise2);
    const sd = this.scale * Math.sqrt(noise2 + pr.sdModel * pr.sdModel);
    return { H: pr.H, sd, sdNoise, sdModel: pr.sdModel, scale: this.scale, overflow: pr.overflow, m: m2, anchor: A.H };
  };

  /** Interval residual in the §2 convention with the running fit. */
  Session.prototype._resid = function (L, H) {
    const A = this.levels[L.from], p = this.fit.p;
    const pred = volume(H, p) - volume(A.H, p);
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
        advice: "Pour the next can.",
      });
      if (!L.start && L.step.kind !== "known" && this.fit) {
        const A = this.levels[L.from], p = this.fit.p, m = Math.max(slope(a.H, p), 1e-3);
        const x = volume(a.H, p) - volume(A.H, p) - L.step.base;
        const sr = cfg.sigmaRead;
        const sx = this.scale * Math.sqrt(m * m * sr * sr * (1 / Math.max(A.n, 1) + 1 / a.n)
          + Math.pow(cfg.pourRel * L.step.base + cfg.pourAbs, 2));
        verdict.unknown = { x, sigma: sx, base: L.step.base };
        verdict.message += ` Back-predicted pour: ${L.step.base ? fmt(L.step.base, 0) + " + " : ""}${fmt(x, 1)} ± ${fmt(2 * sx, 1)} L (running shell, refined by the final fit).`;
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
    L.check = { predicted: pr.H, sd: pr.sd, e, z, zRaw, resid: res.resid, mm: res.mm, sharp, scored: sharp && !learning };
    const miss = Math.abs(z) >= cfg.zCheck || Math.abs(res.mm) >= cfg.mmCheck;
    const off = `Reading ${fmt(a.H, 1)} mm, predicted ${fmt(pr.H, 1)} ± ${fmt(2 * pr.sd, 1)} mm (2σ): `
      + `${fmt(Math.abs(e), 1)} mm ${e >= 0 ? "above" : "below"}. resid ${sgn(res.resid, 1)} L = ${sgn(res.mm, 1)} mm-equiv, z ${sgn(z, 1)}.`;

    if (!miss && (sharp || nd >= 2)) {
      Object.assign(verdict, {
        status: "ACCEPT", color: "ok", title: nd >= 2 ? "Reading confirmed" : "Reading good",
        message: off, advice: "Pour the next can.",
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
          + `${cfg.learnN} intervals, so the miss is most likely the shape (bottom, datum), not the pour.`,
        advice: "Pour the next can. The level is kept and used by the fit.",
      });
      setState("learning"); L.verdict = verdict; this._refit(); this._advise(verdict, L); return verdict;
    }
    const big = Math.abs(z) >= cfg.zAlarm && Math.abs(res.mm) >= cfg.mmAlarm;
    if (!big) {
      Object.assign(verdict, {
        status: "WATCH", color: "info", title: "Reading confirmed: watch item",
        message: off + " Two readings agree, so the dip is good. The miss is below the action bar "
          + `(|z| ≥ ${fmt(cfg.zAlarm, 0)} and ≥ ${fmt(cfg.mmAlarm, 0)} mm): a watch item (§6.5), kept in the fit.`,
        advice: "Pour the next can.",
      });
      L.watch = true;
      setState("accepted"); L.verdict = verdict; this._refit(); this._advise(verdict, L); return verdict;
    }
    const cause = res.resid < 0
      ? "OBJECT? or the pour was under-recorded: the rise came too cheap, more liquid went in than recorded or a solid displaced it"
      : "LOSS? or the pour was over-recorded: the rise came too small, less liquid went in than recorded, or liquid went somewhere (leak, film, trapped air)";
    Object.assign(verdict, {
      status: "ALARM", color: "bad",
      title: "Reading confirmed: the pour or the tank is off",
      message: off + ` Two readings agree, so the dip is good. ${cause}.`,
      advice: "Count the cans (or read the meter) of this pour again. If the count was wrong, edit the pour. "
        + "If it was right, keep it: this interval stays out of the running fit and goes to the anomaly register (§6.2). "
        + "A repeat pour of the same size into this band tells an object from a pour error. Pour the next can.",
      cause: res.resid < 0 ? "OBJECT?" : "LOSS?",
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
      verdict.advice = "Count the empty cans now, before the next pour. "
        + (single ? `If you count ${fmt(was + hint.extra, 0)} cans, edit the pour to ${fmt(total, 0)} L. `
          : `If the recount gives ${fmt(total, 0)} L, edit the pour to match it. `)
        + verdict.advice;
    }
    // Pair pattern with the previous interval: the previous level may be the misread one.
    const prev = this.levels[L.from];
    if (prev && prev.check && prev.check.resid != null && prev.check.resid * res.resid < 0) {
      const r1 = prev.check.resid, r2 = res.resid;
      const net = Math.abs(r1 + r2) / (Math.abs(r1) + Math.abs(r2));
      if (net <= 0.15) {
        const delta = (r2 - r1) / (2 * Math.max(slope(prev.H, this.fit.p), 1e-3));
        verdict.pair = { level: prev.H, delta, net };
        verdict.message += ` With the previous interval this is the pattern of a misread at ${fmt(prev.H, 0)} mm `
          + `(δ ≈ ${sgn(delta, 1)} mm, net ${fmt(100 * net, 0)} %).`;
        verdict.advice = `That level is gone and cannot be dipped again. Record it: the final fit corrects it with the pair rule (§6.1). ` + verdict.advice;
        prev.suspect = true;
      }
    }
    setState("anomaly"); L.verdict = verdict; this._refit(); this._advise(verdict, L); return verdict;
  };

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
   * o = { size, cycleSeconds, settleSeconds, dipSeconds, now, pourElapsed }
   *   cycleSeconds  time one can costs: fill, carry and drain
   *   now           ms, for the settle time already spent at a pending level
   *   pourElapsed   s spent on the can that is filling now (fill timer)
   */
  Session.prototype.fillPlan = function (o) {
    const cfg = this.cfg, p = this.fit.p, size = o && o.size;
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
      if (cur.step.kind === "known") V = volume(this.levels[cur.from].H, p) + cur.step.value;
      else if (cur.step.kind === "partial") V = volume(this.levels[cur.from].H, p) + cur.step.base;
      const spent = cur.pourTime && o.now ? (o.now - cur.pourTime) / 1000 : 0;
      t = Math.max(0, settle - spent) + dipS;
    } else if (this.batch) {
      V += this.batchVolume();
      open = this.cans();
    }
    t -= Math.min(Math.max(o.pourElapsed || 0, 0), pourS);
    const start = { volume: V, seconds: t };
    const mark = (levels, cans) => ({ seconds: Math.max(0, t), levels, cans, volume: V });
    let atHalf = V >= half ? Object.assign(mark(0, 0), { done: true }) : null;
    let atBrim = V >= cap - 1e-6 ? Object.assign(mark(0, 0), { done: true }) : null;
    let levels = 0, cans = 0;
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
    return { size, cycleSeconds: pourS, settleSeconds: settle, dipSeconds: dipS, start, half: atHalf, brim: atBrim, capacity: cap };
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
      brim: brim(p), capacity: capacity(p),
    };
  };

  /**
   * Chart series against the running shell as it is now (§6.6): one entry per
   * decided interval with a known pour.  resid = s - pred (§2), z = resid / σ,
   * drift D_k = Σ resid, with its 3σ√n limit (§10 DRIFT).  Pending levels stay
   * blind; overflow readings and unknown pours carry no residual.
   */
  Session.prototype.series = function () {
    const p = this.fit.p, cfg = this.cfg, top = brim(p), out = [];
    let drift = 0, s2 = 0;
    for (const L of this.levels) {
      if (L.start || L.H == null || L.state === "pending" || L.overflow) continue;
      if (L.step.kind !== "known" || L.from == null || L.from < 0) continue;
      const H1 = this.levels[L.from].H, rise = L.H - H1;
      if (!(rise > 0) || L.H > top) continue;
      const s = L.step.value, pred = volume(L.H, p) - volume(H1, p), resid = s - pred;
      const m = Math.max(slope(L.H, p), 1e-3);
      const v = 2 * m * m * cfg.sigmaRead * cfg.sigmaRead + Math.pow(pourSigma(s, cfg), 2);
      const sigma = this.scale * Math.sqrt(v);
      drift += resid; s2 += v;
      out.push({
        row: L.row, H: L.H, H1, mid: 0.5 * (H1 + L.H), rise, s, pred, resid, m, mm: resid / m,
        sigma, z: resid / sigma, drift, limit: 3 * Math.sqrt(s2), state: L.state, watch: !!L.watch,
      });
    }
    return out;
  };

  /** Raw file for calib init / calib fit (§3.9).  One row per level, adopted reading. */
  Session.prototype.toRawCsv = function () {
    const out = ["step_volume,measured_height,note"];
    for (const L of this.levels) {
      if (L.H == null) continue;
      const bits = [];
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
        bits.push(`cans ${spec} L` + (L.cans.partial ? " last can part" : "")
          + (ts.length ? ` ${clock(ts[0])}-${clock(ts[ts.length - 1])}` : ""));
      }
      if (L.tags) for (const t of L.tags) bits.push(t);
      if (L.note) bits.push(L.note);
      const note = bits.join("; ").replace(/[",\r\n]/g, " ");
      out.push(`${L.step.text},${round(L.H, 2)},${note}`);
    }
    return out.join("\n") + "\n";
  };

  // ---------------------------------------------------------------- replay
  /**
   * Feed raw rows [{step, H}] through the check, as if each were dipped now.
   * When the check asks for another dip, second(i, k) gives it; by default the
   * recorded reading again: the answer a correct reading gives.
   */
  function replayRows(rows, config, opts) {
    const o = opts || {};
    const s = new Session(config);
    const second = o.second || ((i) => rows[i].H);
    const overflow = o.overflowRows || new Set();
    const out = [];
    const settle = (i, v) => {
      let d = 1;
      while ((v.status === "REDIP" || v.status === "UNSETTLED") && d < 4) { v = s.dip(second(i, d)); d++; }
      return { v, d };
    };
    for (let i = 0; i < rows.length; i++) {
      let v;
      if (i === 0) v = s.start(rows[0].step, rows[0].H);
      else { s.pour(rows[i].step, { overflow: overflow.has(i + 1) }); v = s.dip(o.first ? o.first(i) : rows[i].H); }
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
    resolveConfig, Session, DEFAULTS, adopt, canHint, NAMES, replayRows, readRawText,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CalibSite = api;
})(typeof globalThis !== "undefined" ? globalThis : this);

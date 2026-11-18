#!/usr/bin/env node
/* Power study of the live check on synthetic campaigns.
 *
 *   node site/simulate.js [--runs 200] [--seed 1] [--drain [--start shell]] [--deltas 3,4] [--json]
 *
 * Each run draws a 25 m³ shell (h0 ≈ −30 mm), builds a campaign with a
 * representative pour schedule, adds reading noise and pour
 * noise, and slips ONE reading by δ mm.  The operator's second reading is
 * honest (true level + reading noise).  The study counts:
 *   caught   the check asked for a second dip at the slipped level
 *   false    extra dips asked at honest levels
 *   alarms   ALARM verdicts at honest levels (after the second dip)
 *
 * --drain builds the campaign top-down (reverse strapping): the first level
 * is the start reading at the brim (true brim + reading noise), the drain
 * schedule is the fill schedule mirrored (small steps near the top, large in
 * the middle, small near the bottom), and the campaign stops above the
 * bottom.  --start shell treats the same first reading as a plain shell
 * start (no brim prior): the ablation for the start at the brim.
 */
"use strict";
const path = require("path");
const core = require(path.join(__dirname, "site_core.js"));

function rng(seed) {
  let s = seed >>> 0 || 1;
  const u = () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return (s + 0.5) / 4294967296; };
  const n = () => Math.sqrt(-2 * Math.log(u())) * Math.cos(2 * Math.PI * u());
  return { u, n };
}

const SCHEDULE = [200, 200, 200, 200, 400, 400, 400, 400, 400, 400, 600, 600, 600, 600, 600,
  1200, 1200, 1200, 1200, 1200, 1200, 1200, 1200, 1200, 1200, 600, 600, 600, 600, 600,
  400, 400, 400, 400, 400, 400, 200, 200, 200, 200, 100, 100, 100, 100, 100, 100];

const DRAIN_SCHEDULE = SCHEDULE.slice().reverse();

function campaign(R, opt) {
  const truth = { r: 1240 + 20 * R.n(), L: 5200 + 80 * R.n(), h0: -30 + 6 * R.n() };
  const q = (x) => Math.round(x / opt.resolution) * opt.resolution;
  const read = (H) => q(H + opt.sigmaRead * R.n());
  const cap = core.capacity(truth);
  let levels;
  if (opt.drain) {
    // Start at the brim: the true level is the brim itself.
    let V = cap;
    const stop = 400 + 100 * R.u();                // stay above the bottom: the pump keeps suction
    levels = [{ step: "?", H: core.brim(truth) }];
    for (const s of DRAIN_SCHEDULE) {
      const actual = s + (opt.pourRel * s + opt.pourAbs) * R.n() * 0.6;
      if (V - actual < stop) break;
      V -= actual;
      levels.push({ step: String(s), H: core.levelFor(V, truth) });
    }
  } else {
    let V = 400 + 100 * R.u();                     // heel
    levels = [{ step: "?", H: core.levelFor(V, truth) }];
    for (const s of SCHEDULE) {
      const actual = s + (opt.pourRel * s + opt.pourAbs) * R.n() * 0.6;
      if (V + actual > cap * 0.985) break;
      V += actual;
      levels.push({ step: String(s), H: core.levelFor(V, truth) });
    }
  }
  const config = {
    D: 2 * truth.r + opt.Dpm / 2 * R.n(), Dpm: opt.Dpm,
    Lest: truth.L * (1 + 0.015 * R.n()), Lpm: 0.03 * truth.L,
    pourUnit: 100, sigmaRead: opt.sigmaRead,
    direction: opt.drain ? "drain" : "fill",
  };
  return { truth, levels, config, read };
}

function run(R, opt, delta) {
  const c = campaign(R, opt);
  const n = c.levels.length;
  const k = 6 + Math.floor(R.u() * (n - 8));       // slipped level, past the first pours
  const s = new core.Session(c.config);
  const tally = { caught: null, falseRedip: 0, honest: 0, alarms: 0, accepted: null, adoptedErr: null };
  const finish = (i, v) => {
    let d = 1;
    while ((v.status === "REDIP" || v.status === "UNSETTLED") && d < 4) { v = s.dip(c.read(c.levels[i].H)); d++; }
    return { v, d };
  };
  let v = opt.drain ? s.start(c.levels[0].step, c.read(c.levels[0].H), "", null, { at: opt.at || "entrance" })
    : s.start(c.levels[0].step, c.read(c.levels[0].H));
  finish(0, v);
  for (let i = 1; i < n; i++) {
    s.pour(c.levels[i].step);
    const first = i === k ? c.read(c.levels[i].H) + delta : c.read(c.levels[i].H);
    v = s.dip(first);
    const askedAgain = v.status === "REDIP";
    const r = finish(i, v);
    const L = s.levels[i];
    if (i === k) { tally.caught = askedAgain; tally.adoptedErr = L.H - c.levels[i].H; tally.final = r.v.status; }
    else if (i > 4) {                            // past the learning pours
      tally.honest++;
      if (askedAgain) tally.falseRedip++;
      if (r.v.status === "ALARM") tally.alarms++;
    }
  }
  tally.shell = s.fit.p; tally.truth = c.truth;
  return tally;
}

function main(argv) {
  const a = {};
  for (let i = 0; i < argv.length; i++) if (argv[i].startsWith("--")) a[argv[i].slice(2)] = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : true;
  const runs = +(a.runs || 200), seed = +(a.seed || 1);
  const opt = { sigmaRead: +(a["sigma-read"] || 0.4), resolution: 0.5, pourRel: 0.005, pourAbs: 3, Dpm: +(a.Dpm || 200), drain: !!a.drain, at: a.start === "shell" ? "shell" : "entrance" };
  const deltas = a.deltas && a.deltas !== true ? String(a.deltas).split(",").map(Number) : [1, 2, 3, 4, 5, 7, 10];
  const rows = [];
  for (const delta of deltas) {
    const R = rng(seed * 7919 + delta);
    let caught = 0, fr = 0, hon = 0, al = 0, leak = 0, dr = 0, dL = 0;
    for (let j = 0; j < runs; j++) {
      const sign = j % 2 ? 1 : -1;
      const t = run(R, opt, sign * delta);
      if (t.caught) caught++;
      if (Math.abs(t.adoptedErr) > 1.5) leak++;
      fr += t.falseRedip; hon += t.honest; al += t.alarms;
      dr += Math.abs(t.shell.r - t.truth.r); dL += Math.abs(t.shell.L - t.truth.L);
    }
    rows.push({ delta, caught: caught / runs, leaked: leak / runs, falseRedip: fr / hon, falseAlarm: al / hon, meanAbsDr: dr / runs, meanAbsDL: dL / runs });
  }
  if (a.json) { console.log(JSON.stringify({ opt, runs, rows }, null, 2)); return; }
  console.log(`${opt.drain ? `DRAIN (start ${opt.at === "shell" ? "in the shell, no brim prior" : "at the brim"})` : "FILL"}  runs ${runs}  sigmaRead ${opt.sigmaRead} mm  D ± ${opt.Dpm} mm  one slipped reading per run`);
  console.log("slip mm  caught  kept >1.5 mm off  extra dips at honest levels  false ALARM  |dr| mm  |dL| mm");
  for (const r of rows) {
    console.log(`${String(r.delta).padStart(7)}  ${(100 * r.caught).toFixed(0).padStart(5)} %  ${(100 * r.leaked).toFixed(0).padStart(15)} %  ${(100 * r.falseRedip).toFixed(1).padStart(26)} %  ${(100 * r.falseAlarm).toFixed(2).padStart(9)} %  ${r.meanAbsDr.toFixed(1).padStart(7)}  ${r.meanAbsDL.toFixed(1).padStart(7)}`);
  }
}

if (require.main === module) main(process.argv.slice(2));
module.exports = { run, campaign, rng };

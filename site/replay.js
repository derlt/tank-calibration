#!/usr/bin/env node
/* Replay a raw CSV through the live check, as if each row were dipped now.
 *
 *   node site/replay.js RAW.csv --D 2480 --L 5280 [--Dpm 200] [--Lpm 150]
 *                       [--unit 100] [--sigma-read 0.4] [--json]
 *
 * A raw file holds one reading per level.  When the check asks for a second
 * dip, the replay repeats the recorded reading: the answer a correct reading
 * gives.  So every REDIP is one extra dip on site, and every CHECK / ALARM /
 * LEARNING is what the operator would have seen after it.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const core = require(path.join(__dirname, "site_core.js"));

function readRaw(file) { return core.readRawText(fs.readFileSync(file, "utf8")); }
const replay = core.replayRows;

function main(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const k = a.slice(2);
      if (k === "json") args.json = true;
      else args[k] = argv[++i];
    } else args._.push(a);
  }
  if (!args._[0] || !args.D || !args.L) {
    console.error("usage: node site/replay.js RAW.csv --D mm --L mm [--Dpm 200] [--Lpm mm] [--unit L] [--sigma-read 0.4] [--overflow ROW] [--json]");
    process.exit(2);
  }
  const config = {
    D: +args.D, Lest: +args.L,
    Dpm: args.Dpm ? +args.Dpm : undefined, Lpm: args.Lpm ? +args.Lpm : undefined,
    pourUnit: args.unit ? +args.unit : null,
    sigmaRead: args["sigma-read"] ? +args["sigma-read"] : undefined,
  };
  for (const k of Object.keys(config)) if (config[k] === undefined) delete config[k];
  const rows = readRaw(args._[0]);
  const overflowRows = new Set(args.overflow ? String(args.overflow).split(",").map(Number) : []);
  const r = replay(rows, config, { overflowRows });
  if (args.json) { console.log(JSON.stringify({ out: r.out, status: r.status }, null, 2)); return; }
  const f = (x, d = 1) => (x == null || !isFinite(x) ? "" : x.toFixed(d));
  console.log("row      H   step  dips  first     final        pred    ±2σ      e      z");
  for (const o of r.out) {
    console.log(`${String(o.row).padStart(3)} ${f(o.H, 1).padStart(7)} ${String(o.step).padStart(6)} ${String(o.dips).padStart(5)}  ${(o.firstStatus || "").padEnd(8)}  ${o.status.padEnd(10)} ${f(o.predicted).padStart(7)} ${f(o.sd ? 2 * o.sd : null).padStart(6)} ${f(o.e).padStart(6)} ${f(o.z).padStart(6)}${o.pair ? `  pair: misread at ${f(o.pair.level, 0)} δ ${f(o.pair.delta)}` : ""}`);
  }
  const st = r.status, p = st.fit.p;
  console.log(`\nshell  r ${f(p.r)} ± ${f(st.fit.sd.r)}  L ${f(p.L)} ± ${f(st.fit.sd.L)}  h0 ${f(p.h0)} ± ${f(st.fit.sd.h0)} mm   noise scale ${f(st.scale, 2)}`);
  console.log(`extra dips ${st.redips} over ${st.levels} levels   states ${JSON.stringify(st.counts)}`);
  console.log(`drift ${f(st.drift)} L (limit ±${f(st.driftLimit)} L)`);
}

if (require.main === module) main(process.argv.slice(2));
module.exports = { readRaw, replay };

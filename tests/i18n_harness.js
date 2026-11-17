// Coverage harness for the page translator (site/i18n.js).
//
// It drives the on-site page (under the DOM stub) and the core through many
// campaign paths: fill, drain, transfer, simple and verbose mode, misreads,
// unknown pours, overflow, neck levels, errors and every tab.  After each
// step it collects the text of every element: what the operator can see.
// Then it asks the translator for the parts that have no key.
//
//   node tests/i18n_harness.js LANG STATIC.json   -> JSON list of missing parts
//
// STATIC.json holds the static texts of page.html (the Python test extracts
// them with an HTML parser).
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..");
const stub = require(path.join(__dirname, "page_stub.js"));
const core = require(path.join(ROOT, "site", "site_core.js"));
const I18N = require(path.join(ROOT, "site", "i18n.js"));
const PAGE = path.join(ROOT, "site", "page.html");
const CORE = path.join(ROOT, "site", "site_core.js");

const lang = process.argv[2] || "vi";
console.error = () => {};   // the page logs the errors it shows; the harness collects them from the page
const statics = process.argv[3] ? JSON.parse(fs.readFileSync(process.argv[3], "utf8")) : [];

// Names the scenarios give: user text, never translated.
const NAMES = new Set(["t1", "t2", "alpha", "beta", "tank", "tank-b", "calib site", "alpha_raw.csv", "beta_raw.csv", "t1_raw.csv", "checked the cans"]);
const SKIP_IDS = new Set(["f-text", "set-lang", "hdr-title", "d-val", "d-val-b", "p-vol", "p-note"]);

const texts = new Set();
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const add = (s) => { if (s != null) { const t = String(s).replace(/\s+/g, " ").trim(); if (/[A-Za-z]/.test(t)) texts.add(t); } };

/** The text nodes of an innerHTML string, skipping translate="no" and <title>-less script. */
function htmlTexts(html) {
  const out = [];
  let skip = 0;
  const re = /<(\/?)([a-zA-Z0-9]+)([^>]*)>|([^<]+)/g;
  let m;
  const stack = [];
  while ((m = re.exec(html))) {
    if (m[4] != null) { if (!skip) out.push(decode(m[4])); continue; }
    const close = m[1] === "/", tag = m[2].toLowerCase(), attrs = m[3] || "";
    const attr = (name) => { const a = new RegExp(`${name}="([^"]*)"`).exec(attrs); return a ? decode(a[1]) : null; };
    if (!close) {
      for (const a of ["title", "aria-label", "placeholder"]) if (!skip && attr(a)) out.push(attr(a));
      if (/\/\s*$/.test(attrs) || ["br", "input", "img", "rect", "circle", "line", "path"].includes(tag) && /\/\s*$/.test(attrs)) continue;
      const no = /translate="no"/.test(attrs);
      stack.push({ tag, no });
      if (no) skip++;
    } else {
      while (stack.length) { const t = stack.pop(); if (t.no) skip--; if (t.tag === tag) break; }
    }
  }
  return out;
}

function collect(p) {
  for (const [id, el] of p.els) {
    if (SKIP_IDS.has(id)) continue;
    add(el.textContent);
    if (el.innerHTML) for (const t of htmlTexts(String(el.innerHTML))) add(t);
    add(el.title); add(el["aria-label"]); add(el.placeholder);
  }
}

const tabsOf = (p) => (t) => p.el("tabs")._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: t } }) } });
const modeOf = (p) => (m) => { if (p.el("hdr-mode")["aria-pressed"] !== String(m === "simple")) p.el("hdr-mode").click(); };

/** Visit every tab, in both modes, and collect. */
function sweep(p) {
  const tab = tabsOf(p), mode = modeOf(p);
  for (const m of ["verbose", "simple"]) {
    mode(m);
    for (const t of ["live", "log", "shell", "settings", "files", "replay", "help", "live"]) {
      tab(t);
      if (t === "log" && p.el("hdr-count").textContent) for (const c of ["miss", "slope", "drift", "z"]) { p.el("chart-pick")._listeners.click[0]({ target: { closest: () => ({ dataset: { chart: c } }) } }); collect(p); }
      collect(p);
    }
  }
  mode("verbose");
}

function boot(prefs) {
  const store = new Map();
  if (prefs) store.set("calib-site:prefs", JSON.stringify(prefs));
  const p = stub.boot(PAGE, CORE, store);
  collect(p);
  return p;
}

const tryClick = (p, id) => { try { p.el(id).click(); } catch (e) { add(e.message); } collect(p); };

/** A single-tank campaign: rows [{step, H, dips?: [..], over?, neck?, cans?}]. */
function single(rows, o) {
  const p = boot(o.prefs);
  const el = p.el;
  sweep(p);
  if (o.drain) { el("s-dir-drain").click(); collect(p); if (o.at) { el("s-at")._listeners.click && el("s-at")._listeners.click[0]({ target: { closest: () => ({ dataset: { at: o.at } }) } }); collect(p); } }
  el("s-tank").value = "t1"; el("s-D").value = String(o.D); el("s-L").value = String(o.L);
  el("s-step").value = rows[0].step; el("s-dip").value = String(rows[0].H); el("s-unit").value = o.unit ? String(o.unit) : "";
  tryClick(p, "s-go");
  el("d-val").value = String(rows[0].H); tryClick(p, "d-go");
  sweep(p);
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    el("p-over").checked = !!r.over; el("p-neck").checked = !!r.neck;
    if (r.cans) { for (let k = 0; k < r.cans; k++) tryClick(p, "t-plus"); if (r.part) el("t-part").checked = true; }
    else if (r.step === "?") { el("p-unknown").checked = true; }
    else if (/\+\?$/.test(r.step)) { el("p-vol").value = r.step.replace("+?", ""); el("p-extra").checked = true; }
    else el("p-vol").value = String(r.step);
    collect(p);
    tryClick(p, "p-go");
    el("p-unknown").checked = false; el("p-extra").checked = false; el("t-part").checked = false;
    const dips = r.dips || [r.H, r.H, r.H];
    for (let k = 0; k < dips.length; k++) {
      if (el("dip-card")._classes.has("hidden")) break;
      el("d-val").value = String(dips[k]); tryClick(p, "d-go");
    }
    if (!el("dip-card")._classes.has("hidden")) { tryClick(p, "a-override"); }
    if (r.redip) { tryClick(p, "a-redip"); el("d-val").value = String(r.H); tryClick(p, "d-go"); }
    if (i === 3 || i === rows.length - 1) sweep(p);
  }
  // Errors and actions the operator can reach.
  el("p-vol").value = ""; tryClick(p, "p-go");
  el("p-vol").value = "-5"; tryClick(p, "p-go");
  tryClick(p, "a-undo"); tryClick(p, "a-undo");
  tryClick(p, "set-save"); tryClick(p, "set-noise-save"); tryClick(p, "tm-save");
  sweep(p);
  return p;
}

/** A transfer campaign through the page. */
function transfer(batches, o) {
  const p = boot(o.prefs);
  const el = p.el;
  el("s-dir-transfer").click(); collect(p);
  el("s-tank").value = "alpha"; el("s-D").value = "1800"; el("s-L").value = "3000";
  el("sB-tank").value = "beta"; el("sB-D").value = "2480"; el("sB-L").value = "5200";
  el("s-dip").value = String(batches[0].a); el("sB-dip").value = String(batches[0].b); el("s-unit").value = "200";
  tryClick(p, "s-go");
  for (let k = 0; k < 3; k++) {
    if (!el("d-go-a").disabled) { el("d-val").value = String(batches[0].a); tryClick(p, "d-go-a"); }
    if (!el("d-go-b").disabled) { el("d-val-b").value = String(batches[0].b); tryClick(p, "d-go-b"); }
  }
  sweep(p);
  for (let i = 1; i < batches.length; i++) {
    const b = batches[i];
    for (let k = 0; k < b.cans; k++) tryClick(p, "t-plus");
    collect(p);
    tryClick(p, "p-go");
    for (let k = 0; k < 3; k++) {
      if (!el("d-go-a").disabled) { el("d-val").value = String(b.a); tryClick(p, "d-go-a"); }
      if (!el("d-go-b").disabled) { el("d-val-b").value = String(b.b); tryClick(p, "d-go-b"); }
    }
    collect(p);
    if (i === 2) sweep(p);
  }
  sweep(p);
  return p;
}

// ---------------------------------------------------------------- scenarios
const readRows = (f) => core.readRawText(fs.readFileSync(path.join(ROOT, "examples", f), "utf8"));
// Only files tracked in the repository: the demo campaigns.
const fillRows = readRows("demo_raw.csv").slice(0, 14);
const shape = (rows) => rows.map((r) => ({ step: r.step, H: r.H }));

for (const prefs of [{}, { mode: "simple" }]) {
  // Honest fill with a slip, a creeping level, an unknown pour, a part can and an overflow.
  const rows = shape(fillRows);
  rows[5].dips = [rows[5].H + 6, rows[5].H, rows[5].H];
  rows[7].dips = [rows[7].H + 3, rows[7].H + 5, rows[7].H + 7, rows[7].H];
  rows[8].step = "?";
  rows[9].step = "200+?";
  rows[10].dips = [rows[10].H + 9, rows[10].H + 9];
  rows[11].H += 9; rows[11].dips = [rows[11].H, rows[11].H];
  rows[12].redip = true;
  rows.push({ step: "100", H: rows[rows.length - 1].H + 40, over: true });
  single(rows, { D: 1760, L: 2950, unit: 50, prefs });
  // Cans tally path.
  const rc = shape(fillRows.slice(0, 6)).map((r, i) => (i ? Object.assign(r, { cans: Math.round(r.step / 50) }) : r));
  rc[3].part = true;
  single(rc, { D: 1760, L: 2950, unit: 50, prefs });
  // A drain from the neck entrance, with a neck level start.
  const dr = core.readRawText(fs.readFileSync(path.join(ROOT, "examples", "demo_drain_raw.csv"), "utf8")).slice(0, 12).map((r) => ({ step: r.step, H: r.H }));
  dr[4].dips = [dr[4].H - 8, dr[4].H - 8];
  single(dr, { D: 2480, L: 5280, unit: 200, drain: true, at: "entrance", prefs });
  single(dr.slice(0, 5), { D: 2480, L: 5280, unit: 200, drain: true, at: "shell", prefs });
  // A transfer: honest, then a shared pour error.
  transfer([{ a: 1800, b: 400 }, { a: 1755, b: 440 }, { a: 1710, b: 470 }, { a: 1660, b: 520 }, { a: 1610, b: 560 }, { a: 1560, b: 640 }], { prefs });
}

// The core's own texts, over replayed campaigns with faults.
function coreTexts(rows, config, opts) {
  const r = core.replayRows(rows, config, opts || {});
  const s = r.session;
  for (const L of s.levels) {
    const v = L.verdict;
    if (!v) continue;
    add(v.title); add(v.message); add(v.advice); if (v.next) add(v.next.text);
  }
}
{
  const rows = readRows("demo_raw.csv");
  coreTexts(rows, { D: 1760, Lest: 2950, pourUnit: 50 });
  // Faults: pours miscounted by one and by two cans, slipped readings.
  for (const [i, j, k] of [[10, 14, 50], [8, 16, 100], [12, 18, -50]]) {
    const bad = rows.map((r) => Object.assign({}, r));
    bad[i].H += 12; bad[j].step = String(+bad[j].step + k);
    coreTexts(bad, { D: 1760, Lest: 2950, pourUnit: 50 });
  }
  // One misread dip shared by two intervals: the pair pattern (§6.1).
  const pair = rows.map((r) => Object.assign({}, r));
  pair[7].H += 6;
  coreTexts(pair, { D: 1760, Lest: 2950, pourUnit: 50 });
}
coreTexts(readRows("demo_drain_raw.csv"), { D: 2480, Lest: 5280, pourUnit: 200, direction: "drain" }, { neckEntrance: true });
coreTexts(readRows("demo_drain_raw.csv"), { D: 2480, Lest: 5280, pourUnit: 200, direction: "drain" }, { neckRows: new Set([1, 2]) });

// Timers, alarm, archive and override through the page, with a fake clock.
(function timersAndFiles() {
  const realNow = Date.now;
  let now = realNow();
  Date.now = () => now;
  try {
    const p = boot({});
    const el = p.el, tab = tabsOf(p);
    el("s-tank").value = "t1"; el("s-D").value = "2480"; el("s-L").value = "5280";
    el("s-step").value = "?"; el("s-dip").value = "400"; el("s-unit").value = "200";
    tryClick(p, "s-go"); el("d-val").value = "400"; tryClick(p, "d-go");
    tryClick(p, "pt-start");                       // no fill time yet: the page asks for one
    tab("settings");
    el("tm-fill-200").value = "1:30"; el("tm-settle").value = "2:00"; el("tm-lead").value = "15";
    tryClick(p, "tm-save");
    el("tm-lead").value = "500"; tryClick(p, "tm-save"); el("tm-lead").value = "15";
    tryClick(p, "tm-test");
    tab("live");
    tryClick(p, "pt-start");
    for (const dt of [10, 70, 20, 30]) { now += dt * 1000; tab("live"); }
    tryClick(p, "pt-stop");
    tryClick(p, "t-plus"); tryClick(p, "p-go");
    for (const dt of [30, 200]) { now += dt * 1000; tab("live"); }
    el("d-val").value = "520"; tryClick(p, "d-go");
    now += 60000; tab("live");
    if (!el("dip-card")._classes.has("hidden")) { el("d-val").value = "500"; tryClick(p, "d-go"); tryClick(p, "a-override"); }
    tab("files"); tryClick(p, "f-new"); tab("files");
    sweep(p);
  } finally { Date.now = realNow; }
})();

// The core's pair view: every signature of a transfer (§3.12).
(function pairs() {
  const PA = { r: 900, L: 3000, h0: 0 }, PB = { r: 1240, L: 5200, h0: 0 };
  function runTransfer(batches, wide) {
    const X = new core.TransferSession(
      { D: 1800, Dpm: 200, Lest: 3000, Lpm: wide ? 90 : undefined, tank: "alpha", pourUnit: 200 },
      wide ? { D: 2480, Dpm: 2500, Lest: 5200, Lpm: 4000, tank: "beta", pourUnit: 200 } : { D: 2480, Dpm: 200, Lest: 5200, tank: "beta", pourUnit: 200 });
    let VA = core.capacity(PA), VB = 2000, t = 0;
    X.start("?", core.brim(PA), "?", core.levelFor(VB, PB), "", null, { at: "entrance" });
    X.dip(core.brim(PA)); X.dip(core.levelFor(VB, PB));
    const dipTank = (k, H) => { X.dip(H); let n = 1; while (X.pendingTank() === k && n < 4) { X.dip(H); n++; } };
    for (const b of batches) {
      const aOut = b.aOut == null ? b.s : b.aOut, aIn = b.aIn == null ? aOut : b.aIn;
      VA -= aOut; VB += aIn;
      for (let k = 0; k < b.s / 200; k++) X.tap(++t, 200);
      X.closeBatch({});
      dipTank("out", core.levelFor(VA, PA));
      dipTank("in", core.levelFor(VB, PB));
    }
    return X;
  }
  const clean = Array.from({ length: 5 }, () => ({ s: 600 }));
  const cases = [
    { s: 600, aOut: 800, aIn: 800 }, { s: 600, aIn: 500 }, { s: 600, aIn: 700 }, { s: 600, aOut: 800, aIn: 600 },
    { s: 600, aOut: 450, aIn: 600 }, { s: 600, aOut: 800, aIn: 450 }, { s: 600, aOut: 620, aIn: 620 }, { s: 600, aIn: 580 },
  ];
  for (const c of cases) {
    try {
      const X = runTransfer([...clean, c]);
      for (const v of [X.pair, X.out.current().verdict, X.in.current().verdict]) if (v) { add(v.title); add(v.message); add(v.advice); }
      for (const tg of (X.out.current().tags || []).concat(X.in.current().tags || [])) add(tg);
      X.active = "in"; X.override("checked the cans");
      const v = X.in.current().verdict; add(v.title); add(v.message);
      for (const tg of X.in.current().tags || []) add(tg);
    } catch (e) { add(e.message); }
  }
  try {
    const X = runTransfer([{ s: 600 }, { s: 600 }, { s: 600 }, { s: 4000, aOut: 4200, aIn: 4000 }], true);
    if (X.pair) { add(X.pair.title); add(X.pair.message); add(X.pair.advice); }
  } catch (e) { add(e.message); }
})();

// Batch plan campaigns through the page: the setup rows and their errors,
// then batches to the end of the plan on a synthetic tank that holds more
// (or less) than the nominal, so the end of the plan changes.
(function plans() {
  const planUi = (p, groups, o) => {
    const el = p.el;
    const click = (act, i) => el("s-plan")._listeners.click[0]({ target: { closest: () => ({ dataset: { act, i: String(i) }, disabled: false }) } });
    const size = (i, v) => el("s-plan")._listeners.input[0]({ target: { dataset: { i: String(i) }, value: String(v) } });
    el("s-unit").value = "200"; el("s-unit")._listeners.input[0]({});
    tryClick(p, "s-can-go");                                   // no size typed: an error
    el("s-can-add").value = "100"; tryClick(p, "s-can-go");
    el("s-can-add").value = "50"; tryClick(p, "s-can-go");
    el("s-cans")._listeners.click[0]({ target: { closest: () => ({ dataset: { can: "50" }, disabled: false }) } }); collect(p);
    tryClick(p, "s-plan-add"); collect(p);                     // a blank size
    size(0, 250); collect(p);
    groups.forEach((g, i) => { if (i) tryClick(p, "s-plan-add"); size(i, g.size); for (let k = 1; k < g.count; k++) click("inc", i); collect(p); });
    tryClick(p, "s-go");                                        // no nominal, not symmetric: errors
    size(0, 333); collect(p); size(0, groups[0].size);          // not a sum of the cans
    el("s-nom").value = String(o.nominal + 300); el("s-nom")._listeners.input[0]({}); collect(p);
    el("s-nom").value = String(o.nominal); el("s-nom")._listeners.input[0]({});
    if (o.nominalB) { el("sB-nom").value = String(o.nominalB); el("sB-nom")._listeners.input[0]({}); }
    tryClick(p, "s-plan-add"); size(groups.length, 9000); collect(p); click("del", groups.length);   // the largest at the top: not peaked
    tryClick(p, "s-plan-mirror"); collect(p);
    click("dec", 0); click("inc", 0); collect(p);
  };
  const run = (o) => {
    const p = boot(o.prefs);
    const el = p.el;
    if (o.drain) el("s-dir-drain").click();
    if (o.transfer) el("s-dir-transfer").click();
    collect(p);
    el("s-tank").value = o.transfer ? "alpha" : "t1"; el("s-D").value = String(2 * o.P.r); el("s-L").value = String(o.P.L);
    if (o.transfer) { el("sB-tank").value = "beta"; el("sB-D").value = String(2 * o.PB.r); el("sB-L").value = String(o.PB.L); }
    el("s-D")._listeners.input[0]({});
    planUi(p, o.groups, o);
    const cap = core.capacity(o.P), capB = o.PB ? core.capacity(o.PB) : 0;
    let V = o.drain || o.transfer ? cap : 0, VB = 100;
    const H0 = core.levelFor(V, o.P), HB0 = o.PB ? core.levelFor(VB, o.PB) : 0;
    el("s-step").value = "?"; el("s-dip").value = String(H0);
    if (o.transfer) { el("sB-step").value = "?"; el("sB-dip").value = String(HB0); }
    tryClick(p, "s-go");
    const dipAll = (H, HB) => {
      for (let k = 0; k < 4; k++) {
        if (el("dip-card")._classes.has("hidden")) break;
        if (o.transfer) {
          if (!el("d-go-a").disabled) { el("d-val").value = String(H); tryClick(p, "d-go-a"); }
          if (!el("d-go-b").disabled) { el("d-val-b").value = String(HB); tryClick(p, "d-go-b"); }
        } else { el("d-val").value = String(H); tryClick(p, "d-go"); }
      }
      if (!el("dip-card")._classes.has("hidden")) tryClick(p, "a-override");
    };
    dipAll(H0, HB0);
    // A fill time: the Now card estimates the time to the end of the plan.
    tabsOf(p)("settings"); el("tm-fill-200").value = "1:30"; tryClick(p, "tm-save"); tabsOf(p)("live");
    sweep(p);
    for (let b = 0; b < 40; b++) {
      if (!el("pour-card")._classes.has("hidden")) {
        for (let k = 0; k < 8 && el("t-bar").style.width !== "100%"; k++) tryClick(p, "t-plus");
        if (b === 2) { tryClick(p, "t-plus"); collect(p); tryClick(p, "t-undo"); }
        collect(p);
      }
      const vol = parseFloat(String(el("t-count").textContent).split("·")[1]) || 0;
      if (!vol) break;
      V += (o.drain || o.transfer ? -1 : 1) * vol; VB += vol;
      if (V <= 0 || V >= cap || (o.PB && VB >= capB)) { el("p-over").checked = !o.drain; el("t-part").checked = !!o.drain; }
      tryClick(p, "p-go");
      el("p-over").checked = false; el("t-part").checked = false;
      dipAll(core.levelFor(Math.min(Math.max(V, 0), cap), o.P), o.PB ? core.levelFor(Math.min(VB, capB), o.PB) : 0);
      if (b % 4 === 3) sweep(p);
      if (V <= 0 || V >= cap || (o.PB && VB >= capB)) break;
    }
    sweep(p);
  };
  // Nominal 10 000 L; the tank holds about 10 600 L (fill) or 9 400 L (drain).
  const groups = [{ count: 2, size: 300 }, { count: 2, size: 600 }, { count: 8, size: 800 }, { count: 2, size: 600 }, { count: 2, size: 300 }];
  for (const prefs of [{}, { mode: "simple" }]) {
    run({ P: { r: 1000, L: 3374, h0: 0 }, groups, nominal: 10000, prefs });
    run({ P: { r: 1000, L: 2992, h0: 0 }, groups, nominal: 10000, drain: true, prefs });
    run({ P: { r: 1000, L: 3374, h0: 0 }, PB: { r: 1000, L: 3183, h0: 0 }, groups, nominal: 10000, nominalB: 10000, transfer: true, prefs });
  }
})();

for (const t of statics) add(t);

// The replay tab reads its file asynchronously: run it, then report.
async function replays() {
  for (const [file, drain] of [["demo_raw.csv", false], ["demo_drain_raw.csv", true]]) {
    for (const prefs of [{}, { mode: "simple" }]) {
      const p = boot(prefs), el = p.el;
      tabsOf(p)("replay");
      el("r-file").files = [];
      tryClick(p, "r-go");                                   // no file yet
      const csv = fs.readFileSync(path.join(ROOT, "examples", file), "utf8");
      el("r-file").files = [{ text: () => Promise.resolve(csv) }];
      tryClick(p, "r-go");                                   // no D and L yet
      el("r-D").value = drain ? "2480" : "1760"; el("r-L").value = drain ? "5280" : "2950"; el("r-unit").value = drain ? "200" : "50";
      el("r-entrance").checked = drain;
      tryClick(p, "r-go");
      await new Promise((r) => setImmediate(r));
      collect(p);
    }
  }
}

replays().then(report);

function report() {
const missing = new Set();
const whole = process.env.I18N_WHOLE ? new Set() : null;
for (const t of texts) {
  if (/^\{"/.test(t)) continue;   // the Shell tab's state counts: data, not text
  for (const m of I18N.report(t, lang)) {
    if (whole && !NAMES.has(m.replace(/:$/, ""))) whole.add(t);
    if (NAMES.has(m.replace(/:$/, ""))) continue;
    if (/^\{"/.test(m)) continue;   // state counts: JSON data, not text
    if (/^[A-Z0-9?!/_.:+\- ]+$/.test(m) && /[A-Z]{3,}/.test(m)) continue;   // status codes: ACCEPT, OBJECT?, …
    missing.add(m);
  }
}
process.stdout.write(JSON.stringify([...(whole || missing)].sort(), null, 1) + "\n");
}

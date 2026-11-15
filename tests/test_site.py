"""On-site live dip check (§10a): the page build and the JavaScript core.

The core runs under Node.  Without Node the core tests skip; the page-build
test still runs.
"""

from __future__ import annotations

import csv
import io
import itertools
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from calib.data import read_raw
from calib.geometry import Shell
from calib.site_page import SITE, build_page, page_is_current

HERE = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
CORE = (SITE / "site_core.js").as_posix()
SIM = (SITE / "simulate.js").as_posix()
DEMO = (HERE / "examples" / "demo_raw.csv").as_posix()


# A synthetic drain campaign (reverse strapping) from a known shell, top-down.
# liquid(H) = F(H) - the solid volume below H; an object fills [a, b] evenly.
DRAIN_JS = r"""
const P = {r: 1240, L: 5200, h0: -30};
const CAP = core.capacity(P), B = core.brim(P);
const SCHED = [100, 100, 200, 200, 400, 400, 600, 600, 1200, 1200, 1200, 1200, 1200, 1200, 1200,
  1200, 600, 600, 400, 400, 200, 200];
function inv(V, obj) {
  if (!obj) return core.levelFor(V, P);
  const liq = (H) => core.volume(H, P) - obj.d * Math.min(Math.max((H - obj.a) / (obj.b - obj.a), 0), 1);
  let lo = P.h0, hi = P.h0 + 2 * P.r;
  for (let i = 0; i < 100; i++) { const mid = 0.5 * (lo + hi); if (liq(mid) < V) lo = mid; else hi = mid; }
  return 0.5 * (lo + hi);
}
/** rows from the neck entrance down; actual[i] overrides the litres that really left at step i. */
function drainRows(obj, actual) {
  const rows = [{step: '?', H: B}];
  let V = CAP - (obj ? obj.d : 0);
  SCHED.forEach((s, i) => {
    V -= actual && actual[i] != null ? actual[i] : s;
    rows.push({step: String(s), H: inv(V, obj)});
  });
  return rows;
}
const DRAIN_CFG = {D: 2400, Dpm: 200, Lest: 5100, direction: 'drain'};
"""


def _node(body: str):
    """Run a script with `core` loaded; it prints one JSON value."""
    script = (
        f"const core = require({json.dumps(CORE)});\n"
        "const fs = require('fs');\n"
        f"{body}\n"
    )
    out = subprocess.run(  # noqa: S603
        [NODE, "-e", script], capture_output=True, text=True, timeout=120, check=False
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class TestSitePage(unittest.TestCase):
    def test_built_page_is_current(self):
        self.assertTrue(
            page_is_current(), "site/calib_site.html is stale: run `calib site-page`"
        )

    def test_page_inlines_the_one_core(self):
        page = build_page()
        core = (SITE / "site_core.js").read_text(encoding="utf-8").rstrip("\n")
        self.assertIn(core, page)
        self.assertNotIn("/*@CORE@*/", page)
        self.assertNotIn("<script src", page, "the page must run offline")

    def test_tally_is_not_hidden(self):
        page = (SITE / "page.html").read_text(encoding="utf-8")
        self.assertNotRegex(
            page,
            r'<div id="tally"[^>]*class="[^"]*hidden',
            "the can tally must show: the size field is the only way to tap a can",
        )

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_tally_shows_and_keeps_the_size(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click();\n"
            "el('d-val').value = '400'; el('d-go').click();\n"
            "out.shown = !el('tally')._classes.has('hidden');\n"
            "out.unit0 = el('t-unit').value;\n"
            "el('t-plus').click();\n"
            "el('t-unit').value = '100';\n"
            "el('t-plus').click();\n"
            "out.count = el('t-count').textContent;\n"
            "out.plus = el('t-plus').textContent;\n"
            "out.width = el('t-bar').style.width;\n"
            "// A reload starts the size field at the last can, not the setup default.\n"
            "const p2 = stub.boot(page, corePath, store);\n"
            "out.reloaded = p2.el('t-unit').value;\n"
            "out.reloadedCount = p2.el('t-count').textContent;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["shown"], "the tally must be visible after the session starts")
        self.assertEqual(got["unit0"], "200", "the setup default fills the size field")
        self.assertEqual(got["count"], "2 cans · 300 L")
        self.assertEqual(got["plus"], "+1 can poured (100 L)")
        self.assertNotIn(got["width"], ("0%", ""), "the progress bar follows the advice")
        self.assertEqual(got["reloaded"], "100", "a reload keeps the last can's size")
        self.assertEqual(got["reloadedCount"], "2 cans · 300 L")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_settings_tab(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "// Before a campaign: the noise card sets the next campaign.\n"
            "out.noSession = {campaign: el('set-campaign')._classes.has('hidden'),"
            " timers: el('timers')._classes.has('hidden'), sr: el('set-sr').value};\n"
            "out.setup = el('s-noise').textContent;\n"
            "el('set-sr').value = '0.7'; el('set-rel').value = '0.4';"
            " el('set-abs').value = '2.5'; el('set-h0').value = '60';\n"
            "el('set-noise-save').click(); out.draftMsg = el('set-noise-msg').textContent;\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.draft = [el('set-sr').value, el('set-rel').value, el('set-abs').value, el('set-h0').value];\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';"
            " el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "out.started = {campaign: el('set-campaign')._classes.has('hidden'),"
            " timers: el('timers')._classes.has('hidden'), tank: el('set-tank').value,"
            " D: el('set-D').value, L: el('set-L').value, Lpm: el('set-Lpm').value, unit: el('set-unit').value};\n"
            "out.cfg0 = JSON.parse(store.get('calib-site:active')).config;\n"
            "// A change of the noise refits and moves the repeat limit, and it does"
            " not throw away an unsaved edit in the campaign card.\n"
            "el('set-tank').value = 'unsaved';\n"
            "el('set-sr').value = '0.6'; el('set-rel').value = '0.3'; el('set-noise-save').click();\n"
            "out.keep = el('set-tank').value;\n"
            "const c1 = JSON.parse(store.get('calib-site:active')).config;\n"
            "out.noise = {sr: c1.sigmaRead, rel: c1.pourRel, tol: c1.repeatTol, msg: el('set-noise-msg').textContent};\n"
            "el('set-sr').value = '0'; el('set-noise-save').click(); out.badNoise = el('set-noise-err').textContent;\n"
            "// The campaign record is editable after the first level.\n"
            "el('set-tank').value = 't2'; el('set-D').value = '1900'; el('set-L').value = '3100';"
            " el('set-unit').value = '100'; el('set-save').click();\n"
            "const c2 = JSON.parse(store.get('calib-site:active')).config;\n"
            "out.campaign = {tank: c2.tank, D: c2.D, L: c2.Lest, Lpm: c2.Lpm,"
            " LpmField: el('set-Lpm').value, unit: c2.pourUnit, msg: el('set-msg').textContent};\n"
            "el('set-D').value = '0'; el('set-save').click(); out.badD = el('set-err').textContent;\n"
            "// A missing fill time sends the operator to the settings tab.\n"
            "el('pt-start').click();\n"
            "out.jump = {settings: !el('settings')._classes.has('hidden'), open: el('timers').open,"
            " err: el('tm-err').textContent, live: el('p-err').textContent};\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["noSession"]["campaign"], "no campaign card before the first level")
        self.assertTrue(got["noSession"]["timers"], "no timers before the first level")
        self.assertEqual(got["noSession"]["sr"], "0.4", "the noise card shows the defaults")
        self.assertIn("Change them in Settings", got["setup"])
        self.assertIn("next campaign", got["draftMsg"])
        self.assertEqual(got["draft"], ["0.7", "0.4", "2.5", "60"], "the draft survives a reload")
        self.assertFalse(got["started"]["campaign"])
        self.assertFalse(got["started"]["timers"])
        self.assertEqual(got["started"]["tank"], "t1")
        self.assertEqual(got["started"]["D"], "1800")
        self.assertEqual(got["started"]["L"], "3000")
        self.assertEqual(got["started"]["Lpm"], "", "the 3 % default shows blank")
        self.assertEqual(got["started"]["unit"], "200")
        self.assertEqual(got["cfg0"]["sigmaRead"], 0.7, "the next campaign uses the saved noise")
        self.assertEqual(got["cfg0"]["pourRel"], 0.004)
        self.assertAlmostEqual(got["cfg0"]["repeatTol"], 2.5 * 2**0.5 * 0.7, places=6)
        self.assertEqual(got["keep"], "unsaved", "saving the noise card keeps an unsaved campaign edit")
        self.assertEqual(got["noise"]["sr"], 0.6)
        self.assertEqual(got["noise"]["rel"], 0.003)
        self.assertAlmostEqual(got["noise"]["tol"], 2.5 * 2**0.5 * 0.6, places=6)
        self.assertIn("noise scale restarts", got["noise"]["msg"])
        self.assertIn("more than 0 mm", got["badNoise"])
        self.assertEqual(got["campaign"]["tank"], "t2")
        self.assertEqual(got["campaign"]["D"], 1900)
        self.assertEqual(got["campaign"]["L"], 3100)
        self.assertAlmostEqual(got["campaign"]["Lpm"], 93, places=6, msg="a blank L ± follows the corrected L")
        self.assertEqual(got["campaign"]["LpmField"], "", "the 3 % default still shows blank")
        self.assertEqual(got["campaign"]["unit"], 100)
        self.assertIn("refitted", got["campaign"]["msg"])
        self.assertIn("must be more than 0 mm", got["badD"])
        self.assertTrue(got["jump"]["settings"], "a missing fill time opens the settings tab")
        self.assertTrue(got["jump"]["open"])
        self.assertIn("Set the fill time", got["jump"]["err"])
        self.assertEqual(got["jump"]["live"], "", "the message is not left on the hidden Live tab")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_now_previews_the_pour_input(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "out.pending = el('now-pred').textContent;\n"
            "el('d-val').value = '400'; el('d-go').click();\n"
            "out.empty = el('now-pred').textContent;\n"
            "// The manual field: a known pour, an unknown pour, an unknown extra.\n"
            "el('p-vol').value = '250'; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "out.manual = el('now-pred').textContent;\n"
            "el('p-unknown').checked = true; el('p-unknown')._listeners.change[0]({target: el('p-unknown')});\n"
            "out.unknown = el('now-pred').textContent;\n"
            "el('p-unknown').checked = false; el('p-unknown')._listeners.change[0]({target: el('p-unknown')});\n"
            "el('p-extra').checked = true; el('p-extra')._listeners.change[0]({target: el('p-extra')});\n"
            "out.extra = el('now-pred').textContent;\n"
            "el('p-extra').checked = false; el('p-extra')._listeners.change[0]({target: el('p-extra')});\n"
            "el('p-over').checked = true; el('p-over')._listeners.change[0]({target: el('p-over')});\n"
            "out.over = el('now-pred').textContent;\n"
            "el('p-over').checked = false; el('p-over')._listeners.change[0]({target: el('p-over')});\n"
            "// A pour larger than the gap: the computed overflow, not the operator's tick.\n"
            "el('p-vol').value = '99999'; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "out.overflow = el('now-pred').textContent;\n"
            "// The can tally follows each tap, and a part can has no prediction.\n"
            "el('p-vol').value = ''; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "el('t-plus').click();\n"
            "out.can = el('now-pred').textContent;\n"
            "el('t-part').checked = true; el('t-part')._listeners.change[0]({target: el('t-part')});\n"
            "out.part = el('now-pred').textContent;\n"
            "el('t-part').checked = false; el('t-part')._listeners.change[0]({target: el('t-part')});\n"
            "el('p-go').click();\n"
            "out.closed = el('now-pred').textContent;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["pending"], "", "the first level has no prediction")
        self.assertEqual(got["empty"], "", "no pour input, no line")
        self.assertTrue(got["manual"].startswith("After this pour (250 L):"), got["manual"])
        self.assertIn("mm ±", got["manual"])
        self.assertIn("(2σ)", got["manual"])
        self.assertIn("mm rise", got["manual"])
        self.assertTrue(
            "one reading may do" in got["manual"]
            or "expect two readings" in got["manual"],
            got["manual"],
        )
        self.assertIn("too wide to judge", got["manual"], "an early wide band must say so")
        self.assertIn("no prediction", got["unknown"])
        self.assertIn("unknown extra", got["extra"])
        self.assertIn("overflow", got["over"])
        self.assertIn("is more than the gap", got["overflow"])
        self.assertTrue(got["can"].startswith("After this pour (200 L):"), got["can"])
        self.assertIn("part can", got["part"])
        self.assertEqual(got["closed"], "", "the line hides while the level waits for its dip")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_now_line_agrees_with_the_check(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "const P = {r: 900, L: 3000, h0: 0};\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click();\n"
            "let V = 400;\n"
            "const dipAt = (v) => { el('d-val').value = String(core.levelFor(v, P)); el('d-go').click(); };\n"
            "dipAt(V);\n"
            "// Five 400 L pours at the true level: the fit and the band settle.\n"
            "for (let i = 0; i < 5; i++) {\n"
            "  el('p-vol').value = '400'; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "  el('p-go').click();\n"
            "  V += 400; dipAt(V); dipAt(V);\n"
            "}\n"
            "// The line for the next pour, then the check's own prediction for it.\n"
            "el('p-vol').value = '250'; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "out.page = el('now-pred').textContent;\n"
            "out.before = store.get('calib-site:active');\n"
            "el('p-go').click();\n"
            "V += 250; dipAt(V); dipAt(V);\n"
            "out.verdict = el('verdict').innerHTML;\n"
            "const S1 = core.Session.fromJSON(JSON.parse(out.before));\n"
            "const g1 = S1.lastGood();\n"
            "const pr = S1.preview(S1.levels[g1].H, 250, S1.levels[g1].n);\n"
            "out.prH = pr.H; out.sd = pr.sd; out.sharpMm = S1.cfg.sharpMm;\n"
            "// The advice and unit buttons drive the same line.\n"
            "el('p-advice').click();\n"
            "out.advice = el('p-vol').value; out.adviceLine = el('now-pred').textContent;\n"
            "el('p-plus').click(); out.plus = el('p-vol').value;\n"
            "el('p-minus').click(); out.minus = el('p-vol').value;\n"
            "console.log(JSON.stringify(out));"
        )
        page_level = got["page"].split("): ")[1].split(" mm")[0]
        self.assertIn(
            f"predicted {page_level} ±",
            got["verdict"],
            "the check must predict the level the line showed",
        )
        self.assertAlmostEqual(
            float(page_level), got["prH"], delta=1.0, msg="the line must start from the last good level"
        )
        sharp = 2 * got["sd"] <= got["sharpMm"]
        self.assertTrue(sharp, "the settled band should be sharp in this fixture")
        self.assertEqual(
            "sharp: one reading may do" in got["page"], sharp, got["page"]
        )
        self.assertTrue(
            got["adviceLine"].startswith(f"After this pour ({got['advice']} L):"),
            got["adviceLine"],
        )
        self.assertEqual(got["plus"], str(int(got["advice"]) + 200))
        self.assertEqual(got["minus"], got["advice"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_pour_and_settle_timers(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "out.etaBefore = el('now-eta').innerHTML;\n"
            "el('pt-start').click(); out.noTime = el('tm-err').textContent; out.opened = el('timers').open;"
            " out.liveErr = el('p-err').textContent;\n"
            "el('tm-settle').value = '4:30'; el('tm-dip').value = '0.5'; el('tm-fill-200').value = '1:30';\n"
            "el('tm-lead').value = '15';\n"
            "el('tm-save').click();\n"
            "out.msg = el('tm-msg').textContent; out.err = el('tm-err').textContent;\n"
            "out.cfg = JSON.parse(store.get('calib-site:active')).config;\n"
            "out.cfgKeys = Object.keys(out.cfg).filter((k) => /Seconds|Lead/.test(k)).sort();\n"
            "out.eta = el('now-eta').innerHTML;\n"
            "el('pt-start').click();\n"
            "const tm = JSON.parse(store.get('calib-site:timer'));\n"
            "out.timer = {dur: tm.pour.dur, size: tm.pour.size, lead: tm.pour.lead, pre: tm.pour.preAlarmed, full: tm.pour.fullAlarmed};\n"
            "out.running = {cls: el('pt').className, start: el('pt-start')._classes.has('hidden'),"
            " stop: el('pt-stop')._classes.has('hidden'), clock: el('pt-clock').textContent};\n"
            "el('pt-more').click(); out.more = JSON.parse(store.get('calib-site:timer')).pour.dur;\n"
            "// The drawing: the hose fills the can, the stream runs while the pump is on.\n"
            "const tm2 = JSON.parse(store.get('calib-site:timer')); tm2.pour.start = Date.now() - 30000;"
            " store.set('calib-site:timer', JSON.stringify(tm2));\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.anim = {stream: el('pt-stream').opacity, can: +el('pt-can').height,"
            " y: +el('pt-can').y, clock: el('pt-clock').textContent, cls: el('pt').className};\n"
            "// 15 s before the end the pre-alarm rings: close the valve.\n"
            "const tm4 = JSON.parse(store.get('calib-site:timer')); tm4.pour.start = Date.now() - 96000;"
            " store.set('calib-site:timer', JSON.stringify(tm4));\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.pre = {cls: el('pt').className, status: el('pt-status').textContent,"
            " alarm: el('alarm-text').textContent, shown: !el('alarm')._classes.has('hidden'),"
            " stream: el('pt-stream').opacity, flagged: JSON.parse(store.get('calib-site:timer')).pour.preAlarmed};\n"
            "// The animation is a setting: off hides the drawing, the timer still runs.\n"
            "el('tm-anim').checked = false; el('tm-save').click();\n"
            "out.animOff = {hidden: el('pt-anim')._classes.has('hidden'), stream: el('pt-stream').opacity,"
            " can: el('pt-can').height, clock: el('pt-clock').textContent, cls: el('pt').className};\n"
            "el('tm-anim').checked = true; el('tm-save').click();\n"
            "out.animOn = el('pt-anim')._classes.has('hidden');\n"
            "// The pour ran out while the page was closed: a reload shows it and rings.\n"
            "tm.pour.start = Date.now() - 200000; tm.pour.dur = 90; store.set('calib-site:timer', JSON.stringify(tm));\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.done = {cls: el('pt').className, status: el('pt-status').textContent,"
            " alarm: !el('alarm')._classes.has('hidden'), text: el('alarm-text').textContent,"
            " pulse: el('t-plus')._classes.has('pulse')};\n"
            "out.alarmedSaved = JSON.parse(store.get('calib-site:timer')).pour.fullAlarmed;\n"
            "// A second reload does not ring again.\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.again = el('alarm-text').textContent;\n"
            "// Counting the can ends the timer.\n"
            "el('t-plus').click();\n"
            "out.afterCount = {pour: JSON.parse(store.get('calib-site:timer')).pour || null,"
            " cls: el('pt').className, alarm: !el('alarm')._classes.has('hidden'), count: el('t-count').textContent};\n"
            "// Batch done: the settle timer runs, then rings once.\n"
            "el('p-go').click();\n"
            "out.settling = el('dip-settle').textContent;\n"
            "const s = JSON.parse(store.get('calib-site:active'));\n"
            "s.levels[s.levels.length - 1].pourTime = Date.now() - 300000; store.set('calib-site:active', JSON.stringify(s));\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.settled = {text: el('dip-settle').textContent, alarm: el('alarm-text').textContent,"
            " shown: !el('alarm')._classes.has('hidden')};\n"
            "el('alarm-stop').click(); out.stopped = el('alarm')._classes.has('hidden');\n"
            "el('tm-settle').value = 'abc'; el('tm-save').click(); out.bad = el('tm-err').textContent;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIn("Set the fill time for 200 L", got["etaBefore"])
        self.assertIn("Set the fill time for 200 L", got["noTime"])
        self.assertEqual(got["liveErr"], "", "the message is not left on the hidden Live tab")
        self.assertTrue(got["opened"], "a missing fill time opens the timer settings")
        self.assertEqual(got["err"], "")
        self.assertIn("below the 5-minute minimum", got["msg"])
        self.assertEqual(got["cfg"]["settleSeconds"], 270)
        self.assertEqual(got["cfg"]["dipSeconds"], 30, "a plain number is minutes")
        self.assertEqual(got["cfg"]["fillSeconds"], {"200": 90})
        self.assertEqual(got["cfg"]["alarmLead"], 15)
        self.assertNotIn("pourSeconds", got["cfg"], "the old key is gone")
        self.assertEqual(got["cfgKeys"], ["alarmLead", "dipSeconds", "fillSeconds", "settleSeconds"])
        self.assertIn("To half", got["eta"])
        self.assertIn("To brim", got["eta"])
        self.assertIn("× 200 L", got["eta"])
        self.assertEqual(got["timer"], {"dur": 90, "size": 200, "lead": 15, "pre": False, "full": False})
        self.assertEqual(got["running"]["cls"], "timer run")
        self.assertTrue(got["running"]["start"], "the start button hides while the timer runs")
        self.assertFalse(got["running"]["stop"])
        self.assertIn(got["running"]["clock"], ("1:30", "1:29"))
        self.assertEqual(got["more"], 110, "the step is 20 s: 90 + 20")
        self.assertEqual(got["anim"]["stream"], "1", "the stream shows while the pump is on")
        self.assertAlmostEqual(got["anim"]["can"], 44 * (30 / 110), delta=0.3)
        self.assertAlmostEqual(got["anim"]["y"], 74 - 44 * (30 / 110), delta=0.3)
        self.assertIn(got["anim"]["clock"], ("1:20", "1:19"))
        self.assertEqual(got["anim"]["cls"], "timer run")
        self.assertEqual(got["pre"]["cls"], "timer pre", "the last 15 s is the pre-alarm")
        self.assertIn("to full: close the valve now", got["pre"]["status"])
        self.assertIn("Close the valve", got["pre"]["alarm"])
        self.assertTrue(got["pre"]["shown"])
        self.assertEqual(got["pre"]["stream"], "1", "the pump is still on at the pre-alarm")
        self.assertTrue(got["pre"]["flagged"], "one pre-alarm per pour")
        self.assertTrue(got["animOff"]["hidden"], "the animation setting hides the drawing")
        self.assertEqual(got["animOff"]["stream"], "0", "no frame is drawn with the animation off")
        self.assertEqual(got["animOff"]["can"], "0")
        self.assertRegex(got["animOff"]["clock"], r"^0:1[0-5]$", "the clock keeps running")
        self.assertEqual(got["animOff"]["cls"], "timer pre")
        self.assertFalse(got["animOn"], "the drawing comes back")
        self.assertEqual(got["done"]["cls"], "timer done")
        self.assertIn("Can full", got["done"]["status"])
        self.assertTrue(got["done"]["alarm"])
        self.assertIn("Can full: pump off (200 L)", got["done"]["text"])
        self.assertTrue(got["done"]["pulse"], "the count button asks for the tap")
        self.assertTrue(got["alarmedSaved"])
        self.assertEqual(got["again"], "", "one alarm per timer: a second reload does not ring")
        self.assertIsNone(got["afterCount"]["pour"])
        self.assertEqual(got["afterCount"]["cls"], "timer")
        self.assertFalse(got["afterCount"]["alarm"])
        self.assertEqual(got["afterCount"]["count"], "1 can · 200 L")
        self.assertRegex(got["settling"], r"Settling: 4:[23]\d left of 4:30")
        self.assertIn("Dip now", got["settled"]["text"])
        self.assertEqual(got["settled"]["alarm"], "Settled: dip now")
        self.assertTrue(got["settled"]["shown"])
        self.assertTrue(got["stopped"])
        self.assertIn("Cannot read the time", got["bad"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_edits_a_level_note(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "el('p-note').value = 'slow pump'; el('p-vol').value = '400'; el('p-go').click();\n"
            "el('d-val').value = '800'; el('d-go').click();\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "out.table = el('log-table').innerHTML;\n"
            "const click = (sel, data) => el('log-table')._listeners.click[0]("
            "{ target: { closest: (s) => (s === sel ? { dataset: data } : null) } });\n"
            "const key = (k) => el('log-table')._listeners.keydown[0]("
            "{ target: { id: 'note-edit' }, key: k, preventDefault() {} });\n"
            "const note = (i) => JSON.parse(store.get('calib-site:active')).levels[i].note;\n"
            "click('button[data-note-edit]', { noteEdit: '2' });\n"
            "out.open = el('log-table').innerHTML;\n"
            "el('note-edit').value = 'pump was slow';\n"
            "click('button[data-note-save]', { noteSave: '2' });\n"
            "out.saved = note(1);\n"
            "out.closed = el('log-table').innerHTML;\n"
            "// Cancel keeps the old note.\n"
            "click('button[data-note-edit]', { noteEdit: '2' });\n"
            "el('note-edit').value = 'throw this away';\n"
            "click('button[data-note-cancel]', { noteCancel: '2' });\n"
            "out.cancelled = note(1);\n"
            "out.cancelClosed = el('log-table').innerHTML;\n"
            "// Escape keeps it too.\n"
            "click('button[data-note-edit]', { noteEdit: '2' });\n"
            "el('note-edit').value = 'also thrown away';\n"
            "key('Escape');\n"
            "out.escaped = note(1);\n"
            "// Enter saves.\n"
            "click('button[data-note-edit]', { noteEdit: '2' });\n"
            "el('note-edit').value = 'saved by Enter';\n"
            "key('Enter');\n"
            "out.entered = note(1);\n"
            "// Enter during an input method composition does nothing.\n"
            "click('button[data-note-edit]', { noteEdit: '2' });\n"
            "el('note-edit').value = 'still typing';\n"
            "el('log-table')._listeners.keydown[0]({ target: { id: 'note-edit' }, key: 'Enter', isComposing: true });\n"
            "out.composing = note(1);\n"
            "key('Escape');\n"
            "// A second Edit closes the first editor.\n"
            "click('button[data-note-edit]', { noteEdit: '2' });\n"
            "click('button[data-note-edit]', { noteEdit: '1' });\n"
            "out.one = (el('log-table').innerHTML.match(/id=\"note-edit\"/g) || []).length;\n"
            "// Quotes and tags survive the round trip.\n"
            "el('note-edit').value = 'say \"hi\" <b>';\n"
            "click('button[data-note-save]', { noteSave: '1' });\n"
            "out.kept = note(0);\n"
            "out.escapedHtml = el('log-table').innerHTML;\n"
            "click('button[data-note-edit]', { noteEdit: '1' });\n"
            "out.reopen = el('log-table').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIn('data-note-edit="1"', got["table"], "every level has an edit button")
        self.assertIn('data-note-edit="2"', got["table"])
        self.assertIn('id="note-edit"', got["open"])
        self.assertIn('value="slow pump"', got["open"])
        self.assertEqual(got["saved"], "pump was slow")
        self.assertNotIn('id="note-edit"', got["closed"], "Save closes the editor")
        self.assertIn("pump was slow", got["closed"])
        self.assertEqual(got["cancelled"], "pump was slow", "Cancel keeps the note")
        self.assertNotIn('id="note-edit"', got["cancelClosed"], "Cancel closes the editor")
        self.assertEqual(got["escaped"], "pump was slow", "Escape keeps the note")
        self.assertEqual(got["entered"], "saved by Enter", "Enter saves")
        self.assertEqual(got["composing"], "saved by Enter", "Enter during a composition does not save")
        self.assertEqual(got["one"], 1, "one editor at a time")
        self.assertEqual(got["kept"], 'say "hi" <b>', "the note is stored as typed")
        self.assertIn("&quot;hi&quot; &lt;b&gt;", got["escapedHtml"], "the cell escapes the note")
        self.assertIn('value="say &quot;hi&quot; &lt;b&gt;"', got["reopen"], "the editor escapes the note")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_drain_wording(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "out.atHiddenFill = el('s-at-wrap')._classes.has('hidden');\n"
            "el('s-step').value = '400';\n"
            "el('s-dir-drain').click();\n"
            "out.atShown = !el('s-at-wrap')._classes.has('hidden');\n"
            "out.step = el('s-step').value; out.pressed = el('s-dir-drain')['aria-pressed'];\n"
            "out.atPressed = el('s-at-entrance')['aria-pressed'];\n"
            "out.stepLabel = el('s-step-label').textContent; out.firstNote = el('s-first-note').textContent;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '1800'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '1800'; el('d-go').click();\n"
            "const cfg = JSON.parse(store.get('calib-site:active')).config;\n"
            "out.cfg = {direction: cfg.direction, brimStart: cfg.brimStart, brimPm: cfg.brimPm};\n"
            "out.csv1 = JSON.parse(store.get('calib-site:active')).levels[0].tags;\n"
            "out.plus = el('t-plus').textContent; out.go = el('p-go').textContent;\n"
            "out.title = el('pour-title').textContent; out.over = el('p-over-text').textContent;\n"
            "out.part = el('t-part-text').textContent; out.help = el('t-help').innerHTML;\n"
            "out.phase = el('hdr-phase').textContent; out.kv = el('now-kv').innerHTML;\n"
            "out.advice = el('now-advice').textContent;\n"
            "el('p-vol').value = '400'; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "out.pred = el('now-pred').textContent;\n"
            "el('p-vol').value = '99999'; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "out.dry = el('now-pred').textContent;\n"
            "el('p-vol').value = '400'; el('p-over').checked = true; el('p-over')._listeners.change[0]({target: el('p-over')});\n"
            "out.neckLine = el('now-pred').textContent;\n"
            "el('p-over').checked = false; el('p-vol').value = '';\n"
            "el('t-plus').click(); out.batch = el('p-go').textContent; out.tally = el('t-target').textContent;\n"
            "el('p-go').click(); out.dip = el('dip-label').textContent;\n"
            "el('d-val').value = '1700'; el('d-go').click();\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'settings' } }) } });\n"
            "out.dir = el('set-dir').textContent; out.brim = el('set-brim').value;\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "out.table = el('log-table').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["atHiddenFill"], "a fill has no start-level choice")
        self.assertTrue(got["atShown"], "a drain asks where the first level stands")
        self.assertEqual(got["step"], "?", "a drain starts with an unknown volume")
        self.assertEqual(got["pressed"], "true")
        self.assertEqual(got["atPressed"], "true", "the neck entrance is the default")
        self.assertIn("in the tank", got["stepLabel"])
        self.assertIn("Prime the pump", got["firstNote"])
        self.assertEqual(got["cfg"], {"direction": "drain", "brimStart": 1800, "brimPm": 6})
        self.assertEqual(got["csv1"], ["at neck entrance"])
        self.assertEqual(got["plus"], "+1 can full (200 L)")
        self.assertEqual(got["go"], "Drained")
        self.assertEqual(got["title"], "1 · Drain")
        self.assertEqual(got["over"], "level still in the neck")
        self.assertEqual(got["part"], "pump lost suction: last can part")
        self.assertIn("from the tank", got["help"])
        self.assertIn("drain", got["phase"])
        self.assertIn("L left", got["kv"])
        self.assertIn("Next drain", got["advice"])
        self.assertNotIn("halve", got["advice"])
        self.assertTrue(got["pred"].startswith("After this drain (400 L):"), got["pred"])
        self.assertIn("mm fall", got["pred"])
        self.assertIn("−", got["pred"].split("(2σ)")[1], "the fall is negative")
        self.assertIn("L left", got["pred"])
        self.assertIn("runs dry", got["dry"])
        self.assertIn("still in the neck", got["neckLine"])
        self.assertEqual(got["batch"], "Drained: 1 can, 200 L → dip")
        self.assertIn("mm fall", got["tally"])
        self.assertIn("draining 200 L", got["dip"])
        self.assertIn("drain", got["dir"])
        self.assertIn("neck entrance", got["dir"])
        self.assertEqual(got["brim"], "6")
        self.assertIn("drained L", got["table"])


# A synthetic transfer campaign (§3.12): two known shells, one shared batch.
# Tank A (drain) starts full at the neck entrance; tank B (fill) starts with
# 2000 L.  batches: [{s, aOut?, aIn?}] — s is the recorded batch, aOut the
# litres that really left A, aIn the litres that really reached B (each
# defaults to the previous one, so {s: 600} is an honest batch).
TRANSFER_JS = r"""
const PA = {r: 900, L: 3000, h0: 0};   // tank A truth: capacity 7634 L
const PB = {r: 1240, L: 5200, h0: 0};  // tank B truth: capacity 25273 L
const CAPA = core.capacity(PA);
function runTransfer(batches) {
  const X = new core.TransferSession(
    {D: 1800, Dpm: 200, Lest: 3000, tank: 'alpha', pourUnit: 200},
    {D: 2480, Dpm: 200, Lest: 5200, tank: 'beta', pourUnit: 200});
  let VA = CAPA, VB = 2000, t = 0;
  X.start('?', core.brim(PA), '?', core.levelFor(VB, PB), '', null, {at: 'entrance'});
  X.dip(core.brim(PA)); X.dip(core.levelFor(VB, PB));
  const dipTank = (k, H) => {
    X.dip(H);
    let n = 1;
    while (X.pendingTank() === k && n < 4) { X.dip(H); n++; }
  };
  for (const b of batches) {
    const aOut = b.aOut == null ? b.s : b.aOut, aIn = b.aIn == null ? aOut : b.aIn;
    VA -= aOut; VB += aIn;
    for (let k = 0; k < b.s / 200; k++) X.tap(++t, 200);
    X.closeBatch({note: b.note || ''});
    dipTank('out', core.levelFor(VA, PA));
    dipTank('in', core.levelFor(VB, PB));
    if (X.pendingTank()) throw new Error('still pending after a batch');
  }
  return X;
}
"""


@unittest.skipUnless(NODE, "node is not installed")
class TestSiteTransfer(unittest.TestCase):
    def test_transfer_session_flow(self):
        got = _node(
            TRANSFER_JS
            + """
const clean = Array.from({length: 5}, () => ({s: 600}));
const X = runTransfer(clean);
const out = {};
out.dirs = [X.out.cfg.direction, X.in.cfg.direction, X.out.cfg.dir, X.in.cfg.dir];
out.start = [X.out.levels[0].state, X.in.levels[0].state, X.out.cfg.brimStart, X.in.cfg.brimStart];
out.rows = [X.out.levels.length, X.in.levels.length];
out.csvA = X.out.toRawCsv();
out.csvB = X.in.toRawCsv();
out.pairClean = X.pair;
// A dip with both tanks decided waits for the next batch.
out.decided = null;
try { X.dip(1000); } catch (e) { out.decided = e.message; }
// A tap while a level waits for its dip is refused.
X.tap(1, 200); X.tap(2, 200); X.tap(3, 200);
X.closeBatch({});
out.openTap = null;
X.dip(core.levelFor(CAPA - 3600 - 600, PA));
try { X.tap(4, 200); } catch (e) { out.openTap = e.message; }
// Undo takes back the reading, then the whole batch from both tanks.
X.undo();
out.afterUndo = [X.out.current().state, X.in.current().state, X.out.current().dips.length];
X.undo();
out.batchGone = [X.out.levels.length, X.in.levels.length];
out.reopened = [X.cans(), X.batchVolume()];
// One recount edits the batch on both tanks.
const Lo = X.closeBatch({});
X.editPour('800');
out.edited = [X.out.current().step.text, X.in.current().step.text,
  X.out.current().tags.indexOf('pour edited on site') >= 0,
  X.in.current().tags.indexOf('pour edited on site') >= 0];
// The tank record follows the active tank; the noise is one set for both.
X.setCampaign({D: 1900});
out.geo = [X.out.cfg.D, X.in.cfg.D];
X.active = 'in';
X.setCampaign({D: 2100});
out.geoB = [X.out.cfg.D, X.in.cfg.D];
X.setCampaign({sigmaRead: 0.5});
out.noise = [X.out.cfg.sigmaRead, X.in.cfg.sigmaRead];
out.dirErr = null;
try { X.setCampaign({direction: 'fill'}); } catch (e) { out.dirErr = e.message; }
// The JSON round trip keeps both raw files, the edit included.
const Y = core.TransferSession.fromJSON(JSON.parse(JSON.stringify(X.toJSON())));
out.roundTrip = [Y.out.toRawCsv() === X.out.toRawCsv(), Y.in.toRawCsv() === X.in.toRawCsv(), Y.active];
out.advice = X.adviceBatch().text;
// A failed settings save changes nothing on either tank.
out.atomicErr = null;
try { X.setCampaign({D: -1, sigmaRead: 0.7}); } catch (e) { out.atomicErr = e.message; }
out.atomic = [X.out.cfg.sigmaRead, X.in.cfg.sigmaRead, X.out.cfg.D, X.in.cfg.D];
// The first undo takes back B's reading: B was dipped last.
const Z = new core.TransferSession(
  {D: 1800, Dpm: 200, Lest: 3000, tank: 'alpha', pourUnit: 200},
  {D: 2480, Dpm: 200, Lest: 5200, tank: 'beta', pourUnit: 200});
Z.start('?', 1800, '?', 400, '', null, {at: 'entrance'});
Z.dip(1800); Z.dip(400);
Z.undo();
out.undoStart = [Z.out.current().dips.length, Z.in.current().dips.length, Z.pendingTank()];
console.log(JSON.stringify(out));
"""
        )
        self.assertEqual(got["dirs"], ["drain", "fill", -1, 1])
        self.assertEqual(got["start"], ["start", "start", 1800.0, None])
        self.assertEqual(got["rows"], [6, 6], "one level per tank per batch")
        self.assertIn("drain campaign", got["csvA"])
        self.assertIn("at neck entrance", got["csvA"])
        self.assertNotIn("drain campaign", got["csvB"])
        self.assertIsNone(got["pairClean"], "an honest batch has no pair verdict")
        self.assertIn("pour the next batch", got["decided"])
        self.assertIsNotNone(got["openTap"], "no tap while a level waits for its dip")
        self.assertEqual(got["afterUndo"], ["pending", "pending", 0], "undo takes back the reading")
        self.assertEqual(got["batchGone"], [6, 6], "undo removes the batch from both tanks")
        self.assertEqual(got["reopened"], [3, 600], "the batch reopens with its cans")
        self.assertEqual(got["edited"], ["800", "800", True, True])
        self.assertEqual(got["geo"], [1900, 2480], "the tank record follows the active tank")
        self.assertEqual(got["geoB"], [1900, 2100])
        self.assertEqual(got["noise"], [0.5, 0.5], "the noise is one set for both")
        self.assertIn("fixed at the start", got["dirErr"])
        self.assertEqual(got["roundTrip"], [True, True, "in"], "the round trip keeps both raw files")
        self.assertIn("Next batch", got["advice"])
        self.assertIn("must be more than 0", got["atomicErr"])
        self.assertEqual(got["atomic"], [0.5, 0.5, 1900.0, 2100.0],
                         "a failed settings save changes nothing on either tank")
        self.assertEqual(got["undoStart"], [2, 1, "in"], "the first undo takes back B's reading")

    def test_transfer_pair_decomposes_the_causes(self):
        got = _node(
            TRANSFER_JS
            + r"""
const clean = Array.from({length: 5}, () => ({s: 600}));
const out = {};
out.clean = runTransfer(clean).pair;
// One can pumped but not tapped: both tanks see the same wrong litres.
const C = runTransfer([...clean, {s: 600, aOut: 800, aIn: 800}]);
out.cans = {status: C.pair.status, ro: C.pair.ro, ri: C.pair.ri, diff: C.pair.diff,
  states: [C.out.current().state, C.in.current().state],
  tagA: C.out.current().tags, csv: C.in.toRawCsv()};
// A spill on the carry: A gave what the record says, B received less.
const S = runTransfer([...clean, {s: 600, aIn: 500}]);
out.spill = {status: S.pair.status, diff: S.pair.diff,
  states: [S.out.current().state, S.in.current().state]};
// An object in B: B's rise comes too cheap, A is clean.
const O = runTransfer([...clean, {s: 600, aIn: 700}]);
out.object = {status: O.pair.status, diff: O.pair.diff};
// A leak at A's hose: more left A than the record says, B received the record.
const L = runTransfer([...clean, {s: 600, aOut: 800, aIn: 600}]);
out.leak = {status: L.pair.status, diff: L.pair.diff,
  states: [L.out.current().state, L.in.current().state]};
console.log(JSON.stringify(out));
"""
        )
        self.assertIsNone(got["clean"])
        self.assertEqual(got["cans"]["status"], "POUR")
        for k in ("ro", "ri"):
            self.assertAlmostEqual(got["cans"][k], -200.0, delta=1.0, msg=k)
        self.assertLess(abs(got["cans"]["diff"]), 2.0, "a shared pour error shows the same litres")
        self.assertEqual(got["cans"]["states"], ["anomaly", "anomaly"])
        self.assertIn("transfer: shared pour error", got["cans"]["tagA"])
        self.assertIn("transfer: shared pour error", got["cans"]["csv"], "the raw file keeps the pair finding")
        self.assertEqual(got["spill"]["status"], "LOSS")
        self.assertAlmostEqual(got["spill"]["diff"], 100.0, delta=1.0)
        self.assertEqual(got["spill"]["states"], ["accepted", "anomaly"], "A's interval is good")
        self.assertEqual(got["object"]["status"], "BOBJECT")
        self.assertAlmostEqual(got["object"]["diff"], -100.0, delta=1.0)
        self.assertEqual(got["leak"]["status"], "ALEAK")
        self.assertAlmostEqual(got["leak"]["diff"], 200.0, delta=1.0)
        self.assertEqual(got["leak"]["states"], ["anomaly", "accepted"], "B's interval is good")

    def test_transfer_pair_leaves_with_the_level(self):
        got = _node(
            TRANSFER_JS
            + r"""
const clean = Array.from({length: 5}, () => ({s: 600}));
const out = {};
// A shared pour error, then a recount to an unknown volume: the pair and
// its tags leave with the residual they judged.
const C = runTransfer([...clean, {s: 600, aOut: 800, aIn: 800}]);
out.before = {status: C.pair.status, states: [C.out.current().state, C.in.current().state]};
C.editPour('?');
out.recount = {pair: C.pair, states: [C.out.current().state, C.in.current().state],
  csvA: C.out.toRawCsv(), csvB: C.in.toRawCsv()};
// An override is an operator decision, not a prediction test: the pair
// leaves with it too.
const S = runTransfer([...clean, {s: 600, aIn: 500}]);
out.spill = S.pair.status;
S.active = 'in';
S.override('accepted after inspection');
out.override = {pair: S.pair, state: S.in.current().state, csvB: S.in.toRawCsv()};
console.log(JSON.stringify(out));
"""
        )
        self.assertEqual(got["before"]["status"], "POUR")
        self.assertEqual(got["before"]["states"], ["anomaly", "anomaly"])
        self.assertIsNone(got["recount"]["pair"], "an unknown pour has no comparable residual")
        self.assertEqual(got["recount"]["states"], ["unknown", "unknown"])
        self.assertNotIn("transfer:", got["recount"]["csvA"], "the finding leaves both raw files")
        self.assertNotIn("transfer:", got["recount"]["csvB"], "the finding leaves both raw files")
        self.assertEqual(got["spill"], "LOSS")
        self.assertIsNone(got["override"]["pair"], "an override is not a prediction test")
        self.assertEqual(got["override"]["state"], "override")
        self.assertNotIn("transfer:", got["override"]["csvB"])

    def test_transfer_pair_unsure_with_a_wide_clean_side(self):
        got = _node(
            r"""
const PA = {r: 900, L: 3000, h0: 0}, PB = {r: 1240, L: 5200, h0: 0};
const CAPA = core.capacity(PA);
// Tank B's record is weak (wide priors) and the last batch rises far above
// the levels B has seen, so B's check is wide: an honest B can confirm
// nothing.  Tank A is sharp and at its action bar: 200 L left it off the
// record.  One cause fits both readings, so the pair says UNSURE.
const X = new core.TransferSession(
  {D: 1800, Dpm: 200, Lest: 3000, Lpm: 90, tank: 'alpha', pourUnit: 200},
  {D: 2480, Dpm: 2500, Lest: 5200, Lpm: 4000, tank: 'beta', pourUnit: 200});
let VA = CAPA, VB = 2000, t = 0;
X.start('?', core.brim(PA), '?', core.levelFor(VB, PB), '', null, {at: 'entrance'});
X.dip(core.brim(PA)); X.dip(core.levelFor(VB, PB));
const dipTank = (k, H) => {
  X.dip(H);
  let n = 1;
  while (X.pendingTank() === k && n < 4) { X.dip(H); n++; }
};
for (let i = 0; i < 3; i++) {
  VA -= 600; VB += 600;
  for (let k = 0; k < 3; k++) X.tap(++t, 200);
  X.closeBatch({});
  dipTank('out', core.levelFor(VA, PA));
  dipTank('in', core.levelFor(VB, PB));
}
VA -= 4200; VB += 4000;   // 200 L left A off the record; B got what the count says
for (let k = 0; k < 20; k++) X.tap(++t, 200);
X.closeBatch({});
dipTank('out', core.levelFor(VA, PA));
dipTank('in', core.levelFor(VB, PB));
const out = {};
const Lo = X.out.current(), Li = X.in.current();
out.sides = [Lo.state, Li.state, Li.check.sharp, +Li.check.mm.toFixed(2)];
out.pair = {status: X.pair.status, title: X.pair.title, tagA: Lo.tags,
  z: +X.pair.z.toFixed(2), diff: +X.pair.diff.toFixed(1)};
out.csv = X.in.toRawCsv();
console.log(JSON.stringify(out));
"""
        )
        self.assertEqual(got["sides"], ["anomaly", "accepted", False, 0.0],
                         "A at the bar, B honest behind a wide band")
        self.assertEqual(got["pair"]["status"], "UNSURE")
        self.assertEqual(got["pair"]["title"], "only tank A shows it")
        self.assertIn("transfer: A-side only", got["pair"]["tagA"])
        self.assertLess(abs(got["pair"]["z"]), 2.0, "the difference is inside the two checks' noise")
        self.assertAlmostEqual(got["pair"]["diff"], 200.0, delta=2.0)
        self.assertIn("transfer: A-side only", got["csv"], "the finding goes into both raw files")

    def test_page_transfer(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-dir-transfer').click();\n"
            "out.setup = {b: !el('s-b-wrap')._classes.has('hidden'),"
            " at: !el('s-at-wrap')._classes.has('hidden'),"
            " note: el('s-dir-note').textContent, a: el('s-tank-label').textContent,"
            " dip: el('s-dip-label').textContent, first: el('s-first-note').textContent};\n"
            "el('s-tank').value = 'alpha'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('sB-tank').value = 'beta'; el('sB-D').value = '2480'; el('sB-L').value = '5200';\n"
            "el('s-dip').value = '1800'; el('sB-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click();\n"
            "out.hdr = {title: el('hdr-title').textContent, phase: el('hdr-phase').textContent,"
            " seg: !el('hdr-tank')._classes.has('hidden'), a: el('hdr-tank-a').textContent,"
            " b: el('hdr-tank-b').textContent};\n"
            "out.dipA = el('dip-title').textContent + ' | ' + el('dip-label').textContent;\n"
            "el('d-val').value = '1800'; el('d-go').click();\n"
            "el('d-val').value = '1800'; el('d-go').click();\n"
            "out.dipB = el('dip-title').textContent + ' | ' + el('dip-label').textContent;\n"
            "el('d-val').value = '400'; el('d-go').click();\n"
            "el('d-val').value = '400'; el('d-go').click();\n"
            "out.card = {title: el('pour-title').textContent, plus: el('t-plus').textContent,"
            " neck: !el('p-neck-wrap')._classes.has('hidden'), over: el('p-over-text').textContent,"
            " neckText: el('p-neck-text').textContent, advice: el('now-advice').textContent};\n"
            "el('t-plus').click(); el('t-plus').click(); el('t-plus').click();\n"
            "out.go = el('p-go').textContent;\n"
            "el('p-go').click();\n"
            "out.dip1 = el('dip-label').textContent;\n"
            "el('d-val').value = '1700'; el('d-go').click();\n"
            "el('d-val').value = '1700'; el('d-go').click();\n"
            "out.dip2 = el('dip-label').textContent;\n"
            "el('d-val').value = '500'; el('d-go').click();\n"
            "el('d-val').value = '500'; el('d-go').click();\n"
            "out.verdict = el('verdict').innerHTML;\n"
            "const cfg = JSON.parse(store.get('calib-site:active'));\n"
            "out.saved = {kind: cfg.kind, levels: [cfg.out.levels.length, cfg.in.levels.length],"
            " pour: [cfg.out.levels[1].pourTime != null, cfg.in.levels[1].pourTime != null]};\n"
            "// Files: one raw file per tank.\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'files' } }) } });\n"
            "out.files = {a: el('f-csv').textContent, b: !el('f-csv-b')._classes.has('hidden')};\n"
            "// The header switch turns the log, the shell and the settings to tank B.\n"
            "el('hdr-tank')._listeners.click[0]({ target: { closest: () => ({ dataset: { tank: 'in' } }) } });\n"
            "// The A button still exports tank A's file with B active.\n"
            "el('f-csv').click(); el('f-csv-b').click();\n"
            "out.export = {a: p.downloads[p.downloads.length - 2].download,"
            " b: p.downloads[p.downloads.length - 1].download,"
            " label: el('f-csv').textContent, show: el('f-show').textContent};\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "out.log = el('log-table').innerHTML;\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'shell' } }) } });\n"
            "out.shell = el('shell-kv').innerHTML;\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'settings' } }) } });\n"
            "out.settings = {title: el('set-campaign-title').textContent, dir: el('set-dir').textContent};\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["setup"]["b"], "tank B's fields show")
        self.assertTrue(got["setup"]["at"], "tank A is a drain: the start-level choice shows")
        self.assertIn("Two tanks, one water", got["setup"]["note"])
        self.assertIn("Tank A name", got["setup"]["a"])
        self.assertEqual(got["setup"]["dip"], "Tank A first reading, mm")
        self.assertIn("Prime the pump", got["setup"]["first"])
        self.assertEqual(got["hdr"]["title"], "alpha → beta — transfer")
        self.assertIn("transfer", got["hdr"]["phase"])
        self.assertTrue(got["hdr"]["seg"])
        self.assertEqual(got["hdr"]["a"], "alpha")
        self.assertEqual(got["hdr"]["b"], "beta")
        self.assertIn("alpha", got["dipA"])
        self.assertIn("beta", got["dipB"], "the dip goes to B once A is decided")
        self.assertEqual(got["card"]["title"], "1 · Pump out")
        self.assertEqual(got["card"]["plus"], "+1 can full (200 L)")
        self.assertTrue(got["card"]["neck"], "the neck tick shows for tank A")
        self.assertEqual(got["card"]["over"], "tank B: reached the neck / overflowed")
        self.assertEqual(got["card"]["neckText"], "tank A: level still in the neck")
        self.assertIn("Next batch", got["card"]["advice"])
        self.assertIn("pour into B, then dip both", got["go"])
        self.assertIn("alpha", got["dip1"])
        self.assertIn("beta", got["dip2"])
        self.assertIn("alpha:", got["verdict"])
        self.assertIn("beta:", got["verdict"])
        self.assertEqual(got["saved"], {"kind": "transfer", "levels": [2, 2], "pour": [True, True]})
        self.assertEqual(got["files"]["a"], "Download alpha_raw.csv (tank A)")
        self.assertTrue(got["files"]["b"])
        self.assertEqual(got["export"], {"a": "alpha_raw.csv", "b": "beta_raw.csv",
                                         "label": "Download alpha_raw.csv (tank A)",
                                         "show": "Show beta CSV"},
                         "with tank B active, the A button still exports tank A")
        self.assertIn("pour L", got["log"], "tank B's log reads as a fill")
        self.assertIn("beta", got["shell"])
        self.assertIn("beta", got["settings"]["title"])
        self.assertIn("transfer", got["settings"]["dir"])


@unittest.skipUnless(NODE, "node is not installed")
class TestSiteCore(unittest.TestCase):
    def test_geometry_matches_python(self):
        shell = Shell(1243.6, 5285.1, -36.3)
        hs = [-50.0, 0.0, 12.5, 300.0, 1207.0, 2000.0, 2450.0, 2600.0]
        got = _node(
            "const p = {r: 1243.6, L: 5285.1, h0: -36.3};\n"
            f"const hs = {json.dumps(hs)};\n"
            "console.log(JSON.stringify({v: hs.map(h => core.volume(h, p)),"
            " m: hs.map(h => core.slope(h, p)), cap: core.capacity(p), brim: core.brim(p),"
            " inv: [1000, 12000, 25000].map(V => core.levelFor(V, p))}));"
        )
        for h, v, m in zip(hs, got["v"], got["m"]):
            self.assertAlmostEqual(v, float(shell.volume(h)), places=6)
            self.assertAlmostEqual(m, float(shell.slope(h)), places=9)
        self.assertAlmostEqual(got["cap"], shell.capacity(), places=6)
        self.assertAlmostEqual(got["brim"], shell.brim(), places=9)
        for V, H in zip([1000, 12000, 25000], got["inv"]):
            self.assertAlmostEqual(float(shell.volume(H)), V, places=4)

    def _demo(self, second_fix: bool):
        # The demo misreads row 12 by +4 mm (truth 629).  A live re-dip reads truth.
        second = "(i) => (i === 11 ? 629.0 : rows[i].H)" if second_fix else "(i) => rows[i].H"
        return _node(
            f"const rows = core.readRawText(fs.readFileSync({json.dumps(DEMO)}, 'utf8'));\n"
            "const cfg = {D: 1760, Dpm: 200, Lest: 2950, pourUnit: 50, sigmaRead: 1.0,"
            " pourRel: 0.003, pourAbs: 1.0};\n"
            f"const r = core.replayRows(rows, cfg, {{overflowRows: new Set([22]), second: {second}}});\n"
            "const L = r.session.levels;\n"
            "console.log(JSON.stringify({out: r.out, status: r.status,"
            " unknown: L[15].verdict.unknown, csv: r.session.toRawCsv(),"
            " series: r.session.series(), scale: r.session.scale}));"
        )

    def test_demo_misread_is_caught_live(self):
        res = self._demo(second_fix=False)
        row12 = res["out"][11]
        self.assertEqual(row12["firstStatus"], "REDIP", "the +4 mm misread asks for a re-dip")
        # Replayed with the misread value again, the pair partner alarms next.
        self.assertEqual(res["out"][12]["status"], "ALARM")

    def test_demo_redip_settles_the_pair(self):
        res = self._demo(second_fix=True)
        row12, row13 = res["out"][11], res["out"][12]
        self.assertEqual(row12["firstStatus"], "REDIP")
        self.assertEqual(row12["status"], "ACCEPT")
        self.assertNotIn(row13["status"], ("ALARM", "WATCH"))
        self.assertLess(abs(row13["e"]), 3.0)

    def test_demo_unknown_and_overflow(self):
        res = self._demo(second_fix=True)
        self.assertEqual(res["out"][15]["status"], "ACCEPT")
        self.assertEqual(res["out"][15]["dips"], 2, "an unknown pour always needs a repeat")
        self.assertEqual(res["out"][21]["status"], "OVERFLOW")
        truth = Shell(900.0, 3000.0, -5.0)
        rise = float(truth.volume(1047.0) - truth.volume(928.9))
        self.assertLess(abs(res["unknown"]["x"] - rise), 3 * res["unknown"]["sigma"] + 10)
        p = res["status"]["fit"]["p"]
        self.assertLess(abs(p["r"] - 900.0), 10.0)
        self.assertLess(abs(p["L"] - 3000.0), 60.0)

    def test_chart_series_follow_the_python_charts(self):
        res = self._demo(second_fix=True)
        series, p = res["series"], res["status"]["fit"]["p"]
        shell = Shell(p["r"], p["L"], p["h0"])
        rows = [d["row"] for d in series]
        self.assertNotIn(1, rows, "the first level has no interval")
        self.assertNotIn(16, rows, "an unknown pour has no residual")
        self.assertNotIn(22, rows, "an overflow reading is not shell level")
        self.assertEqual(len(rows), 19)
        drift, var = 0.0, 0.0
        for d in series:
            pred = float(shell.volume(d["H"]) - shell.volume(d["H1"]))
            m = float(shell.slope(d["H"]))
            v = 2 * (m * 1.0) ** 2 + (0.003 * d["s"] + 1.0) ** 2
            drift += d["s"] - pred
            var += v
            self.assertAlmostEqual(d["resid"], d["s"] - pred, places=6)  # §2 sign
            self.assertAlmostEqual(d["z"], d["resid"] / (res["scale"] * v**0.5), places=6)
            self.assertAlmostEqual(d["drift"], drift, places=6)
            self.assertAlmostEqual(d["limit"], 3 * var**0.5, places=6)
            self.assertAlmostEqual(d["mid"], 0.5 * (d["H"] + d["H1"]), places=9)
            self.assertGreater(d["rise"], 0)

    def test_exported_csv_reads_back(self):
        res = self._demo(second_fix=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo_site_raw.csv"
            path.write_text(res["csv"], encoding="utf-8")
            rows = read_raw(path)
        self.assertEqual(len(rows), 22)
        # 633 and 629 disagree at sigma 1 mm, so a third reading decides: 629/629.
        self.assertAlmostEqual(rows[11].height, 629.0, places=6)
        self.assertIn("dips 633.0/629.0/629.0", rows[11].note)
        self.assertFalse(rows[15].step.known)
        self.assertIn("overflow", rows[21].note)

    def test_session_rules(self):
        got = _node(
            "const s = new core.Session({D: 2480, Lest: 5280, pourUnit: 100});\n"
            "const out = {};\n"
            "out.start1 = s.start('?', 62).status;\n"
            "out.start2 = s.dip(62.5).status;\n"
            "out.startH = s.levels[0].H;\n"
            "try { s.dip; s.pour('abc'); } catch (e) { out.badPour = e.message; }\n"
            "const rows = [[200,95],[200,133],[200,160],[200,188],[400,239],[400,287],"
            "[400,333],[400,375],[400,416]];\n"
            "for (const [v, h] of rows) { s.pour(String(v)); let x = s.dip(h); let k = 0;"
            " while (x.status === 'REDIP' && k++ < 3) x = s.dip(h); }\n"
            "out.learning = s.learning();\n"
            "s.pour('400');\n"
            "const v1 = s.dip(464);\n"
            "out.slip = {status: v1.status, hidden: !!v1.hidden};\n"
            "const v2 = s.dip(458);\n"
            "out.disagree = v2.status;\n"
            "const v3 = s.dip(454);\n"
            "out.creep = {status: v3.status, msg: v3.message};\n"
            "out.override = s.override('test').status;\n"
            "out.overrideState = s.current().state;\n"
            "s.undo();\n"
            "out.afterUndo = s.current().state;\n"
            "s.undo(); s.undo();\n"
            "out.dipsLeft = s.current().dips.length;\n"
            "const v4 = s.dip(454.5);\n"
            "out.good = v4.status;\n"
            "s.pour('400');\n"
            "s.dip(505.0); const v5 = s.dip(505.5);\n"
            "out.alarm = {status: v5.status, cause: v5.cause};\n"
            "const v6 = s.editPour('525');\n"
            "out.afterRecount = v6.status;\n"
            "const j = JSON.parse(JSON.stringify(s.toJSON()));\n"
            "out.roundTrip = core.Session.fromJSON(j).toRawCsv() === s.toRawCsv();\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["start1"], "REDIP", "the first level always needs a repeat")
        self.assertEqual(got["start2"], "ACCEPT")
        self.assertAlmostEqual(got["startH"], 62.25)
        self.assertIn("cannot read pour", got["badPour"])
        self.assertFalse(got["learning"])
        self.assertEqual(got["slip"], {"status": "REDIP", "hidden": True})
        self.assertEqual(got["disagree"], "REDIP")
        self.assertEqual(got["creep"]["status"], "UNSETTLED")
        self.assertIn("not settled", got["creep"]["msg"])
        self.assertEqual(got["override"], "OVERRIDE")
        self.assertEqual(got["overrideState"], "override")
        self.assertEqual(got["afterUndo"], "pending")
        self.assertEqual(got["dipsLeft"], 0)
        self.assertEqual(got["good"], "ACCEPT")
        # 400 L recorded, but the level rose as for ~525 L: the rise came too cheap.
        self.assertEqual(got["alarm"], {"status": "ALARM", "cause": "OBJECT?"})
        self.assertIn(got["afterRecount"], ("ACCEPT", "WATCH"))
        self.assertTrue(got["roundTrip"])

    def test_set_campaign_refits_and_validates(self):
        got = _node(
            "const p = {r: 900, L: 3000, h0: 0};\n"
            "const s = new core.Session({D: 1800, Dpm: 100, Lest: 3000, pourUnit: 200});\n"
            "const out = {};\n"
            "let V = 400;\n"
            "s.start('400', core.levelFor(V, p)); s.dip(core.levelFor(V, p));\n"
            "for (let i = 0; i < 4; i++) { s.pour('400'); V += 400; let v = s.dip(core.levelFor(V, p));"
            " if (v.status === 'REDIP') s.dip(core.levelFor(V, p)); }\n"
            "out.dims = [s.cfg.D, s.cfg.prior.r, s.cfg.Lest, s.cfg.prior.L];\n"
            "s.setCampaign({D: 1900, Dpm: '', Lest: 3100, Lpm: '', pourUnit: ''});\n"
            "out.new = [s.cfg.D, s.cfg.Dpm, s.cfg.prior.r, s.cfg.Lest, s.cfg.Lpm, s.cfg.prior.L, s.cfg.pourUnit];\n"
            "out.fitR = s.fit.p.r;\n"
            "s.setCampaign({sigmaRead: 0.6});\n"
            "out.noise = [s.cfg.sigmaRead, s.cfg.repeatTol];\n"
            "s.setCampaign({tank: 't1'}); s.setCampaign({tank: '  '}); out.tank = s.cfg.tank;\n"
            "out.bad = [];\n"
            "for (const o of [{D: 0}, {Dpm: 0}, {Lest: -1}, {Lpm: -1}, {pourUnit: -1},"
            " {sigmaRead: 0}, {pourRel: -0.1}, {pourAbs: -1}, {h0pm: 0}]) {"
            " try { s.setCampaign(o); out.bad.push('ok'); } catch (e) { out.bad.push(e.message); } }\n"
            "try { s.setCampaign({D: 1950, Lest: -1}); } catch (e) {}\n"
            "out.atomic = s.cfg.D;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["dims"], [1800, 900, 3000, 3000])
        self.assertEqual(got["new"][0:2], [1900, 200], "a blank D ± falls back to 200 mm")
        self.assertAlmostEqual(got["new"][2], 950)
        self.assertEqual(got["new"][3], 3100)
        self.assertAlmostEqual(got["new"][4], 93, places=6, msg="a blank L ± is 3 %")
        self.assertAlmostEqual(got["new"][5], 3100)
        self.assertIsNone(got["new"][6])
        self.assertLess(abs(got["fitR"] - 900.0), 50.0, "the refit follows the data and the new prior")
        self.assertAlmostEqual(got["noise"][0], 0.6)
        self.assertAlmostEqual(got["noise"][1], 2.5 * 2**0.5 * 0.6, places=6)
        self.assertEqual(got["tank"], "t1", "a blank tank name keeps the old one")
        self.assertEqual(len(got["bad"]), 9)
        for msg in got["bad"]:
            self.assertNotEqual(msg, "ok")
        self.assertEqual(got["atomic"], 1900, "a bad field changes nothing")

    def test_set_campaign_noise_scale_and_repeat_tol(self):
        got = _node(
            "const p = {r: 900, L: 3000, h0: 0};\n"
            "const out = {};\n"
            "// A custom repeat limit set by hand survives a sigma change.\n"
            "const a = new core.Session({D: 1800, Lest: 3000, repeatTol: 5});\n"
            "a.setCampaign({sigmaRead: 0.5}); out.kept = a.cfg.repeatTol;\n"
            "const b = new core.Session({D: 1800, Lest: 3000});\n"
            "b.setCampaign({sigmaRead: 0.5}); out.followed = b.cfg.repeatTol;\n"
            "// Old z values were formed with the old sigma: they must not set the\n"
            "// scale after a noise change, or the change counts twice.\n"
            "let seed = 7; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };\n"
            "const g = () => { let u = 0; for (let i = 0; i < 12; i++) u += rnd(); return u - 6; };\n"
            "const s = new core.Session({D: 1800, Lest: 3000, pourUnit: 200, sigmaRead: 0.2});\n"
            "let V = 400; s.start('400', core.levelFor(V, p)); s.dip(core.levelFor(V, p) + 0.8 * g());\n"
            "for (let i = 0; i < 12; i++) {\n"
            "  s.pour('200'); V += 200 + 3 * g();\n"
            "  s.dip(core.levelFor(V, p) + 0.8 * g());\n"
            "  for (let k = 0; k < 4 && s.current().state === 'pending'; k++) s.dip(core.levelFor(V, p) + 0.8 * g());\n"
            "}\n"
            "out.scale0 = s.scale; out.scored0 = s.levels.filter((L) => L.check && L.check.scored).length;\n"
            "s.setCampaign({sigmaRead: 0.8});\n"
            "out.scale1 = s.scale; out.scored1 = s.levels.filter((L) => L.check && L.check.scored).length;\n"
            "// A row dipped after the change counts again.\n"
            "s.pour('200'); V += 200; s.dip(core.levelFor(V, p));\n"
            "for (let k = 0; k < 4 && s.current().state === 'pending'; k++) s.dip(core.levelFor(V, p));\n"
            "out.scale2 = s.scale; out.scored2 = s.levels.filter((L) => L.check && L.check.scored).length;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["kept"], 5, "a repeat limit set by hand is kept")
        self.assertAlmostEqual(got["followed"], 2.5 * 2**0.5 * 0.5, places=6, msg="a default repeat limit follows sigma")
        self.assertGreater(got["scale0"], 1.2, "the old sigma inflated the scale")
        self.assertGreater(got["scored0"], 0)
        self.assertEqual(got["scale1"], 1, "a noise change drops the stale z values from the scale")
        self.assertEqual(got["scored1"], got["scored0"], "the rows keep their z")
        self.assertGreater(got["scored2"], 0, "a new row is scored under the new noise")

    def test_edit_note(self):
        got = _node(
            "const s = new core.Session({D: 1800, Lest: 3000});\n"
            "s.start('400', 400); s.dip(400); s.pour('400', {note: 'old'}); s.dip(800);\n"
            "const out = {};\n"
            "out.set = s.editNote(2, '  new note  ').note;\n"
            "out.csv = s.toRawCsv().split('\\n')[2];\n"
            "out.cleared = s.editNote(2, '   ').note;\n"
            "out.empty = s.toRawCsv().split('\\n')[2];\n"
            "try { s.editNote(99, 'x'); } catch (e) { out.bad = e.message; }\n"
            "// Site markers stay apart from the operator note and cannot be erased.\n"
            "s.editPour('500');\n"
            "out.tags = s.levels[1].tags.slice();\n"
            "s.editNote(2, 'fixed');\n"
            "out.kept = s.toRawCsv().split('\\n')[2];\n"
            "s.override('looks right');\n"
            "out.overrideTags = s.levels[1].tags;\n"
            "s.editNote(2, '');\n"
            "out.overrideKept = s.toRawCsv().split('\\n')[2];\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["set"], "new note", "the note is trimmed")
        self.assertIn("new note", got["csv"], "the note goes into the raw file")
        self.assertEqual(got["cleared"], "", "an empty text clears the note")
        self.assertNotIn("new note", got["empty"])
        self.assertIn("no row 99", got["bad"])
        self.assertEqual(got["tags"], ["pour edited on site"], "the pour marker is a tag, not a note")
        self.assertIn("pour edited on site", got["kept"], "the marker survives a note edit")
        self.assertIn("fixed", got["kept"])
        self.assertEqual(got["overrideTags"], ["pour edited on site", "accepted against the check: looks right"])
        self.assertIn("accepted against the check: looks right", got["overrideKept"],
                      "the override marker survives a cleared note")

    def test_preview_matches_the_check_prediction(self):
        got = _node(
            "const p = {r: 900, L: 3000, h0: 0};\n"
            "const s = new core.Session({D: 1800, Dpm: 100, Lest: 3000, pourUnit: 200});\n"
            "let V = 400;\n"
            "s.start('400', core.levelFor(V, p)); s.dip(core.levelFor(V, p));\n"
            "for (let i = 0; i < 5; i++) {\n"
            "  V += 400; s.pour('400');\n"
            "  let v = s.dip(core.levelFor(V, p));\n"
            "  if (v.status === 'REDIP') v = s.dip(core.levelFor(V, p));\n"
            "}\n"
            "const gi = s.lastGood(), G = s.levels[gi];\n"
            "const pv = s.preview(G.H, 400, G.n);\n"
            "s.pour('400');\n"
            "const chk = s._predict(s.current(), 1);\n"
            "console.log(JSON.stringify({pv, chk, anchor: G.H, n: G.n}));"
        )
        pv, chk = got["pv"], got["chk"]
        self.assertAlmostEqual(pv["H"], chk["H"], places=9)
        self.assertAlmostEqual(pv["sd"], chk["sd"], places=9)
        self.assertEqual(pv["overflow"], chk["overflow"])
        self.assertGreater(pv["sd"], 0)
        self.assertGreater(pv["H"], got["anchor"])

    def test_batch_can_tally(self):
        # Truth shell r 900, L 3000, h0 0.  Batches of 200 L cans, one dip each.
        got = _node(
            "const p = {r: 900, L: 3000, h0: 0};\n"
            "const s = new core.Session({D: 1800, Dpm: 100, Lest: 3000, pourUnit: 200});\n"
            "const out = {};\n"
            "let V = 400, t = 0;\n"
            "s.start('400', core.levelFor(V, p)); s.dip(core.levelFor(V, p));\n"
            "function batch(n, real, opts) {\n"
            "  for (let i = 0; i < n; i++) { t += 180000; s.tap(t); }\n"
            "  const L = s.closeBatch(opts); V += (real == null ? n : real) * 200;\n"
            "  const H = core.levelFor(V, p); let v = s.dip(H);\n"
            "  if (v.status === 'REDIP') v = s.dip(H);\n"
            "  return {L, v};\n"
            "}\n"
            "for (let i = 0; i < 5; i++) batch(2);\n"
            "out.quick0 = s.quickTap(t + 5000);\n"
            "s.tap(t + 1000); out.quick = [s.quickTap(t + 6000), s.quickTap(t + 61000)];\n"
            "s.tap(t + 2000); out.afterTaps = s.cans();\n"
            "const saved = core.Session.fromJSON(JSON.parse(JSON.stringify(s.toJSON())));\n"
            "out.restored = saved.cans();\n"
            "s.undo(); out.afterUndo = s.cans(); out.levelsKept = s.levels.length;\n"
            "s.untap(); out.empty = [s.cans(), s.batch];\n"
            "try { s.closeBatch(); } catch (e) { out.noCan = e.message; }\n"
            "const good = batch(3);\n"
            "out.good = {text: good.L.step.text, status: good.v.status, cans: good.L.cans.tapped};\n"
            "const bad = batch(3, 4);\n"
            "out.bad = {status: bad.v.status, hint: bad.v.cans, msg: bad.v.message, advice: bad.v.advice};\n"
            "s.editPour('800'); out.fixed = s.current().verdict.status;\n"
            "for (let i = 0; i < 2; i++) { t += 180000; s.tap(t); }\n"
            "const part = s.closeBatch({partial: true}); out.part = part.step.text;\n"
            "s.undo(); out.reopened = s.cans();\n"
            "s.untap(); out.one = s.closeBatch({partial: true}).step.text; s.undo(); s.untap();\n"
            "out.csv = s.toRawCsv();\n"
            "out.hints = [core.canHint(-198, -10, 1200, s.cfg), core.canHint(-90, -5, 1200, s.cfg),"
            " core.canHint(205, 9, 200, s.cfg), core.canHint(395, 9, 1200, s.cfg)];\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertFalse(got["quick0"], "the first can of a batch is never a double tap")
        self.assertEqual(got["quick"], [True, False], "a tap inside 20 s asks 'same can?'")
        self.assertEqual(got["afterTaps"], 2)
        self.assertEqual(got["restored"], 2, "an open tally survives a page reload")
        self.assertEqual(got["afterUndo"], 1, "undo removes a can before it touches a level")
        self.assertEqual(got["levelsKept"], 6)
        self.assertEqual(got["empty"], [0, None])
        self.assertIn("no can", got["noCan"])
        self.assertEqual(got["good"], {"text": "600", "status": "ACCEPT", "cans": 3})
        # Three taps, four cans poured: the miss is one whole can.
        self.assertEqual(got["bad"]["status"], "ALARM")
        self.assertEqual(got["bad"]["hint"]["extra"], 1)
        self.assertLess(abs(got["bad"]["hint"]["zAfter"]), 2.0)
        self.assertIn("1 can more than the count (4, not 3)", got["bad"]["msg"])
        self.assertIn("edit the pour to 800 L", got["bad"]["advice"])
        self.assertEqual(got["fixed"], "ACCEPT", "the recount clears the alarm")
        self.assertEqual(got["part"], "200+?")
        self.assertEqual(got["reopened"], 2, "undo of a closed batch opens it again")
        self.assertEqual(got["one"], "?")
        self.assertRegex(got["csv"], r"600,[0-9.]+,.*cans 3x200 L \d\d:\d\d-\d\d:\d\d")
        h = got["hints"]
        self.assertEqual(h[0]["extra"], 1)
        self.assertIsNone(h[1], "half a can is not a count error")
        self.assertIsNone(h[2], "a count cannot go to zero cans")
        self.assertEqual(h[3]["extra"], -2)

    def test_mixed_can_sizes(self):
        got = _node(
            "const p = {r: 900, L: 3000, h0: 0};\n"
            "const s = new core.Session({D: 1800, Dpm: 100, Lest: 3000, pourUnit: 200});\n"
            "const out = {};\n"
            "let t = 0;\n"
            "s.start('400', core.levelFor(400, p)); s.dip(core.levelFor(400, p));\n"
            "s.tap(t += 60000, 200); s.tap(t += 60000, 100); s.tap(t += 60000, 100);\n"
            "out.batch = {n: s.cans(), vol: s.batchVolume(), units: s.canUnits(), list: s.canList().map((c) => c.u)};\n"
            "const L = s.closeBatch();\n"
            "out.text = L.step.text; out.cans = L.cans;\n"
            "out.hint = core.canHint(-101, -8, 400, s.cfg, L.cans.units);\n"
            "out.byDefault = core.canHint(-101, -8, 400, s.cfg);\n"
            "let v = s.dip(core.levelFor(800, p)); if (v.status === 'REDIP') v = s.dip(core.levelFor(800, p));\n"
            "out.note = s.toRawCsv().trim().split('\\n').pop();\n"
            "const s3 = new core.Session({D: 1800, Lest: 3000, pourUnit: 200});\n"
            "s3.start('400', 400); s3.dip(400); s3.tap(1, 200); s3.tap(2, 100); s3.closeBatch();\n"
            "s3.undo(); out.reopened = s3.canList().map((c) => c.u);\n"
            "// A batch of one size keeps the can count and the unit.\n"
            "const s2 = new core.Session({D: 1800, Lest: 3000, pourUnit: 200});\n"
            "s2.start('400', 400); s2.dip(400); s2.tap(1); s2.tap(2);\n"
            "const two = s2.closeBatch(); out.two = {text: two.step.text, unit: two.cans.unit};\n"
            "// A page saved before can sizes were per can.\n"
            "const old = core.Session.fromJSON({config: {D: 1800, Lest: 3000, pourUnit: 200}, levels: [],"
            " batch: {unit: 200, taps: [1000, 2000]}});\n"
            "out.legacy = {n: old.cans(), vol: old.batchVolume(), units: old.canUnits()};\n"
            "// No default size: the tap carries its own.\n"
            "const no = new core.Session({D: 1800, Lest: 3000});\n"
            "no.start('400', 400); no.dip(400);\n"
            "try { no.tap(1); } catch (e) { out.noUnit = e.message; }\n"
            "no.tap(1, 50); no.tap(2, 25); out.anyUnit = {vol: no.batchVolume(), units: no.canUnits()};\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["batch"], {"n": 3, "vol": 400, "units": [{"unit": 200, "count": 1}, {"unit": 100, "count": 2}],
                                        "list": [200, 100, 100]})
        self.assertEqual(got["text"], "400", "the pour is the sum of the cans")
        self.assertIsNone(got["cans"]["unit"], "a mixed batch has no single unit")
        self.assertEqual(got["cans"]["units"], [200, 100, 100])
        self.assertIn("cans 1x200+2x100 L", got["note"])
        self.assertEqual(got["hint"]["extra"], 1)
        self.assertEqual(got["hint"]["unit"], 100, "the hint picks the size that fits")
        self.assertIsNone(got["byDefault"], "200 L does not fit a 101 L miss")
        self.assertEqual(got["reopened"], [200, 100], "undo reopens the batch with each size")
        self.assertEqual(got["two"], {"text": "400", "unit": 200})
        self.assertEqual(got["legacy"], {"n": 2, "vol": 400, "units": [{"unit": 200, "count": 2}]})
        self.assertIn("can size", got["noUnit"])
        self.assertEqual(got["anyUnit"], {"vol": 75, "units": [{"unit": 50, "count": 1}, {"unit": 25, "count": 1}]})

    def test_can_size_migration_and_hint_limits(self):
        got = _node(
            "const p = {r: 900, L: 3000, h0: 0};\n"
            "const out = {};\n"
            "// A closed batch saved before per-can sizes (the committed page shape).\n"
            "const lvl = (dips, H) => ({row: 2, step: {text: '400', kind: 'known', value: 400}, dips, times: [1],"
            " state: dips.length ? 'accepted' : 'pending', from: 0, note: '', overflow: false, H, n: dips.length,"
            " cans: {tapped: 2, unit: 200, partial: false, taps: [1000, 2000]}});\n"
            "const cfg = {D: 1800, Lest: 3000, pourUnit: 200};\n"
            "const old = core.Session.fromJSON({version: 1, config: cfg, levels: [lvl([400], 400)], batch: null});\n"
            "out.csv = old.toRawCsv();\n"
            "const old2 = core.Session.fromJSON({version: 1, config: cfg, levels: [lvl([], null)], batch: null});\n"
            "old2.undo(); out.reopened = old2.canList().map((c) => c.u);\n"
            "// A plain pour keeps the can-count wording when the setup unit fits.\n"
            "const s = new core.Session(cfg);\n"
            "let V = 400;\n"
            "s.start('400', core.levelFor(V, p)); s.dip(core.levelFor(V, p));\n"
            "function pour(text, real) {\n"
            "  s.pour(text); V += real;\n"
            "  const H = core.levelFor(V, p); let v = s.dip(H);\n"
            "  if (v.status === 'REDIP') v = s.dip(H);\n"
            "  return v;\n"
            "}\n"
            "for (let i = 0; i < 5; i++) pour('400', 400);\n"
            "const v = pour('600', 800);\n"
            "out.plain = {status: v.status, msg: v.message, advice: v.advice};\n"
            "// The hint never removes more cans of a size than the batch holds.\n"
            "out.cap = [core.canHint(290, -9, 400, s.cfg, [200, 100, 100], {200: 1, 100: 2}),\n"
            "           core.canHint(290, -9, 400, s.cfg, [200, 100, 100])];\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIn("cans 2x200 L", got["csv"], "an old closed batch still exports")
        self.assertEqual(got["reopened"], [200, 200], "undo reopens an old batch with its unit")
        self.assertEqual(got["plain"]["status"], "ALARM")
        self.assertIn("(4, not 3)", got["plain"]["msg"])
        self.assertIn("If you count 4 cans, edit the pour to 800 L", got["plain"]["advice"])
        self.assertIsNone(got["cap"][0], "3 fewer 100 L cans is impossible in a 2 x 100 L batch")
        self.assertEqual(got["cap"][1]["extra"], -3, "without counts the old behaviour stays")

    def test_timer_settings_and_measured_pour_time(self):
        got = _node(
            "const s = new core.Session({D: 1800, Lest: 3000, pourUnit: 200});\n"
            "const out = {};\n"
            "out.defaults = JSON.parse(JSON.stringify([s.cfg.settleSeconds, s.cfg.dipSeconds, s.cfg.fillSeconds, s.cfg.alarmLead]));\n"
            "s.start('400', 400); s.dip(400);\n"
            "out.none = s.fillSecondsFor(200);\n"
            "// Taps 100 s, 120 s, 110 s apart; one 100 L can between them breaks a pair.\n"
            "s.tap(0, 200); s.tap(100000, 200); s.tap(220000, 200); s.tap(330000, 200); s.tap(400000, 100);\n"
            "out.measured = s.cycleSecondsFor(200); out.other = s.cycleSecondsFor(100);\n"
            "out.noFill = s.fillSecondsFor(200);\n"
            "s.setTimers({settleSeconds: 420, dipSeconds: 45, alarmLead: 12, fillSeconds: {200: 95, '100.0': 50}});\n"
            "out.set = [s.fillSecondsFor(200), s.fillSecondsFor(100), s.cfg.settleSeconds, s.cfg.dipSeconds, s.cfg.alarmLead];\n"
            "out.cycle = s.cycleSecondsFor(200);\n"
            "const back = core.Session.fromJSON(JSON.parse(JSON.stringify(s.toJSON())));\n"
            "out.saved = [back.cfg.settleSeconds, back.cfg.fillSeconds, back.cfg.alarmLead];\n"
            "s.setTimers({fillSeconds: {200: null}}); out.cleared = s.fillSecondsFor(200);\n"
            "for (const bad of [{settleSeconds: -1}, {fillSeconds: {200: 0}}, {alarmLead: 121}, {alarmLead: -1}]) {\n"
            "  try { s.setTimers(bad); out.bad = (out.bad || 0) + 1000; } catch (e) { out.bad = (out.bad || 0) + 1; } }\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["defaults"], [300, 60, {}, 15])
        self.assertIsNone(got["none"], "the timer needs a set fill time")
        self.assertEqual(got["measured"], {"seconds": 110, "source": "measured", "n": 3})
        self.assertIsNone(got["other"], "one 100 L can has no gap of its own size")
        self.assertIsNone(got["noFill"], "a tap gap never gives the fill time")
        self.assertEqual(got["set"][0], {"seconds": 95, "source": "set"})
        self.assertEqual(got["set"][1], {"seconds": 50, "source": "set"}, "100.0 and 100 are one size")
        self.assertEqual(got["set"][2:], [420, 45, 12])
        self.assertEqual(got["cycle"]["source"], "measured", "the estimate prefers the measured cycle")
        self.assertEqual(got["saved"], [420, {"200": 95, "100": 50}, 12])
        self.assertEqual(got["cleared"], None, "a cleared fill time leaves the timer without one")
        self.assertEqual(got["bad"], 4)

    def test_fill_plan(self):
        got = _node(
            "const p = {r: 900, L: 3000, h0: 0};\n"
            "const s = new core.Session({D: 1800, Dpm: 20, Lest: 3000, Lpm: 30, h0pm: 2, pourUnit: 200});\n"
            "let V = 400;\n"
            "s.start('400', core.levelFor(V, p)); s.dip(core.levelFor(V, p));\n"
            "for (let i = 0; i < 4; i++) { s.pour('400'); V += 400; let v = s.dip(core.levelFor(V, p));"
            " if (v.status === 'REDIP') s.dip(core.levelFor(V, p)); }\n"
            "const cap = core.capacity(s.fit.p), V0 = core.volume(s.levels[s.lastGood()].H, s.fit.p);\n"
            "const o = {size: 200, cycleSeconds: 90, settleSeconds: 300, dipSeconds: 60};\n"
            "const out = {cap, V0, a: s.fillPlan(o)};\n"
            "out.big = s.fillPlan(Object.assign({}, o, {size: 400, cycleSeconds: 150}));\n"
            "out.elapsed = s.fillPlan(Object.assign({}, o, {pourElapsed: 30}));\n"
            "out.noTime = s.fillPlan({size: 200});\n"
            "s.tap(1, 200); s.tap(2, 200); out.open = s.fillPlan(o);\n"
            "s.closeBatch(); s.current().pourTime = 1000;\n"
            "out.pend = s.fillPlan(Object.assign({}, o, {now: 1000 + 120000}));\n"
            "console.log(JSON.stringify(out));"
        )
        a, cap, v0 = got["a"], got["cap"], got["V0"]
        self.assertIsNone(got["noTime"], "no cycle time, no estimate")
        for m in (a["half"], a["brim"]):
            # Every level: its cans, one settle and one dip.
            self.assertAlmostEqual(m["seconds"], 90 * m["cans"] + 360 * m["levels"], places=6)
        self.assertGreaterEqual(v0 + 200 * a["half"]["cans"], cap / 2)
        self.assertLess(v0 + 200 * (a["half"]["cans"] - 1), cap / 2 + 200 * 3, "half is the first level past it")
        self.assertGreaterEqual(v0 + 200 * a["brim"]["cans"], cap)
        self.assertLess(v0 + 200 * (a["brim"]["cans"] - 1), cap, "the last pour takes only the cans the gap needs")
        self.assertLess(a["half"]["seconds"], a["brim"]["seconds"])
        self.assertGreater(a["brim"]["levels"], a["half"]["levels"])
        self.assertLessEqual(got["big"]["brim"]["cans"], a["brim"]["cans"] / 2 + 1, "bigger cans, fewer cans")
        self.assertAlmostEqual(got["elapsed"]["brim"]["seconds"], a["brim"]["seconds"] - 30, places=6)
        # Two cans already in the open batch count toward the first level.
        op = got["open"]
        self.assertAlmostEqual(op["start"]["volume"], v0 + 400, places=6)
        self.assertGreaterEqual(op["start"]["volume"] + 200 * op["brim"]["cans"], cap)
        # A pending level: the pour is in, 3 min of settle and the dip are left.
        pe = got["pend"]
        self.assertAlmostEqual(pe["start"]["seconds"], 180 + 60, places=6)
        self.assertAlmostEqual(pe["start"]["volume"], v0 + 400, places=6)

    def test_power_on_synthetic_campaigns(self):
        got = _node(
            f"const sim = require({json.dumps(SIM)});\n"
            "const opt = {sigmaRead: 0.4, resolution: 0.5, pourRel: 0.005, pourAbs: 3, Dpm: 200};\n"
            "const res = {};\n"
            "for (const d of [5]) { const R = sim.rng(17 + d); let c = 0, fr = 0, h = 0;\n"
            "  for (let j = 0; j < 25; j++) { const t = sim.run(R, opt, (j % 2 ? 1 : -1) * d);"
            " if (t.caught) c++; fr += t.falseRedip; h += t.honest; }\n"
            "  res[d] = {caught: c / 25, falseRedip: fr / h}; }\n"
            "console.log(JSON.stringify(res));"
        )
        self.assertGreaterEqual(got["5"]["caught"], 0.95)
        self.assertLessEqual(got["5"]["falseRedip"], 0.12)

    # ------------------------------------------------------------ drain mode
    def test_drain_clean_campaign(self):
        got = _node(
            DRAIN_JS
            + "const rows = drainRows();\n"
            "const r = core.replayRows(rows, Object.assign({pourUnit: 100}, DRAIN_CFG), {neckEntrance: true});\n"
            "const s = r.session;\n"
            "const j = JSON.parse(JSON.stringify(s.toJSON()));\n"
            "const back = core.Session.fromJSON(j);\n"
            "console.log(JSON.stringify({out: r.out, status: r.status, csv: s.toRawCsv(), P, B,"
            " brimStart: s.cfg.brimStart, priorB: s.cfg.prior.B, series: s.series(),"
            " cfg: {direction: j.config.direction, brimPm: j.config.brimPm, brimStart: j.config.brimStart},"
            " backCsv: back.toRawCsv(), backB: back.cfg.prior.B, backDir: back.cfg.dir,"
            " detected: core.detectDirection(rows)}));"
        )
        statuses = [o["status"] for o in got["out"]]
        self.assertNotIn("ALARM", statuses, statuses)
        self.assertNotIn("NECK", statuses)
        self.assertEqual(got["detected"], "drain")
        self.assertEqual(got["out"][0]["dips"], 2, "the first level needs two readings")
        self.assertAlmostEqual(got["brimStart"], got["B"], places=6, msg="the neck-entrance reading is B")
        self.assertAlmostEqual(got["priorB"], got["B"], places=6)
        p, t = got["status"]["fit"]["p"], got["P"]
        self.assertLess(abs(p["r"] - t["r"]) / t["r"], 0.02, p)
        self.assertLess(abs(p["L"] - t["L"]) / t["L"], 0.03, p)
        self.assertLess(abs(2 * p["r"] + p["h0"] - got["B"]), 3.0, "the brim prior holds the top")
        self.assertEqual(got["status"]["direction"], "drain")
        self.assertEqual(got["cfg"], {"direction": "drain", "brimPm": 6, "brimStart": got["B"]})
        self.assertEqual(got["backCsv"], got["csv"], "the session JSON round-trips")
        self.assertAlmostEqual(got["backB"], got["B"], places=6)
        self.assertEqual(got["backDir"], -1)
        rows = list(csv.reader(io.StringIO(got["csv"])))
        self.assertEqual(rows[0], ["step_volume", "measured_height", "note"])
        heights = [float(r[1]) for r in rows[1:]]
        self.assertTrue(all(b < a for a, b in itertools.pairwise(heights)), "heights fall")
        self.assertEqual(rows[1][0], "?")
        self.assertTrue(all(float(r[0]) > 0 for r in rows[2:]), "drain volumes are positive")
        notes = rows[1][2].split("; ")
        self.assertEqual(notes[0], "drain campaign", "the token comes first")
        self.assertEqual(notes[1], "at neck entrance")
        self.assertEqual(rows[1][2].count("at neck entrance"), 1)
        for r in rows[2:]:
            self.assertNotIn("drain campaign", r[2])
        # Charts: travel > 0, the §2 residual, drift = Σ resid.
        drift = 0.0
        for d in got["series"]:
            self.assertGreater(d["rise"], 0)
            self.assertLess(d["H"], d["H1"])
            drift += d["resid"]
            self.assertAlmostEqual(d["drift"], drift, places=6)
        self.assertEqual(len(got["series"]), len(rows) - 2)
        self.assertAlmostEqual(got["status"]["drift"], drift, places=3)

    def _drain_event(self, obj, actual):
        return _node(
            DRAIN_JS
            + f"const obj = {obj}, actual = {actual};\n"
            "const rows = drainRows(obj, actual);\n"
            "const r = core.replayRows(rows, Object.assign({}, DRAIN_CFG, {D: 2480, Lest: 5200}), {neckEntrance: true});\n"
            "const L = r.session.levels;\n"
            "console.log(JSON.stringify({out: r.out, verdicts: L.map((l) => l.verdict && {cause: l.verdict.cause,"
            " message: l.verdict.message, status: l.verdict.status}), csv: r.session.toRawCsv(),"
            " rows: rows.map((x) => x.H)}));"
        )

    def test_drain_signs_object_and_over_record(self):
        # Object: 150 L of solid in a band inside interval 10 (rows 10 → 11).
        band = (
            "(() => { const a = drainRows(); const mid = 0.5 * (a[9].H + a[10].H);"
            " return {d: 150, a: mid - 5, b: mid + 5}; })()"
        )
        got = self._drain_event(band, "null")
        alarms = [o for o in got["out"] if o["status"] == "ALARM"]
        self.assertEqual([o["row"] for o in alarms], [11], got["out"])
        o, v = alarms[0], got["verdicts"][10]
        self.assertLess(o["resid"], 0, "an exposed object: the fall came too large")
        self.assertAlmostEqual(o["resid"], -150, delta=20)
        self.assertEqual(v["cause"], "OBJECT?")
        self.assertIn("OBJECT? or LEAK? or the drain was under-recorded", v["message"])
        self.assertIn("a spill at the can counts here", v["message"])
        self.assertIn("OBJECT?", got["csv"].splitlines()[11])
        # Over-recorded: 1200 L on the record, 1050 L really left at step 11.
        got = self._drain_event("null", "{10: 1050}")
        alarms = [o for o in got["out"] if o["status"] == "ALARM"]
        self.assertEqual([o["row"] for o in alarms], [12], got["out"])
        self.assertGreater(alarms[0]["resid"], 0, "the fall came too small")
        self.assertAlmostEqual(alarms[0]["resid"], 150, delta=20)
        v = got["verdicts"][11]
        self.assertEqual(v["cause"], "RETURN?")
        self.assertIn("RETURN? or the drain was over-recorded", v["message"])

    def test_drain_pair_rule_sign(self):
        # Row 11 (the earlier level of the pair) is misread by +5 mm, twice.
        got = _node(
            DRAIN_JS
            + "const rows = drainRows(); const k = 10; const delta = 5;\n"
            "rows[k].H += delta;\n"
            "const r = core.replayRows(rows, Object.assign({}, DRAIN_CFG, {D: 2480, Lest: 5200}), {neckEntrance: true});\n"
            "console.log(JSON.stringify({out: r.out, suspect: r.session.levels[k].suspect, misread: rows[k].H,"
            " csv: r.session.toRawCsv().split('\\n')[k + 1]}));"
        )
        o = got["out"][11]
        self.assertEqual(o["status"], "ALARM")
        self.assertIsNotNone(o["pair"], got["out"][10:12])
        self.assertAlmostEqual(o["pair"]["level"], got["misread"], places=6)
        self.assertAlmostEqual(o["pair"]["delta"], 5.0, delta=0.7, msg="δ = recorded − true, same sign as a fill")
        self.assertGreater(got["out"][10]["resid"], 0, "a high reading in a drain: the fall came too small")
        self.assertLess(o["resid"], 0)
        self.assertTrue(got["suspect"])
        self.assertIn("suspect dip (pair pattern)", got["csv"])

    def test_drain_neck_start(self):
        got = _node(
            DRAIN_JS
            + "const s = new core.Session(Object.assign({}, DRAIN_CFG, {D: 2480, Lest: 5200, pourUnit: 100}));\n"
            "const out = {first: [], states: [], dips: []};\n"
            "const dipTwice = (H) => { const a = s.dip(H); const b = a.status === 'REDIP' ? s.dip(H) : a;"
            " out.first.push(a.status); return b; };\n"
            "s.start('?', B + 60, '', null, {at: 'neck'}); out.first.push(s.current().verdict.status);"
            " out.v0 = s.dip(B + 60);\n"
            "s.pour('50', {neck: true}); out.v1 = dipTwice(B + 25);\n"
            "try { s.pour('50', {overflow: true}); } catch (e) { out.noOverflow = e.message; }\n"
            "// 400 L: the last 25 L of the neck, then 375 L of shell.\n"
            "let V = CAP - 375; s.pour('400'); out.v2 = dipTwice(core.levelFor(V, P));\n"
            "out.anchor = s.levels[2].from;\n"
            "try { s.pour('50', {neck: true}); } catch (e) { out.notBack = e.message; }\n"
            "for (const st of [600, 600, 600, 600, 600]) { V -= st; s.pour(String(st)); dipTwice(core.levelFor(V, P)); }\n"
            "out.states = s.levels.map((l) => l.state); out.dips = s.levels.map((l) => l.dips.length);\n"
            "out.fitRows = s._fitIntervals().map((iv) => iv.row);\n"
            "out.from3 = s.levels[3].from; out.brimStart = s.cfg.brimStart; out.priorB = s.cfg.prior.B || null;\n"
            "out.series = s.series().map((d) => d.row);\n"
            "out.csv = s.toRawCsv().split('\\n');\n"
            "const f = new core.Session({D: 1800, Lest: 3000}); f.start('400', 400); f.dip(400);\n"
            "try { f.pour('100', {neck: true}); } catch (e) { out.fillNeck = e.message; }\n"
            "try { new core.Session({D: 1800, Lest: 3000}).start('?', 400, '', null, {at: 'entrance'}); }"
            " catch (e) { out.fillEntrance = e.message; }\n"
            "try { new core.Session({D: 1800, Lest: 3000, direction: 'up'}); } catch (e) { out.badDir = e.message; }\n"
            "try { s.setCampaign({direction: 'fill'}); } catch (e) { out.fixed = e.message; }\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["v0"]["status"], "NECK")
        self.assertEqual(got["v1"]["status"], "NECK")
        self.assertEqual(got["v2"]["status"], "NECK", "the first shell level after the neck")
        self.assertEqual(got["first"][:3], ["REDIP", "REDIP", "REDIP"], "two readings at each neck level")
        self.assertEqual(got["v2"]["color"], "info")
        self.assertIn("brim constraint Vcap − F(H) ≤ P", got["v2"]["message"])
        self.assertIn("stays out of the running fit", got["v1"]["message"])
        self.assertIn("vent-column height", got["v1"]["message"])
        self.assertEqual(got["states"][:3], ["neck", "neck", "neck"])
        self.assertEqual(got["dips"][:3], [2, 2, 2])
        self.assertEqual(got["anchor"], 1, "the first shell level spans the neck from the last neck level")
        self.assertEqual(got["from3"], 2, "the next level uses the first shell level as anchor")
        self.assertNotIn("neck", got["states"][3:])
        self.assertEqual(got["fitRows"], [3, 4, 5, 6, 7], "neck intervals stay out of the running fit")
        self.assertEqual(got["series"], [4, 5, 6, 7, 8])
        self.assertIsNone(got["brimStart"], "only a neck-entrance start gives B")
        self.assertIsNone(got["priorB"])
        self.assertIn("overflow", got["noOverflow"])
        self.assertIn("only falls", got["notBack"])
        self.assertTrue(got["csv"][1].split(",")[2].startswith("drain campaign; neck level"), got["csv"][1])
        self.assertIn("neck level", got["csv"][2])
        self.assertIn("neck interval", got["csv"][3])
        self.assertNotIn("neck", got["csv"][4])
        self.assertIn("drain campaign", got["fillNeck"])
        self.assertIn("drain campaign", got["fillEntrance"])
        self.assertIn("fill", got["badDir"])
        self.assertIn("fixed", got["fixed"])

    def test_drain_advice_and_plan(self):
        got = _node(
            DRAIN_JS
            + "const r = core.replayRows(drainRows(), Object.assign({}, DRAIN_CFG, {D: 2480, Lest: 5200, pourUnit: 100}),"
            " {neckEntrance: true});\n"
            "const s = r.session, p = s.fit.p;\n"
            "const adv = [];\n"
            "for (let H = core.brim(p); H > p.h0 + 5; H -= 10) adv.push(s.advice(H));\n"
            "const plan = s.fillPlan({size: 100, cycleSeconds: 60, settleSeconds: 300, dipSeconds: 60});\n"
            "const V0 = core.volume(s.levels[s.lastGood()].H, p), cap = core.capacity(p);\n"
            "s.tap(1, 100); s.tap(2, 100); const open = s.fillPlan({size: 100, cycleSeconds: 60});\n"
            "// A fill near the brim still halves.\n"
            "const f = new core.Session({D: 1800, Lest: 3000}); f.start('400', 400); f.dip(400);\n"
            "console.log(JSON.stringify({adv: adv.map((a) => ({text: a.text, halve: a.halve, bottom: a.bottom,"
            " left: a.left, toBottom: a.toBottom})), plan, V0, cap, open, fill: f.advice(1790).text, h0: p.h0}));"
        )
        adv = got["adv"]
        for a in adv:
            self.assertNotIn("halve", a["text"])
            self.assertFalse(a["halve"])
            self.assertIn("Next drain", a["text"])
            self.assertIn("mm fall", a["text"])
            self.assertIsNotNone(a["left"])
            self.assertIsNotNone(a["toBottom"])
        self.assertFalse(adv[len(adv) // 2]["bottom"], "no bottom warning mid-tank")
        low = adv[-1]
        self.assertTrue(low["bottom"])
        self.assertIn("Near the bottom", low["text"])
        self.assertIn("a part can is fine (N+?)", low["text"])
        self.assertIn("halve", got["fill"], "fill advice is unchanged")
        plan, cap, v0 = got["plan"], got["cap"], got["V0"]
        self.assertIsNone(plan["brim"])
        self.assertTrue(plan["half"]["done"], "the replay ends below half")
        end = plan["end"]
        self.assertLessEqual(end["volume"], plan["endVolume"] + 1e-6)
        self.assertGreaterEqual(end["levels"], 1)
        self.assertGreater(v0, plan["endVolume"], "the replay stops above the bottom zone")
        self.assertAlmostEqual(v0 - 100 * end["cans"], end["volume"], places=6, msg="the volume counts down")
        self.assertAlmostEqual(end["seconds"], 60 * end["cans"] + 360 * end["levels"], places=6)
        self.assertGreaterEqual(plan["endVolume"], 0.05 * cap - 1e-6)
        self.assertAlmostEqual(got["open"]["start"]["volume"], v0 - 200, places=6, msg="an open batch leaves the tank")

    def test_drain_power_on_synthetic_campaigns(self):
        got = _node(
            f"const sim = require({json.dumps(SIM)});\n"
            "const opt = {sigmaRead: 0.4, resolution: 0.5, pourRel: 0.005, pourAbs: 3, Dpm: 200, drain: true};\n"
            "const R = sim.rng(23); let c = 0, fr = 0, h = 0, al = 0;\n"
            "for (let j = 0; j < 25; j++) { const t = sim.run(R, opt, (j % 2 ? 1 : -1) * 5);"
            " if (t.caught) c++; fr += t.falseRedip; h += t.honest; al += t.alarms; }\n"
            "console.log(JSON.stringify({caught: c / 25, falseRedip: fr / h, falseAlarm: al / h}));"
        )
        self.assertGreaterEqual(got["caught"], 0.95)
        self.assertLessEqual(got["falseRedip"], 0.12)
        self.assertLessEqual(got["falseAlarm"], 0.01)


if __name__ == "__main__":
    unittest.main()

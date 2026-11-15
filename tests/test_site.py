"""On-site live dip check (§10a): the page build and the JavaScript core.

The core runs under Node.  Without Node the core tests skip; the page-build
test still runs.
"""

from __future__ import annotations

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
            "el('pt-start').click(); out.noTime = el('p-err').textContent; out.opened = el('timers').open;\n"
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


if __name__ == "__main__":
    unittest.main()

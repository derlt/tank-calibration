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
            " unknown: L[15].verdict.unknown, csv: r.session.toRawCsv()}));"
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

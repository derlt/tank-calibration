"""On-site live dip check (§10a): the page build and the JavaScript core.

The core runs under Node.  Without Node the core tests skip; the page-build
test still runs.
"""

from __future__ import annotations

import csv
import io
import itertools
import json
import os
import re
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
SH = shutil.which("sh")
GIT = shutil.which("git")
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
/** rows from the brim down; actual[i] overrides the litres that really left at step i. */
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

    def test_site_public_is_the_current_build(self):
        """site/public is committed and must match the build.

        The dashboard's Workers Build deploys the repository, so the assets
        directory has to be in git.  It is a copy of the built page: this
        test fails when the page changed and the copy did not follow.
        """
        built = (SITE / "public" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(built, build_page(), "site/public/index.html is stale: run `make site-public`")
        headers = (SITE / "public" / "_headers").read_text(encoding="utf-8")
        self.assertEqual(headers, (SITE / "_headers").read_text(encoding="utf-8"))

    @unittest.skipUnless(SH, "sh is not installed")
    def test_cloud_build_copies_the_committed_page(self):
        """scripts/cloud-build.sh builds site/public from the committed page.

        A Workers Build deploys a fresh checkout, where site/public does not
        exist (it is built, not committed).  The script must give the same
        bytes as the Python build, or the dashboard would serve an old page.
        """
        script = HERE / "scripts" / "cloud-build.sh"
        self.assertTrue(script.exists())
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if k != "D1_DATABASE_ID"}
            # A copy of the tree the script needs: site/, scripts/ and wrangler.jsonc.
            run = Path(tmp) / "repo"
            shutil.copytree(SITE, run / "site", ignore=shutil.ignore_patterns("public"))
            shutil.copy(HERE / "wrangler.jsonc", run / "wrangler.jsonc")
            shutil.copytree(HERE / "scripts", run / "scripts")
            subprocess.run(  # noqa: S603 - SH is an absolute path
                [SH, "scripts/cloud-build.sh", "site/public"], cwd=run, env=env, check=True
            )
            built = (run / "site" / "public" / "index.html").read_text(encoding="utf-8")
            headers = (run / "site" / "public" / "_headers").read_text(encoding="utf-8")
            self.assertEqual(built, build_page(), "the assets must be the current build")
            self.assertEqual(headers, (SITE / "_headers").read_text(encoding="utf-8"))
            self.assertFalse(
                (run / "wrangler.deploy.jsonc").exists(),
                "no D1 id in the environment: no deploy config, and none with a placeholder",
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

    def test_pour_card_foot_order(self):
        """The foot reads +1 can, Undo last can, Batch done, can size, Options."""
        page = (SITE / "page.html").read_text(encoding="utf-8")
        order = [page.index(f'id="{i}"') for i in ("t-plus", "t-undo", "p-go", "t-unit", "p-opts")]
        self.assertEqual(order, sorted(order), "the pour card's foot is in the set order")
        opts = page.split('<details id="p-opts">', 1)[1].split("</details>", 1)[0]
        for i in ("t-part", "p-over", "p-neck", "p-unknown", "p-extra", "p-note", "p-vol"):
            self.assertIn(f'id="{i}"', opts, f"{i} is folded into Options")

    def test_css_colours_come_from_the_theme(self):
        """Every colour in a CSS rule is a theme variable, so dark mode covers it.

        Only the variable declarations hold colours; the one exception is
        white text (#fff) on the brand and alarm colours, the same in both
        themes.
        """
        page = (SITE / "page.html").read_text(encoding="utf-8")
        css = page.split("<style>", 1)[1].split("</style>", 1)[0]
        rules = [ln for ln in css.splitlines() if not ln.strip().startswith("--")]
        stray = []
        for ln in rules:
            for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)", ln):
                ok = m.group(0) == "#fff" and re.search(r"(color|border-color|background): #fff", ln)
                ok = ok or "rgba(255, 255, 255" in m.group(0) or "rgba(29, 122, 62" in m.group(0)
                if not ok:
                    stray.append(ln.strip())
        self.assertEqual(stray, [], "a colour outside the theme variables")
        self.assertIn(':root[data-theme="dark"]', css)
        self.assertIn("prefers-color-scheme: dark", css)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_theme_setting(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "out.options = el('set-theme').innerHTML;\n"
            "out.value = el('set-theme').value;\n"
            "el('set-theme').value = 'dark';\n"
            "el('set-theme')._listeners.change[0]({});\n"
            "out.saved = JSON.parse(store.get('calib-site:prefs')).theme;\n"
            "const p2 = stub.boot(page, corePath, store);\n"
            "out.reloaded = p2.el('set-theme').value;\n"
            "console.log(JSON.stringify(out));"
        )
        for v in ("auto", "light", "dark"):
            self.assertIn(f'value="{v}"', got["options"])
        self.assertEqual(got["value"], "auto", "without a choice the device theme applies")
        self.assertEqual(got["saved"], "dark")
        self.assertEqual(got["reloaded"], "dark", "the choice stays on the device")

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
            "out.seg1 = el('t-bar').innerHTML;\n"
            "out.times1 = el('t-times').innerHTML;\n"
            "el('t-unit').value = '100';\n"
            "el('t-plus').click();\n"
            "out.count = el('t-count').textContent;\n"
            "out.plus = el('t-plus').textContent;\n"
            "out.seg = el('t-bar').innerHTML;\n"
            "out.times = el('t-times').innerHTML;\n"
            "out.done = el('t-bar').dataset.done;\n"
            "// A reload starts the size field at the last can, not the setup default.\n"
            "const p2 = stub.boot(page, corePath, store);\n"
            "out.reloaded = p2.el('t-unit').value;\n"
            "out.reloadedCount = p2.el('t-count').textContent;\n"
            "// One can past the advice keeps its cell, in the warning colour.\n"
            "p2.el('t-plus').click();\n"
            "out.overSeg = p2.el('t-bar').innerHTML;\n"
            "out.overCount = p2.el('t-count').textContent;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["shown"], "the tally must be visible after the session starts")
        self.assertEqual(got["unit0"], "200", "the setup default fills the size field")
        self.assertEqual(got["count"], "2 / 1 can · 300 L",
                         "the poured can keeps its own size in the denominator")
        self.assertEqual(got["plus"], "+1 can poured (100 L)")
        self.assertEqual(got["seg1"].count('data-state="done"'), 1, "the first can fills its cell")
        self.assertNotIn('data-state="now"', got["seg1"], "one can of the advice closes the batch")
        self.assertIn('class="pill"', got["times1"], "a counted can shows its finish time")
        self.assertRegex(got["times1"], r'class="pill">\d\d:\d\d<', "the pill carries the tap time")
        self.assertEqual(got["seg"].count('data-state="done"'), 1, "the first can stays done")
        self.assertEqual(got["seg"].count('data-state="over"'), 1,
                         "a can past the advice shows in the warning colour")
        self.assertEqual(got["times"].count('class="pill"'), 2, "each counted can keeps its time")
        self.assertEqual(got["done"], "1", "the tally closes on the last can of the batch")
        self.assertEqual(got["reloaded"], "100", "a reload keeps the last can's size")
        self.assertEqual(got["reloadedCount"], "2 / 1 can · 300 L")
        self.assertEqual(got["overSeg"].count('data-state="over"'), 2,
                         "every can past the advice shows in the warning colour")
        self.assertEqual(got["overCount"], "3 / 1 can · 400 L")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_tally_counts_poured_litres_at_their_own_size(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1000'; el('s-L').value = '12000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "out.count0 = el('t-count').textContent;\n"
            "out.note0 = el('t-target').textContent;\n"
            "el('t-plus').click();\n"
            "out.count1 = el('t-count').textContent;\n"
            "// A smaller can mid-batch: the poured 200 L keeps its own size, and the\n"
            "// two 100 L cans that complete the advice are counted, not four.\n"
            "el('t-unit').value = '100';\n"
            "el('t-plus').click();\n"
            "out.count2 = el('t-count').textContent;\n"
            "out.note2 = el('t-target').textContent;\n"
            "out.seg = el('t-bar').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["count0"], "0 / 2 cans · 0 L")
        self.assertEqual(got["note0"], "Advice ≈ 400 L = 2 × 200 L (≈ 30 mm rise).")
        self.assertEqual(got["count1"], "1 / 2 cans · 200 L")
        self.assertEqual(got["count2"], "2 / 3 cans · 300 L",
                         "the poured can keeps its own size in the denominator")
        self.assertEqual(got["seg"].count('data-state="done"'), 2, "both counted cans stay done")
        self.assertNotIn('data-state="over"', got["seg"], "the batch is not over the advice")
        self.assertEqual(got["note2"], "Advice ≈ 400 L (≈ 30 mm rise).",
                         "no multiplication when the cans no longer divide the advice evenly")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_batch_done_button_states(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '50';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "const state = () => ({text: el('p-go').textContent, ok: el('p-go')._classes.has('ok'),"
            " over: el('p-go')._classes.has('over'), quiet: el('p-go')._classes.has('quiet'),"
            " off: el('p-go').disabled});\n"
            "out.none = state();\n"
            "el('t-plus').click(); out.one = state();\n"
            "el('t-plus').click(); out.two = state();\n"
            "el('t-plus').click(); out.three = state();\n"
            "el('t-plus').click(); out.four = state();\n"
            "out.opts = el('p-opts').open;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["none"],
                         {"text": "Poured", "ok": False, "over": False, "quiet": True, "off": True},
                         "no cans and no litres: the action is faded and disabled")
        self.assertEqual(got["one"]["text"], "Batch done", "the label is short once a can is counted")
        self.assertTrue(got["one"]["quiet"], "below the advice the batch action stays quiet")
        self.assertEqual(got["two"]["quiet"], True)
        self.assertEqual(got["three"], {"text": "Batch done", "ok": True, "over": False,
                                        "quiet": False, "off": False},
                         "the reached batch is green and bold")
        self.assertTrue(got["four"]["over"], "one can past the batch is amber")
        self.assertFalse(got["four"]["ok"])
        self.assertFalse(got["opts"], "the Options block starts folded")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_undo_asks_first_and_remembers_options(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map(), asks = [];\n"
            "let yes = false;\n"
            "const p = stub.boot(page, corePath, store, { confirm: (m) => { asks.push(m); return yes; } });\n"
            "const el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "el('t-plus').click(); out.saved = el('t-count').textContent;\n"
            "el('t-undo').click(); out.kept = el('t-count').textContent;\n"
            "yes = true; el('t-undo').click(); out.removed = el('t-count').textContent;\n"
            "out.asks = asks.slice();\n"
            "// The Options fold is a device choice, like the Now card's.\n"
            "el('p-opts').open = true; el('p-opts')._listeners.toggle[0]();\n"
            "const p2 = stub.boot(page, corePath, store);\n"
            "out.reopened = p2.el('p-opts').open;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["saved"], "1 can · 200 L")
        self.assertEqual(got["kept"], "1 can · 200 L", "Keep leaves the can in the count")
        self.assertEqual(got["removed"], "0 cans · 0 L", "Undo removes it after the question")
        self.assertEqual(got["asks"], ["Remove the last can from the count?"] * 2,
                         "Undo last can asks before each removal")
        self.assertTrue(got["reopened"], "the device keeps the Options fold")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_typed_litres_replace_the_batch_volume(self):
        got = _node(
            "const p = {r: 900, L: 3000, h0: 0};\n"
            "const s = new core.Session({D: 1800, Dpm: 100, Lest: 3000, pourUnit: 200});\n"
            "const out = {};\n"
            "let V = 400, t = 0;\n"
            "s.start('400', core.levelFor(V, p)); s.dip(core.levelFor(V, p));\n"
            "function honest() {\n"
            "  for (let i = 0; i < 2; i++) s.tap(t += 60000, 200);\n"
            "  s.closeBatch(); V += 400;\n"
            "  const H = core.levelFor(V, p); let v = s.dip(H);\n"
            "  if (v.status === 'REDIP') s.dip(H);\n"
            "}\n"
            "for (let i = 0; i < 4; i++) honest();\n"
            "s.tap(t += 60000, 200); s.tap(t += 60000, 200);\n"
            "const L = s.closeBatch({volume: '600'});\n"
            "out.text = L.step.text;\n"
            "out.cans = {tapped: L.cans.tapped, typed: L.cans.typed, partial: L.cans.partial,\n"
            " taps: L.cans.taps.length, units: L.cans.units};\n"
            "V += 400;\n"
            "const H = core.levelFor(V, p);\n"
            "let v = s.dip(H); v = s.dip(H);\n"
            "out.status = v.status;\n"
            "out.hint = v.cans || null;\n"
            "out.csv = s.toRawCsv();\n"
            "// A transfer records the same typed volume on both tanks.\n"
            "const PA = {r: 900, L: 3000, h0: 0}, PB = {r: 1240, L: 5200, h0: 0};\n"
            "const X = new core.TransferSession(\n"
            "  {D: 1800, Dpm: 100, Lest: 3000, tank: 'alpha', pourUnit: 200},\n"
            "  {D: 2480, Dpm: 200, Lest: 5200, tank: 'beta', pourUnit: 200});\n"
            "X.start('?', core.brim(PA), '?', core.levelFor(2000, PB), '', null, {at: 'entrance'});\n"
            "X.dip(core.brim(PA)); X.dip(core.levelFor(2000, PB));\n"
            "let k = 0; while (X.pendingTank() === 'out' && k++ < 4) X.dip(core.brim(PA));\n"
            "k = 0; while (X.pendingTank() === 'in' && k++ < 4) X.dip(core.levelFor(2000, PB));\n"
            "X.tap(60000, 200); X.tap(120000, 200);\n"
            "X.closeBatch({volume: '487'});\n"
            "out.transfer = {a: X.out.current().step.text, b: X.in.current().step.text,\n"
            " typed: [X.out.current().cans.typed, X.in.current().cans.typed]};\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["text"], "600", "typed litres are the batch volume")
        self.assertEqual(got["cans"], {"tapped": 2, "typed": "600", "partial": False,
                                       "taps": 2, "units": [200, 200]},
                         "the can taps stay for the note and the time trend")
        self.assertEqual(got["status"], "ALARM", "a whole-can miss still alarms")
        self.assertIsNone(got["hint"], "a typed volume is measured: no count-error hint")
        self.assertIn("cans 2x200 L", got["csv"])
        self.assertIn("typed 600 L", got["csv"])
        self.assertEqual(got["transfer"], {"a": "487", "b": "487", "typed": ["487", "487"]},
                         "a transfer records the typed volume on both tanks")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_header_live_indicator(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "let clock = Date.UTC(2026, 10, 16, 8, 0, 0), beats = [];\n"
            "class FD extends Date { constructor(...a) { if (a.length) super(...a); else super(clock); } }\n"
            "FD.now = () => clock;\n"
            "const extra = () => ({ Date: FD, setInterval: (fn) => { beats.push(fn); return beats.length; } });\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store, extra()), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "// 60 s to fill a 200 L can, 30 s to empty it; the alarm 15 s before full.\n"
            "const s = JSON.parse(store.get('calib-site:active'));\n"
            "s.config.fillSeconds = { '200': 60 }; s.config.drainSeconds = { '200': 30 };\n"
            "store.set('calib-site:active', JSON.stringify(s));\n"
            "beats = []; p = stub.boot(page, corePath, store, extra()); el = p.el;\n"
            "const beat = () => { for (const fn of beats) fn(); };\n"
            "const look = () => ({ dot: el('hdr-live').className, bar: el('hdr-bar').className,"
            " w: el('hdr-bar').style.width, label: el('hdr-live')['aria-label'],"
            " liq: el('hdr-can-liq').height, tick: !el('hdr-can-tick')._classes.has('hidden') });\n"
            "beat(); out.idle = look();\n"
            "el('pt-start').click(); clock += 15000; beat(); out.fill = look();\n"
            "clock += 35000; beat(); out.pre = look();\n"
            "clock += 15000; beat(); out.full = look();\n"
            "el('t-plus').click(); clock += 15000; beat(); out.drain = look();\n"
            "clock += 20000; beat(); out.after = look();\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIn("hidden", got["idle"]["dot"], "no dot while no can is in work")
        self.assertEqual(got["fill"]["dot"], "live l-fill")
        self.assertEqual(got["fill"]["bar"], "live-bar l-fill")
        self.assertEqual(got["fill"]["w"], "25%")
        self.assertEqual(got["fill"]["label"], "Filling a 200 L can")
        self.assertEqual(got["fill"]["liq"], "3.50", "the can is a quarter full")
        self.assertFalse(got["fill"]["tick"])
        self.assertEqual(got["full"]["liq"], "14.00")
        self.assertTrue(got["full"]["tick"], "a full can shows a tick")
        self.assertEqual(got["drain"]["liq"], "7.00", "the can empties as it drains")
        self.assertEqual(got["idle"]["liq"], "0.00")
        self.assertEqual(got["pre"]["dot"], "live l-pre", "15 s before full: close the valve")
        self.assertEqual(got["full"]["dot"], "live l-full")
        self.assertEqual(got["full"]["w"], "100%")
        self.assertEqual(got["drain"]["dot"], "live l-drain", "after +1 can, the can drains")
        self.assertEqual(got["drain"]["w"], "50%", "the bar falls as the can empties")
        self.assertIn("hidden", got["after"]["dot"], "the drain time is over")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_starts_the_iphone_timer(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const start = (el) => {\n"
            "  el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "  el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "  el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "};\n"
            "// A desktop browser: no Shortcuts, so no setting.\n"
            "let p = stub.boot(page, corePath, new Map()); start(p.el);\n"
            "out.desktop = p.el('tm-ios')._classes.has('hidden');\n"
            "const loc = { protocol: 'https:', href: 'https://site.test/' };\n"
            "const iphone = { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)' };\n"
            "p = stub.boot(page, corePath, store, { location: loc, navigator: iphone }); let el = p.el; start(el);\n"
            "out.iphone = el('tm-ios')._classes.has('hidden');\n"
            "// 90 s fill, 15 s lead: the iPhone timer rings at 75 s, with the page's first alarm.\n"
            "el('tm-fill-200').value = '1:30'; el('tm-lead').value = '15';\n"
            "el('tm-ios-on').checked = true; el('tm-ios-name').value = 'Bồn timer';\n"
            "el('tm-save').click();\n"
            "const timer = () => JSON.parse(store.get('calib-site:timer') || '{}');\n"
            "el('pt-start').click(); out.url = loc.href;\n"
            "// Safari asks 'Open in Shortcuts?': the page timer waits for the answer.\n"
            "out.waiting = { pour: !!timer().pour, wait: !!timer().wait, status: el('pt-status').textContent,"
            " again: el('pt-start').textContent, alone: !el('pt-page')._classes.has('hidden'), cancel: el('pt-stop').textContent };\n"
            "p.document.hidden = true; p.document.fire('visibilitychange'); p.document.hidden = false;\n"
            "out.opened = { pour: !!timer().pour, wait: !!timer().wait };\n"
            "// The operator taps Cancel at the question: Start without iPhone timer.\n"
            "el('pt-stop').click(); el('pt-start').click(); el('pt-page').click();\n"
            "out.alone = { pour: !!timer().pour, wait: !!timer().wait };\n"
            "// A wait that is cancelled: hiding the page later starts nothing.\n"
            "el('pt-stop').click(); el('pt-start').click(); el('pt-stop').click();\n"
            "p.document.hidden = true; p.document.fire('visibilitychange'); p.document.hidden = false;\n"
            "out.cancelled = { pour: !!timer().pour, wait: !!timer().wait };\n"
            "el('tm-ios-test').click(); out.test = loc.href;\n"
            "// A Home Screen app gets no x-success: iOS cannot open it by address.\n"
            "loc.href = 'https://site.test/';\n"
            "p = stub.boot(page, corePath, store, { location: loc, navigator: Object.assign({ standalone: true }, iphone) });\n"
            "p.el('pt-stop').click(); p.el('pt-start').click(); out.standalone = loc.href;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["desktop"], "no Shortcuts setting off iOS")
        self.assertFalse(got["iphone"])
        self.assertEqual(
            got["url"],
            "shortcuts://x-callback-url/run-shortcut?name=B%E1%BB%93n%20timer&input=text&text=75"
            "&x-success=https%3A%2F%2Fsite.test%2F",
        )
        self.assertEqual(got["waiting"]["pour"], False, "no page timer before Shortcuts opens")
        self.assertTrue(got["waiting"]["wait"])
        self.assertIn("Waiting for Shortcuts", got["waiting"]["status"])
        self.assertEqual(got["waiting"]["again"], "Open Shortcuts again")
        self.assertTrue(got["waiting"]["alone"])
        self.assertEqual(got["waiting"]["cancel"], "Cancel")
        self.assertEqual(got["opened"], {"pour": True, "wait": False}, "Shortcuts opened: the page timer starts")
        self.assertEqual(got["alone"], {"pour": True, "wait": False})
        self.assertEqual(got["cancelled"], {"pour": False, "wait": False})
        self.assertIn("text=10&", got["test"])
        self.assertTrue(got["standalone"].endswith("text=75"), got["standalone"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_iphone_timer_silences_the_page_alarm(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "let clock = Date.UTC(2026, 10, 16, 8, 0, 0), beats = [];\n"
            "class FD extends Date { constructor(...a) { if (a.length) super(...a); else super(clock); } }\n"
            "FD.now = () => clock;\n"
            "const loc = { protocol: 'https:', href: 'https://site.test/' };\n"
            "const extra = { Date: FD, location: loc, setInterval: (fn) => { beats.push(fn); return 1; },\n"
            "  navigator: { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)' } };\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store, extra), el = p.el;\n"
            "const beat = () => { for (const fn of beats) fn(); };\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "el('tm-fill-200').value = '1:00'; el('tm-lead').value = '15'; el('tm-ios-on').checked = true; el('tm-save').click();\n"
            "const banner = () => !el('alarm')._classes.has('hidden');\n"
            "// Shortcuts opens: the iPhone timer runs, the page stays quiet.\n"
            "el('pt-start').click(); p.document.hidden = true; p.document.fire('visibilitychange'); p.document.hidden = false;\n"
            "clock += 5000; beat(); out.status = el('pt-status').textContent;\n"
            "clock += 45000; beat(); out.pre = banner();\n"
            "clock += 15000; beat(); out.full = banner(); out.box = el('pt').className;\n"
            "// Without the iPhone timer the page alarm rings as before.\n"
            "el('pt-stop').click(); el('pt-start').click(); el('pt-page').click();\n"
            "clock += 50000; beat(); out.alone = banner();\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIn("The iPhone timer rings at 0:15 left.", got["status"])
        self.assertFalse(got["pre"], "no close-the-valve banner: the iPhone rings")
        self.assertFalse(got["full"], "no can-full banner either")
        self.assertEqual(got["box"], "timer done", "the panel still shows the can is full")
        self.assertTrue(got["alone"], "a page timer alone keeps its alarm")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_swipe_changes_the_tab(self):
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
            "const fire = (type, ev) => { for (const fn of el('main')._listeners[type] || []) fn(ev); };\n"
            "const swipe = (x0, y0, x1, y1, target) => {\n"
            "  const t = target || el('live');\n"
            "  fire('touchstart', { target: t, touches: [{ clientX: x0, clientY: y0 }] });\n"
            "  fire('touchend', { target: t, changedTouches: [{ clientX: x1, clientY: y1 }] });\n"
            "};\n"
            "const shown = () => ['live', 'log', 'shell', 'settings', 'files', 'replay', 'help']"
            ".filter((id) => !el(id)._classes.has('hidden'));\n"
            "swipe(250, 300, 120, 310); out.next = shown();\n"
            "swipe(250, 300, 120, 310); out.next2 = shown();\n"
            "swipe(120, 300, 250, 300); out.back = shown();\n"
            "swipe(250, 300, 200, 300); out.short = shown();\n"
            "swipe(250, 300, 150, 400); out.scroll = shown();\n"
            "swipe(250, 300, 120, 300, { tagName: 'INPUT' }); out.input = shown();\n"
            "swipe(120, 300, 250, 300); swipe(120, 300, 250, 300); out.first = shown();\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["next"], ["log"], "a swipe to the left goes to the next tab")
        self.assertEqual(got["next2"], ["shell"])
        self.assertEqual(got["back"], ["log"], "a swipe to the right goes back")
        self.assertEqual(got["short"], ["log"], "a short drag is not a swipe")
        self.assertEqual(got["scroll"], ["log"], "a mostly vertical drag is a scroll")
        self.assertEqual(got["input"], ["log"], "a drag in a field is not a swipe")
        self.assertEqual(got["first"], ["live"], "the first tab is the end: no wrap")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_can_size_steps_by_the_pour_unit(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '50';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "out.start = [el('t-unit').value, el('t-dec').textContent, el('t-inc').textContent, el('t-dec').disabled];\n"
            "el('t-inc').click(); el('t-inc').click(); el('t-inc').click();\n"
            "out.up = [el('t-unit').value, el('t-plus').textContent, el('t-dec').disabled];\n"
            "el('t-dec').click(); out.down = el('t-unit').value;\n"
            "// A typed size off the grid steps from where it is, never below one step.\n"
            "el('t-unit').value = '70'; el('t-unit')._listeners.input[0]({});\n"
            "el('t-dec').click(); out.off = el('t-unit').value; el('t-dec').click(); out.floor = el('t-unit').value;\n"
            "p = stub.boot(page, corePath, store); out.reloaded = p.el('t-unit').value;\n"
            "// No pour unit: no step buttons.\n"
            "const q = stub.boot(page, corePath, new Map()), e = q.el;\n"
            "e('s-tank').value = 't2'; e('s-D').value = '1800'; e('s-L').value = '3000'; e('s-dip').value = '400';\n"
            "e('s-go').click(); e('d-val').value = '400'; e('d-go').click();\n"
            "out.none = [e('t-dec')._classes.has('hidden'), e('t-inc')._classes.has('hidden')];\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["start"], ["50", "−50 L", "+50 L", True], "at one step, − is off")
        self.assertEqual(got["up"], ["200", "+1 can poured (200 L)", False])
        self.assertEqual(got["down"], "150")
        self.assertEqual(got["off"], "50", "70 − 50 = 20 is below one step: the floor is 50")
        self.assertEqual(got["floor"], "50")
        self.assertEqual(got["reloaded"], "50", "a stepped size survives a reload")
        self.assertEqual(got["none"], [True, True])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_can_size_survives_a_reload(self):
        """A size chosen before the first can of a batch survives a reload.

        The return from Shortcuts (x-success) reloads the page, so this is
        also the iPhone timer path.
        """
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '50';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "// Typed, no can counted yet.\n"
            "el('t-unit').value = '200'; el('t-unit')._listeners.input[0]({});\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.typed = el('t-unit').value;\n"
            "// Tapped on a size button: the setup default again.\n"
            "el('t-units')._listeners.click[0]({ target: { closest: () => ({ dataset: { unit: '50' } }) } });\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.button = el('t-unit').value;\n"
            "// A size chosen after a counted can of another size wins too.\n"
            "el('t-plus').click(); el('t-unit').value = '100'; el('t-unit')._listeners.input[0]({});\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.afterCan = el('t-unit').value;\n"
            "// A new campaign starts at its own default.\n"
            "el('f-new').click();\n"
            "el('s-tank').value = 't2'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '25';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "out.fresh = el('t-unit').value;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["typed"], "200", "a typed size survives a reload")
        self.assertEqual(got["button"], "50")
        self.assertEqual(got["afterCan"], "100")
        self.assertEqual(got["fresh"], "25", "a new campaign takes its own default")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_dip_panel_shows_the_expected_level(self):
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
            "out.first = el('dip-expect-a').textContent;\n"
            "el('d-val').value = '400'; el('d-go').click();\n"
            "el('t-plus').click(); el('p-go').click();\n"
            "out.pour = el('dip-expect-a').textContent;\n"
            "// A reading far off asks for a repeat: the repeat stays blind.\n"
            "el('d-val').value = '600'; el('d-go').click();\n"
            "out.repeat = el('dip-expect-a').textContent;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIn("none (the first level)", got["first"])
        self.assertRegex(got["pour"], r"^Expected level: \d+(\.\d)? mm ± \d+(\.\d)? mm \(2σ\)")
        self.assertIn("hidden", got["repeat"], "a repeat reading must stay blind (§10a.6)")

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
        # A half-typed start level has no batch yet, and a decided start level
        # has no can: both say pour to predict, as the tile does.
        self.assertIn("pour to predict", got["pending"])
        self.assertIn("pour to predict", got["empty"], "no plan and no can: the line asks for a pour")
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
        self.assertTrue(got["overflow"].startswith("After this pour (99999 L):"), got["overflow"])
        self.assertIn("≥ 1800.0 mm", got["overflow"], "past the brim: the limit, marked")
        self.assertIn("more than the gap", got["overflow"])
        self.assertTrue(got["can"].startswith("After this pour (200 L):"), got["can"])
        self.assertIn("part can", got["part"])
        self.assertTrue(got["closed"].startswith("After this pour (200 L):"), got["closed"])
        self.assertIn("mm ±", got["closed"], "while the dip waits the line shows the expected dip")

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
    def test_page_drain_time_and_tap_check(self):
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
            "el('tm-fill-200').value = '1:30'; el('tm-drain-200').value = '0:40'; el('tm-save').click();\n"
            "out.cfg = JSON.parse(store.get('calib-site:active')).config.drainSeconds;\n"
            "out.eta = el('now-eta').innerHTML; out.useHidden = el('eta-use')._classes.has('hidden');\n"
            "// Two taps 150 s apart: the check says 2:30, the button offers drain 1:00.\n"
            "el('t-plus').click(); el('t-plus').click();\n"
            "const s = JSON.parse(store.get('calib-site:active'));\n"
            "s.batch.cans[0].t = Date.now() - 150000; s.batch.cans[1].t = Date.now();\n"
            "store.set('calib-site:active', JSON.stringify(s));\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.eta2 = el('now-eta').innerHTML;\n"
            "out.use = {hidden: el('eta-use')._classes.has('hidden'), text: el('eta-use').textContent};\n"
            "el('eta-use').click();\n"
            "out.after = JSON.parse(store.get('calib-site:active')).config.drainSeconds;\n"
            "out.useAfter = el('eta-use')._classes.has('hidden');\n"
            "out.eta3 = el('now-eta').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["cfg"], {"200": 40})
        self.assertIn("2:10 per can (fill 1:30 + drain 0:40)", got["eta"])
        self.assertIn("no settle and no dip time", got["eta"])
        self.assertTrue(got["useHidden"], "no taps, no button")
        self.assertIn("Your trend for 200 L cans (1 can, the most recent weigh most) · cycle 2:30", got["eta2"])
        self.assertIn("2:10 per can", got["eta2"], "a tap gap does not replace a typed fill + drain")
        self.assertFalse(got["use"]["hidden"])
        self.assertEqual(got["use"]["text"], "Use the trend: drain 1:00 per 200 L can")
        self.assertEqual(got["after"], {"200": 60})
        self.assertTrue(got["useAfter"], "once adopted, the button goes away")
        self.assertIn("2:30 per can (fill 1:30 + drain 1:00)", got["eta3"])

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
        self.assertIn("2:10 per can (default fill 1:30 + drain 0:40", got["etaBefore"],
                      "no typed time and no trend: a default per can, marked a rough guess")
        self.assertIn("To half", got["etaBefore"])
        self.assertIn("To brim", got["etaBefore"])
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
        self.assertEqual(got["cfgKeys"], ["alarmLead", "dipSeconds", "drainSeconds", "fillSeconds", "settleSeconds"])
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
    def test_page_logs_the_time_of_each_recording(self):
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
            "el('p-vol').value = '400'; el('p-go').click();\n"
            "el('d-val').value = '800'; el('d-go').click();\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "out.table = el('log-table').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIn("<th class=l>time</th>", got["table"])
        self.assertRegex(got["table"], r"read \d\d:\d\d / \d\d:\d\d", "both start readings carry a time")
        self.assertRegex(got["table"], r"poured \d\d:\d\d", "the pour carries a time")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_selects_a_level_in_table_and_chart(self):
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
            "for (const h of ['489', '573', '651']) {\n"
            "  el('p-vol').value = '400'; el('p-go').click();\n"
            "  el('d-val').value = h; el('d-go').click();\n"
            "  if (!el('dip-card')._classes.has('hidden')) { el('d-val').value = h; el('d-go').click(); }\n"
            "}\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "const rows = [...el('chart').innerHTML.matchAll(/data-row=\"(\\d+)\"/g)].map((m) => m[1]);\n"
            "out.rows = rows;\n"
            "const r = rows[rows.length - 1];\n"
            "// A tap on a table row: the row and its mark are selected.\n"
            "const rowTarget = { closest: (s) => (s === 'tr[data-row]' ? { dataset: { row: r } } : null) };\n"
            "el('log-table')._listeners.click[0]({ target: rowTarget });\n"
            "out.tableSel = (el('log-table').innerHTML.match(/<tr [^>]*class=\"sel\"[^>]*>/g) || []);\n"
            "out.chartSel = (el('chart').innerHTML.match(/class=\"mark sel\" data-row=\"(\\d+)\"/) || [])[1];\n"
            "out.note = el('chart-sel').textContent;\n"
            "// A tap on the same mark clears it.\n"
            "const markTarget = (row) => ({ closest: (s) => (s === '[data-row]' ? { dataset: { row } } : null) });\n"
            "el('chart')._listeners.click[0]({ target: markTarget(r) });\n"
            "out.cleared = /class=\"sel\"/.test(el('log-table').innerHTML) || /mark sel/.test(el('chart').innerHTML);\n"
            "// A tap on another mark selects its row.\n"
            "el('chart')._listeners.click[0]({ target: markTarget(rows[0]) });\n"
            "out.fromChart = (el('log-table').innerHTML.match(/<tr id=\"log-row-(\\d+)\"[^>]*class=\"sel\"/) || [])[1];\n"
            "// A tap on the empty chart clears the selection.\n"
            "el('chart')._listeners.click[0]({ target: { closest: () => null } });\n"
            "out.blank = /class=\"sel\"/.test(el('log-table').innerHTML);\n"
            "// A row without a mark in this chart (the start level) says so.\n"
            "el('log-table')._listeners.click[0]({ target: { closest: (s) => (s === 'tr[data-row]' ? { dataset: { row: '1' } } : null) } });\n"
            "out.noMark = el('chart-sel').textContent;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertGreaterEqual(len(got["rows"]), 2, got["rows"])
        last = got["rows"][-1]
        self.assertEqual(len(got["tableSel"]), 1)
        self.assertIn(f'data-row="{last}"', got["tableSel"][0])
        self.assertEqual(got["chartSel"], last)
        self.assertIn(f"Selected: row {last}", got["note"])
        self.assertFalse(got["cleared"], "a second tap on the same mark clears the selection")
        self.assertEqual(got["fromChart"], got["rows"][0])
        self.assertFalse(got["blank"], "a tap on the empty chart clears the selection")
        self.assertIn("row 1 has no mark in this chart", got["noMark"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_simple_mode(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "// The header switch toggles; aria-pressed is true in simple mode.\n"
            "const mode = (m) => { if (el('hdr-mode')['aria-pressed'] !== String(m === 'simple')) el('hdr-mode').click(); };\n"
            "const grab = () => ({ kv: el('now-kv').innerHTML, advice: el('now-advice').textContent,"
            " target: el('t-target').textContent, verdict: el('verdict').innerHTML,"
            " expect: el('dip-expect-a').textContent, drift: el('now-drift').textContent });\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "out.verbose = grab();\n"
            "out.btnV = [el('hdr-mode').textContent, el('hdr-mode')['aria-pressed'], el('hdr-mode')._classes.has('hidden')];\n"
            "mode('simple');\n"
            "out.simple = grab();\n"
            "out.btnS = [el('hdr-mode').textContent, el('hdr-mode')['aria-pressed']];\n"
            "out.saved = JSON.parse(store.get('calib-site:prefs')).mode;\n"
            "el('t-plus').click(); el('t-plus').click(); el('p-go').click();\n"
            "out.dip = grab();\n"
            "// A reload keeps the mode.\n"
            "const p2 = stub.boot(page, corePath, store);\n"
            "out.reloaded = p2.el('dip-expect-a').textContent;\n"
            "mode('verbose');\n"
            "out.back = grab();\n"
            "// A transfer renders in simple mode too.\n"
            "const s3 = new Map([['calib-site:prefs', JSON.stringify({ mode: 'simple' })]]);\n"
            "const q = stub.boot(page, corePath, s3), e3 = q.el;\n"
            "e3('s-dir-transfer').click();\n"
            "e3('s-tank').value = 'alpha'; e3('s-D').value = '1800'; e3('s-L').value = '3000';\n"
            "e3('sB-tank').value = 'beta'; e3('sB-D').value = '2480'; e3('sB-L').value = '5200';\n"
            "e3('s-dip').value = '1800'; e3('sB-dip').value = '400'; e3('s-unit').value = '200';\n"
            "e3('s-go').click();\n"
            "e3('d-val').value = '1800'; e3('d-val-b').value = '400'; e3('d-go-a').click(); e3('d-go-b').click();\n"
            "out.transfer = { kv: e3('now-kv').innerHTML, advice: e3('now-advice').textContent };\n"
            "console.log(JSON.stringify(out));"
        )
        v, s = got["verbose"], got["simple"]
        self.assertIn("liquid (running shell)", v["kv"])
        self.assertNotIn("liquid (running shell)", s["kv"], "simple mode shows the level only")
        self.assertIn("<dt>level</dt>", s["kv"])
        self.assertEqual(s["advice"], "", "no advised next pour and no prediction for it")
        self.assertEqual(v["advice"], "")
        self.assertEqual(s["target"], "Target: ≈ 200 L",
                         "one can of the advice: no multiplication to show")
        self.assertNotIn("<p>", s["verdict"], "simple mode drops the verdict message")
        self.assertIn("<h3>", s["verdict"])
        self.assertEqual(got["saved"], "simple")
        self.assertEqual(got["btnV"], ["Aa", "false", False], "the header switch shows Aa in verbose mode")
        self.assertEqual(got["btnS"], ["A", "true"])
        self.assertRegex(got["dip"]["expect"], r"^Expect \d+(\.\d)? ± \d+(\.\d)? mm$")
        self.assertRegex(got["reloaded"], r"^Expect ")
        self.assertIn("liquid (running shell)", got["back"]["kv"], "verbose mode comes back in full")
        self.assertRegex(got["back"]["expect"], r"^Expected level: ")
        self.assertIn("<dt>level</dt>", got["transfer"]["kv"])
        self.assertNotIn("liquid", got["transfer"]["kv"])
        self.assertNotIn("Next", got["transfer"]["advice"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_now_card_folds_and_keeps_warnings(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "out.open0 = el('now-card').open;\n"
            "// A level 20 mm under the brim of a 1800 mm tank: the warning stays.\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '1780'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '1780'; el('d-go').click();\n"
            "out.advice = el('now-advice').textContent;\n"
            "out.sum = el('now-sum').textContent; out.sumClass = el('now-sum').className;\n"
            "el('now-card').open = false; el('now-card')._listeners.toggle[0]({});\n"
            "out.saved = JSON.parse(store.get('calib-site:prefs')).nowOpen;\n"
            "p = stub.boot(page, corePath, store); out.reloaded = p.el('now-card').open;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["open0"], "the Now card starts open")
        self.assertIn("Near the brim", got["advice"])
        self.assertIn("halve the pour", got["advice"])
        self.assertNotIn("Next pour", got["advice"])
        self.assertEqual(got["sum"], "1780.0 mm · near the brim", "the folded line keeps the level and the warning")
        self.assertEqual(got["sumClass"], "now-sum warn")
        self.assertFalse(got["saved"])
        self.assertFalse(got["reloaded"], "the device keeps the card folded")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_core_exports_the_times_in_the_note(self):
        got = _node(
            "const s = new core.Session({ D: 1800, Lest: 3000 });\n"
            "const t0 = new Date(2026, 10, 16, 9, 5).getTime();\n"
            "s.start('?', 400, '', t0); s.dip(400, t0 + 300000);\n"
            "const L = s.pour('400'); L.pourTime = t0 + 600000;\n"
            "s.dip(500, t0 + 900000);\n"
            "const replay = core.replayRows([{ step: '?', H: 400 }, { step: '400', H: 500 }], { D: 1800, Lest: 3000 });\n"
            "console.log(JSON.stringify({ csv: s.toRawCsv().split('\\n'), replay: replay.session.toRawCsv().split('\\n') }));"
        )
        self.assertIn("date 2026-11-16 read 09:05/09:10", got["csv"][1])
        self.assertIn("poured 09:15 read 09:20", got["csv"][2])
        self.assertNotIn("read ", got["replay"][1], "no time recorded, no time in the note")

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
            "out.roles = [el('dip-role')._classes.has('hidden'), el('dip-role-b')._classes.has('hidden'),"
            " el('d-val')._classes.has('dip-out'), el('d-val-b')._classes.has('dip-in'),"
            " el('d-go')._classes.has('hidden'), el('d-go-a')._classes.has('hidden'),"
            " el('dip-card')._classes.has('two')];\n"
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
            "out.dir = el('set-dir').textContent; out.brim = el('set-brim').value; out.brimPm = el('set-brimpm').value;\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "out.table = el('log-table').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["atHiddenFill"], "a fill has no start-level choice")
        self.assertTrue(got["atShown"], "a drain asks where the first level stands")
        self.assertEqual(got["step"], "?", "a drain starts with an unknown volume")
        self.assertEqual(got["pressed"], "true")
        self.assertEqual(got["atPressed"], "true", "the start at the brim is the default")
        self.assertIn("in the tank", got["stepLabel"])
        self.assertIn("Prime the pump", got["firstNote"])
        self.assertEqual(got["cfg"], {"direction": "drain", "brimStart": 1800, "brimPm": 6})
        self.assertEqual(got["csv1"], ["at brim"])
        self.assertEqual(got["roles"], [True, True, False, False, False, True, False],
                         "a single tank shows no role badge, no coloured edge, and one button")
        self.assertEqual(got["plus"], "+1 can full (200 L)")
        self.assertEqual(got["go"], "Drained")
        self.assertEqual(got["title"], "1 · Drain")
        self.assertEqual(got["over"], "level still in the neck")
        self.assertEqual(got["part"], "pump lost suction: last can part")
        self.assertIn("from the tank", got["help"])
        self.assertIn("drain", got["phase"])
        self.assertIn("<dt>suction floor</dt><dd>65 mm · ≈ 1735 mm to go", got["kv"])
        self.assertIn("L to pump", got["kv"])
        self.assertEqual(got["advice"], "", "the Now card predicts this batch only, not an advised next drain")
        self.assertTrue(got["pred"].startswith("After this drain (400 L):"), got["pred"])
        self.assertIn("mm fall", got["pred"])
        self.assertIn("−", got["pred"].split("(2σ)")[1], "the fall is negative")
        self.assertIn("L left", got["pred"])
        self.assertIn("runs dry", got["dry"])
        self.assertIn("still in the neck", got["neckLine"])
        self.assertEqual(got["batch"], "Batch done")

        self.assertIn("mm fall", got["tally"])
        self.assertIn("draining 200 L", got["dip"])
        self.assertIn("drain", got["dir"])
        self.assertIn("at the brim (brim B = 1800.0 mm)", got["dir"])
        self.assertEqual(got["brim"], "", "no brim typed at setup")
        self.assertEqual(got["brimPm"], "6", "the brim ± is the campaign's own, 6 mm by default")
        self.assertIn("drained L", got["table"])


# A synthetic transfer campaign (§3.12): two known shells, one shared batch.
# Tank A (drain) starts full at the brim; tank B (fill) starts with
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
        self.assertIn("at brim", got["csvA"])
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

    def test_transfer_dip_both(self):
        got = _node(
            r"""
const X = new core.TransferSession(
  {D: 1800, Dpm: 200, Lest: 3000, tank: 'alpha', pourUnit: 200},
  {D: 2480, Dpm: 200, Lest: 5200, tank: 'beta', pourUnit: 200});
X.start('?', 1800, '?', 400, '', null, {at: 'entrance'});
const out = {};
const dips = (S) => [S.out.current().dips.length, S.in.current().dips.length];
out.start = dips(X).concat([X.pendingTanks()]);
// One field only: the other tank keeps waiting.
X.dipBoth(1800, null);
out.one = dips(X).concat([X.pendingTanks()]);
X.dipBoth(null, 400);
out.oneB = dips(X).concat([X.pendingTanks()]);
out.states = [X.out.current().state, X.in.current().state];
// Both fields at once on a fresh session: A first, then B.
const Y = new core.TransferSession(
  {D: 1800, Dpm: 200, Lest: 3000, tank: 'alpha', pourUnit: 200},
  {D: 2480, Dpm: 200, Lest: 5200, tank: 'beta', pourUnit: 200});
Y.start('?', 1800, '?', 400, '', null, {at: 'entrance'});
Y.dipBoth(1800, 400);
out.both = dips(Y).concat([Y.pendingTanks()]);
// A value for a decided tank is refused before anything is recorded.
out.err = null;
try { X.dipBoth(1700, 300); } catch (e) { out.err = e.message; }
out.after = dips(X);
out.blank = null;
try { X.dipBoth(null, ''); } catch (e) { out.blank = e.message; }
// A typo in one field records neither reading.
const Z = new core.TransferSession(
  {D: 1800, Dpm: 200, Lest: 3000, tank: 'alpha', pourUnit: 200},
  {D: 2480, Dpm: 200, Lest: 5200, tank: 'beta', pourUnit: 200});
Z.start('?', 1800, '?', 400, '', null, {at: 'entrance'});
out.bad = null;
try { Z.dipBoth(1800, 'abc'); } catch (e) { out.bad = e.message; }
out.badAfter = dips(Z);
// The current tank takes the override while both levels wait for a reading.
const W = new core.TransferSession(
  {D: 1800, Dpm: 200, Lest: 3000, tank: 'alpha', pourUnit: 200},
  {D: 2480, Dpm: 200, Lest: 5200, tank: 'beta', pourUnit: 200});
W.start('?', 1800, '?', 400, '', null, {at: 'entrance'});
W.dipBoth(1800, 400);   // the start levels are decided
W.tap(1, 200); W.tap(2, 200); W.tap(3, 200);
W.closeBatch({});
W.dipBoth(1000, 100);   // first readings, both miss: both wait
W.dipBoth(1003, 103);   // the readings disagree: both wait with two readings
out.wait = [W.pendingTanks(), W.out.current().dips.length, W.in.current().dips.length];
W.active = 'in';
W.override('accepted after inspection');
out.over = [W.out.current().state, W.in.current().state];
console.log(JSON.stringify(out));
"""
        )
        self.assertEqual(got["start"], [1, 1, ["out", "in"]], "start takes one reading per tank")
        self.assertEqual(got["one"], [2, 1, ["in"]], "only A was filled: B keeps waiting")
        self.assertEqual(got["oneB"], [2, 2, []], "B's reading alone finishes the batch")
        self.assertEqual(got["states"], ["start", "start"])
        self.assertEqual(got["both"], [2, 2, []], "both readings in one call")
        self.assertIn("alpha is decided", got["err"])
        self.assertEqual(got["after"], [2, 2], "a refused entry records nothing")
        self.assertIn("at least one reading", got["blank"])
        self.assertIn("cannot read dip", got["bad"])
        self.assertEqual(got["badAfter"], [1, 1], "a bad field records neither reading")
        self.assertEqual(got["wait"], [["out", "in"], 2, 2], "both levels wait on disagreeing readings")
        self.assertEqual(got["over"], ["pending", "override"],
                         "the current tank takes the override")

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
            " tiles: el('tiles').innerHTML, tilesHidden: el('tiles')._classes.has('hidden'),"
            " titleHidden: el('hdr-title')._classes.has('hidden'),"
            " count: el('hdr-count').textContent, now: el('now-kv').innerHTML};\n"
            "out.dipA = {a: el('dip-label').textContent, b: el('dip-label-b').textContent,"
            " row: !el('dip-row-b')._classes.has('hidden'),"
            " two: el('dip-card')._classes.has('two'), one: !el('d-go')._classes.has('hidden'),"
            " btnA: el('d-go-a').textContent, btnB: el('d-go-b').textContent,"
            " batch: !el('dip-batch')._classes.has('hidden'), batchText: el('dip-batch-text').textContent,"
            " legend: !el('dip-legend')._classes.has('hidden'),"
            " chip: !el('dip-chip-a')._classes.has('hidden'),"
            " tank: !el('dip-tank-a')._classes.has('hidden'),"
            " wm: !el('dip-wm')._classes.has('hidden'),"
            " waterA: el('dip-tank-a-water').getAttribute('height'),"
            " waterB: el('dip-tank-b-water').getAttribute('height'),"
            " role: el('dip-role').textContent, roleB: el('dip-role-b').textContent,"
            " roleHidden: el('dip-role')._classes.has('hidden'),"
            " roleBHidden: el('dip-role-b')._classes.has('hidden'),"
            " edgeOut: el('d-val')._classes.has('dip-out'),"
            " edgeIn: el('d-val-b')._classes.has('dip-in')};\n"
            "const dips = () => { const c = JSON.parse(store.get('calib-site:active'));"
            " return [c.out.levels[0].dips.length, c.in.levels[0].dips.length]; };\n"
            "// One button per tank: each submits only its own field.\n"
            "el('d-val').value = '1800'; el('d-val-b').value = '400';\n"
            "el('d-go-a').click(); out.afterA = dips(); out.keepB = el('d-val-b').value;\n"
            "el('d-go-b').click(); out.afterB = dips();\n"
            "out.card = {title: el('pour-title').textContent, plus: el('t-plus').textContent,"
            " neck: !el('p-neck-wrap')._classes.has('hidden'), over: el('p-over-text').textContent,"
            " neckText: el('p-neck-text').textContent, advice: el('now-advice').textContent};\n"
            "el('t-plus').click(); el('t-plus').click(); el('t-plus').click();\n"
            "out.go = el('p-go').textContent;\n"
            "el('p-go').click();\n"
            "out.dip1 = {a: el('dip-label').textContent, b: el('dip-label-b').textContent,"
            " btnA: el('d-go-a').textContent, btnB: el('d-go-b').textContent,"
            " two: el('dip-card')._classes.has('two'), batchText: el('dip-batch-text').textContent};\n"
            "el('d-val').value = '1700'; el('d-val-b').value = '500';\n"
            "el('d-go-a').click();\n"
            "el('d-go-b').click();\n"
            "if (!el('d-go-a').disabled) { el('d-val').value = '1700'; el('d-go-a').click(); }\n"
            "if (!el('d-go-b').disabled) { el('d-val-b').value = '500'; el('d-go-b').click(); }\n"
            "out.verdict = el('verdict').innerHTML;\n"
            "out.actions = [el('a-redip').textContent, el('a-override').textContent];\n"
            "const cfg = JSON.parse(store.get('calib-site:active'));\n"
            "out.saved = {kind: cfg.kind, levels: [cfg.out.levels.length, cfg.in.levels.length],"
            " pour: [cfg.out.levels[1].pourTime != null, cfg.in.levels[1].pourTime != null]};\n"
            "// Files: one raw file per tank.\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'files' } }) } });\n"
            "out.files = {a: el('f-csv').textContent, b: !el('f-csv-b')._classes.has('hidden')};\n"
            "// The tank tiles turn the log, the shell and the settings to tank B.\n"
            "el('tiles')._listeners.click[0]({ target: { closest: () => ({ dataset: { tank: 'in' } }) } });\n"
            "// The A button still exports tank A's file with B active.\n"
            "el('f-csv').click(); el('f-csv-b').click();\n"
            "out.export = {a: p.downloads[p.downloads.length - 2].download,"
            " b: p.downloads[p.downloads.length - 1].download,"
            " label: el('f-csv').textContent, show: el('f-show').textContent};\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "out.log = {title: el('log-title').textContent, chart: el('chart-title').textContent,"
            " tiles: el('tiles').innerHTML, table: el('log-table').innerHTML,"
            " now: el('now-kv').innerHTML};\n"
            "// A tap on the tiles turns its table and chart to tank A.\n"
            "el('tiles')._listeners.click[0]({ target: { closest: () => ({ dataset: { tank: 'out' } }) } });\n"
            "out.logA = {title: el('log-title').textContent, chart: el('chart-title').textContent,"
            " table: el('log-table').innerHTML, tiles: el('tiles').innerHTML};\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'shell' } }) } });\n"
            "out.shell = el('shell-kv').innerHTML;\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'settings' } }) } });\n"
            "out.settings = {title: el('set-campaign-title').textContent, dir: el('set-dir').textContent};\n"
            "// The tiles stay on Replay, read-only: a tap changes nothing.\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'replay' } }) } });\n"
            "const beforeReplay = el('tiles').innerHTML;\n"
            "el('tiles')._listeners.click[0]({ target: { closest: () => ({ dataset: { tank: 'in' } }) } });\n"
            "out.hdrReplay = [!el('tiles')._classes.has('hidden'), el('hdr-title')._classes.has('hidden'),"
            " el('hdr-title').textContent, beforeReplay === el('tiles').innerHTML];\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["setup"]["b"], "tank B's fields show")
        self.assertTrue(got["setup"]["at"], "tank A is a drain: the start-level choice shows")
        self.assertIn("Two tanks, one water", got["setup"]["note"])
        self.assertIn("Tank A name", got["setup"]["a"])
        self.assertEqual(got["setup"]["dip"], "Tank A first reading, mm")
        self.assertIn("Prime the pump", got["setup"]["first"])
        self.assertEqual(got["hdr"]["title"], "alpha → beta")
        self.assertFalse(got["hdr"]["titleHidden"], "the title stays: the tiles name both tanks")
        self.assertNotIn("transfer", got["hdr"]["phase"], "the header stays one slim line")
        self.assertFalse(got["hdr"]["tilesHidden"], "the tiles show")
        self.assertIn('data-tank="out"', got["hdr"]["tiles"])
        self.assertIn('data-tank="in"', got["hdr"]["tiles"])
        self.assertIn('aria-pressed="true"', got["hdr"]["tiles"], "tank A is the current tank")
        self.assertIn('data-dir="down"', got["hdr"]["tiles"], "A pumps out")
        self.assertIn('data-dir="up"', got["hdr"]["tiles"], "B pours in")
        self.assertIn("arw down", got["hdr"]["tiles"])
        self.assertIn("arw up", got["hdr"]["tiles"])
        self.assertIn('class="wave"', got["hdr"]["tiles"], "the arrow has its wave")
        self.assertIn('<span class="wv"><svg viewBox="0 0 40 6"', got["hdr"]["tiles"],
                      "the wave sits in its own clipped box, twice as wide, so it can flow")
        self.assertIn("alpha", got["hdr"]["tiles"])
        self.assertIn("beta", got["hdr"]["tiles"])
        self.assertIn("no prediction (the first level)", got["hdr"]["tiles"])
        self.assertNotIn("extra dip", got["hdr"]["count"], "no extra dips yet: none shown")
        self.assertLess(got["hdr"]["now"].index("current"), got["hdr"]["now"].index("beta"),
                        "the current marker sits on tank A")
        self.assertNotIn("<dd></dd>", got["hdr"]["now"], "no empty cell shifts the Now grid")
        self.assertIn("alpha: next reading", got["dipA"]["a"])
        self.assertIn("beta: next reading", got["dipA"]["b"], "both tanks ask for a reading at once")
        self.assertTrue(got["dipA"]["row"], "the second field shows")
        self.assertTrue(got["dipA"]["two"], "each tank has its own button")
        self.assertFalse(got["dipA"]["one"], "the single button hides")
        self.assertTrue(got["dipA"]["batch"], "the shared batch header shows")
        self.assertIn("Both start levels", got["dipA"]["batchText"])
        self.assertTrue(got["dipA"]["legend"], "the role legend shows")
        self.assertTrue(got["dipA"]["chip"], "the A letter chip shows")
        self.assertTrue(got["dipA"]["tank"], "the tank pictogram shows")
        self.assertTrue(got["dipA"]["wm"], "the input arrow watermark shows")
        self.assertNotEqual(got["dipA"]["waterA"], got["dipA"]["waterB"],
                            "the two tank icons show different levels")
        self.assertEqual(got["dipA"]["btnA"], "Check alpha")
        self.assertEqual(got["dipA"]["btnB"], "Check beta")
        self.assertIn("pump out", got["dipA"]["role"], "tank A's field is marked pump out")
        self.assertIn("pour in", got["dipA"]["roleB"], "tank B's field is marked pour in")
        self.assertTrue(got["dipA"]["role"].startswith("↑"), "the pump-out arrow points up, out of the tank")
        self.assertTrue(got["dipA"]["roleB"].startswith("↓"), "the pour-in arrow points down, into the tank")
        self.assertFalse(got["dipA"]["roleHidden"])
        self.assertFalse(got["dipA"]["roleBHidden"])
        self.assertTrue(got["dipA"]["edgeOut"], "tank A's field has its own edge colour")
        self.assertTrue(got["dipA"]["edgeIn"], "tank B's field has its own edge colour")
        self.assertEqual(got["afterA"], [2, 1], "the A button submits only tank A")
        self.assertEqual(got["keepB"], "400", "tank B's field keeps its value")
        self.assertEqual(got["afterB"], [2, 2], "the B button submits only tank B")
        self.assertEqual(got["card"]["title"], "1 · Pump out")
        self.assertEqual(got["card"]["plus"], "+1 can full (200 L)")
        self.assertTrue(got["card"]["neck"], "the neck tick shows for tank A")
        self.assertEqual(got["card"]["over"], "tank B: reached the neck / overflowed")
        self.assertEqual(got["card"]["neckText"], "tank A: level still in the neck")
        self.assertNotIn("Next batch", got["card"]["advice"], "the Now card predicts this batch only")
        self.assertEqual(got["go"], "Batch done")
        self.assertIn("alpha", got["dip1"]["a"])
        self.assertIn("beta", got["dip1"]["b"])
        self.assertEqual(got["dip1"]["btnA"], "Check alpha")
        self.assertEqual(got["dip1"]["btnB"], "Check beta")
        self.assertTrue(got["dip1"]["two"])
        self.assertIn("600 L pumped from A into B", got["dip1"]["batchText"])
        self.assertEqual(got["actions"], ["Take another reading (alpha)", "Accept anyway (alpha)"],
                         "the level actions name the current tank")
        self.assertIn("alpha — ", got["verdict"])
        self.assertIn("beta — ", got["verdict"])
        self.assertEqual(got["saved"], {"kind": "transfer", "levels": [2, 2], "pour": [True, True]})
        self.assertEqual(got["files"]["a"], "Download alpha_raw.csv (tank A)")
        self.assertTrue(got["files"]["b"])
        self.assertEqual(got["export"], {"a": "alpha_raw.csv", "b": "beta_raw.csv",
                                         "label": "Download alpha_raw.csv (tank A)",
                                         "show": "Show beta CSV"},
                         "with tank B active, the A button still exports tank A")
        self.assertEqual(got["log"]["title"], "Levels")
        self.assertEqual(got["log"]["chart"], "Reading minus prediction", "the chart title has no tank prefix")
        self.assertIn("pour L", got["log"]["table"], "tank B's log reads as a fill")
        self.assertIn('data-tank="in" aria-pressed="true"', got["log"]["tiles"],
                      "the B tile is the current tank")
        self.assertEqual(got["logA"]["title"], "Levels")
        self.assertEqual(got["logA"]["chart"], "Reading minus prediction")
        self.assertIn("drained L", got["logA"]["table"], "tank A's table is its own drain")
        self.assertIn('data-tank="out" aria-pressed="true"', got["logA"]["tiles"],
                      "the A tile is the current tank")
        self.assertGreater(got["log"]["now"].index("current"), got["log"]["now"].index("beta"),
                           "the current marker follows the tile to tank B")
        self.assertEqual(got["hdrReplay"], [True, False, "alpha → beta", True],
                         "the tiles stay on Replay, read-only; the title stays")
        self.assertIn("alpha", got["shell"], "the log switch carries to the shell tab")
        self.assertIn("alpha", got["settings"]["title"])
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
            "out.measured = s.measuredPourSeconds(200); out.other = s.measuredPourSeconds(100);\n"
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
        # The trend: the last gap weighs most (weights 0.5^(2/3), 0.5^(1/3), 1).
        w = [0.5 ** (2 / 3), 0.5 ** (1 / 3), 1]
        self.assertAlmostEqual(got["measured"]["seconds"], (100 * w[0] + 120 * w[1] + 110 * w[2]) / sum(w), places=6)
        self.assertEqual(got["measured"]["n"], 3)
        self.assertIsNone(got["other"], "one 100 L can has no gap of its own size")
        self.assertIsNone(got["noFill"], "a tap gap never gives the fill time")
        self.assertEqual(got["set"][0], {"seconds": 95, "source": "set"})
        self.assertEqual(got["set"][1], {"seconds": 50, "source": "set"}, "100.0 and 100 are one size")
        self.assertEqual(got["set"][2:], [420, 45, 12])
        self.assertEqual(got["cycle"]["source"], "taps", "a whole cycle from the taps beats a fill time alone")
        self.assertAlmostEqual(got["cycle"]["seconds"], got["measured"]["seconds"], places=6)
        self.assertEqual(got["saved"], [420, {"200": 95, "100": 50}, 12])
        self.assertEqual(got["cleared"], None, "a cleared fill time leaves the timer without one")
        self.assertEqual(got["bad"], 4)

    def test_drain_time_adds_to_the_cycle(self):
        got = _node(
            "const s = new core.Session({D: 1800, Lest: 3000, pourUnit: 200});\n"
            "const out = {};\n"
            "out.default = JSON.parse(JSON.stringify(s.cfg.drainSeconds));\n"
            "s.start('400', 400); s.dip(400);\n"
            "s.setTimers({drainSeconds: {200: 40}}); out.drainOnly = s.cycleSecondsFor(200);\n"
            "s.setTimers({fillSeconds: {200: 90}}); out.both = s.cycleSecondsFor(200);\n"
            "out.timer = s.fillSecondsFor(200);\n"
            "const back = core.Session.fromJSON(JSON.parse(JSON.stringify(s.toJSON())));\n"
            "out.saved = back.cfg.drainSeconds;\n"
            "s.setTimers({drainSeconds: {200: null}}); out.cleared = s.cycleSecondsFor(200);\n"
            "try { s.setTimers({drainSeconds: {200: 0}}); out.bad = false; } catch (e) { out.bad = true; }\n"
            "s.setTimers({drainSeconds: {200: 40}});\n"
            "s.tap(0, 200); s.tap(150000, 200); out.measured = s.cycleSecondsFor(200);\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["default"], {})
        self.assertEqual(got["drainOnly"], {"seconds": 40, "source": "drain", "drain": 40, "drainSource": "set"})
        self.assertEqual(got["both"], {"seconds": 130, "source": "set", "fill": 90, "drain": 40, "fillSource": "set", "drainSource": "set"})
        self.assertEqual(got["timer"], {"seconds": 90, "source": "set"}, "the fill timer ignores the drain")
        self.assertEqual(got["saved"], {"200": 40})
        self.assertEqual(got["cleared"], {"seconds": 90, "source": "fill", "fill": 90, "fillSource": "set"})
        self.assertTrue(got["bad"])
        self.assertEqual(got["measured"]["source"], "set", "a tap gap does not replace a typed fill + drain")

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
        self.assertEqual(notes[1], "at brim")
        self.assertEqual(rows[1][2].count("at brim"), 1)
        self.assertNotIn("neck entrance", rows[1][2], "the old note is gone from new files")
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
            " left: a.left, toBottom: a.toBottom})), plan, V0, cap, open, fill: f.advice(1790).text, h0: p.h0,"
            " floorV: core.volume(65, p)}));"
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
        plan, v0 = got["plan"], got["V0"]
        self.assertIsNone(plan["brim"])
        self.assertTrue(plan["half"]["done"], "the replay ends below half")
        end = plan["end"]
        self.assertLessEqual(end["volume"], plan["endVolume"] + 1e-6)
        self.assertGreaterEqual(end["levels"], 1)
        self.assertGreater(v0, plan["endVolume"], "the replay stops above the suction floor")
        self.assertAlmostEqual(v0 - 100 * end["cans"], end["volume"], places=6, msg="the volume counts down")
        self.assertAlmostEqual(end["seconds"], 60 * end["cans"] + 360 * end["levels"], places=6)
        self.assertAlmostEqual(plan["endVolume"], got["floorV"], places=6, msg="the drain ends at the suction floor (65 mm)")
        self.assertEqual(plan["endLevel"], 65)
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


# A planned campaign on a synthetic tank: nominal 10 000 L, cans 200 L and
# 100 L.  Each batch takes the cans of its mix; every dip is exact.
PLAN_JS = r"""
const GROUPS = [{count: 2, size: 300}, {count: 2, size: 600}, {count: 8, size: 800},
  {count: 2, size: 600}, {count: 2, size: 300}];
function planned(P, o) {
  const cfg = Object.assign({D: 2 * P.r, Dpm: 50, Lest: P.L, h0pm: 5, pourUnit: 100,
    canSizes: [200, 100], nominal: 10000, plan: GROUPS}, o || {});
  const s = new core.Session(cfg);
  const cap = core.capacity(P), drain = cfg.direction === 'drain';
  let V = drain ? cap : 50, t = 0;
  s.start(drain ? '?' : '50', core.levelFor(V, P)); s.dip(core.levelFor(V, P));
  const log = [];
  for (let k = 0; k < 40; k++) {
    const st = s.planNow();
    if (!st.batch) break;
    const b = st.batch, a = s.advice(s.levels[s.lastGood()].H);
    log.push({group: b.group, inGroup: b.inGroup, count: b.count, planned: b.planned, size: b.size,
      target: a.target, text: a.text, cans: core.mixCans(b.mix), past: st.past, total: st.total});
    for (const u of core.mixCans(b.mix)) s.tap(++t * 30000, u);
    V += (drain ? -1 : 1) * b.size;
    const end = drain ? V <= 0 : V >= cap;
    s.closeBatch(drain ? {partial: end} : {overflow: end});
    const H = core.levelFor(Math.min(Math.max(V, 0), cap), P);
    let n = 0;
    while (s.current().state === 'pending' && n < 4) { s.dip(H); n++; }
    if (end) break;
  }
  return {s, log, cap};
}
"""


class TestSiteTimeTrend(unittest.TestCase):
    """The time trend of the cans, the suction floor, and what the time estimate counts."""

    @unittest.skipUnless(NODE, "node is not installed")
    def test_trend_from_the_fill_timer(self):
        got = _node(
            "const s = new core.Session({D: 2000, Lest: 3000, pourUnit: 100, direction: 'drain'});\n"
            "s.start('?', 1990); s.dip(1990);\n"
            "// Four 200 L cans: the pump slows (fills 80, 85, 90, 95 s), each can drains in 40 s.\n"
            "let t = 0;\n"
            "for (let i = 0; i < 4; i++) { const f = t + 40000; t = f + (80 + 5 * i) * 1000; s.tap(t, 200, f); }\n"
            "// A 100 L can: its fill is its own; the drain before it belongs to the 200 L can.\n"
            "const f5 = t + 40000; t = f5 + 50000; s.tap(t, 100, f5);\n"
            "const out = {open: s.timeTrend(200), small: s.timeTrend(100)};\n"
            "out.cycle = s.cycleSecondsFor(200); out.sug = s.timerSuggestion(200);\n"
            "s.setTimers({fillSeconds: {200: 89}, drainSeconds: {200: 40}}); out.sugSet = s.timerSuggestion(200);\n"
            "s.closeBatch({}); out.fills = s.current().cans.fills.length;\n"
            "out.closed = s.timeTrend(200).fill.seconds;\n"
            "const back = core.Session.fromJSON(JSON.parse(JSON.stringify(s.toJSON())));\n"
            "out.reload = back.timeTrend(200).fill.seconds;\n"
            "s.undo(); out.reopened = s.batch.cans.map((c) => c.f != null);\n"
            "// One long break: a 25 min drain does not drag the trend.\n"
            "const b = new core.Session({D: 2000, Lest: 3000, pourUnit: 200}); b.start('?', 10); b.dip(10); b.dip(10);\n"
            "t = 0; for (let i = 0; i < 5; i++) { const f = t + (i === 3 ? 1500000 : 40000); t = f + 80000; b.tap(t, 200, f); }\n"
            "out.brk = b.timeTrend(200).drain;\n"
            "out.trendTimer = b.fillSecondsFor(200);\n"
            "console.log(JSON.stringify(out));"
        )
        w = [0.5 ** (3 / 3), 0.5 ** (2 / 3), 0.5 ** (1 / 3), 1]
        fill = sum(wi * x for wi, x in zip(w, (80, 85, 90, 95))) / sum(w)
        tr = got["open"]
        self.assertAlmostEqual(tr["fill"]["seconds"], fill, places=6)
        self.assertGreater(tr["fill"]["seconds"], tr["fill"]["median"], "a slowing pump: the trend follows the last cans")
        self.assertEqual(tr["drain"]["n"], 4, "the drain before the 100 L can belongs to the 200 L can")
        self.assertAlmostEqual(tr["drain"]["seconds"], 40, places=6)
        self.assertEqual(tr["gap"]["n"], 3, "a gap counts between two cans of one size only")
        self.assertAlmostEqual(got["small"]["fill"]["seconds"], 50, places=6)
        self.assertIsNone(got["small"]["drain"], "the last can has no drain yet")
        self.assertEqual(got["cycle"]["source"], "trend")
        self.assertAlmostEqual(got["cycle"]["seconds"], fill + 40, places=6)
        self.assertEqual(got["sug"], {"size": 200, "fill": round(fill), "drain": 40})
        self.assertIsNone(got["sugSet"], "the settings already hold the trend: nothing to suggest")
        self.assertEqual(got["fills"], 5, "a closed batch keeps the fill starts")
        self.assertAlmostEqual(got["closed"], fill, places=6)
        self.assertAlmostEqual(got["reload"], fill, places=6)
        self.assertEqual(got["reopened"], [True] * 5, "undo opens the batch with its fill starts")
        self.assertLess(got["brk"]["seconds"], 70, "the break is held at three times the median")
        self.assertIsNone(got["trendTimer"], "the fill alarm keeps the typed time: the trend is only a suggestion")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_suction_floor(self):
        got = _node(
            PLAN_JS
            + "const P = {r: 1000, L: 3000, h0: 0};\n"
            "const s = new core.Session({D: 2000, Dpm: 20, Lest: 3000, h0pm: 2, pourUnit: 200, direction: 'drain'});\n"
            "let V = core.capacity(P); s.start('?', core.levelFor(V, P)); s.dip(core.levelFor(V, P));\n"
            "for (let i = 0; i < 3; i++) { s.pour('600'); V -= 600; while (s.current().state === 'pending') s.dip(core.levelFor(V, P)); }\n"
            "const o = {size: 200, cycleSeconds: 100, settleSeconds: 0, dipSeconds: 0};\n"
            "const out = {def: s.cfg.suctionFloor, a: s.fillPlan(o), V: core.volume(s.levels[s.lastGood()].H, s.fit.p)};\n"
            "out.fv = core.volume(65, s.fit.p);\n"
            "out.adv = (({suction, toSuction, aboveSuction, left}) => ({suction, toSuction, aboveSuction, left}))(s.advice(s.levels[s.lastGood()].H));\n"
            "s.setCampaign({suctionFloor: 300}); out.high = s.fillPlan(o); out.fv300 = core.volume(300, s.fit.p);\n"
            "s.setCampaign({suctionFloor: ''}); out.blank = s.cfg.suctionFloor;\n"
            "try { s.setCampaign({suctionFloor: -1}); out.bad = false; } catch (e) { out.bad = e.message; }\n"
            "// A planned drain ends at the floor too: the room is the liquid above it.\n"
            "const r = planned({r: 1000, L: 3183, h0: 0}, {direction: 'drain', suctionFloor: 200});\n"
            "out.planned = r.log.reduce((a, e) => a + e.size, 0); out.cap = r.cap; out.below = core.volume(200, {r: 1000, L: 3183, h0: 0});\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["def"], 65, "the default suction floor is 65 mm")
        end = got["a"]["end"]
        self.assertEqual(got["a"]["endLevel"], 65)
        self.assertAlmostEqual(got["a"]["endVolume"], got["fv"], places=6)
        self.assertLessEqual(end["volume"], got["fv"] + 1e-6, "the end is the first level at or below the floor")
        self.assertGreater(end["volume"] + 200, got["fv"], "the last can is a part can down to the floor")
        self.assertEqual(sum(b["count"] for b in end["batches"]), end["levels"], "every batch is counted by volume")
        self.assertEqual(sum(u["count"] for u in end["units"]), end["cans"], "every can is counted by size")
        self.assertEqual(end["units"], [{"size": 200, "count": end["cans"]}])
        adv = got["adv"]
        self.assertEqual(adv["suction"], 65)
        self.assertAlmostEqual(adv["aboveSuction"], adv["left"] - got["fv"], places=6)
        self.assertLess(got["high"]["end"]["cans"], end["cans"], "a higher floor: fewer cans")
        self.assertAlmostEqual(got["high"]["endVolume"], got["fv300"], places=6)
        self.assertEqual(got["blank"], 65, "blank is the default")
        self.assertIn("suction floor", got["bad"])
        self.assertGreaterEqual(got["planned"], got["cap"] - got["below"] - 1, "the plan's batches reach the floor")
        self.assertLess(got["planned"], got["cap"] - got["below"] + 300, "and stop there: the liquid below stays")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_fill_timer_takes_the_trend(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-dir-drain').click();\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '1790'; el('s-unit').value = '200'; el('s-go').click();\n"
            "el('d-val').value = '1790'; el('d-go').click(); el('d-val').value = '1790'; el('d-go').click();\n"
            "// No typed fill time and no timed can: the timer asks for one.\n"
            "el('pt-start').click(); out.ask = el('tm-err').textContent;\n"
            "// A can filled with the timer running: 100 s from start to tap.\n"
            "store.set('calib-site:timer', JSON.stringify({ pour: { start: Date.now() - 100000, dur: 90, size: 200, lead: 15 } }));\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "el('t-plus').click();\n"
            "out.idle = el('pt-status').textContent; out.startLabel = el('pt-start').textContent;\n"
            "el('pt-start').click();\n"
            "out.run = JSON.parse(store.get('calib-site:timer')).pour;\n"
            "out.status = el('pt-status').textContent;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIn("Set the fill time for 200 L cans", got["ask"])
        self.assertIn("(the trend of your cans)", got["idle"])
        self.assertIn("Start fill timer (1:40)", got["startLabel"])
        self.assertEqual(got["run"]["dur"], 100, "the timer runs on the trend when no time is typed")
        self.assertIn("left of 1:40", got["status"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_trend_floor_and_breakdown(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "const tab = (t) => el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: t } }) } });\n"
            "out.floor0 = el('set-floor').value;\n"
            "el('s-dir-drain').click();\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '1790'; el('s-unit').value = '200'; el('s-go').click();\n"
            "el('d-val').value = '1790'; el('d-go').click(); el('d-val').value = '1790'; el('d-go').click();\n"
            "tab('settings'); el('set-floor').value = '120'; el('set-noise-save').click();\n"
            "out.cfgFloor = JSON.parse(store.get('calib-site:active')).config.suctionFloor;\n"
            "el('tm-fill-200').value = '1:30'; el('tm-drain-200').value = '0:40'; el('tm-save').click(); tab('live');\n"
            "out.eta = el('now-eta').innerHTML; out.kv = el('now-kv').innerHTML;\n"
            "// A can with its fill timer: the tap records when the timer started.\n"
            "el('pt-start').click(); const tm = JSON.parse(store.get('calib-site:timer'));\n"
            "tm.pour.start = Date.now() - 100000; store.set('calib-site:timer', JSON.stringify(tm));\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "el('t-plus').click();\n"
            "out.f = JSON.parse(store.get('calib-site:active')).batch.cans[0].f != null;\n"
            "out.use = [el('eta-use')._classes.has('hidden'), el('eta-use').textContent];\n"
            "out.trendLine = el('now-eta').innerHTML;\n"
            "el('eta-use').click();\n"
            "out.adopted = JSON.parse(store.get('calib-site:active')).config.fillSeconds;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["floor0"], "65", "the default suction floor shows in Settings")
        self.assertEqual(got["cfgFloor"], 120)
        self.assertIn("To the suction floor (120 mm)", got["eta"])
        self.assertNotIn("To bottom", got["eta"])
        self.assertRegex(got["eta"], r"\d+ batch(es)?: [0-9 ×+]+ L · \d+ cans?: [0-9 ×+]+ L",
                         "batches by volume and cans by size")
        self.assertIn("The pump cannot draw below the suction floor", got["eta"])
        self.assertIn("<dt>suction floor</dt><dd>120 mm", got["kv"])
        self.assertTrue(got["f"])
        self.assertFalse(got["use"][0])
        self.assertEqual(got["use"][1], "Use the trend: fill 1:40 per 200 L can")
        self.assertIn("Your trend for 200 L cans (1 can, the most recent weigh most) · fill 1:40", got["trendLine"])
        self.assertEqual(got["adopted"], {"200": 100}, "one tap adopts the trend for the fill alarm")


class TestSitePlan(unittest.TestCase):
    """The batch plan: cans per batch, the setup check, and the end of the plan (§3.4, §3.10)."""

    @unittest.skipUnless(NODE, "node is not installed")
    def test_can_mix_fewest_then_largest(self):
        got = _node(
            "const m = (v, s) => core.canMix(v, s);\n"
            "console.log(JSON.stringify({\n"
            "  a: m(300, [200, 100]), b: m(300, [150, 100]), c: m(800, [200, 100]),\n"
            "  tie: m(300, [200, 150, 100]), none: m(250, [200, 100]), half: m(2.5, [1, 0.5]),\n"
            "  text: core.mixText(m(500, [200, 100])), cans: core.mixCans(m(500, [200, 100])),\n"
            "}));"
        )
        self.assertEqual(got["a"], [{"unit": 200, "count": 1}, {"unit": 100, "count": 1}])
        self.assertEqual(got["b"], [{"unit": 150, "count": 2}], "a 150 L can: 2 cans, not 3")
        self.assertEqual(got["c"], [{"unit": 200, "count": 4}])
        self.assertEqual(got["tie"], [{"unit": 200, "count": 1}, {"unit": 100, "count": 1}],
                         "two cans either way: the largest can wins")
        self.assertIsNone(got["none"], "a batch lives on the can grid")
        self.assertEqual(got["half"], [{"unit": 1, "count": 2}, {"unit": 0.5, "count": 1}])
        self.assertEqual(got["text"], "2 × 200 + 100")
        self.assertEqual(got["cans"], [200, 200, 100], "tap order: the largest first")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_check_plan(self):
        got = _node(
            "const G = [{count: 2, size: 300}, {count: 2, size: 600}, {count: 8, size: 800},"
            " {count: 2, size: 600}, {count: 2, size: 300}];\n"
            "const c = (p, s, n) => core.checkPlan(p, s, n);\n"
            "console.log(JSON.stringify({\n"
            "  ok: c(G, [200, 100], 10000),\n"
            "  text: c('2:300, 2:600, 8:800, 2:600, 2:300', [200, 100], 10000).ok,\n"
            "  merged: core.normalizePlan('2:300, 1:300, 4:800'),\n"
            "  sum: c(G, [200, 100], 10500).errors,\n"
            "  sym: c('2:300, 8:800, 3:300', [200, 100], 7900).errors,\n"
            "  peak: c('2:800, 2:300, 2:800', [200, 100], 3800).errors,\n"
            "  grid: c(G, [200], 10000).errors,\n"
            "  none: c(null, null, null),\n"
            "}));"
        )
        ok = got["ok"]
        self.assertTrue(ok["ok"], ok["errors"])
        self.assertEqual((ok["batches"], ok["total"], ok["diff"]), (16, 10000, 0))
        self.assertTrue(got["text"], "count:size, as the operator writes 4:300")
        self.assertEqual(got["merged"], [{"count": 3, "size": 300}, {"count": 4, "size": 800}],
                         "adjacent groups of one size are one group")
        self.assertEqual(got["sum"], ["The batches add up to 10000 L, not the nominal 10500 L (−500 L)."])
        self.assertEqual(len(got["sym"]), 1)
        self.assertIn("not symmetric", got["sym"][0])
        self.assertEqual(len(got["peak"]), 1)
        self.assertIn("largest batches belong in the middle", got["peak"][0])
        self.assertEqual(got["grid"], ["Group 1: 300 L is not a sum of the can sizes.",
                                       "Group 5: 300 L is not a sum of the can sizes."])
        self.assertTrue(got["none"]["ok"], "no plan: nothing to check")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_plan_state_counts_the_end_again(self):
        got = _node(
            "const G = [{count: 2, size: 300}, {count: 2, size: 600}, {count: 8, size: 800},"
            " {count: 2, size: 600}, {count: 2, size: 300}];\n"
            "const hist = [0, 0, 1, 1, 2, 2, 2, 2, 2, 2];   // 6 of the 8 middle batches poured\n"
            "const counts = (R, adapt, h) => { const s = core.planState(G, h || hist, R, adapt);"
            " return {c: s.groups.map((g) => g.count), next: s.next}; };\n"
            "const top = [0, 0, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 4];\n"
            "console.log(JSON.stringify({\n"
            "  asPlanned: counts(4200 - 800, true), larger: counts(4200, true), smaller: counts(3400 - 800, true),\n"
            "  before: counts(4200, false), tiny: counts(500, true), full: counts(0, true),\n"
            "  lastGroup: counts(900, true, top), past: counts(null, false, top.concat([4])),\n"
            "  first: counts(9000, false, []),\n"
            "}));"
        )
        self.assertEqual(got["asPlanned"]["c"], [2, 2, 8, 2, 2])
        self.assertEqual(got["larger"]["c"], [2, 2, 9, 2, 2], "a larger tank: one more middle batch")
        self.assertEqual(got["smaller"]["c"], [2, 2, 7, 2, 2], "a smaller tank: one less")
        self.assertEqual(got["before"]["c"], [2, 2, 8, 2, 2], "before the mid-dip the plan stands")
        self.assertEqual(got["tiny"]["c"], [2, 2, 6, 0, 2], "the small top batches stay to the end")
        self.assertEqual(got["tiny"]["next"], 4)
        self.assertIsNone(got["full"]["next"], "no room left: the plan is complete")
        self.assertEqual(got["lastGroup"]["c"], [2, 2, 8, 2, 4], "the last group fills the gap")
        self.assertEqual(got["past"]["c"][4], 3, "past the plan: on with the last size")
        self.assertEqual(got["first"]["next"], 0)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_plan_state_closes_groups_and_holds_counts(self):
        got = _node(
            "const G = [{count: 2, size: 300}, {count: 2, size: 600}, {count: 8, size: 800},"
            " {count: 2, size: 600}, {count: 2, size: 300}];\n"
            "const c = (s) => s.groups.map((g) => g.count);\n"
            "// 9 middle batches poured, then one of group 4: the middle group is closed at 9.\n"
            "const after = [0, 0, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3];\n"
            "const closed = core.planState(G, after, 900, true);\n"
            "// 6 middle batches poured; the last batch was poured with 9 for the middle group.\n"
            "const hist = [0, 0, 1, 1, 2, 2, 2, 2, 2, 2];\n"
            "const prev = [2, 2, 9, 2, 2];\n"
            "console.log(JSON.stringify({\n"
            "  closed: c(closed), next: closed.next,\n"
            "  free: c(core.planState(G, hist, 1800 + 2.4 * 800, true)),\n"
            "  held: c(core.planState(G, hist, 1800 + 2.4 * 800, true, prev)),\n"
            "  moved: c(core.planState(G, hist, 1800 + 2.2 * 800, true, prev)),\n"
            "  oldSave: c(core.planState(G, hist, 1800 + 2.4 * 800, true, [2, 2, 9])),\n"
            "}));"
        )
        self.assertEqual(got["closed"][2], 9, "a closed group counts what was poured, never less")
        self.assertTrue(all(n >= 0 for n in got["closed"]))
        self.assertEqual(got["free"][2], 8, "no earlier count: 2.4 batches left round to 2")
        self.assertEqual(got["held"][2], 9, "within the hold the earlier count stays")
        self.assertEqual(got["moved"][2], 8, "beyond the hold the count changes")
        self.assertEqual(got["oldSave"][2], 8, "counts of another plan shape are ignored")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_planned_fill_with_noisy_dips_changes_a_count_once(self):
        """Dip noise moves the shell's figure: the plan must not flip 8, 9, 8."""
        got = _node(
            "const GROUPS = [{count: 2, size: 300}, {count: 2, size: 600}, {count: 8, size: 800},"
            " {count: 2, size: 600}, {count: 2, size: 300}];\n"
            "const runs = [];\n"
            "for (let L = 3300; L <= 3480; L += 12) for (const seed of [1, 7, 42]) {\n"
            "  let x = seed; const rnd = () => { x = (x * 1103515245 + 12345) % 2147483648; return x / 2147483648 - 0.5; };\n"
            "  const P = {r: 1000, L, h0: 0}, cap = core.capacity(P);\n"
            "  const s = new core.Session({D: 2000, Dpm: 50, Lest: L, h0pm: 5, pourUnit: 100, canSizes: [200, 100],"
            " nominal: 10000, plan: GROUPS});\n"
            "  const H = (v) => core.levelFor(Math.min(v, cap), P);\n"
            "  let V = 50, t = 0; s.start('50', H(V)); s.dip(H(V) + 2 * rnd());\n"
            "  const seq = []; let low = false;\n"
            "  for (let k = 0; k < 40; k++) {\n"
            "    const st = s.planNow(); if (!st || !st.batch) break;\n"
            "    seq.push(st.groups[2].count);\n"
            "    if (st.groups.some((g) => g.count < g.done)) low = true;\n"
            "    for (const u of core.mixCans(st.batch.mix)) s.tap(++t * 30000, u);\n"
            "    V += st.batch.size; const end = V >= cap;\n"
            "    s.closeBatch({overflow: end});\n"
            "    let n = 0; const h = H(V);\n"
            "    while (s.current().state === 'pending' && n < 4) { s.dip(h + 2 * rnd()); n++; }\n"
            "    if (s.current().state === 'pending') s.override('test');\n"
            "    if (end) break;\n"
            "  }\n"
            "  runs.push({L, seed, seq, low, end: V >= cap, flips: seq.slice(1).filter((c, i) => c !== seq[i]).length});\n"
            "}\n"
            "console.log(JSON.stringify(runs));"
        )
        self.assertGreater(len(got), 40)
        for r in got:
            self.assertLessEqual(r["flips"], 1, f"the middle count changes once at most: {r}")
            self.assertFalse(r["low"], f"no group counts fewer batches than were poured: {r}")
            self.assertTrue(r["end"], f"the campaign reaches the brim: {r}")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_planned_fill_on_a_larger_tank(self):
        got = _node(
            PLAN_JS
            + "const r = planned({r: 1000, L: 3374, h0: 0});\n"
            "const s = r.s, s2 = core.Session.fromJSON(JSON.parse(JSON.stringify(s.toJSON())));\n"
            "console.log(JSON.stringify({log: r.log, cap: r.cap,"
            " levels: s.levels.slice(1).map((L) => L.plan && L.plan.group),"
            " poured: s.levels.slice(1).reduce((a, L) => a + (L.step.value || 0), 0),"
            " reload: [s2.planNow().poured, s2.planNow().total, s2.cfg.plan.length, s2.cfg.nominal],"
            " now: [s.planNow().poured, s.planNow().total]}));"
        )
        log = got["log"]
        self.assertGreater(got["cap"], 10500, "the tank holds more than the nominal")
        for e in log:
            self.assertEqual(e["target"], e["size"], "the recommended batch is the plan's batch")
            self.assertIn(f"Batch {log.index(e) + 1} of {e['total']}: ", e["text"])
            if not e["past"]:
                self.assertEqual(e["count"], e["planned"], "before the mid-dip the plan stands")
        self.assertEqual(log[0]["cans"], [200, 100])
        self.assertEqual(log[4]["cans"], [200, 200, 200, 200])
        groups = [e["group"] for e in log]
        self.assertEqual(groups, sorted(groups), "the groups follow in order")
        self.assertEqual(got["levels"], groups, "each level records its plan group")
        top = [e["inGroup"] for e in log if e["group"] == 4]
        self.assertEqual(top[0], 1, "the top 300 L group counts its own batches, not the bottom ones")
        self.assertEqual(top, list(range(1, len(top) + 1)))
        self.assertGreater(sum(1 for e in log), 16, "a larger tank takes more batches than the plan")
        self.assertEqual(log[-1]["size"], 300, "the small batches stay at the top")
        self.assertGreaterEqual(got["poured"] + 50, got["cap"], "the campaign reaches the brim")
        self.assertEqual(got["reload"][:2], got["now"], "the plan and its tally survive a reload")
        self.assertEqual(got["reload"][2:], [5, 10000])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_planned_drain_on_a_smaller_tank(self):
        got = _node(
            PLAN_JS
            + "const r = planned({r: 1000, L: 2992, h0: 0}, {direction: 'drain'});\n"
            "console.log(JSON.stringify({log: r.log, cap: r.cap,"
            " poured: r.s.levels.slice(1).reduce((a, L) => a + (L.step.value || L.step.base || 0), 0)}));"
        )
        log = got["log"]
        self.assertLess(got["cap"], 9500)
        self.assertIn(7, [e["count"] for e in log if e["group"] == 2], "the middle group loses a batch")
        planned = sum(e["size"] for e in log)
        self.assertGreaterEqual(planned, got["cap"], "the batches reach the bottom")
        self.assertLess(planned, got["cap"] + 300, "the last batch is a part batch at most")
        self.assertEqual(log[-1]["size"], 300, "the small batches stay at the bottom of a drain")
        self.assertTrue(all("fall" in e["text"] for e in log))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_planned_transfer_and_time(self):
        got = _node(
            PLAN_JS
            + "const PA = {r: 1100, L: 3000, h0: 0}, PB = {r: 1000, L: 3183, h0: 0};\n"
            "const shared = {Dpm: 50, h0pm: 5, pourUnit: 100, canSizes: [200, 100], plan: GROUPS};\n"
            "const X = new core.TransferSession(Object.assign({D: 2200, Lest: 3000, tank: 'a', nominal: 11000}, shared),"
            " Object.assign({D: 2000, Lest: 3183, tank: 'b', nominal: 10000}, shared));\n"
            "let VA = core.capacity(PA), VB = 0.5 * 0 + 60, t = 0;\n"
            "X.start('?', core.levelFor(VA, PA), '60', core.levelFor(VB, PB));\n"
            "const dip = (k, H) => { let n = 0; while (X.pendingTank() === k && n < 4) { X.dip(H); n++; } };\n"
            "dip('out', core.levelFor(VA, PA)); dip('in', core.levelFor(VB, PB));\n"
            "const out = {first: X.adviceBatch().text, groups: []};\n"
            "for (let k = 0; k < 6; k++) {\n"
            "  const b = X.planNow().batch;\n"
            "  for (const u of core.mixCans(b.mix)) X.tap(++t * 30000, u);\n"
            "  X.closeBatch({}); VA -= b.size; VB += b.size;\n"
            "  dip('out', core.levelFor(VA, PA)); dip('in', core.levelFor(VB, PB));\n"
            "  out.groups.push([X.out.current().plan.group, X.in.current().plan.group]);\n"
            "}\n"
            "out.room = X._planRoom().R; out.gapB = X.in._planRoom().R; out.leftA = X.out._planRoom().R;\n"
            "const s = new core.Session({D: 2000, Lest: 3183, pourUnit: 100, canSizes: [200, 100], nominal: 10000, plan: GROUPS});\n"
            "s.start('60', core.levelFor(60, PB)); s.dip(core.levelFor(60, PB));\n"
            "const cyc = (u) => (u === 100 ? 50 : 90);\n"
            "out.eta = s.fillPlan({size: 200, cycleSeconds: 90, settleSeconds: 0, dipSeconds: 0, cycleFor: cyc});\n"
            "out.list = s.planProjection();\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["first"].startswith("Batch 1 of 16: 300 L = 200 + 100 L"), got["first"])
        self.assertEqual(got["groups"], [[0, 0], [0, 0], [1, 1], [1, 1], [2, 2], [2, 2]],
                         "one batch is one plan step for both tanks")
        self.assertAlmostEqual(got["room"], min(got["gapB"], got["leftA"]), places=6,
                               msg="the tighter tank sets the room")
        eta, lst = got["eta"], got["list"]
        self.assertTrue(eta["mixed"])
        cans = sum(len([u for c in b["mix"] for u in [c["unit"]] * c["count"]]) for b in lst)
        secs = sum(cyc_u * c["count"] for b in lst for c in b["mix"] for cyc_u in [50 if c["unit"] == 100 else 90])
        self.assertEqual(eta["brim"]["levels"], len(lst), "one level per batch of the plan")
        self.assertEqual(eta["brim"]["cans"], cans)
        self.assertAlmostEqual(eta["brim"]["seconds"], secs, places=6, msg="each can at its own cycle time")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_batch_plan(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "const click = (act, i) => el('s-plan')._listeners.click[0]({ target: { closest: () => ({ dataset: { act, i: String(i) }, disabled: false }) } });\n"
            "const size = (i, v) => el('s-plan')._listeners.input[0]({ target: { dataset: { i: String(i) }, value: String(v) } });\n"
            "out.none = el('s-plan-check').textContent;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '2000'; el('s-L').value = '3183';\n"
            "el('s-step').value = '?'; el('s-dip').value = '10'; el('s-unit').value = '200';\n"
            "el('s-unit')._listeners.input[0]({});\n"
            "el('s-can-add').value = '100'; el('s-can-go').click();\n"
            "el('s-nom').value = '10500'; el('s-nom')._listeners.input[0]({});\n"
            "out.nomNote = el('s-nom-note').textContent;\n"
            "el('s-plan-add').click(); size(0, 300); click('inc', 0);\n"
            "el('s-plan-add').click(); size(1, 600); click('inc', 1);\n"
            "el('s-plan-add').click(); size(2, 800); for (let k = 0; k < 7; k++) click('inc', 2);\n"
            "out.mix = el('s-plan-mix-0').textContent;\n"
            "el('s-plan-mirror').click();\n"
            "out.wrong = el('s-plan-check').textContent;\n"
            "el('s-go').click(); out.blocked = el('s-err').textContent; out.started = !!store.get('calib-site:active');\n"
            "el('s-nom').value = '10000'; el('s-nom')._listeners.input[0]({});\n"
            "out.ok = [el('s-plan-check').textContent, el('s-plan-check').className];\n"
            "// The draft stays on the device: a reload shows the same plan.\n"
            "const p2 = stub.boot(page, corePath, store);\n"
            "out.draft = [p2.el('s-plan').innerHTML.split('plan-row').length - 1, p2.el('s-plan-check').textContent];\n"
            "el('s-go').click(); out.err = el('s-err').textContent;\n"
            "el('d-val').value = '10'; el('d-go').click(); el('d-val').value = '10'; el('d-go').click();\n"
            "out.head = el('t-plan-head').textContent; out.chips = el('t-plan-chips').innerHTML;\n"
            "out.hidden = el('t-plan')._classes.has('hidden');\n"
            "out.unit0 = el('t-unit').value; out.target = el('t-target').textContent;\n"
            "el('t-plus').click(); out.unit1 = el('t-unit').value; out.todo = el('t-bar').innerHTML; out.todoLab = el('t-times').innerHTML;\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'settings' } }) } });\n"
            "out.settings = el('set-plan').textContent;\n"
            "out.cfg = JSON.parse(store.get('calib-site:active')).config;\n"
            "// Without a plan the pour card has no plan block.\n"
            "const s3 = new Map(); const p3 = stub.boot(page, corePath, s3), e3 = p3.el;\n"
            "e3('s-D').value = '1800'; e3('s-L').value = '3000'; e3('s-dip').value = '400'; e3('s-unit').value = '200';\n"
            "e3('s-go').click(); e3('d-val').value = '400'; e3('d-go').click(); e3('d-val').value = '400'; e3('d-go').click();\n"
            "out.plain = [e3('t-plan')._classes.has('hidden'), e3('t-target').textContent];\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["none"], "No batch plan yet: tap + group.")
        self.assertEqual(got["nomNote"], "D and L give ≈ 10000 L.")
        self.assertEqual(got["mix"], "= 200 + 100 L")
        self.assertEqual(got["wrong"], "The batches add up to 10000 L, not the nominal 10500 L (−500 L).")
        self.assertEqual(got["blocked"], got["wrong"], "a plan with errors does not start")
        self.assertFalse(got["started"])
        self.assertEqual(got["ok"], ["16 batches · 10000 L = nominal ✓ · symmetric ✓", "ok"])
        self.assertEqual(got["draft"], [5, "16 batches · 10000 L = nominal ✓ · symmetric ✓"])
        self.assertEqual(got["err"], "")
        self.assertFalse(got["hidden"])
        self.assertEqual(got["head"], "Group 1 of 5 · 300 L · batch 1 of 2 · 1 of 16 in all")
        self.assertEqual(got["chips"], '<span class="now">1</span><span class="todo">2</span>')
        self.assertEqual(got["unit0"], "200", "the batch starts with its largest can")
        self.assertTrue(got["target"].startswith("Plan: 200 + 100 L = 300 L"), got["target"])
        self.assertEqual(got["unit1"], "100", "the next tap is the 100 L can of the mix")
        self.assertIn('data-state="now"', got["todo"], "the next planned can is the cell in work")
        self.assertIn('aria-hidden="true">100</span>', got["todo"],
                      "the planned can shows its size in its cell, hidden from the progressbar's name")
        self.assertNotIn(" · ", got["todoLab"], "the tag carries no can number")
        self.assertEqual(got["settings"], "Batch plan: 2 × 300, 2 × 600, 8 × 800, 2 × 600, 2 × 300 L"
                         " · nominal 10000 L · cans 200, 100 L. Fixed at the start.")
        cfg = got["cfg"]
        self.assertEqual((cfg["canSizes"], cfg["nominal"], len(cfg["plan"])), ([200, 100], 10000, 5))
        self.assertTrue(got["plain"][0], "no plan: no plan block")
        self.assertTrue(got["plain"][1].startswith("Advice ≈"), "no plan: the 30 mm advice")


@unittest.skipUnless(NODE, "node is not installed")
class TestSiteTiles(unittest.TestCase):
    @staticmethod
    def _tile(html):
        def one(cls):
            m = re.search(r'class="' + cls + r'">([^<]*)<', html)
            return m.group(1) if m else None
        w = re.search(r"width:([0-9.]+)%", html)
        e = re.search(r'data-edge="(\w+)"><span aria-hidden="true">([≥≤])</span>([^<]*)<', html)
        return {
            "cur": one("num cur"),
            "pred": one("num pred") or one("num pred words") or (e.group(3) if e else None),
            "edge": (e.group(1), e.group(2)) if e else None,
            "wait": 'class="wt"' in html,
            "tally": 'class="prog"' in html,
            "width": w.group(1) if w else None,
            "plain": 'class="trk plain"' in html,
        }

    def test_page_now_card_and_tile_share_the_prediction(self):
        """One rule for both: the plan's batch, the typed litres and the ticks.

        The Now card and the tile draw the same view (tileOne), so a typed
        pour, a tick or a part can changes both, and the numbers agree.
        """
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "const size = (i, v) => el('s-plan')._listeners.input[0]({ target: { dataset: { i: String(i) }, value: String(v) } });\n"
            "const tilePred = () => /class=\"num pred\">([^<]*)</.exec(el('tiles').innerHTML)[1];\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1000'; el('s-L').value = '1528';\n"
            "el('s-step').value = '?'; el('s-dip').value = '10'; el('s-unit').value = '200';\n"
            "el('s-unit')._listeners.input[0]({});\n"
            "el('s-nom').value = '1200'; el('s-nom')._listeners.input[0]({});\n"
            "for (let k = 0; k < 3; k++) { el('s-plan-add').click(); size(k, 400); }\n"
            "el('s-go').click();\n"
            "el('d-val').value = '10'; el('d-go').click(); el('d-val').value = '10'; el('d-go').click();\n"
            "out.zero = { tile: tilePred(), now: el('now-pred').textContent };\n"
            "el('p-vol').value = '100'; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "out.typed = { tile: tilePred(), now: el('now-pred').textContent };\n"
            "el('p-vol').value = ''; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "el('t-plus').click();\n"
            "out.one = { tile: tilePred(), now: el('now-pred').textContent };\n"
            "el('t-plus').click();\n"
            "out.tapped = { tile: tilePred(), now: el('now-pred').textContent };\n"
            "el('t-part').checked = true; el('t-part')._listeners.change[0]({target: el('t-part')});\n"
            "out.part = { tile: el('tiles').innerHTML, now: el('now-pred').textContent };\n"
            "el('t-part').checked = false; el('t-part')._listeners.change[0]({target: el('t-part')});\n"
            "el('p-unknown').checked = true; el('p-go').click();\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["zero"]["tile"], "368.9", "the tile shows the plan's batch end")
        self.assertIn("After the plan's batch (400 L, 0 L tapped so far): 368.9 mm", got["zero"]["now"])
        self.assertEqual(got["one"]["tile"], "368.9", "the tile stays at the plan's batch end")
        self.assertIn("After the plan's batch (400 L, 200 L tapped so far):", got["one"]["now"])
        self.assertEqual(got["tapped"]["tile"], "368.9", "the tile stays at the batch end")
        self.assertIn("After this pour (400 L):", got["tapped"]["now"],
                      "the tapped cans are the batch: no plan label")
        self.assertTrue(got["typed"]["now"].startswith("After this pour (100 L):"), got["typed"]["now"])
        self.assertNotEqual(got["typed"]["tile"], "368.9", "typed litres replace the plan's batch on the tile too")
        self.assertEqual(got["typed"]["now"].split(": ")[1].split(" mm")[0], got["typed"]["tile"])
        self.assertIn("part can", got["part"]["now"])
        self.assertIn("no prediction (a part can)", got["part"]["tile"], "the tile names the part can as no prediction")

    def test_page_now_card_left_to_the_limit(self):
        """The brim and suction floor rows: the way left now and after the batch."""
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '1500'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '1500'; el('d-go').click(); el('d-val').value = '1500'; el('d-go').click();\n"
            "out.fillKv = el('now-kv').innerHTML;\n"
            "el('p-vol').value = '200'; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "out.fillKv2 = el('now-kv').innerHTML;\n"
            "out.fillPred = el('now-pred').textContent;\n"
            "el('p-vol').value = '99999'; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "out.pastBrim = { pred: el('now-pred').textContent, kv: el('now-kv').innerHTML };\n"
            "el('p-vol').value = ''; el('p-vol')._listeners.input[0]({target: el('p-vol')});\n"
            "el('t-plus').click();\n"
            "// A drain: the suction floor instead of the brim.\n"
            "const s2 = new Map(); const p2 = stub.boot(page, corePath, s2), e2 = p2.el;\n"
            "e2('s-dir-drain').click();\n"
            "e2('s-tank').value = 't2'; e2('s-D').value = '1800'; e2('s-L').value = '3000';\n"
            "e2('s-dip').value = '1790'; e2('s-unit').value = '200'; e2('s-go').click();\n"
            "e2('d-val').value = '1790'; e2('d-go').click(); e2('d-val').value = '1790'; e2('d-go').click();\n"
            "e2('t-plus').click(); e2('t-plus').click();\n"
            "out.drain = { kv: e2('now-kv').innerHTML, pred: e2('now-pred').textContent };\n"
            "// Simple mode: one short line to the brim.\n"
            "el('hdr-mode').click(); out.simple = el('now-eta').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIn("<dt>brim</dt><dd>≈ 1800", got["fillKv"])
        self.assertIn("mm · ≈", got["fillKv"])
        self.assertIn("L to go", got["fillKv"], "a fill shows the height and the litres left")
        self.assertIn("after this pour:", got["fillKv2"], "the row also counts from the predicted level")
        self.assertIn("After this pour (200 L):", got["fillPred"])
        self.assertIn("mm ±", got["fillPred"])
        self.assertIn("rise", got["fillPred"])
        self.assertIn("≥ 1800.0 mm · the brim", got["pastBrim"]["pred"])
        self.assertIn("more than the gap", got["pastBrim"]["pred"])
        self.assertIn("after this pour: reaches the brim", got["pastBrim"]["kv"])
        self.assertIn("<dt>suction floor</dt><dd>65 mm", got["drain"]["kv"])
        self.assertIn("L to pump", got["drain"]["kv"])
        self.assertIn("after this drain:", got["drain"]["kv"])
        self.assertIn("mm fall", got["drain"]["pred"])
        self.assertIn("<b>To brim</b>:", got["simple"], "simple mode keeps one short line")
        self.assertIn("mm · ≈", got["simple"])
        self.assertIn("done ≈ <b>", got["simple"])
        self.assertIn("rough guess", got["simple"], "the default time says it is a guess")

    def test_page_tiles_plan_and_no_plan(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "const click = (act, i) => el('s-plan')._listeners.click[0]({ target: { closest: () => ({ dataset: { act, i: String(i) }, disabled: false }) } });\n"
            "const size = (i, v) => el('s-plan')._listeners.input[0]({ target: { dataset: { i: String(i) }, value: String(v) } });\n"
            "out.empty = [el('tiles')._classes.has('hidden'), el('hdr-title').textContent];\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1000'; el('s-L').value = '1528';\n"
            "el('s-step').value = '?'; el('s-dip').value = '10'; el('s-unit').value = '200';\n"
            "el('s-unit')._listeners.input[0]({});\n"
            "el('s-nom').value = '1200'; el('s-nom')._listeners.input[0]({});\n"
            "for (let k = 0; k < 3; k++) { el('s-plan-add').click(); size(k, 400); }\n"
            "out.plan = el('s-plan-check').textContent;\n"
            "el('s-go').click(); out.started = !!store.get('calib-site:active');\n"
            "out.before = el('tiles').innerHTML;\n"
            "el('d-val').value = '10'; el('d-go').click(); el('d-val').value = '10'; el('d-go').click();\n"
            "out.t0 = el('tiles').innerHTML;\n"
            "el('t-plus').click(); out.t1 = el('tiles').innerHTML;\n"
            "el('t-plus').click(); out.t2 = el('tiles').innerHTML;\n"
            "el('p-go').click(); out.t3 = el('tiles').innerHTML; out.expect = el('dip-expect-a').textContent;\n"
            "el('d-val').value = '368.9'; el('d-go').click();\n"
            "if (!el('dip-card')._classes.has('hidden')) { el('d-val').value = '368.9'; el('d-go').click(); }\n"
            "out.t4 = el('tiles').innerHTML;\n"
            "// No plan: the right number follows the tapped cans, and the track is a plain connector.\n"
            "const s2 = new Map(); const p2 = stub.boot(page, corePath, s2), e2 = p2.el;\n"
            "e2('s-tank').value = 't2'; e2('s-D').value = '1800'; e2('s-L').value = '3000';\n"
            "e2('s-dip').value = '400'; e2('s-unit').value = '200';\n"
            "e2('s-go').click(); e2('d-val').value = '400'; e2('d-go').click(); e2('d-val').value = '400'; e2('d-go').click();\n"
            "out.n0 = e2('tiles').innerHTML;\n"
            "e2('t-plus').click(); e2('t-plus').click(); out.n1 = e2('tiles').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["empty"], [True, "calib site"], "no campaign: no tile row")
        self.assertEqual(got["plan"], "3 batches · 1200 L = nominal ✓ · symmetric ✓")
        self.assertTrue(got["started"])
        self.assertIn("no level", got["before"])
        self.assertIn("no prediction (the first level)", got["before"])
        t0 = self._tile(got["t0"])
        self.assertEqual((t0["cur"], t0["pred"], t0["width"]),
                         ("10.0", "368.9", "0.0"), "the plan batch is 2 cans of 200 L")
        self.assertFalse(t0["plain"], "a plan draws the progress track")
        self.assertFalse(t0["tally"], "the tile has no can tally: the batch card has it")
        self.assertNotIn(" cans", got["t0"], "no can count in the tooltip either")
        self.assertFalse(t0["wait"], "no reading waits")
        self.assertIsNone(t0["edge"])
        t1 = self._tile(got["t1"])
        self.assertEqual((t1["width"], t1["pred"]), ("50.0", "368.9"),
                         "the prediction stays at the batch end while the track fills")
        t2 = self._tile(got["t2"])
        self.assertEqual((t2["width"], t2["pred"]), ("100.0", "368.9"))
        t3 = self._tile(got["t3"])
        self.assertEqual((t3["width"], t3["pred"]), ("100.0", "368.9"),
                         "after Batch done the prediction is the expected dip")
        self.assertFalse(t3["wait"], "the dip waits, but no reading is typed yet")
        self.assertIn("368.9", got["expect"], "the tile agrees with the dip card")
        t4 = self._tile(got["t4"])
        self.assertEqual((t4["cur"], t4["width"]), ("368.9", "0.0"),
                         "the accepted dip becomes the current level; the next batch starts empty")
        self.assertNotEqual(t4["pred"], "368.9", "the next batch predicts from the new level")
        n0 = self._tile(got["n0"])
        self.assertEqual((n0["cur"], n0["pred"]), ("400.0", "pour to predict"),
                         "no plan and no can: the tile asks for a pour")
        self.assertTrue(n0["plain"], "no plan: a plain connector")
        n1 = self._tile(got["n1"])
        self.assertEqual(n1["cur"], "400.0")
        self.assertNotEqual(n1["pred"], "pour to predict", "the tapped cans give the prediction")
        self.assertTrue(n1["plain"], "no plan: still a plain connector")

    @staticmethod
    def _mark(html):
        """The result marks of the tiles, in order: [(class, text)]."""
        return re.findall(r'class="mk (\w+)" aria-hidden="true">([^<]*)<', html)

    def test_page_tile_result_mark(self):
        """The tile shows the last reading's result, from the reading to the next Batch done."""
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); out.first = el('tiles').innerHTML;\n"
            "el('d-val').value = '400'; el('d-go').click(); out.good = el('tiles').innerHTML;\n"
            "el('t-plus').click(); out.tapped = el('tiles').innerHTML;\n"
            "el('p-go').click(); out.batch = el('tiles').innerHTML;\n"
            "const pred = /class=\"num pred\">([^<]*)</.exec(out.batch)[1];\n"
            "el('d-val').value = String(Number(pred) + 40); el('d-go').click(); out.miss = el('tiles').innerHTML;\n"
            "// A tap on a tile with a mark brings the result card into view on the Live tab.\n"
            "let scrolled = 0; el('verdict').scrollIntoView = () => { scrolled++; };\n"
            "const tap = () => el('tiles')._listeners.click[0]({ target: { closest: () => ({ dataset: { tank: 'one' }, querySelector: (s) => (s === '.mk' ? {} : null) }) } });\n"
            "tap(); out.scrolled = scrolled;\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "tap(); out.otherTab = scrolled;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(self._mark(got["first"]), [("warn", "↻ again")],
                         "the start reading asks for a second reading")
        self.assertEqual(self._mark(got["good"]), [("ok", "✓ good")])
        self.assertIn("Reading confirmed", got["good"], "the tooltip names the verdict")
        self.assertEqual(self._mark(got["tapped"]), [("ok", "✓ good")], "the mark stays while the cans are tapped")
        self.assertEqual(self._mark(got["batch"]), [], "Batch done: the new level has no reading yet")
        self.assertEqual(self._mark(got["miss"]), [("warn", "↻ again")], "a miss asks for another dip")
        self.assertIn('class="wt"', got["miss"], "the waiting ring stays with the mark")
        self.assertEqual(got["scrolled"], 1, "a tap on the tile shows the result card")
        self.assertEqual(got["otherTab"], 1, "other tabs do not scroll")

    def test_page_tile_result_mark_transfer(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-dir-transfer').click();\n"
            "el('s-tank').value = 'alpha'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('sB-tank').value = 'beta'; el('sB-D').value = '2480'; el('sB-L').value = '5200';\n"
            "el('s-dip').value = '1800'; el('sB-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click();\n"
            "out.start = el('tiles').innerHTML;\n"
            "el('d-val').value = '1800'; el('d-go-a').click(); out.a = el('tiles').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(self._mark(got["start"]), [("warn", "↻ again"), ("warn", "↻ again")],
                         "both start readings wait for a second reading")
        self.assertEqual(self._mark(got["a"]), [("ok", "✓ good"), ("warn", "↻ again")],
                         "each tile has its own mark: A is decided, B still waits")

    def test_page_tiles_pending_batch_and_the_waiting_ring(self):
        """A batch waiting for its dip: a full track and the expected dip.

        A reading that the page has not decided yet (here a far miss, so
        the page asks for a re-dip) keeps the accepted dip on the tile and
        adds the red ring after it.
        """
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "const size = (i, v) => el('s-plan')._listeners.input[0]({ target: { dataset: { i: String(i) }, value: String(v) } });\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-step').value = '?'; el('s-dip').value = '10'; el('s-unit').value = '200';\n"
            "el('s-unit')._listeners.input[0]({});\n"
            "el('s-nom').value = '1800'; el('s-nom')._listeners.input[0]({});\n"
            "[[0, 400], [1, 1000], [2, 400]].forEach(([i, v]) => { el('s-plan-add').click(); size(i, v); });\n"
            "out.plan = el('s-plan-check').textContent;\n"
            "el('s-go').click();\n"
            "el('d-val').value = '10'; el('d-go').click(); el('d-val').value = '10'; el('d-go').click();\n"
            "out.open0 = el('tiles').innerHTML;\n"
            "el('t-plus').click(); el('t-plus').click(); out.tapped = el('tiles').innerHTML;\n"
            "el('p-go').click(); out.pending = el('tiles').innerHTML;\n"
            "const pred = /class=\"num pred\">([^<]*)</.exec(out.pending)[1];\n"
            "el('d-val').value = String(Number(pred) + 40); el('d-go').click();\n"
            "out.miss = el('tiles').innerHTML; out.missCard = !el('dip-card')._classes.has('hidden');\n"
            "el('d-val').value = pred; el('d-go').click();\n"
            "if (!el('dip-card')._classes.has('hidden')) { el('d-val').value = pred; el('d-go').click(); }\n"
            "out.next = el('tiles').innerHTML;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["plan"], "3 batches · 1800 L = nominal ✓ · symmetric ✓")
        self.assertEqual(self._tile(got["open0"])["width"], "0.0")
        self.assertEqual(self._tile(got["tapped"])["width"], "100.0")
        pending = self._tile(got["pending"])
        self.assertEqual(pending["width"], "100.0", "the track is full while the dip waits")
        self.assertFalse(pending["wait"], "no reading is typed yet")
        self.assertTrue(got["missCard"], "a far miss asks for another dip")
        miss = self._tile(got["miss"])
        self.assertTrue(miss["wait"], "the typed reading waits: the ring shows")
        self.assertEqual(miss["cur"], "10.0", "the tile keeps the accepted dip")
        self.assertIn("a newer reading waits", got["miss"], "the tooltip says why")
        self.assertEqual(got["next"].count('class="num cur"'), 1)
        nxt = self._tile(got["next"])
        self.assertFalse(nxt["wait"], "the level is decided: no ring")
        self.assertEqual(nxt["cur"], pending["pred"], "the accepted dip is the new current level")

    def test_page_tiles_transfer_own_levels(self):
        """Each transfer tile keeps its own level and prediction."""
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-dir-transfer').click();\n"
            "el('s-tank').value = 'alpha'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('sB-tank').value = 'beta'; el('sB-D').value = '2480'; el('sB-L').value = '5200';\n"
            "el('s-dip').value = '1800'; el('sB-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click();\n"
            "el('d-val').value = '1800'; el('d-val-b').value = '400'; el('d-go-a').click(); el('d-go-b').click();\n"
            "el('d-val').value = '1800'; el('d-go-a').click(); el('d-val-b').value = '400'; el('d-go-b').click();\n"
            "out.start = el('tiles').innerHTML.split('</button>').slice(0, 2);\n"
            "el('t-plus').click(); el('t-plus').click(); el('p-go').click();\n"
            "out.tiles = el('tiles').innerHTML.split('</button>').slice(0, 2);\n"
            "console.log(JSON.stringify(out));"
        )
        start = [self._tile(h) for h in got["start"]]
        self.assertEqual([t["cur"] for t in start], ["1800.0", "400.0"], "each tile shows its own first dip")
        tiles = [self._tile(h) for h in got["tiles"]]
        self.assertEqual([t["tally"] for t in tiles], [False, False], "no tally on the tiles")
        self.assertIn('data-tank="out"', got["tiles"][0])
        self.assertIn('data-tank="in"', got["tiles"][1])
        a, b = tiles
        self.assertEqual(a["cur"], "1800.0")
        self.assertEqual(b["cur"], "400.0")
        self.assertLess(float(a["pred"]), 1800.0, "A falls as it pumps out")
        self.assertGreater(float(b["pred"]), 400.0, "B rises as it pours in")
        self.assertNotEqual(a["pred"], b["pred"], "the same litres land differently in each shell")

    def test_tile_view_overflow_and_neck(self):
        """A brim or neck reading is shown as the level, with no prediction.

        An overflow row is vent-column height, so lastGood() skips it; the
        tile must take it from the current level instead.
        """
        got = _node(
            "const s = new core.Session({D: 1800, Lest: 3000, direction: 'fill', pourUnit: 200});\n"
            "s.start('?', 400); s.dip(400); s.dip(400);\n"
            "const before = s.tileView();\n"
            "s.pour('200', {overflow: true}); s.dip(500); s.dip(500);\n"
            "const over = s.tileView();\n"
            "const d = new core.Session({D: 2400, Lest: 5100, direction: 'drain'});\n"
            "d.start('?', 2600, '', undefined, {at: 'neck'}); d.dip(2600); d.dip(2600);\n"
            "d.pour('200', {neck: true}); d.dip(2500); d.dip(2500);\n"
            "console.log(JSON.stringify({before, over, neck: d.tileView()}));"
        )
        self.assertEqual(got["before"]["why"], "no-cans", "the shell level stands while no can is tapped")
        self.assertEqual((got["over"]["from"], got["over"]["to"], got["over"]["why"]),
                         (500, None, "overflow"), "the overflow reading is the level, with no prediction")
        self.assertNotIn("cans", got["over"], "the tile view has no tally")
        self.assertEqual((got["neck"]["from"], got["neck"]["to"], got["neck"]["why"]),
                         (2500, None, "neck"), "the neck reading is the level, with no prediction")

    def test_tile_view_edges(self):
        """A prediction at a limit keeps its number and names the limit.

        Past the brim the level is held at the brim (2r + h0); a drain below the
        suction floor (65 mm by default) is "floor"; one that empties the
        shell is "dry", held at the floor of the shell.
        """
        got = _node(
            "const f = new core.Session({D: 1800, Lest: 3000, direction: 'fill', pourUnit: 200});\n"
            "f.start('?', 1650); f.dip(1650); f.dip(1650);\n"
            "const fill = [];\n"
            "for (let k = 0; k < 2; k++) { f.tap(1000 + k, 200); fill.push(f.tileView()); }\n"

            "const d = new core.Session({D: 1800, Lest: 3000, direction: 'drain', pourUnit: 50});\n"
            "d.start('?', 200); d.dip(200); d.dip(200);\n"
            "const drain = [];\n"
            "for (let k = 0; k < 10; k++) { d.tap(1000 + k, 50); drain.push(d.tileView()); }\n"
            "console.log(JSON.stringify({fill, drain}));"
        )
        f1, f2 = got["fill"]
        self.assertIsNone(f1["edge"])
        self.assertLess(f1["to"], 1800)
        self.assertEqual((f2["edge"], f2["why"]), ("brim", None), "past the brim: the number stays, marked")
        self.assertAlmostEqual(f2["to"], 1800, places=6, msg="held at the brim (2r + h0)")
        edges = [t["edge"] for t in got["drain"]]
        self.assertEqual(edges[:7], [None] * 7)
        self.assertEqual(edges[7:9], ["floor", "floor"], "below the 65 mm suction floor")
        self.assertEqual(edges[9], "dry", "the drain empties the shell")
        self.assertLess(got["drain"][7]["to"], 65)
        self.assertGreater(got["drain"][6]["to"], 65)
        self.assertTrue(all(t["why"] is None and t["to"] is not None for t in got["drain"]))

    def test_tile_view_pour_panel_input(self):
        """Typed litres and the ticks reach the view the tile and the Now card share."""
        got = _node(
            "const f = new core.Session({D: 1800, Lest: 3000, direction: 'fill', pourUnit: 200});\n"
            "f.start('?', 1000); f.dip(1000); f.dip(1000);\n"
            "const out = { none: f.tileView() };\n"
            "out.typed = f.tileView({ s: 100 });\n"
            "out.part = f.tileView({ why: 'part' });\n"
            "f.tap(1, 200);\n"
            "out.tapped = f.tileView();\n"
            "const d = new core.Session({D: 1800, Lest: 3000, direction: 'drain', pourUnit: 200});\n"
            "d.start('?', 400); d.dip(400); d.dip(400);\n"
            "out.drainLeft = d.tileView().left;\n"
            "// A transfer shares the tally: both tanks label the plan's batch, or neither does.\n"
            "const t = new core.TransferSession({D: 1800, Lest: 3000, direction: 'transfer', pourUnit: 200},\n"
            "  {tank: 'B', D: 1800, Lest: 3000, direction: 'fill', pourUnit: 200});\n"
            "t.start('?', 1800, '?', 400); t.dipBoth(1800, 400);\n"
            "t.tap(1, 200);\n"
            "out.transfer = t.tiles();\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["none"]["why"], "no-cans", "no plan and no can")
        self.assertAlmostEqual(got["none"]["left"]["now"]["mm"], 800, places=6)
        self.assertEqual(got["typed"]["s"], 100, "typed litres replace the batch")
        self.assertLess(got["typed"]["to"], got["none"]["left"]["now"]["level"] + 1)
        self.assertEqual(got["part"]["why"], "part")
        self.assertIsNone(got["part"]["to"], "a part can has no prediction")
        self.assertEqual(got["tapped"]["s"], 200, "the tally is the batch without a plan")
        self.assertFalse(got["tapped"]["planned"])
        self.assertIsNotNone(got["tapped"]["sd"], "the view carries the band §10a.2 shows")
        self.assertAlmostEqual(got["tapped"]["left"]["after"]["mm"], 800 - (got["tapped"]["to"] - 1000), places=0)
        self.assertEqual(got["transfer"]["out"]["planned"], got["transfer"]["in"]["planned"],
                         "one shared tally: both tanks agree on the plan's batch")
        self.assertFalse(got["transfer"]["out"]["planned"], "no plan: the tapped cans are the batch")
        self.assertEqual(got["drainLeft"]["now"]["limit"], "floor", "a drain counts to the suction floor")
        self.assertAlmostEqual(got["drainLeft"]["now"]["level"], 65, places=6)

    def test_tile_view_left_past_the_limit(self):
        """The litres past the brim or the floor, and the emptied left figures."""
        got = _node(
            "const f = new core.Session({D: 1800, Lest: 3000, direction: 'fill', pourUnit: 200});\n"
            "f.start('?', 1780); f.dip(1780); f.dip(1780);\n"
            "f.tap(1, 200);\n"
            "const t = f.tileView();\n"
            "const d = new core.Session({D: 1800, Lest: 3000, direction: 'drain', pourUnit: 50});\n"
            "d.start('?', 200); d.dip(200); d.dip(200);\n"
            "for (let k = 0; k < 10; k++) d.tap(1000 + k, 50);\n"
            "console.log(JSON.stringify({ t, d: d.tileView() }));"
        )
        t = got["t"]
        self.assertEqual((t["edge"], t["past"] is not None, t["beyond"] is not None), ("brim", True, True))
        self.assertGreater(t["past"], 0)
        self.assertGreater(t["beyond"], 0)
        self.assertTrue(t["left"]["after"]["reached"], "past the brim the way left is 0")
        self.assertEqual((t["left"]["after"]["mm"], t["left"]["after"]["L"]), (0, 0))
        d = got["d"]
        self.assertEqual(d["edge"], "dry")
        self.assertGreater(d["beyond"], 0, "past the suction floor too")
        self.assertGreater(d["left"]["now"]["L"], 0)

    def test_cycle_default_time(self):
        """No typed time and no trend: a fixed 1:30 + 0:40 per can, marked default."""
        got = _node(
            "const s = new core.Session({D: 1800, Lest: 3000, direction: 'fill'});\n"
            "const d = s.cycleSecondsFor(200);\n"
            "s.setTimers({ fillSeconds: { 200: 120 }, drainSeconds: { 200: 60 } });\n"
            "const set = s.cycleSecondsFor(200);\n"
            "console.log(JSON.stringify({ d, set }));"
        )
        self.assertEqual(got["d"], {"seconds": 130, "source": "default", "fill": 90, "drain": 40})
        self.assertEqual(got["set"]["source"], "set", "a typed time wins over the default")
        self.assertEqual(got["set"]["seconds"], 180)

    def test_tile_view_edge_while_the_dip_waits(self):
        """Batch done past the brim: the dip card has no number, the tile has the limit."""
        got = _node(
            "const f = new core.Session({D: 1800, Lest: 3000, direction: 'fill', pourUnit: 200});\n"
            "f.start('?', 1650); f.dip(1650); f.dip(1650);\n"
            "f.pour('800');\n"
            "console.log(JSON.stringify({t: f.tileView(), e: f.expectPending()}));"
        )
        self.assertEqual(got["e"]["why"], "the pour reaches the neck")
        self.assertEqual((got["t"]["edge"], got["t"]["why"], got["t"]["frac"]), ("brim", None, 1))
        self.assertAlmostEqual(got["t"]["to"], 1800, places=6)

    def test_page_tally_crowded_cells_keep_one_time(self):
        """Cells too narrow for a time show one pill with the last time."""
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {};\n"
            "const run = (unit, n) => { const p = stub.boot(page, corePath, new Map()), el = p.el;\n"
            "  el('s-tank').value = 't'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "  el('s-dip').value = '400'; el('s-unit').value = String(unit);\n"
            "  el('s-go').click(); el('d-val').value = '400'; el('d-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "  for (let k = 0; k < n; k++) el('t-plus').click();\n"
            "  return {times: el('t-times').innerHTML, cells: el('t-bar').innerHTML, count: el('t-count').textContent}; };\n"
            "out.few = run(200, 2); out.many = run(20, 9);\n"
            "console.log(JSON.stringify(out));"
        )
        few, many = got["few"], got["many"]
        self.assertEqual(few["times"].count('class="pill"'), 2, "room for a time under each can")
        self.assertNotIn("last", few["times"])
        self.assertEqual(many["times"].count('class="pill"'), 1, "crowded: one pill")
        self.assertIn("last ", many["times"])
        self.assertNotIn("last", many["count"], "the big count line stays one line")
        self.assertIn('title="20 L · ', many["cells"], "each cell keeps its size and time in the tooltip")

    def test_page_tile_arrow_follows_the_live_can(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "let clock = Date.UTC(2026, 10, 16, 8, 0, 0), beats = [];\n"
            "class FD extends Date { constructor(...a) { if (a.length) super(...a); else super(clock); } }\n"
            "FD.now = () => clock;\n"
            "const extra = () => ({ Date: FD, setInterval: (fn) => { beats.push(fn); return beats.length; } });\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store, extra()), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "const s = JSON.parse(store.get('calib-site:active'));\n"
            "s.config.fillSeconds = { '200': 60 }; s.config.drainSeconds = { '200': 30 };\n"
            "store.set('calib-site:active', JSON.stringify(s));\n"
            "beats = []; p = stub.boot(page, corePath, store, extra()); el = p.el;\n"
            "const beat = () => { for (const fn of beats) fn(); };\n"
            "const look = () => [el('tiles').dataset.liveOne, el('tiles').dataset.liveOut, el('tiles').dataset.liveIn];\n"
            "beat(); out.idle = look();\n"
            "el('pt-start').click(); clock += 15000; beat(); out.fill = look();\n"
            "el('t-plus').click(); clock += 15000; beat(); out.drain = look();\n"
            "clock += 30000; beat(); out.after = look();\n"
            "// A transfer: A loses water while the pump fills the can, B gains it while the can empties.\n"
            "const s2 = new Map(); let p2 = stub.boot(page, corePath, s2, extra()), e2 = p2.el;\n"
            "e2('s-dir-transfer').click();\n"
            "e2('s-tank').value = 'alpha'; e2('s-D').value = '1800'; e2('s-L').value = '3000';\n"
            "e2('sB-tank').value = 'beta'; e2('sB-D').value = '2480'; e2('sB-L').value = '5200';\n"
            "e2('s-dip').value = '1800'; e2('sB-dip').value = '400'; e2('s-unit').value = '200';\n"
            "e2('s-go').click();\n"
            "e2('d-val').value = '1800'; e2('d-val-b').value = '400'; e2('d-go-a').click(); e2('d-go-b').click();\n"
            "e2('d-val').value = '1800'; e2('d-go-a').click(); e2('d-val-b').value = '400'; e2('d-go-b').click();\n"
            "const t = JSON.parse(s2.get('calib-site:active'));\n"
            "for (const side of [t.out, t.in]) { side.config.fillSeconds = { '200': 60 }; side.config.drainSeconds = { '200': 30 }; }\n"
            "s2.set('calib-site:active', JSON.stringify(t));\n"
            "beats = []; p2 = stub.boot(page, corePath, s2, extra()); e2 = p2.el;\n"
            "const beat2 = () => { for (const fn of beats) fn(); };\n"
            "const look2 = () => [e2('tiles').dataset.liveOne, e2('tiles').dataset.liveOut, e2('tiles').dataset.liveIn];\n"
            "beat2(); out.tidle = look2();\n"
            "e2('pt-start').click(); clock += 15000; beat2(); out.tfill = look2();\n"
            "e2('t-plus').click(); clock += 15000; beat2(); out.tdrain = look2();\n"
            "clock += 30000; beat2(); out.tafter = look2();\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["idle"], ["", "", ""])
        self.assertEqual(got["fill"], ["", "", ""], "a fill tank does not move while the can fills")
        self.assertEqual(got["drain"], ["up", "", ""], "the can empties into the tank: the arrow rises")
        self.assertEqual(got["after"], ["", "", ""])
        self.assertEqual(got["tidle"], ["", "", ""])
        self.assertEqual(got["tfill"], ["", "down", ""], "A loses water while the pump fills the can")
        self.assertEqual(got["tdrain"], ["", "", "up"], "B gains water while the can empties")
        self.assertEqual(got["tafter"], ["", "", ""])
        css = (SITE / "page.html").read_text(encoding="utf-8")
        self.assertIn('.tiles[data-live-out="down"] .tile[data-tank="out"] .wv svg', css,
                      "the wave flows under the same live state as the bob")
        self.assertIn("@keyframes tile-wave { to { transform: translateX(-50%); } }", css,
                      "half the double-width wave: two whole waves, no jump")
        self.assertIn(".tiles .arw, .tiles .wv svg, .tiles .wt { animation: none !important; }", css,
                      "Reduce Motion stops the bob, the wave and the ring")


@unittest.skipUnless(NODE, "node is not installed")
class TestSiteFinish(unittest.TestCase):
    """Finishing a tank: no more dips for it, the other tank carries on."""

    def test_finish_and_reopen_a_single_tank(self):
        got = _node(
            "const s = new core.Session({D: 1800, Lest: 3000, direction: 'fill', pourUnit: 200});\n"
            "const out = {};\n"
            "s.start('?', 1000); s.dip(1000); s.dip(1000);\n"
            "out.before = { why: s.tileView().why, can: !!s.finished };\n"
            "try { s.finish !== null; } catch (e) { out.err = e.message; }\n"
            "const f = s.finish(1700000000000);\n"
            "out.f = f;\n"
            "out.tile = s.tileView();\n"
            "out.csv = s.toRawCsv();\n"
            "out.json = s.toJSON();\n"
            "const back = core.Session.fromJSON(JSON.parse(JSON.stringify(out.json)));\n"
            "out.back = { why: back.tileView().why, level: back.finished.level };\n"
            "out.pourErr = (() => { try { s.pour('200'); return null; } catch (e) { return e.message; } })();\n"
            "back.reopen();\n"
            "out.reopened = { fin: !!back.finished, why: back.tileView().why, csv: back.toRawCsv() };\n"
            "// No accepted level: nothing to close.\n"
            "const e = new core.Session({D: 1800, Lest: 3000, direction: 'fill'});\n"
            "e.start('?', 1000);\n"
            "out.noLevel = (() => { try { e.finish(1); return null; } catch (x) { return x.message; } })();\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["before"]["why"], "no-cans", "no batch yet")
        self.assertFalse(got["before"]["can"])
        self.assertEqual(got["f"]["level"], 1000)
        self.assertEqual(got["f"]["after"], 0)
        self.assertEqual(got["tile"]["why"], "finished", "no prediction for a finished tank")
        self.assertIsNone(got["tile"]["to"])
        self.assertIn("finished at 1000.0 mm", got["csv"])
        self.assertEqual(got["back"], {"why": "finished", "level": 1000}, "the mark survives the session JSON")
        self.assertIn("finished", got["pourErr"], "a finished tank takes no pour")
        self.assertFalse(got["reopened"]["fin"])
        self.assertNotIn("finished at", got["reopened"]["csv"], "Reopen takes the tag back")
        self.assertIn("no level to finish", got["noLevel"])

    def test_finish_discards_the_waiting_level(self):
        got = _node(
            "const s = new core.Session({D: 1800, Lest: 3000, direction: 'fill', pourUnit: 200});\n"
            "s.start('?', 1000); s.dip(1000); s.dip(1000);\n"
            "s.pour('200'); s.dip(1080);\n"
            "// One reading: the level still waits.\n"
            "const rows = s.levels.length;\n"
            "s.finish(5);\n"
            "console.log(JSON.stringify({ rows, after: s.levels.length, last: s.levels[s.levels.length - 1].state, f: s.finished }));"
        )
        self.assertEqual(got["rows"], 2)
        self.assertEqual(got["after"], 1, "the waiting level is discarded")
        self.assertNotEqual(got["last"], "pending")
        self.assertEqual(got["f"]["level"], 1000)

    def test_transfer_finish_skips_one_tank(self):
        got = _node(
            "const t = new core.TransferSession({D: 1800, Lest: 3000, direction: 'drain', pourUnit: 200},\n"
            "  {tank: 'B', D: 1800, Lest: 3000, direction: 'fill', pourUnit: 200});\n"
            "t.start('?', 1800, '?', 400); t.dipBoth(1800, 400);\n"
            "t.tap(1, 200); t.tap(2, 200); t.closeBatch(); t.dipBoth(1700, 500); t.dipBoth(1700, 500);\n"
            "const out = { pending: t.pendingTank() };\n"
            "t.out.finish(3);\n"
            "out.after = { pending: t.pendingTank(), pair: !!t.pair, live: t.liveKeys(), tile: t.tiles().out.why };\n"
            "out.dipErr = (() => { try { t.dipBoth(1700, null); return null; } catch (e) { return e.message; } })();\n"
            "t.tap(3, 200); t.closeBatch();\n"
            "out.levels = { out: t.out.levels.length, in: t.in.levels.length };\n"
            "out.bBatch = t.in.current().step.text;\n"
            "out.adv = t.adviceBatch();\n"
            "out.planRoom = t._planRoom();\n"
            "out.reopen = (() => { try { t.out.reopen(); return null; } catch (e) { return e.message; } })();\n"
            "t.dipBoth('', 560); t.dipBoth('', 560);\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertIsNone(got["after"]["pending"], "the finished tank is not asked for a dip")
        self.assertFalse(got["after"]["pair"], "no pair with one tank finished")
        self.assertEqual(got["after"]["live"], ["in"])
        self.assertEqual(got["after"]["tile"], "finished")
        self.assertIn("finished", got["dipErr"], "a reading for it is refused")
        self.assertEqual(got["levels"], {"out": 2, "in": 3}, "the batch opens a level only on B")
        self.assertEqual(got["bBatch"], "200", "B takes the batch step without A")
        self.assertEqual(got["adv"]["live"], ["in"], "the open tank alone advises")
        self.assertIsNotNone(got["planRoom"])
        self.assertIn("a batch was pumped", got["reopen"], "Reopen is closed after a later batch")

    def test_page_finish_a_single_calibration(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "let p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '1000'; el('s-unit').value = '200'; el('s-go').click();\n"
            "out.noLevel = { disabled: el('now-fin-a').disabled, label: el('now-fin-a').textContent, title: el('now-fin-a').title };\n"
            "el('d-val').value = '1000'; el('d-go').click();\n"
            "out.ready = { disabled: el('now-fin-a').disabled, label: el('now-fin-a').textContent };\n"
            "el('now-fin-a').click();\n"
            "out.fin = { banner: el('fin-banner').textContent, hidden: el('fin-banner')._classes.has('hidden'),\n"
            "  pour: el('pour-card')._classes.has('hidden'), dip: el('dip-card')._classes.has('hidden'),\n"
            "  label: el('now-fin-a').textContent, note: el('now-fin-note').textContent,\n"
            "  tile: el('tiles').innerHTML, pred: el('now-pred').textContent, eta: el('now-eta').innerHTML,\n"
            "  phase: el('hdr-phase').textContent };\n"
            "p = stub.boot(page, corePath, store); el = p.el;\n"
            "out.reload = { finished: !!JSON.parse(store.get('calib-site:active')).finished, banner: el('fin-banner').textContent };\n"
            "el('now-fin-a').click();\n"
            "out.reopened = { pour: el('pour-card')._classes.has('hidden'), banner: el('fin-banner')._classes.has('hidden'),\n"
            "  csv: JSON.parse(JSON.stringify(store.get('calib-site:active'))).finished || null };\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertTrue(got["noLevel"]["disabled"], "no level to finish: the button is closed")
        self.assertIn("No level to finish", got["noLevel"]["title"])
        self.assertFalse(got["ready"]["disabled"])
        self.assertIn("Finish this calibration", got["ready"]["label"])
        self.assertIn("Calibration finished at 1000.0 mm", got["fin"]["banner"])
        self.assertFalse(got["fin"]["hidden"])
        self.assertTrue(got["fin"]["pour"], "the pour card closes")
        self.assertTrue(got["fin"]["dip"])
        self.assertIn("Reopen this calibration", got["fin"]["label"])
        self.assertIn("finished at 1000.0 mm", got["fin"]["note"])
        self.assertIn(">finished<", got["fin"]["tile"], "the tile says finished")
        self.assertEqual(got["fin"]["pred"], "")
        self.assertEqual(got["fin"]["eta"], "")
        self.assertIn("finished", got["fin"]["phase"])
        self.assertTrue(got["reload"]["finished"])
        self.assertIn("Calibration finished", got["reload"]["banner"])
        self.assertFalse(got["reopened"]["pour"], "Reopen brings the pour card back")
        self.assertTrue(got["reopened"]["banner"])
        self.assertIsNone(got["reopened"]["csv"], "Reopen clears the mark")

    def test_page_finish_one_tank_of_a_transfer(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-dir-transfer').click();\n"
            "el('s-tank').value = 'alpha'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('sB-tank').value = 'beta'; el('sB-D').value = '2480'; el('sB-L').value = '5200';\n"
            "el('s-dip').value = '1800'; el('sB-dip').value = '400'; el('s-unit').value = '200'; el('s-go').click();\n"
            "el('d-val').value = '1800'; el('d-val-b').value = '400'; el('d-go-a').click(); el('d-go-b').click();\n"
            "out.buttons = [el('now-fin-a').textContent, el('now-fin-b').textContent];\n"
            "el('now-fin-a').click();\n"
            "out.fin = { note: el('now-fin-note').textContent, a: el('d-val').disabled, aLabel: el('dip-label').textContent,\n"
            "  goA: el('d-go-a')._classes.has('hidden'), b: el('d-val-b').disabled };\n"
            "el('t-plus').click(); el('t-plus').click(); el('p-go').click();\n"
            "out.batch = { header: el('dip-batch-text').textContent, title: el('dip-title').textContent,\n"
            "  bLabel: el('dip-label-b').textContent, pour: el('pour-card')._classes.has('hidden'),\n"
            "  verdict: el('verdict').innerHTML, eta: el('now-eta').innerHTML };\n"
            "out.reopenBtn = { disabled: el('now-fin-a').disabled, title: el('now-fin-a').title };\n"
            "el('d-val-b').value = '441'; el('d-go-b').click();\n"
            "out.one = { pending: JSON.parse(store.get('calib-site:active')).out.levels.length,\n"
            "  inLevels: JSON.parse(store.get('calib-site:active')).in.levels.length };\n"
            "el('now-fin-b').click();\n"
            "out.both = { pred: el('now-pred').textContent, pour: el('pour-card')._classes.has('hidden'),\n"
            "  dip: el('dip-card')._classes.has('hidden'), note: el('now-fin-note').textContent };\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["buttons"], ["Finish (alpha)", "Finish (beta)"])
        self.assertIn("alpha: finished at 1800.0 mm", got["fin"]["note"])
        self.assertTrue(got["fin"]["a"], "the finished tank's field is closed")
        self.assertIn("alpha: finished at 1800.0 mm", got["fin"]["aLabel"])
        self.assertTrue(got["fin"]["goA"], "and its button hides")
        self.assertIn("alpha: finished", got["fin"]["aLabel"], "only the finished tank's label says finished")
        self.assertIn("the reading belongs to beta", got["batch"]["header"])
        self.assertEqual(got["batch"]["title"], "2 · Dip beta")
        self.assertIn("beta: reading after the 400 L batch", got["batch"]["bLabel"])
        self.assertFalse(got["batch"]["pour"],
                         "A is finished, only B waits: the pour card stays for the next can's fill timer")
        self.assertIn("alpha — finished", got["batch"]["verdict"])
        self.assertIn("beta", got["batch"]["eta"], "the time line keeps the open tank")
        self.assertNotIn("alpha", got["batch"]["eta"], "and drops the finished one")
        self.assertTrue(got["reopenBtn"]["disabled"], "Reopen is closed after a batch")
        self.assertIn("A batch was pumped", got["reopenBtn"]["title"])
        self.assertEqual(got["one"]["pending"], 1, "no level was opened for alpha")
        self.assertEqual(got["one"]["inLevels"], 2)
        self.assertIn("Both tanks are finished", got["both"]["pred"])
        self.assertTrue(got["both"]["pour"])
        self.assertTrue(got["both"]["dip"])


class TestSiteBrim(unittest.TestCase):
    """The brim reading the operator types: a prior, a CSV note, a Settings field."""

    def test_typed_brim_is_the_prior(self):
        got = _node(
            "const plain = new core.Session({D: 1800, Lest: 3000, pourUnit: 200});\n"
            "const s = new core.Session({D: 1800, Lest: 3000, pourUnit: 200, brim: 1830, brimPm: 4});\n"
            "s.start('?', 400); s.dip(400); s.dip(400);\n"
            "const p0 = s.cfg.prior;\n"
            "const set = s.setCampaign({brim: 1790}); const p1 = s.cfg.prior;\n"
            "s.setCampaign({brim: ''}); const p2 = s.cfg.prior;\n"
            "let bad = null; try { s.setCampaign({brim: -5}); } catch (e) { bad = e.message; }\n"
            "const blank = new core.Session({D: 1800, Lest: 3000, brim: ''}).cfg.brim;\n"
            "console.log(JSON.stringify({plain: plain.cfg.prior, p0, p1, p2, bad, blank,\n"
            "  fitBrim: [2 * s.fit.p.r + s.fit.p.h0], saved: s.toJSON().config.brim}));"
        )
        self.assertNotIn("B", got["plain"], "no typed brim: no brim prior")
        self.assertEqual((got["p0"]["B"], got["p0"]["sB"], got["p0"]["Bsource"]), (1830, 2, "typed"),
                         "the typed brim is B ± brimPm/2")
        self.assertEqual(got["p1"]["B"], 1790, "a Settings change moves the prior")
        self.assertNotIn("B", got["p2"], "a cleared brim drops the prior")
        self.assertEqual(got["bad"], "the brim reading must be more than 0 mm")
        self.assertIsNone(got["blank"], "a blank field is no brim")
        self.assertIsNone(got["saved"], "the cleared brim is saved as none")

    def test_typed_brim_pulls_the_running_shell(self):
        got = _node(
            "const a = new core.Session({D: 1800, Lest: 3000, pourUnit: 200});\n"
            "const b = new core.Session({D: 1800, Lest: 3000, pourUnit: 200, brim: 1840});\n"
            "for (const s of [a, b]) { s.start('?', 400); s.dip(400); s.dip(400); }\n"
            "const B = (s) => 2 * s.fit.p.r + s.fit.p.h0;\n"
            "console.log(JSON.stringify({a: B(a), b: B(b), adv: b.advice(400).brim}));"
        )
        self.assertAlmostEqual(got["a"], 1800, delta=1, msg="no typed brim: D and the datum give the brim")
        self.assertAlmostEqual(got["b"], 1840, delta=3, msg="the typed brim pins 2r + h0")
        self.assertAlmostEqual(got["adv"], got["b"], places=6, msg="the Now card's brim follows the fit")

    def test_start_reading_wins_and_a_conflict_is_named(self):
        got = _node(
            "const mk = (brim) => { const d = new core.Session({D: 1800, Lest: 3000, direction: 'drain', brim});\n"
            "  const v1 = d.start('?', 1800, '', undefined, {at: 'entrance'}); const v = d.dip(1800);\n"
            "  return {prior: d.cfg.prior, k: d.brimConflict(), msg: v.message, flag: !!v.brimConflict}; };\n"
            "console.log(JSON.stringify({ok: mk(1803), off: mk(1830), none: mk(null)}));"
        )
        self.assertEqual((got["ok"]["prior"]["B"], got["ok"]["prior"]["Bsource"]), (1800, "start"),
                         "the start reading at the brim wins over the typed brim")
        self.assertIsNone(got["ok"]["k"], "3 mm is inside √2 · 6 mm")
        self.assertNotIn("typed brim", got["ok"]["msg"])
        self.assertEqual(got["off"]["prior"]["B"], 1800)
        k = got["off"]["k"]
        self.assertEqual((k["typed"], k["start"], k["diff"]), (1830, 1800, -30))
        self.assertAlmostEqual(k["limit"], 6 * 2 ** 0.5)
        self.assertTrue(got["off"]["flag"])
        self.assertIn("It differs from the typed brim (1830.0 mm) by 30.0 mm, more than ±8.5 mm.", got["off"]["msg"])
        self.assertIn("This is the brim B:", got["off"]["msg"])
        self.assertIsNone(got["none"]["k"])

    def test_raw_csv_carries_the_typed_brim(self):
        got = _node(
            "const s = new core.Session({D: 1800, Lest: 3000, pourUnit: 200, brim: 1830.5, brimPm: 4});\n"
            "s.start('?', 400); s.dip(400); s.dip(400);\n"
            "s.pour('200'); s.dip(s.preview(400, 200, 2).H);\n"
            "const d = new core.Session({D: 1800, Lest: 3000, direction: 'drain', brim: 1801});\n"
            "d.start('?', 1800, '', undefined, {at: 'entrance'}); d.dip(1800);\n"
            "const plain = new core.Session({D: 1800, Lest: 3000}); plain.start('?', 400); plain.dip(400); plain.dip(400);\n"
            "console.log(JSON.stringify({fill: s.toRawCsv(), drain: d.toRawCsv(), plain: plain.toRawCsv()}));"
        )
        fill = got["fill"].splitlines()
        self.assertIn("brim 1830.5 ± 4.0 mm", fill[1].split(",")[2].split("; "))
        self.assertNotIn("brim", fill[2], "only row 1 carries it")
        notes = got["drain"].splitlines()[1].split(",")[2].split("; ")
        self.assertEqual(notes[:3], ["drain campaign", "at brim", "brim 1801.0 ± 6.0 mm"])
        self.assertNotIn("brim", got["plain"].splitlines()[1], "no typed brim: no note")

    def test_transfer_brim_per_tank(self):
        got = _node(
            "const t = new core.TransferSession({tank: 'a', D: 1800, Lest: 3000, brim: 1810}, {tank: 'b', D: 2480, Lest: 5200});\n"
            "t.start('?', 1800, '?', 400, '', Date.now(), {at: 'shell'});\n"
            "t.out.dip(1800); t.in.dip(400); t.in.dip(400);\n"
            "t.active = 'in'; t.setCampaign({brim: 2490, brimPm: 3});\n"
            "console.log(JSON.stringify({a: [t.out.cfg.brim, t.out.cfg.brimPm], b: [t.in.cfg.brim, t.in.cfg.brimPm],\n"
            "  pb: t.in.cfg.prior.B}));"
        )
        self.assertEqual(got["a"], [1810, 6], "tank A keeps its own brim")
        self.assertEqual(got["b"], [2490, 3], "the Settings card edits the chosen tank only")
        self.assertEqual(got["pb"], 2490)

    def test_page_setup_settings_and_now_card(self):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-brim').value = '1830'; el('s-brimpm').value = '4';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click(); el('d-val').value = '400'; el('d-go').click(); el('d-val').value = '400'; el('d-go').click();\n"
            "let cfg = JSON.parse(store.get('calib-site:active')).config;\n"
            "out.cfg = [cfg.brim, cfg.brimPm];\n"
            "out.kv = el('now-kv').innerHTML;\n"
            "el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'settings' } }) } });\n"
            "out.fields = [el('set-brim').value, el('set-brimpm').value];\n"
            "el('set-brim').value = ''; el('set-brimpm').value = ''; el('set-save').click();\n"
            "cfg = JSON.parse(store.get('calib-site:active')).config;\n"
            "out.cleared = [cfg.brim, cfg.brimPm, el('set-msg').textContent];\n"
            "el('set-brim').value = '-3'; el('set-save').click(); out.err = el('set-err').textContent;\n"
            "out.noise = typeof el('set-floor').value;\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["cfg"], [1830, 4], "the setup fields go into the campaign")
        self.assertIn("(typed 1830.0 mm) ·", got["kv"], "the Now card names the typed brim")
        self.assertEqual(got["fields"], ["1830", "4"], "Settings shows the campaign's brim")
        self.assertEqual(got["cleared"][:2], [None, 6], "blank: no brim, ± back to 6 mm")
        self.assertIn("refitted", got["cleared"][2])
        self.assertEqual(got["err"], "Enter the brim reading, more than 0 mm, or leave it blank.")

    def test_page_noise_card_has_no_brim(self):
        html = (SITE / "page.html").read_text(encoding="utf-8")
        noise = html[html.index('id="set-noise"'):html.index('id="set-noise-save"')]
        self.assertNotIn("brim", noise, "the brim ± is a campaign field, not a noise setting")
        self.assertNotIn("neck entrance", html)
        self.assertNotIn("shell crown", html)


class TestSiteFileNames(unittest.TestCase):
    @unittest.skipUnless(NODE, "node is not installed")
    def test_downloads_carry_the_workspace(self):
        """workspace_tank_raw.csv: the campaign's workspace, else the login's, else none."""
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        got = _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            "const out = {};\n"
            "function names(seed) {\n"
            "  const store = new Map(Object.entries(seed));\n"
            "  let p = stub.boot(page, corePath, store), el = p.el;\n"
            "  el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "  el('s-dip').value = '400'; el('s-go').click();\n"
            "  if (seed.link) { store.set('calib-site:link', seed.link); p = stub.boot(page, corePath, store); el = p.el; }\n"
            "  el('f-csv').click(); el('f-json').click();\n"
            "  return p.downloads.slice(-2).map((a) => a.download);\n"
            "}\n"
            "out.none = names({});\n"
            "out.login = names({ 'calib-site:cloud': JSON.stringify({ workspace: 'crew9' }) });\n"
            "out.link = names({ 'calib-site:cloud': JSON.stringify({ workspace: 'crew9' }),"
            " link: JSON.stringify({ id: 'c1', copy: 'k1', ws: 'yard', base: '', rev: 1, synced: 1, version: 1 }) });\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got["none"], ["t1_raw.csv", "t1_site.json"], "no workspace: the tank name alone")
        self.assertEqual(got["login"], ["crew9_t1_raw.csv", "crew9_t1_site.json"], "the logged-in workspace")
        self.assertEqual(got["link"], ["yard_t1_raw.csv", "yard_t1_site.json"], "the campaign's own workspace wins")


_EARLY_HEAD = """
let clock = Date.UTC(2026, 10, 18, 8, 0, 0), beats = [], answer = true;
const asked = [];
class FD extends Date { constructor(...a) { if (a.length) super(...a); else super(clock); } }
FD.now = () => clock;
const extra = () => ({ Date: FD, setInterval: (fn) => { beats.push(fn); return beats.length; },
  confirm: (q) => { asked.push(q); return answer; } });
const beat = () => { for (const fn of beats) fn(); };
const out = {}, store = new Map();
let p = stub.boot(page, corePath, store, extra()), el = p.el;
/** Set the timers in the saved session and boot again. */
function timers(s) {
  const a = JSON.parse(store.get('calib-site:active'));
  for (const c of a.out ? [a.out.config, a.in.config] : [a.config]) {
    c.fillSeconds = { '200': 60 }; c.settleSeconds = s;
  }
  store.set('calib-site:active', JSON.stringify(a));
  beats = []; p = stub.boot(page, corePath, store, extra()); el = p.el;
}
const card = () => ({ hidden: el('pour-card')._classes.has('hidden'),
  note: el('t-early')._classes.has('hidden') ? '' : el('t-early').textContent,
  title: el('pour-title').textContent, plus: el('t-plus').disabled, go: el('p-go').disabled,
  undo: el('t-undo').disabled, opts: el('p-opts')._classes.has('hidden'),
  start: !el('pt-start')._classes.has('hidden'), size: el('t-unit').disabled });
const timer = () => JSON.parse(store.get('calib-site:timer') || '{}');
"""


class TestSiteEarlyTimer(unittest.TestCase):
    """The next can's fill timer while the dip waits (fill; transfer once A is decided)."""

    def _run(self, body: str):
        stub = (HERE / "tests" / "page_stub.js").as_posix()
        return _node(
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps(CORE)};\n"
            + _EARLY_HEAD + body + "\nconsole.log(JSON.stringify(out));"
        )

    @unittest.skipUnless(NODE, "node is not installed")
    def test_fill_timer_runs_while_the_dip_waits(self):
        got = self._run(
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click();\n"
            "for (let k = 0; k < 3 && !el('dip-card')._classes.has('hidden'); k++) { el('d-val').value = '400'; el('d-go').click(); }\n"
            "timers(90);\n"
            "out.before = card();\n"
            "el('t-plus').click(); el('p-go').click();\n"
            "out.wait = card();\n"
            "out.dip = !el('dip-card')._classes.has('hidden');\n"
            "el('pt-start').click(); out.early = timer().pour && timer().pour.early;\n"
            "clock += 65000; beat();\n"
            "out.full = { status: el('pt-status').textContent, pulse: el('t-plus')._classes.has('pulse'),"
            " alarm: el('alarm-text').textContent };\n"
            "clock += 30000; beat();\n"
            "out.settled = { line: el('dip-settle').textContent, alarm: el('alarm-text').textContent };\n"
            "for (let k = 0; k < 3 && !el('dip-card')._classes.has('hidden'); k++) { el('d-val').value = '470'; el('d-go').click(); }\n"
            "if (!el('dip-card')._classes.has('hidden')) el('a-override').click();\n"
            "out.after = card(); out.running = !!timer().pour;\n"
            "el('t-plus').click();\n"
            "const s = JSON.parse(store.get('calib-site:active'));\n"
            "out.can = s.batch.cans[0]; out.stopped = !timer().pour;\n"
        )
        self.assertFalse(got["before"]["hidden"])
        self.assertEqual(got["before"]["note"], "")
        w = got["wait"]
        self.assertTrue(got["dip"], "the dip waits")
        self.assertFalse(w["hidden"], "the pour card stays for the next can")
        self.assertEqual(w["title"], "1 · Next can")
        self.assertIn("The pump can fill the next can now", w["note"])
        self.assertTrue(w["plus"] and w["go"] and w["undo"], "the count and the batch wait for the verdict")
        self.assertTrue(w["opts"], "Options hide while the dip waits")
        self.assertTrue(w["start"])
        self.assertFalse(w["size"], "the can size stays editable")
        self.assertTrue(got["early"], "the run knows it started while a dip waited")
        self.assertIn("Empty it into the tank after the dip", got["full"]["status"])
        self.assertFalse(got["full"]["pulse"], "+1 can is locked: no pulse")
        self.assertIn("Can full", got["full"]["alarm"])
        self.assertIn("Settled", got["settled"]["line"])
        self.assertIn("Can full", got["settled"]["alarm"], "the fill alarm wins over the settle alarm")
        a = got["after"]
        self.assertFalse(a["hidden"])
        self.assertEqual(a["note"], "")
        self.assertFalse(a["plus"], "+1 can opens after the verdict")
        self.assertFalse(a["opts"])
        self.assertTrue(got["running"], "the timer runs on after the verdict")
        self.assertNotIn("f", got["can"], "the can that waited for the verdict gives no fill time")
        self.assertTrue(got["stopped"], "the tap ends the timer")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_drain_keeps_the_timer_locked(self):
        got = self._run(
            "el('s-dir-drain').click();\n"
            "el('s-tank').value = 't1'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('s-dip').value = '1500'; el('s-unit').value = '200';\n"
            "el('s-go').click();\n"
            "for (let k = 0; k < 3 && !el('dip-card')._classes.has('hidden'); k++) { el('d-val').value = '1500'; el('d-go').click(); }\n"
            "timers(90);\n"
            "el('t-plus').click(); el('p-go').click();\n"
            "out.wait = card(); out.dip = !el('dip-card')._classes.has('hidden');\n"
        )
        self.assertTrue(got["dip"])
        self.assertTrue(got["wait"]["hidden"], "a drain draws from the dipped tank: no early timer")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_transfer_unlocks_when_tank_a_is_decided(self):
        got = self._run(
            "el('s-dir-transfer').click();\n"
            "el('s-tank').value = 'alpha'; el('s-D').value = '1800'; el('s-L').value = '3000';\n"
            "el('sB-tank').value = 'beta'; el('sB-D').value = '2480'; el('sB-L').value = '5200';\n"
            "el('s-dip').value = '1800'; el('sB-dip').value = '400'; el('s-unit').value = '200';\n"
            "el('s-go').click();\n"
            "const dipA = (v) => { for (let k = 0; k < 3 && !el('d-go-a').disabled; k++) { el('d-val').value = v; el('d-go-a').click(); } };\n"
            "const dipB = (v) => { for (let k = 0; k < 3 && !el('d-go-b').disabled; k++) { el('d-val-b').value = v; el('d-go-b').click(); } };\n"
            "dipA('1800'); dipB('400');\n"
            "timers(90);\n"
            "el('t-plus').click(); el('p-go').click();\n"
            "out.both = card();\n"
            "dipA('1770');\n"
            "out.aDone = card(); out.bOpen = !el('d-val-b').disabled;\n"
            "el('pt-start').click(); out.early = timer().pour && timer().pour.early;\n"
            "// Take another reading of A: the page asks to stop the pump first.\n"
            "answer = false; el('a-redip').click();\n"
            "out.kept = { asked: asked.length, running: !!timer().pour, card: card().hidden };\n"
            "answer = true; el('a-redip').click();\n"
            "out.redip = { asked: asked.length, running: !!timer().pour, card: card().hidden };\n"
        )
        self.assertTrue(got["both"]["hidden"], "A waits: the pump must not draw from it")
        self.assertFalse(got["aDone"]["hidden"], "A decided: the next can may fill from A")
        self.assertIn("Tank B waits for its dip", got["aDone"]["note"])
        self.assertTrue(got["aDone"]["plus"] and got["aDone"]["go"])
        self.assertTrue(got["bOpen"], "B's field stays open for its reading")
        self.assertTrue(got["early"])
        self.assertEqual(got["kept"], {"asked": 1, "running": True, "card": False}, "No keeps A decided and the timer on")
        self.assertEqual(got["redip"], {"asked": 2, "running": False, "card": True}, "Yes stops the timer and re-opens A")


if __name__ == "__main__":
    unittest.main()

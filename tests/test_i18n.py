"""The page translator (site/i18n.js) and its Vietnamese dictionary.

The page and the core write English; the translator shows each text in the
chosen language.  These tests check the translator's rules, and that every
text the page can show has a Vietnamese key: the static HTML of page.html,
and every text the page and the core write on the paths the harness drives
(tests/i18n_harness.js).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from calib.site_page import SITE, build_page

HERE = Path(__file__).resolve().parent
NODE = shutil.which("node")
I18N = (SITE / "i18n.js").as_posix()
VOID = {"br", "input", "img", "meta", "link", "rect", "path", "circle", "line", "stop"}


class _Static(HTMLParser):
    """The texts and the title, aria-label and placeholder attributes of page.html.

    Skips script, style, textarea and anything under translate="no", as the
    page's translator does.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.out: set[str] = set()

    def _skipped(self) -> bool:
        return any(t in ("script", "style", "textarea") or no for t, no in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        no = a.get("translate") == "no"
        if not no and not self._skipped():
            for k in ("title", "aria-label", "placeholder"):
                if a.get(k) and re.search(r"[A-Za-z]", a[k]):
                    self.out.add(a[k])
        if tag not in VOID:
            self.stack.append((tag, no))

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        if self._skipped():
            return
        t = " ".join(data.split())
        if re.search(r"[A-Za-z]", t):
            self.out.add(t)


def static_texts() -> list[str]:
    p = _Static()
    p.feed((SITE / "page.html").read_text(encoding="utf-8"))
    return sorted(p.out)


def _node(body: str):
    script = f"const I = require({json.dumps(I18N)});\n{body}\n"
    out = subprocess.run(  # noqa: S603
        [NODE, "-e", script], capture_output=True, text=True, timeout=120, check=False
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class TestI18nBuild(unittest.TestCase):
    def test_page_inlines_the_translator(self):
        page = build_page()
        i18n = (SITE / "i18n.js").read_text(encoding="utf-8").rstrip("\n")
        self.assertIn(i18n, page)
        self.assertNotIn("/*@I18N@*/", page)

    def test_static_texts_found(self):
        texts = static_texts()
        self.assertIn("Start campaign", texts)
        self.assertIn("How the check works", texts)
        self.assertNotIn("calib site", texts, "the title is marked translate=no")


@unittest.skipUnless(NODE, "node is not installed")
class TestI18nEngine(unittest.TestCase):
    def test_rules(self):
        got = _node(
            "const t = (s) => I.translate(s, 'vi');\n"
            "console.log(JSON.stringify({\n"
            "  exact: t('Start campaign'),\n"
            "  en: I.translate('Start campaign', 'en'),\n"
            "  number: t('Expect 125.1 ± 1.9 mm'),\n"
            "  clock: t('Settling: 3:20 left.'),\n"
            "  name: t('Check alpha'),\n"
            "  why: t('No prediction can test the first level.'),\n"
            "  split: t('Dip again. Do not look at the first reading.'),\n"
            "  parts: t('learning 2/3 · drain'),\n"
            "  keep: t('  Reading confirmed  '),\n"
            "  unknown: t('A sentence with no key.'),\n"
            "  partial: t('Dip again. A sentence with no key.'),\n"
            "  report: I.report('Dip again. A sentence with no key.', 'vi'),\n"
            "  names: I.report('Check alpha', 'vi'),\n"
            "  langs: I.LANGS.map((x) => x.code),\n"
            "}));"
        )
        self.assertEqual(got["exact"], "Bắt đầu đợt đo")
        self.assertEqual(got["en"], "Start campaign", "English is the page's own text")
        self.assertEqual(got["number"], "Dự kiến 125.1 ± 1.9 mm", "a digit placeholder carries the number")
        self.assertEqual(got["clock"], "Đang chờ ổn định: còn 3:20.", "a clock is a number")
        self.assertEqual(got["name"], "Kiểm tra alpha", "a tank name stays as typed")
        self.assertEqual(got["why"], "Không có dự đoán nào kiểm tra được mức đầu tiên.",
                         "a named capture that is a key is translated too")
        self.assertEqual(got["split"], "Đo lại. Đừng nhìn số đo đầu tiên.", "sentences are looked up one by one")
        self.assertEqual(got["parts"], "đang học 2/3 · bơm ra", "parts joined by · are looked up one by one")
        self.assertEqual(got["keep"], "  Số đo đã xác nhận  ", "the whitespace around a text stays")
        self.assertEqual(got["unknown"], "A sentence with no key.", "no key: the text stays English")
        self.assertEqual(got["partial"], "Đo lại. A sentence with no key.")
        self.assertEqual(got["report"], ["A sentence with no key."])
        self.assertEqual(got["names"], ["alpha"], "a named capture with no key counts as missing")
        self.assertEqual(got["langs"], ["en", "vi"])

    def test_a_capture_stays_in_one_sentence(self):
        got = _node(
            "console.log(JSON.stringify(I.translate('Dip again. Do not look at the earlier readings.', 'vi')));"
        )
        self.assertEqual(got, "Đo lại. Đừng nhìn các số đo trước.",
                         "'Dip {name}' must not swallow a whole second sentence")

    def test_placeholders_match(self):
        """Every placeholder of a value is a placeholder of its key."""
        got = _node(
            "const out = [];\n"
            "for (const [k, v] of I.entries('vi')) {\n"
            "  const pk = new Set(k.match(/\\{\\w+\\}/g) || []);\n"
            "  for (const p of v.match(/\\{\\w+\\}/g) || []) if (!pk.has(p)) out.push(k);\n"
            "}\n"
            "console.log(JSON.stringify(out));"
        )
        self.assertEqual(got, [])


@unittest.skipUnless(NODE, "node is not installed")
class TestI18nCoverage(unittest.TestCase):
    def test_every_text_has_a_vietnamese_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            statics = Path(tmp) / "static.json"
            statics.write_text(json.dumps(static_texts()), encoding="utf-8")
            out = subprocess.run(  # noqa: S603
                [NODE, (HERE / "i18n_harness.js").as_posix(), "vi", statics.as_posix()],
                capture_output=True, text=True, timeout=300, check=False,
            )
        if out.returncode != 0:
            raise AssertionError(out.stderr)
        missing = json.loads(out.stdout)
        self.assertEqual(missing, [], "texts the page shows with no Vietnamese key (add them to site/i18n.js)")


@unittest.skipUnless(NODE, "node is not installed")
class TestI18nPage(unittest.TestCase):
    def test_language_setting(self):
        stub = (HERE / "page_stub.js").as_posix()
        script = (
            f"const stub = require({json.dumps(stub)});\n"
            f"const page = {json.dumps((SITE / 'page.html').as_posix())};\n"
            f"const corePath = {json.dumps((SITE / 'site_core.js').as_posix())};\n"
            "const out = {}, store = new Map();\n"
            "const p = stub.boot(page, corePath, store), el = p.el;\n"
            "out.options = el('set-lang').innerHTML;\n"
            "out.value = el('set-lang').value;\n"
            "el('set-lang').value = 'vi';\n"
            "el('set-lang')._listeners.change[0]({});\n"
            "out.saved = JSON.parse(store.get('calib-site:prefs')).lang;\n"
            "const p2 = stub.boot(page, corePath, store);\n"
            "out.reloaded = p2.el('set-lang').value;\n"
            "console.log(JSON.stringify(out));"
        )
        out = subprocess.run(  # noqa: S603
            [NODE, "-e", script], capture_output=True, text=True, timeout=120, check=False
        )
        if out.returncode != 0:
            raise AssertionError(out.stderr)
        got = json.loads(out.stdout)
        self.assertIn('value="en"', got["options"])
        self.assertIn("Tiếng Việt", got["options"])
        self.assertEqual(got["value"], "en", "English without a choice or a Vietnamese device")
        self.assertEqual(got["saved"], "vi")
        self.assertEqual(got["reloaded"], "vi", "the choice stays on the device")


if __name__ == "__main__":
    unittest.main()

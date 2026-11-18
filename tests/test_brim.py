"""The brim notes of the raw file and the declared brim (§5.3a).

The site page writes ``at brim`` on row 1 of a drain that starts at the
brim (older files: ``at neck entrance``): that reading is the brim B and the
fit enforces ``2r + h0 = B``.  A brim the operator typed goes on row 1 as
``brim 1795.0 ± 6.0 mm``: a reading from outside the campaign, so the fit
compares it with its own brim and reports the difference, never enforces it.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from calib.config import load_config
from calib.data import read_raw
from calib.pipeline import run
from calib.scaffold import infer_config, infer_declared_brim, infer_neck_entrance

HERE = Path(__file__).resolve().parent.parent
DEMO = HERE / "examples" / "demo.json"


def _write(tmp: Path, name: str, lines: list[str]) -> Path:
    path = tmp / name
    path.write_text("step_volume,measured_height,note\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestBrimNotes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def _drain(self, note: str) -> Path:
        return _write(self.dir, "d_raw.csv", [
            f"?,1790.0,{note}", "200,1740.0,", "200,1700.0,", "200,1663.0,", "200,1628.0,",
        ])

    def test_at_brim_and_the_old_note_give_the_equality(self):
        for note in ("drain campaign; at brim; dips 1790.0/1790.0", "drain campaign; at neck entrance"):
            with self.subTest(note=note):
                raw = self._drain(note)
                self.assertEqual(infer_neck_entrance(read_raw(raw)), 1790.0)
                data, _ = infer_config(raw, r=880.0, L=2950.0)
                self.assertEqual(data["brim"]["reading"], 1790.0)
                self.assertTrue(data["brim"]["neck_equality"])
                self.assertNotIn("declared", data["brim"])

    def test_brim_word_alone_is_not_a_start_at_the_brim(self):
        raw = self._drain("drain campaign; brim 1795.0 ± 6.0 mm")
        self.assertIsNone(infer_neck_entrance(read_raw(raw)))

    def test_declared_brim_on_a_fill(self):
        raw = _write(self.dir, "f_raw.csv", [
            "?,400.0,brim 1795.5 ± 6.0 mm; dips 400.0/400.0; site start",
            "200,430.0,", "200,458.0,",
        ])
        self.assertEqual(infer_declared_brim(read_raw(raw)), (1795.5, 6.0))
        data, _ = infer_config(raw, r=880.0, L=2950.0)
        self.assertEqual(data["brim"], {"declared": 1795.5, "declared_pm": 6.0},
                         "declared only: no reading, no equality")

    def test_declared_without_pm_and_on_a_drain_start(self):
        raw = self._drain("drain campaign; at brim; brim 1801 mm")
        data, _ = infer_config(raw, r=880.0, L=2950.0)
        self.assertEqual((data["brim"]["reading"], data["brim"]["declared"]), (1790.0, 1801.0),
                         "the start reading is the reading; the typed brim is declared beside it")
        self.assertNotIn("declared_pm", data["brim"])

    def test_no_note_no_declared(self):
        raw = _write(self.dir, "p_raw.csv", ["?,400.0,site start", "200,430.0,"])
        self.assertIsNone(infer_declared_brim(read_raw(raw)))

    def test_config_loads_and_checks_the_declared_brim(self):
        raw = _write(self.dir, "c_raw.csv", ["?,400.0,", "200,430.0,"])
        cfg = {"tank": "t", "raw": raw.name, "nominal": {"r": 880.0, "L": 2950.0},
               "brim": {"declared": 1795.0, "declared_pm": 4.0}}
        path = self.dir / "t.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        c = load_config(path)
        self.assertEqual((c.brim_declared, c.brim_declared_pm, c.brim_reading), (1795.0, 4.0, None))
        cfg["brim"]["declared"] = -1
        path.write_text(json.dumps(cfg), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_config(path)


class TestDeclaredBrimPipeline(unittest.TestCase):
    """The declared brim is compared and reported; the fit stays free."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.plain = cls._run(None, "plain")
        cls.near = cls._run(1795.0, "near")
        cls.far = cls._run(1740.0, "far")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def _run(cls, declared, name):
        cfg = json.loads(DEMO.read_text(encoding="utf-8"))
        cfg["raw"] = str((HERE / "examples" / cfg["raw"]).resolve())
        cfg["bootstrap_n"] = 5
        cfg["brim"] = {"overflow_pour": cfg["brim"]["overflow_pour"]}
        if declared is not None:
            cfg["brim"].update({"declared": declared, "declared_pm": 6.0})
        path = cls.dir / f"{name}.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return run(path, cls.dir / name, make_charts=False)

    def test_no_declared_no_check(self):
        self.assertIsNone(self.plain["declared_brim"])
        self.assertNotIn("declared brim", self.plain["shell_record"])

    def test_declared_never_bends_the_shell(self):
        for res in (self.near, self.far):
            self.assertAlmostEqual(res["free_fit"].shell.brim(), self.plain["free_fit"].shell.brim(), places=6)
            self.assertAlmostEqual(res["fit"].shell.r, self.plain["fit"].shell.r, places=6)

    def test_near_agrees_far_differs(self):
        near, far = self.near["declared_brim"], self.far["declared_brim"]
        self.assertTrue(near["agree"], near)
        self.assertFalse(far["agree"], far)
        self.assertAlmostEqual(far["diff"], self.plain["free_fit"].shell.brim() - 1740.0, places=6)
        self.assertGreater(far["sigma"], 3.0 - 1e-9, "the declared ± (2σ) gives at least 3 mm of 1σ")
        self.assertIn("declared brim 1740.0 ± 6 mm: free fit", self.far["shell_record"])
        self.assertIn("compared, not enforced", self.far["shell_record"])


if __name__ == "__main__":
    unittest.main()

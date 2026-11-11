"""Tests for the campaign scaffold and the preflight report."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from calib.config import load_config
from calib.scaffold import infer_config, preflight, tank_stem, write_config

HERE = Path(__file__).resolve().parent.parent
DEMO_RAW = HERE / "examples" / "demo_raw.csv"


class TestTankStem(unittest.TestCase):
    def test_strips_the_raw_suffix(self):
        self.assertEqual(tank_stem("run1_raw.csv"), "run1")
        self.assertEqual(tank_stem("tankA_data.csv"), "tankA")
        self.assertEqual(tank_stem("run1.csv"), "run1")


class TestInferConfig(unittest.TestCase):
    def test_infers_the_demo_fields(self):
        data, warnings = infer_config(DEMO_RAW, r=880.0, L=2950.0)
        self.assertEqual(data["tank"], "demo")
        self.assertEqual(data["raw"], "demo_raw.csv")
        self.assertEqual(data["pour_unit"], 50.0)
        self.assertEqual(data["brim"]["overflow_pour"], 120.0)
        self.assertFalse(data["heel_row"])
        self.assertTrue(any("unknown" in w for w in warnings))

    def test_keeps_the_tank_record(self):
        data, _ = infer_config(
            DEMO_RAW, r=880.0, L=2950.0, tank="run7", site="Farm A", sigma_h=2.0
        )
        self.assertEqual(data["tank"], "run7")
        self.assertEqual(data["site"], "Farm A")
        self.assertEqual(data["sigma_h"], 2.0)
        self.assertEqual(data["nominal"], {"r": 880.0, "L": 2950.0})

    def test_overrides_an_inferred_value(self):
        data, warnings = infer_config(
            DEMO_RAW, r=880.0, L=2950.0, pour_unit=25.0, overflow_pour=0.0
        )
        self.assertEqual(data["pour_unit"], 25.0)
        self.assertEqual(data["brim"]["overflow_pour"], 0.0)
        self.assertTrue(any("overrides" in w for w in warnings))

    def test_rejects_a_bad_tank_record(self):
        with self.assertRaises(ValueError):
            infer_config(DEMO_RAW, r=0.0, L=2950.0)


class TestWriteConfig(unittest.TestCase):
    def test_written_config_loads_and_finds_the_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.json"
            data, _ = infer_config(DEMO_RAW, r=880.0, L=2950.0)
            write_config(out, data, raw_path=DEMO_RAW)
            cfg = load_config(out)
            self.assertEqual(cfg.tank, "demo")
            self.assertEqual(cfg.nominal_r, 880.0)
            self.assertEqual(cfg.pour_unit, 50.0)
            self.assertTrue(Path(cfg.raw).exists())

    def test_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.json"
            out.write_text("{}", encoding="utf-8")
            data, _ = infer_config(DEMO_RAW, r=880.0, L=2950.0)
            with self.assertRaises(FileExistsError):
                write_config(out, data, raw_path=DEMO_RAW)
            write_config(out, data, raw_path=DEMO_RAW, force=True)
            self.assertIn("nominal", out.read_text(encoding="utf-8"))


class TestPreflight(unittest.TestCase):
    def test_reports_the_trusted_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.json"
            data, _ = infer_config(DEMO_RAW, r=880.0, L=2950.0)
            write_config(out, data, raw_path=DEMO_RAW)
            report = preflight(out)
            self.assertEqual(report["rows"], 22)
            self.assertEqual(report["intervals"], 21)
            self.assertGreater(report["trusted"], 0)
            reasons = {item["reason"] for item in report["untrusted"]}
            self.assertIn("unknown pour", reasons)
            self.assertIn("overflow interval", reasons)
            self.assertEqual(len(report["unknown_pours"]), 1)

    def test_reports_a_correction_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.json"
            data, _ = infer_config(DEMO_RAW, r=880.0, L=2950.0)
            data["corrections"] = [
                {"row": 12, "field": "height", "value": 629.0, "rule": "6.1",
                 "magnitude": -4.0, "note": "dip misread"}
            ]
            write_config(out, data, raw_path=DEMO_RAW)
            report = preflight(out)
            self.assertEqual(len(report["corrections"]), 1)
            self.assertEqual(report["corrections"][0]["row"], 12)


if __name__ == "__main__":
    unittest.main()

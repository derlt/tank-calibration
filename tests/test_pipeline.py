"""End-to-end test on the synthetic demo campaign."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from calib.charts import build_series
from calib.data import build_intervals, mark_trusted, read_raw
from calib.fit import fit_joint
from calib.formula_gate import gate_workbook
from calib.pipeline import run

HERE = Path(__file__).resolve().parent.parent
DEMO = HERE / "examples" / "demo.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cfg = json.loads(DEMO.read_text(encoding="utf-8"))
        cfg["bootstrap_n"] = 20
        cfg["raw"] = str((DEMO.parent / cfg["raw"]).resolve())
        cls.cfg_path = cls.out / "demo.json"
        cls.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        cls.raw = Path(cfg["raw"])
        cls.before = _digest(cls.raw)
        cls.result = run(cls.cfg_path, cls.out / "out")
        cls.after = _digest(cls.raw)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_truth_recovered(self):
        fit = self.result["fit"]
        self.assertLess(abs(fit.shell.r - 900.0), 15.0)
        self.assertLess(abs(fit.shell.L - 3000.0), 60.0)
        self.assertLess(abs(fit.shell.h0 + 5.0), 12.0)

    def test_acceptance(self):
        for check in self.result["acceptance"]:
            self.assertTrue(check["pass"], f"{check['check']}: {check['result']}")

    def test_unknown_pour(self):
        self.assertEqual(len(self.result["unknowns"]), 1)
        u = self.result["unknowns"][0]
        self.assertLess(abs(u["x"] - 600.0), 45.0)
        self.assertLess(u["lo"], 600.0)
        self.assertGreater(u["hi"], 600.0)

    def test_raw_untouched(self):
        self.assertEqual(self.before, self.after)

    def test_artifacts(self):
        out = self.out / "out"
        for name in [
            "demo_raw.csv",
            "demo_corrected.csv",
            "demo_strapping.csv",
            "demo_commercial.csv",
            "demo_anomaly_register.csv",
            "demo_shell_record.txt",
            "demo_presets.json",
            "demo_workbook.xlsx",
            "demo_report.md",
        ]:
            self.assertTrue((out / name).exists(), name)
        for name in (
            "01_strapping.png",
            "02_residuals.png",
            "03_predicted_vs_recorded.png",
            "04_slope_profile.png",
            "05_drift.png",
            "06_z_alarms.png",
            "07_pair_scatter.png",
            "08_r_profile.png",
            "pour_fit.png",
            "pour_fit_views.png",
            "anomaly_detector.png",
            "00_all_views.png",
        ):
            self.assertTrue((out / "charts" / name).exists(), name)

    def test_workbook_gate(self):
        out = gate_workbook(self.out / "out" / "demo_workbook.xlsx")
        self.assertTrue(out["ok"], out["errors"][:3])
        self.assertGreater(out["formulas"], 50)

    def test_workbook_chart_sheets(self):
        wb = load_workbook(self.out / "out" / "demo_workbook.xlsx")
        for name in ("Model", "RawModel", "Curve", "Pairs", "RawPairs", "Guides", "Charts"):
            self.assertIn(name, wb.sheetnames)
        self.assertEqual(len(wb["Charts"]._charts), 7)

    def test_strapping_extrapolated_below_lowest_dip(self):
        rows = self.result["strapping"]
        self.assertEqual(rows[0]["flag"], "extrapolated")
        self.assertIn("brim-anchored", rows[-1]["flag"])

    def test_table_header_is_part_of_the_output(self):
        header = self.result["table_header"]
        self.assertEqual(header["title"], "demo — tank calibration certificate")
        self.assertIn("Formula gate", [label for label, _ in header["quality"]])

        out = self.out / "out"
        text = (out / "demo_strapping.csv").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# demo — tank calibration certificate"))
        self.assertIn("#   Radius r (mm):", text)
        self.assertIn("# ---", text)

        wb = load_workbook(out / "demo_workbook.xlsx")
        self.assertEqual(wb.sheetnames[0], "Certificate")

    def test_audit_sheet_uses_trusted_rows(self):
        wb = load_workbook(self.out / "out" / "demo_workbook.xlsx")
        ws = wb["Audit"]
        n = 0
        for row in ws.iter_rows(min_row=15, max_col=4):
            if row[0].value is None:
                break
            n += 1
        trusted = sum(1 for iv in self.result["intervals"] if iv.trusted)
        self.assertEqual(n, trusted)
        self.assertEqual(ws["B10"].value, f"=SUMPRODUCT(J15:J{14 + n},J15:J{14 + n})")

    def test_object_bookkeeping(self):
        fit = self.result["fit"]
        bands = self.result["bands"]
        self.assertAlmostEqual(
            self.result["commercial"][-1]["volume_l"],
            round(fit.shell.capacity() - bands[0]["displacement"]),
            delta=2,
        )

    def test_closure_counts_the_first_pour(self):
        # Before the books fix the diff was -46 L: exactly the first pour,
        # dropped from the books, hidden by the 3-sigma-sqrt(n) limit.
        self.assertLess(abs(self.result["closure"]["diff"]), 20.0)

    def test_qa_books_agreement(self):
        # Before the books fix the max was 52.8 L: the same constant offset
        # at every row, not a data-to-model disagreement.
        self.assertLess(self.result["qa"]["max"], 20.0)

    def test_drift_definitions_agree(self):
        # The interval drift (Diagnostics sheet) and the chart series drift
        # (chart 5, Model sheet) are one quantity (§2).  They used to differ
        # by the first pour and by every unknown pour.
        cfg = self.result["config"]
        series = build_series(
            self.result["rows"], self.result["fit"].shell,
            sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
            heel_row=cfg.heel_row,
        )
        by_row = {iv.row: iv for iv in self.result["intervals"]}
        for k in range(len(series)):
            iv = by_row[int(series.row[k])]
            self.assertAlmostEqual(iv.drift, float(series.drift[k]), places=6)

    def test_workbook_certificate_carries_gate(self):
        wb = load_workbook(self.out / "out" / "demo_workbook.xlsx")
        gate_rows = [
            " ".join(str(c) for c in row if c is not None)
            for row in wb["Certificate"].iter_rows(values_only=True)
            if any(c == "Formula gate" for c in row)
        ]
        self.assertTrue(gate_rows)
        self.assertIn("0 problems", gate_rows[0])
        self.assertNotIn("run `calib gate`", gate_rows[0])

    def test_register_records_the_overflow_interval(self):
        # The demo overflow pour can fill the gap; that fact must ship.
        kinds = [e["kind"] for e in self.result["register"]]
        self.assertIn("overflow interval", kinds)


class TestJoint(unittest.TestCase):
    """`calib joint` must fit the trusted subset (§5.4)."""

    def test_joint_skips_untrusted_intervals(self):
        rows = read_raw(HERE / "examples" / "demo_raw.csv")
        ivs = build_intervals(rows)
        mark_trusted(ivs, brim=1792.0)
        self.assertTrue(any(not iv.trusted for iv in ivs))
        joint = fit_joint([(ivs, {"r": 880.0, "L": 2950.0})], common_r=True)
        self.assertTrue(joint.success)
        self.assertLess(abs(joint.shell.r - 897.4), 5.0)


class TestLockedDatum(unittest.TestCase):
    """A physically set datum must survive the whole pipeline."""

    def _run(self, overflow):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        cfg = json.loads(DEMO.read_text(encoding="utf-8"))
        cfg["raw"] = str((HERE / "examples" / cfg["raw"]).resolve())
        cfg["h0"] = {"mode": "locked", "value": 0.0}
        cfg["bootstrap_n"] = 5
        if overflow is None:
            cfg["brim"].pop("overflow_pour", None)
        else:
            cfg["brim"]["overflow_pour"] = overflow
        path = out / "cfg.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return run(path, out / "out", make_charts=False)

    def test_locked_without_overflow(self):
        result = self._run(None)
        self.assertAlmostEqual(result["fit"].shell.h0, 0.0, places=9)
        self.assertIsNone(result["gls"]["h0"])
        self.assertIsNone(result["lock"])

    def test_locked_with_overflow(self):
        result = self._run(50.0)
        self.assertAlmostEqual(result["fit"].shell.h0, 0.0, places=9)
        self.assertIsNotNone(result["constrained"])
        self.assertNotIn("h0", result["constrained"].free)
        self.assertAlmostEqual(result["constrained"].shell.h0, 0.0, places=9)


if __name__ == "__main__":
    unittest.main()

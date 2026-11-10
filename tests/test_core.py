"""Core tests: geometry, data, fit, diagnostics, unknowns, field, gate."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from openpyxl import Workbook

from calib.blocking import block_intervals
from calib.charts import build_series
from calib.cli import _parse_pour_line
from calib.config import load_config
from calib.data import (
    Correction,
    Interval,
    Row,
    Step,
    apply_corrections,
    books_start,
    build_intervals,
    mark_trusted,
    parse_step,
    read_raw,
)
from calib.diagnostics import (
    apply_model,
    classify,
    closure,
    find_pairs,
    liquid_volume,
    max_liquid,
    noise_split,
    telescoping_blocks,
)
from calib.field import FieldValidator
from calib.fit import (
    empty_start_check,
    fit_constrained,
    fit_difference,
    profile_param,
)
from calib.formula_gate import check_formula, gate_workbook
from calib.geometry import Shell, area, capacity, volume
from calib.unknowns import back_predict, sigma_x


class TestGeometry(unittest.TestCase):
    def test_area_endpoints(self):
        r = 900.0
        self.assertAlmostEqual(float(area(0.0, r)), 0.0, places=6)
        self.assertAlmostEqual(float(area(2 * r, r)), math.pi * r * r, places=3)
        self.assertAlmostEqual(float(area(r, r)), math.pi * r * r / 2, places=3)

    def test_volume_and_capacity(self):
        r, L = 900.0, 3000.0
        self.assertAlmostEqual(volume(0.0, r, L, 0.0), 0.0, places=6)
        self.assertAlmostEqual(volume(2 * r, r, L, 0.0), capacity(r, L), places=3)
        self.assertGreater(volume(1000.0, r, L, 0.0), 0.0)

    def test_slope_matches_numeric_derivative(self):
        shell = Shell(900.0, 3000.0, 0.0)
        h = 700.0
        d = 1e-3
        numeric = (float(shell.volume(h + d)) - float(shell.volume(h - d))) / (2 * d)
        self.assertAlmostEqual(float(shell.slope(h)), numeric, places=4)

    def test_tilt_zero_equals_flat(self):
        flat = Shell(900.0, 3000.0, -5.0)
        tilted = Shell(900.0, 3000.0, -5.0, 0.0)
        self.assertAlmostEqual(float(flat.volume(1200.0)), float(tilted.volume(1200.0)), places=6)

    def test_tilted_slope_matches_numeric(self):
        shell = Shell(900.0, 3000.0, -5.0, 0.01)
        h = 1200.0
        d = 1e-3
        numeric = (float(shell.volume(h + d)) - float(shell.volume(h - d))) / (2 * d)
        self.assertAlmostEqual(float(shell.slope(h)), numeric, places=6)


class TestData(unittest.TestCase):
    def test_parse_step(self):
        self.assertEqual(parse_step("50").value, 50.0)
        self.assertEqual(parse_step("?").kind, "unknown")
        self.assertEqual(parse_step("x2").kind, "unknown")
        self.assertEqual(parse_step("200+?").kind, "partial")
        self.assertEqual(parse_step("200+?").base, 200.0)
        self.assertEqual(parse_step("200+x2").base, 200.0)
        self.assertEqual(parse_step("").kind, "unknown")

    def test_read_semicolon_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            p.write_text("pour(L);height(mm)\n100;50\n200;120\n", encoding="utf-8")
            rows = read_raw(p)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].step.value, 100.0)
            self.assertEqual(rows[1].height, 120.0)

    def test_correction_preserves_raw(self):
        rows = [
            Row(0, Step("known", 50.0, raw="50"), 60.0),
            Row(1, Step("known", 100.0, raw="100"), 130.0),
        ]
        fixed = apply_corrections(
            rows, [Correction(row=2, field="height", value=128.0, rule="6.1", magnitude=-2.0)]
        )
        self.assertEqual(rows[1].height, 130.0)
        self.assertEqual(fixed[1].height, 128.0)
        self.assertTrue(any("128" in f for f in fixed[1].flags))

    def test_trusted_set(self):
        rows = [
            Row(0, Step("known", 50.0, raw="50"), 60.0),
            Row(1, Step("unknown", raw="?"), 120.0),
            Row(2, Step("known", 100.0, raw="100"), 200.0),
            Row(3, Step("known", 100.0, raw="100"), 180.0),
            Row(4, Step("known", 100.0, raw="100"), 2200.0),
        ]
        ivs = build_intervals(rows)
        mark_trusted(ivs, brim=2000.0, object_bands=[{"low": 180, "high": 200}])
        self.assertFalse(ivs[0].trusted)  # unknown pour
        self.assertFalse(ivs[1].trusted)  # object band
        self.assertFalse(ivs[2].trusted)  # non-positive rise
        self.assertFalse(ivs[3].trusted)  # overflow

    def test_pour_without_height_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            p.write_text("pour(L);height(mm)\n100;50\n200;\n", encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                read_raw(p)
            self.assertIn("without a height", str(cm.exception))

    def test_line_numbers_match_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            # An empty record: a blank data row in the user's file.
            p.write_text("pour,height\n100,50\n,\n100,120\n", encoding="utf-8")
            rows = read_raw(p)
            self.assertEqual([r.line for r in rows], [1, 3])


class TestFit(unittest.TestCase):
    def _campaign(self, r=900.0, L=3000.0, h0=-5.0, n=34, sigma=1.0, seed=3, rise=50.0):
        shell = Shell(r, L, h0)
        rng = np.random.default_rng(seed)
        rows = []
        h_prev = 0.0
        for i in range(n):
            h_next = h_prev + rise
            if h_next > shell.brim() - 10.0:
                break
            step = float(shell.volume(h_next) - shell.volume(h_prev))
            rows.append(
                Row(i, Step("known", step, raw=f"{step:.2f}"), h_next + rng.normal(0.0, sigma))
            )
            h_prev = h_next
        return rows

    def test_recovers_truth(self):
        rows = self._campaign()
        ivs = build_intervals(rows)
        mark_trusted(ivs, brim=Shell(900, 3000, -5).brim())
        fit = fit_difference(ivs, {"r": 880.0, "L": 2950.0})
        self.assertLess(abs(fit.shell.r - 900.0), 8.0)
        self.assertLess(abs(fit.shell.L - 3000.0), 40.0)
        self.assertLess(abs(fit.shell.h0 + 5.0), 8.0)

    def test_neck_equality_and_brim_constraint(self):
        rows = self._campaign(seed=9)
        ivs = build_intervals(rows)
        truth = Shell(900.0, 3000.0, -5.0)
        mark_trusted(ivs, brim=truth.brim())
        free = fit_difference(ivs, {"r": 880.0, "L": 2950.0})
        con = fit_constrained(
            ivs, {"r": 880.0, "L": 2950.0}, start=free,
            gap_pour=200.0, brim_reading=truth.brim(), neck=True,
        )
        self.assertAlmostEqual(2.0 * con.shell.r + con.shell.h0, truth.brim(), delta=0.5)
        self.assertLessEqual(con.gap, 200.0 + 1e-6)

    def test_param_sigma_locked_is_none(self):
        rows = self._campaign(seed=4)
        ivs = build_intervals(rows)
        mark_trusted(ivs, brim=Shell(900, 3000, -5).brim())
        fit = fit_difference(ivs, {"r": 880.0, "L": 2950.0}, h0_mode="locked", h0_value=0.0)
        self.assertIsNone(fit.param_sigma("h0"))
        self.assertIsNotNone(fit.param_sigma("r"))
        self.assertNotIn("h0", fit.free)

    def test_constrained_honours_locked_datum(self):
        rows = self._campaign(seed=8)
        ivs = build_intervals(rows)
        truth = Shell(900.0, 3000.0, -5.0)
        mark_trusted(ivs, brim=truth.brim())
        free = fit_difference(ivs, {"r": 880.0, "L": 2950.0}, h0_mode="locked", h0_value=0.0)
        con = fit_constrained(
            ivs, {"r": 880.0, "L": 2950.0}, start=free,
            gap_pour=200.0, brim_reading=truth.brim(), neck=False,
            h0_mode="locked", h0_value=0.0,
        )
        self.assertAlmostEqual(con.shell.h0, 0.0, places=9)
        self.assertNotIn("h0", con.free)

    def test_profile_threshold_uses_delta_sse(self):
        rows = self._campaign(seed=6)
        ivs = build_intervals(rows)
        mark_trusted(ivs, brim=Shell(900, 3000, -5).brim())
        fit = fit_difference(ivs, {"r": 880.0, "L": 2950.0})
        prof = profile_param(ivs, {"r": 880.0, "L": 2950.0}, fit, name="r", span=10, step=2)
        expected = math.sqrt(prof["best"] ** 2 + fit.sigma2 / fit.n)
        self.assertAlmostEqual(prof["threshold"], expected, places=9)

    def test_empty_start_heel_uses_first_pour(self):
        shell = Shell(900.0, 3000.0, 0.0)
        rows = [
            Row(0, Step("known", 40.0, raw="40"), 50.0),
            Row(1, Step("known", 100.0, raw="100"), 140.0),
        ]
        out = empty_start_check(rows, shell, heel_row=True)
        expected = 100.0 - (float(shell.volume(140.0)) - float(shell.volume(50.0)))
        self.assertEqual(out["kind"], "first pour from heel")
        self.assertAlmostEqual(out["resid"], expected, places=9)

    def test_profile_contains_truth(self):
        rows = self._campaign(seed=5)
        ivs = build_intervals(rows)
        mark_trusted(ivs, brim=Shell(900, 3000, -5).brim())
        fit = fit_difference(ivs, {"r": 880.0, "L": 2950.0})
        prof = profile_param(ivs, {"r": 880.0, "L": 2950.0}, fit, name="r", span=12, step=2)
        self.assertLessEqual(prof["lo"], 900.0)
        self.assertGreaterEqual(prof["hi"], 900.0)


class TestDiagnostics(unittest.TestCase):
    def test_action_bar(self):
        self.assertEqual(classify(4.0, 4.0), "candidate")
        self.assertEqual(classify(4.0, 1.0), "watch")
        self.assertEqual(classify(1.0, 3.0), "watch")
        self.assertEqual(classify(0.5, 0.5), "ok")

    def test_pair_rule(self):
        shell = Shell(900.0, 3000.0, 0.0)
        m = float(shell.slope(900.0))
        a = Interval(1, 1, 100.0, True, 0.0, 800.0, 900.0, trusted=True)
        b = Interval(2, 2, 100.0, True, 0.0, 900.0, 1000.0, trusted=True)
        a.resid, b.resid = -10.0, 10.0
        a.mm_equiv, b.mm_equiv = -10.0 / m, 10.0 / m
        a.z = b.z = 4.0
        a.flag = b.flag = "candidate"
        pairs = find_pairs([a, b], shell)
        self.assertEqual(len(pairs), 1)
        p = pairs[0]
        self.assertTrue(p.actionable)
        self.assertAlmostEqual(p.delta_mm, 20.0 / (2.0 * m), places=6)
        self.assertAlmostEqual(p.corrected_dip, 900.0 - 20.0 / (2.0 * m), places=6)

    def test_pair_rule_rejects_large_net(self):
        shell = Shell(900.0, 3000.0, 0.0)
        a = Interval(1, 1, 100.0, True, 0.0, 800.0, 900.0, trusted=True)
        b = Interval(2, 2, 100.0, True, 0.0, 900.0, 1000.0, trusted=True)
        a.resid, b.resid = -10.0, 16.0
        a.flag = b.flag = "candidate"
        a.z = b.z = 4.0
        pairs = find_pairs([a, b], shell)
        self.assertFalse(pairs[0].actionable)

    def test_object_bookkeeping(self):
        shell = Shell(900.0, 3000.0, 0.0)
        bands = [{"low": 900, "high": 1000, "displacement": 40.0}]
        self.assertAlmostEqual(
            liquid_volume(shell, 1200.0, bands),
            float(shell.volume(1200.0)) - 40.0,
            places=6,
        )
        self.assertAlmostEqual(max_liquid(shell, bands), shell.capacity() - 40.0, places=6)

    def test_noise_split(self):
        rng = np.random.default_rng(1)
        n = 600
        m = 10.0
        sigma_h = 1.0
        sigma_pour = 5.0
        dips = rng.normal(0.0, sigma_h, n + 1)
        ivs = []
        for i in range(n):
            resid = -m * (dips[i + 1] - dips[i]) + rng.normal(0.0, sigma_pour)
            iv = Interval(i + 1, i + 1, 100.0, True, 0.0, i, i + 1, trusted=True)
            iv.resid = resid
            iv.m = m
            ivs.append(iv)
        out = noise_split(ivs)
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(out["sigma_h"], 1.0, delta=0.25)
        self.assertAlmostEqual(out["sigma_pour"], 5.0, delta=1.2)

    def test_telescoping_cancels_interior_dips(self):
        shell = Shell(900.0, 3000.0, 0.0)
        ivs = []
        h = 300.0
        for i in range(9):
            step = float(shell.volume(h + 40.0) - shell.volume(h))
            iv = Interval(i + 1, i + 1, step, True, 0.0, h, h + 40.0, trusted=True)
            iv.resid = 0.0
            ivs.append(iv)
            h += 40.0
        blocks = telescoping_blocks(ivs, shell, sigma_h=1.0, rel=0.0, abs_=0.0, n_blocks=3)
        self.assertEqual(len(blocks), 3)
        for b in blocks:
            self.assertAlmostEqual(b["sum"], 0.0, places=6)


class TestUnknowns(unittest.TestCase):
    def test_back_predict_with_base_and_band(self):
        shell = Shell(900.0, 3000.0, 0.0)
        bands = [{"low": 1000, "high": 1100, "displacement": 30.0}]
        x = back_predict(shell, 950.0, 1150.0, base=100.0, bands=bands)
        expected = float(shell.volume(1150.0)) - float(shell.volume(950.0)) - 30.0 - 100.0
        self.assertAlmostEqual(x, expected, places=6)

    def test_sigma_formula(self):
        s = sigma_x(10.0, 1.5, 0.005, 200.0, 3.0)
        expected = math.sqrt((math.sqrt(2) * 10.0 * 1.5) ** 2 + (0.005 * 200.0 + 3.0) ** 2)
        self.assertAlmostEqual(s, expected, places=9)


class TestConfig(unittest.TestCase):
    def test_exclude_rows_are_one_based(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "r.csv"
            raw.write_text("step_volume,measured_height\n50,10\n50,60\n", encoding="utf-8")
            cfgp = Path(tmp) / "c.json"
            cfgp.write_text(json.dumps({
                "tank": "t", "raw": "r.csv", "nominal": {"r": 900, "L": 3000},
                "exclude": [{"row": 2}],
            }), encoding="utf-8")
            cfg = load_config(cfgp)
            self.assertEqual(cfg.excluded_rows, {2})
            self.assertEqual(cfg.excluded_interval_rows, {1})

    def test_exclude_row_zero_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "r.csv"
            raw.write_text("step_volume,measured_height\n50,10\n50,60\n", encoding="utf-8")
            cfgp = Path(tmp) / "c.json"
            cfgp.write_text(json.dumps({
                "tank": "t", "raw": "r.csv", "nominal": {"r": 900, "L": 3000},
                "exclude": [{"row": 0}],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(cfgp)


class TestNoiseSplitGaps(unittest.TestCase):
    def test_gap_pair_is_not_a_lag_one_pair(self):
        ivs = []
        for i in range(1, 7):
            iv = Interval(i, i, 100.0, True, 0.0, i * 10, i * 10 + 10, trusted=True)
            iv.resid = 10.0 if i % 2 else -10.0
            iv.m = 10.0
            ivs.append(iv)
        # A gap: rows jump from 6 to 8, so these two do not share a dip.
        for i, r in ((8, 100.0), (9, 100.0)):
            iv = Interval(i, i, 100.0, True, 0.0, i * 10, i * 10 + 10, trusted=True)
            iv.resid = r
            iv.m = 10.0
            ivs.append(iv)

        out = noise_split(ivs)
        self.assertTrue(out["ok"])
        r = np.array([iv.resid for iv in ivs])
        var = float(np.var(r, ddof=1))
        contiguous = out["n"]  # sanity: all intervals counted in the variance
        self.assertEqual(contiguous, len(ivs))
        expected_cov = float(np.mean([
            ivs[i].resid * ivs[i + 1].resid
            for i in range(len(ivs) - 1)
            if ivs[i].row + 1 == ivs[i + 1].row
        ]))
        self.assertAlmostEqual(out["rho1"], expected_cov / var, places=9)
        # Including the false pair would give a different, biased correlation.
        all_cov = float(np.mean(r[:-1] * r[1:]))
        self.assertNotAlmostEqual(out["rho1"], all_cov / var, places=3)


class TestBlocking(unittest.TestCase):
    def test_merges_and_keeps_unknown_solo(self):
        ivs = []
        h = 0.0
        for i in range(6):
            iv = Interval(i + 1, i + 1, 50.0, True, 0.0, h, h + 10.0, trusted=True)
            ivs.append(iv)
            h += 10.0
        ivs[3].known = False
        ivs[3].s = None
        ivs[3].trusted = False
        ivs[3].reason = "unknown pour"
        blocks = block_intervals(ivs, sigma_h=1.5, target_rise_mm=30.0)
        trusted = [b for b in blocks if b.trusted]
        # Every block but the final one reaches the target rise.
        self.assertTrue(all(b.h_cur - b.h_prev >= 30.0 for b in trusted[:-1]))
        self.assertTrue(any(not b.trusted for b in blocks))


class TestField(unittest.TestCase):
    def setUp(self):
        self.shell = Shell(900.0, 3000.0, 0.0)
        self.v = FieldValidator(self.shell, sigma_h=1.0, rel=0.0, abs_=0.1)

    def test_ok(self):
        h0 = 500.0
        h1 = 600.0
        step = float(self.shell.volume(h1) - self.shell.volume(h0))
        verdict = self.v.check(step, h0, h1)
        self.assertEqual(verdict.flag, "OK")

    def test_alarm(self):
        h0 = 500.0
        h1 = 600.0
        step = float(self.shell.volume(h1) - self.shell.volume(h0)) - 80.0
        verdict = self.v.check(step, h0, h1)
        self.assertEqual(verdict.flag, "ALARM")
        self.assertIn("OBJECT?", verdict.advice)

    def test_overflow(self):
        verdict = self.v.check(10.0, 1700.0, self.shell.brim() + 20.0)
        self.assertEqual(verdict.flag, "OVERFLOW")

    def test_unknown(self):
        verdict = self.v.check(None, 500.0, 600.0)
        self.assertEqual(verdict.flag, "UNKNOWN")
        self.assertIsNotNone(verdict.unknown)


class TestBooksIdentity(unittest.TestCase):
    """The books must count the first pour everywhere (§9.3)."""

    def _perfect(self, unknown_first=False):
        """A noise-free campaign: every pour matches the shell exactly."""
        shell = Shell(900.0, 3000.0, 0.0)
        hs = [100.0, 200.0, 300.0, 400.0]
        steps = [Step("known", float(shell.volume(hs[0])), raw="s0")]
        for i in range(1, len(hs)):
            p = float(shell.volume(hs[i]) - shell.volume(hs[i - 1]))
            steps.append(Step("known", p, raw=f"s{i}"))
        if unknown_first:
            steps[0] = Step("unknown", raw="?")
        return shell, [Row(i, s, h) for i, (s, h) in enumerate(zip(steps, hs))]

    def test_closure_counts_first_pour(self):
        shell, rows = self._perfect()
        ivs = build_intervals(rows)
        mark_trusted(ivs, brim=shell.brim())
        out = closure(
            ivs, shell, [], books_start=books_start(rows, shell),
            sigma_h=1.5, rel=0.0, abs_=0.0,
        )
        # Dropping the first pour used to bias this by exactly -s_0.
        self.assertAlmostEqual(out["diff"], 0.0, places=6)

    def test_closure_back_predicts_unknown_start(self):
        shell, rows = self._perfect(unknown_first=True)
        ivs = build_intervals(rows)
        mark_trusted(ivs, brim=shell.brim())
        out = closure(
            ivs, shell, [], books_start=books_start(rows, shell),
            start_sigma=1.0, sigma_h=1.5, rel=0.0, abs_=0.0,
        )
        self.assertAlmostEqual(out["diff"], 0.0, places=6)

    def test_drift_series_equals_interval_drift(self):
        shell, rows = self._perfect()
        rows[2].step = Step("unknown", raw="?")  # a gap in the books
        ivs = build_intervals(rows)
        mark_trusted(ivs, brim=shell.brim())
        apply_model(
            ivs, shell, sigma_h=1.5, rel=0.0, abs_=0.0,
            books_start=books_start(rows, shell),
        )
        series = build_series(
            rows, shell, sigma_h=1.5, rel=0.0, abs_=0.0, heel_row=False
        )
        by_row = {iv.row: iv for iv in ivs}
        self.assertGreater(len(series), 1)
        for k in range(len(series)):
            iv = by_row[int(series.row[k])]
            self.assertAlmostEqual(iv.drift, float(series.drift[k]), places=6)


class TestPourLine(unittest.TestCase):
    """One malformed entry must not end a field session."""

    def test_parse(self):
        self.assertEqual(_parse_pour_line("200,500"), (200.0, 500.0))
        self.assertEqual(_parse_pour_line("200;500"), (200.0, 500.0))
        self.assertEqual(_parse_pour_line("?,500"), (None, 500.0))
        self.assertEqual(_parse_pour_line(",500"), (None, 500.0))
        self.assertIsNone(_parse_pour_line("600"))
        self.assertIsNone(_parse_pour_line("200,"))
        self.assertIsNone(_parse_pour_line("abc,500"))


class TestFormulaGate(unittest.TestCase):
    def test_valid(self):
        for f in [
            "=SUM(A1:A3)",
            '=IF(A1>0,"yes","no")',
            "=A1*B1+C1^2",
            "=Sheet1!$A$1:$B$2",
            "=MAX(0,MIN(1,(A1-B1)/B1))",
        ]:
            self.assertEqual(check_formula(f), [], f)

    def test_unbalanced(self):
        self.assertTrue(check_formula("=SUM(A1:A3"))

    def test_double_sheet_range(self):
        problems = check_formula("=Sheet1!A1:Sheet2!B2")
        self.assertTrue(problems)

    def test_trailing_operator(self):
        self.assertTrue(check_formula("=A1+"))

    def test_gate_workbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.xlsx"
            wb = Workbook()
            ws = wb.active
            ws["A1"] = 1
            ws["A2"] = "=SUM(A1:A1)"
            wb.save(path)
            out = gate_workbook(path)
            self.assertTrue(out["ok"])
            self.assertEqual(out["formulas"], 1)


if __name__ == "__main__":
    unittest.main()

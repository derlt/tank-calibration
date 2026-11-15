"""Drain campaigns (reverse strapping, §3.11): the Python pipeline.

A drain starts full and pumps the liquid out.  The step is positive litres,
the level falls, and ``resid = s - (F(H_prev) - F(H_cur))``.  The central
check is the mirror: a drain must give the same fit, residuals and pair
corrections as the same steps poured in the reverse order.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from openpyxl import load_workbook
from scipy.optimize import brentq

from calib.config import load_config
from calib.data import (
    DRAIN,
    FILL,
    Row,
    Step,
    build_intervals,
    infer_direction,
    mark_trusted,
    parse_step,
)
from calib.diagnostics import (
    apply_model,
    closure,
    find_pairs,
    residual_meaning,
    telescoping_blocks,
)
from calib.field import FieldValidator
from calib.fit import fit_constrained, fit_difference
from calib.geometry import Shell
from calib.pipeline import run
from calib.scaffold import infer_config, scan_rows
from calib.unknowns import estimate_unknowns

HERE = Path(__file__).resolve().parent.parent
TRUTH = Shell(900.0, 3000.0, -5.0)
NOMINAL = {"r": 880.0, "L": 2950.0}
STEPS = [100, 100, 150, 150, 200, 200, 300, 300, 400, 400, 500, 500,
         600, 700, 600, 500, 400, 300, 200, 150, 100]


def _load_demo():
    spec = importlib.util.spec_from_file_location(
        "make_demo_drain", HERE / "examples" / "make_demo_drain.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def level(shell: Shell, liquid: float) -> float:
    return brentq(lambda h: float(shell.volume(h)) - liquid, shell.h0, shell.brim() - 1e-9)


def rows_of(cells: list[tuple[str, float]]) -> list[Row]:
    return [Row(index=i, step=parse_step(s), height=float(h)) for i, (s, h) in enumerate(cells)]


def fill_campaign(seed: int = 3, misread: tuple[int, float] | None = None):
    """A noisy fill from a 300 L heel; returns (cells, true levels)."""
    rng = np.random.default_rng(seed)
    v = 300.0
    true = [level(TRUTH, v)]
    for s in STEPS:
        v += s + rng.normal(0.0, 2.0)
        true.append(level(TRUTH, v))
    rec = [h + rng.normal(0.0, 0.8) for h in true]
    if misread:
        rec[misread[0]] += misread[1]
    cells = [("?", rec[0])] + [(str(s), rec[i + 1]) for i, s in enumerate(STEPS)]
    return cells, true


def mirror(cells: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """The same steps in reverse: start at the top, pump each step out."""
    heights = [h for _, h in cells]
    steps = [s for s, _ in cells[1:]]
    out = [("?", heights[-1])]
    for k in range(len(steps) - 1, -1, -1):
        out.append((steps[k], heights[k]))
    return out


def fitted(rows, direction):
    ivs = build_intervals(rows, direction)
    mark_trusted(ivs, brim=TRUTH.brim())
    fit = fit_difference(ivs, NOMINAL, multistart=True)
    apply_model(ivs, fit.shell, sigma_h=0.8, rel=0.003, abs_=1.0)
    return ivs, fit


class TestDirection(unittest.TestCase):
    def test_interval_travel_and_prediction(self):
        rows = rows_of([("?", 900.0), ("200", 850.0)])
        iv = build_intervals(rows, "drain")[0]
        self.assertEqual(iv.direction, DRAIN)
        self.assertAlmostEqual(iv.travel, 50.0)
        self.assertEqual((iv.h_lo, iv.h_hi), (850.0, 900.0))
        expected = float(TRUTH.volume(900.0) - TRUTH.volume(850.0))
        self.assertAlmostEqual(iv.predicted(TRUTH), expected)
        self.assertGreater(iv.predicted(TRUTH), 0.0)

    def test_infer_direction(self):
        cells, _ = fill_campaign()
        self.assertEqual(infer_direction(rows_of(cells)), FILL)
        self.assertEqual(infer_direction(rows_of(mirror(cells))), DRAIN)

    def test_rising_level_in_a_drain_is_not_trusted(self):
        rows = rows_of([("?", 900.0), ("200", 910.0), ("200", 860.0)])
        ivs = build_intervals(rows, "drain")
        mark_trusted(ivs, brim=TRUTH.brim())
        self.assertFalse(ivs[0].trusted)
        self.assertEqual(ivs[0].reason, "non-positive fall")
        self.assertTrue(ivs[1].trusted)

    def test_bad_direction(self):
        with self.assertRaises(ValueError):
            build_intervals(rows_of([("?", 1.0), ("1", 2.0)]), "sideways")


class TestMirror(unittest.TestCase):
    """A drain and the same steps poured in reverse are one data set."""

    @classmethod
    def setUpClass(cls):
        cls.cells, _ = fill_campaign()
        cls.f_ivs, cls.f_fit = fitted(rows_of(cls.cells), "fill")
        cls.d_ivs, cls.d_fit = fitted(rows_of(mirror(cls.cells)), "drain")

    def test_same_shell(self):
        for name in ("r", "L", "h0"):
            # Same data in another order: equal to the optimizer tolerance.
            self.assertAlmostEqual(self.f_fit.params[name], self.d_fit.params[name], delta=0.01)
        self.assertAlmostEqual(self.f_fit.sse, self.d_fit.sse, delta=1e-4 * self.f_fit.sse)

    def test_same_residuals_reversed(self):
        f = [(iv.resid, iv.m, iv.z, iv.flag) for iv in self.f_ivs]
        d = [(iv.resid, iv.m, iv.z, iv.flag) for iv in reversed(self.d_ivs)]
        for a, b in zip(f, d, strict=True):
            self.assertAlmostEqual(a[0], b[0], delta=1e-3)
            self.assertAlmostEqual(a[1], b[1], delta=1e-6)
            self.assertAlmostEqual(a[2], b[2], delta=1e-3)
            self.assertEqual(a[3], b[3])

    def test_truth_recovered(self):
        self.assertLess(abs(self.d_fit.shell.r - 900.0), 15.0)
        self.assertLess(abs(self.d_fit.shell.L - 3000.0), 60.0)

    def test_drift_is_the_residual_sum(self):
        total = sum(iv.resid for iv in self.d_ivs if iv.known)
        self.assertAlmostEqual(self.d_ivs[-1].drift, total, places=6)

    def test_telescoping_blocks_agree(self):
        f = telescoping_blocks(self.f_ivs, self.f_fit.shell, sigma_h=0.8, rel=0.003, abs_=1.0)
        d = telescoping_blocks(self.d_ivs, self.d_fit.shell, sigma_h=0.8, rel=0.003, abs_=1.0)
        self.assertAlmostEqual(sum(b["sum"] for b in f), sum(b["sum"] for b in d), delta=1e-3)


class TestSigns(unittest.TestCase):
    """§2 in a drain: object and record signs hold; a leak flips."""

    def _drain(self, extra_out: float = 0.0, recorded_extra: float = 0.0, solid: float = 0.0):
        v = float(TRUTH.capacity()) - 200.0
        cells = [("?", level(TRUTH, v))]
        for k, s in enumerate([400.0] * 8):
            out = s + (extra_out if k == 4 else 0.0)
            v -= out
            h = level(TRUTH, v)
            cells.append((f"{s + (recorded_extra if k == 4 else 0.0):g}", h))
        rows = rows_of(cells)
        if solid:
            # A solid fills the band of interval 5: liquid volume = F - solid
            # above its top, so the fall across the band comes too large.
            top, bottom = rows[4].height, rows[5].height
            for row in rows[:5]:
                row.height = level(TRUTH, float(TRUTH.volume(row.height)) + solid)
            self.assertGreater(top, bottom)
        ivs = build_intervals(rows, "drain")
        mark_trusted(ivs, brim=TRUTH.brim())
        apply_model(ivs, TRUTH, sigma_h=0.5, rel=0.003, abs_=1.0)
        return ivs[4]

    def test_leak_gives_negative_resid(self):
        iv = self._drain(extra_out=30.0)
        self.assertAlmostEqual(iv.resid, -30.0, delta=0.5)
        self.assertIn("leak", residual_meaning(iv.resid, DRAIN))

    def test_over_recorded_drain_gives_positive_resid(self):
        iv = self._drain(recorded_extra=30.0)
        self.assertAlmostEqual(iv.resid, 30.0, delta=0.5)
        self.assertIn("over-recorded", residual_meaning(iv.resid, DRAIN))
        self.assertIn("came back", residual_meaning(iv.resid, DRAIN))

    def test_exposed_solid_gives_negative_resid(self):
        iv = self._drain(solid=25.0)
        self.assertAlmostEqual(iv.resid, -25.0, delta=0.5)
        self.assertIn("solid exposed", residual_meaning(iv.resid, DRAIN))

    def test_fill_meaning_unchanged(self):
        self.assertIn("leak", residual_meaning(+5.0))
        self.assertIn("solid displaced", residual_meaning(-5.0))


class TestPairRuleDrain(unittest.TestCase):
    def test_delta_sign_and_correction(self):
        # Noise-free drain, one shared dip read 4 mm high.
        v = float(TRUTH.capacity()) - 150.0
        cells = [("?", level(TRUTH, v))]
        for s in [500.0] * 10:
            v -= s
            cells.append((f"{s:g}", level(TRUTH, v)))
        true_h = cells[5][1]
        cells[5] = (cells[5][0], true_h + 4.0)
        ivs = build_intervals(rows_of(cells), "drain")
        mark_trusted(ivs, brim=TRUTH.brim())
        apply_model(ivs, TRUTH, sigma_h=0.3, rel=0.0, abs_=0.5)
        pairs = find_pairs(ivs, TRUTH)
        self.assertEqual(len(pairs), 1)
        p = pairs[0]
        # In a drain the earlier interval falls too little: r_first = +m*delta.
        self.assertGreater(p.resid_first, 0.0)
        self.assertLess(p.resid_second, 0.0)
        self.assertAlmostEqual(p.delta_mm, 4.0, delta=0.1)
        self.assertAlmostEqual(p.corrected_dip, true_h, delta=0.1)
        self.assertTrue(p.balanced)


class TestNeck(unittest.TestCase):
    def _cells(self, start_in_neck: bool):
        cap = float(TRUTH.capacity())
        if start_in_neck:
            cells = [("?", TRUTH.brim() + 40.0)]
            v = cap - 120.0  # after the 150 L neck drain (30 L stood in the neck)
            cells.append(("150", level(TRUTH, v)))
        else:
            cells = [("?", TRUTH.brim())]
            v = cap
        for s in STEPS[:-4]:
            v -= s
            cells.append((str(s), level(TRUTH, v)))
        return cells

    def test_neck_interval_is_out_of_the_fit(self):
        ivs = build_intervals(rows_of(self._cells(True)), "drain")
        mark_trusted(ivs, brim=TRUTH.brim())
        self.assertFalse(ivs[0].trusted)
        self.assertEqual(ivs[0].reason, "neck interval")
        self.assertTrue(all(iv.trusted for iv in ivs[1:]))

    def test_neck_drain_bounds_the_gap(self):
        ivs = build_intervals(rows_of(self._cells(True)), "drain")
        mark_trusted(ivs, brim=TRUTH.brim())
        free = fit_difference(ivs, NOMINAL)
        con = fit_constrained(ivs, NOMINAL, start=free, gap_pour=150.0)
        self.assertLessEqual(con.gap, 150.0 + 1e-3)
        self.assertAlmostEqual(con.gap, 120.0, delta=10.0)

    def test_neck_entrance_equality_alone(self):
        cells = self._cells(False)
        ivs = build_intervals(rows_of(cells), "drain")
        mark_trusted(ivs, brim=TRUTH.brim() + 1.0)
        free = fit_difference(ivs, NOMINAL)
        con = fit_constrained(
            ivs, NOMINAL, start=free, gap_pour=None,
            brim_reading=cells[0][1], neck=True,
        )
        self.assertFalse(con.binding)
        self.assertAlmostEqual(con.neck_resid, 0.0, delta=1e-3)
        self.assertAlmostEqual(con.shell.brim(), TRUTH.brim(), delta=0.5)


class TestUnknownAndClosure(unittest.TestCase):
    def test_back_prediction_positive(self):
        cells, _ = fill_campaign(seed=5)
        d = mirror(cells)
        d[6] = ("?", d[6][1])
        ivs = build_intervals(rows_of(d), "drain")
        mark_trusted(ivs, brim=TRUTH.brim())
        est = estimate_unknowns(ivs, TRUTH, sigma_h=0.8, rel=0.003, abs_=1.0)
        self.assertEqual(len(est), 1)
        self.assertAlmostEqual(est[0]["x"], float(mirror(cells)[6][0]), delta=12.0)
        self.assertEqual(est[0]["direction"], DRAIN)

    def test_closure_subtracts_drains(self):
        cells, _ = fill_campaign(seed=5)
        rows = rows_of(mirror(cells))
        ivs, fit = fitted(rows, "drain")
        books = float(fit.shell.volume(rows[0].height))
        c = closure(ivs, fit.shell, [], books_start=books, sigma_h=0.8, rel=0.003, abs_=1.0)
        self.assertTrue(c["ok"], c)
        self.assertLess(abs(c["diff"]), 25.0)
        self.assertLess(c["lhs"], books)


class TestConfigAndInit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _raw(self, cells, notes=None):
        path = self.dir / "t_raw.csv"
        lines = ["step_volume,measured_height,note"]
        for i, (s, h) in enumerate(cells):
            note = (notes or {}).get(i, "")
            lines.append(f"{s},{h:.1f},{note}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_drain_rejects_heel_row(self):
        raw = self._raw(mirror(fill_campaign()[0]))
        cfg = {"tank": "t", "raw": raw.name, "direction": "drain",
               "nominal": NOMINAL, "heel_row": True}
        path = self.dir / "t.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_config(path)

    def test_init_infers_drain_and_neck_drain(self):
        mod = _load_demo()
        cfg_path = mod.write(self.dir)
        raw = self.dir / json.loads(cfg_path.read_text())["raw"]
        data, warnings = infer_config(raw, r=880.0, L=2950.0)
        self.assertEqual(data["direction"], "drain")
        self.assertEqual(data["brim"]["neck_drain"], 150.0)
        self.assertFalse(data["heel_row"])
        self.assertTrue(any("direction: drain" in w for w in warnings))
        self.assertFalse(any("does not" in w for w in warnings), warnings)

    def test_init_reads_the_neck_entrance(self):
        cells = mirror(fill_campaign()[0])
        raw = self._raw(cells, {0: "drain campaign; at neck entrance"})
        data, _ = infer_config(raw, r=880.0, L=2950.0)
        self.assertEqual(data["brim"]["reading"], round(cells[0][1], 1))
        self.assertTrue(data["brim"]["neck_equality"])

    def test_scan_rows_drain(self):
        rows = rows_of([("?", 900.0), ("200", 880.0), ("200", 885.0)])
        warnings = scan_rows(rows, 900.0, 3000.0, "drain")
        self.assertEqual(len(warnings), 1)
        self.assertIn("does not fall below", warnings[0])


class TestFieldDrain(unittest.TestCase):
    def test_field_validator_drain(self):
        mod = _load_demo()
        rows, _ = mod.campaign()
        cells = [(s, float(h)) for s, h, _ in rows]
        shell = Shell(900.0, 3000.0, -5.0)
        bands = [{"low": 990.0, "high": 1000.0, "litres": 30.0}]
        v = FieldValidator(shell, sigma_h=1.0, rel=0.003, abs_=1.0, bands=bands, direction="drain")
        verdicts = v.run(rows_of(cells))
        self.assertEqual(verdicts[0].flag, "NECK")
        flags = [x.flag for x in verdicts]
        # The misread row is the only alarm-class flag on a clean campaign.
        self.assertNotIn("OVERFLOW", flags)
        self.assertNotIn("BRIM-WARN", flags)
        self.assertIn("BOTTOM-WARN", flags)
        self.assertIn("drain", v.advisor(500.0)["advice"])
        self.assertNotIn("halve", v.advisor(TRUTH.brim() - 5.0)["advice"])
        closure_now = v.closure(v.levels[-1])
        self.assertLess(abs(closure_now["diff"]), 40.0, closure_now)


class TestPipelineDrain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        mod = _load_demo()
        cfg_path = mod.write(cls.dir)
        cfg = json.loads(cfg_path.read_text())
        cfg["bootstrap_n"] = 20
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        cls.truth = json.loads((cls.dir / "demo_drain_truth.json").read_text())
        cls.result = run(cfg_path, cls.dir / "out", make_charts=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_truth_recovered(self):
        s = self.result["fit"].shell
        self.assertLess(abs(s.r - 900.0), 15.0)
        self.assertLess(abs(s.L - 3000.0), 60.0)
        self.assertLess(abs(s.h0 + 5.0), 12.0)

    def test_acceptance(self):
        for check in self.result["acceptance"]:
            self.assertTrue(check["pass"], f"{check['check']}: {check['result']}")

    def test_direction_reported(self):
        self.assertEqual(self.result["direction"], "drain")
        self.assertIn("drain campaign", self.result["shell_record"])
        report = (self.dir / "out" / "demo_drain_report.md").read_text()
        self.assertIn("Drain campaign", report)
        self.assertIn("Unknown drains", report)
        presets = json.loads((self.dir / "out" / "demo_drain_presets.json").read_text())
        self.assertEqual(presets["direction"], "drain")

    def test_neck_interval_in_register(self):
        kinds = {e["kind"] for e in self.result["register"]}
        self.assertIn("neck interval", kinds)
        self.assertIn("unknown drain", kinds)
        self.assertLessEqual(self.result["constraint"]["gap"], 150.0 + 1e-3)

    def test_unknowns(self):
        est = {u["row"]: u for u in self.result["unknowns"]}
        u = est[self.truth["unknown_row"]]
        self.assertLess(u["lo"], self.truth["unknown_l"])
        self.assertGreater(u["hi"], self.truth["unknown_l"])
        self.assertEqual(len(est), 2)  # the unknown drain and the part can

    def test_end_heel(self):
        heel = self.result["end_heel"]
        self.assertIsNotNone(heel)
        self.assertLess(abs(heel["liquid"] - self.truth["end_liquid_l"]), 15.0)

    def test_closure_and_qa(self):
        self.assertTrue(self.result["closure"]["ok"])
        self.assertLess(self.result["qa"]["max"], 30.0)

    def test_verified_range_reaches_the_last_trusted_dip(self):
        # The last dip follows a part can (N+?): not fit data, so the
        # verified range ends one level above it.
        rows = self.result["rows"]
        self.assertAlmostEqual(self.result["lowest_verified"], rows[-2].height)
        self.assertGreater(self.result["highest_verified"], 1700.0)

    def test_workbook_and_gate(self):
        gate = self.result["gate"]
        self.assertEqual(gate["errors"], [])
        wb = load_workbook(self.dir / "out" / "demo_drain_workbook.xlsx")
        audit = wb["Audit"]
        self.assertIn("drain", str(audit["B11"].value))
        self.assertIn("(F15-H15)", str(audit["I15"].value))

    def test_charts_written(self):
        for path in self.result["charts"].values():
            self.assertTrue(Path(path).exists())

    def test_raw_rows_kept(self):
        raw = (self.dir / "out" / "demo_drain_raw.csv").read_text()
        self.assertIn("neck interval", raw)


NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed")
class TestSiteExportToPipeline(unittest.TestCase):
    """The site's raw CSV of a drain is what `calib init` and `calib fit` read."""

    def test_site_csv_round_trip(self):
        mod = _load_demo()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cfg_path = mod.write(tmp)
            raw = tmp / json.loads(cfg_path.read_text())["raw"]
            core = (HERE / "site" / "site_core.js").as_posix()
            script = (
                f"const core = require({json.dumps(core)}); const fs = require('fs');\n"
                f"const rows = core.readRawText(fs.readFileSync({json.dumps(raw.as_posix())}, 'utf8'));\n"
                "const r = core.replayRows(rows, {D: 1760, Lest: 2950, direction: 'drain',"
                " pourUnit: 50, sigmaRead: 1.0}, {neckRows: new Set([1])});\n"
                "process.stdout.write(r.session.toRawCsv());\n"
            )
            out = subprocess.run(  # noqa: S603
                [NODE, "-e", script], capture_output=True, text=True, timeout=120, check=True
            )
            site_raw = tmp / "site_raw.csv"
            site_raw.write_text(out.stdout, encoding="utf-8")
            data, _ = infer_config(site_raw, r=880.0, L=2950.0, sigma_h=1.0)
            self.assertEqual(data["direction"], "drain")
            self.assertEqual(data["brim"]["neck_drain"], 150.0)
            path = tmp / "site.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            cfg = json.loads(path.read_text())
            cfg["bootstrap_n"] = 10
            path.write_text(json.dumps(cfg), encoding="utf-8")
            result = run(path, tmp / "out", make_charts=False)
            self.assertLess(abs(result["fit"].shell.r - 900.0), 20.0)
            self.assertTrue(result["closure"]["ok"])
            kinds = {e["kind"] for e in result["register"]}
            self.assertIn("neck interval", kinds)


class TestStepParse(unittest.TestCase):
    def test_partial_can(self):
        step = parse_step("100+?")
        self.assertEqual(step, Step("partial", None, 100.0, "100+?"))


if __name__ == "__main__":
    unittest.main()

"""Excel delivery layer: a values-only workbook, plus an optional audit sheet.

The workbook never carries the fit.  Python owns the numbers; Excel shows
them.  The optional ``Audit`` sheet reproduces the difference fit with live
formulas and an Excel Solver setup, as the fallback of §5.6.  Every formula
in that sheet passes the gate of §11.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from openpyxl import Workbook
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.marker import Marker
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import charts
from .diagnostics import blocked_below

INK = "1F2933"
HEAD = "1F3864"
HEAD_FG = "FFFFFF"
BAND = "EEF2F7"
WARN = "FDE68A"
BAD = "FECACA"
NOTE = "DBEAFE"
GOOD = "BBF7D0"

THIN = Side(style="thin", color="D9DEE5")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _title(ws, text, row=1, span=8):
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(bold=True, size=14, color=INK)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    return row + 2


def _sub(ws, text, row, span=8):
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(italic=True, size=9, color="52606D")
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    return row + 1


def _section(ws, text, row, span=8):
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(bold=True, size=11, color=HEAD)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    return row + 1


def _header(ws, row, headers):
    for c, text in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c, value=text)
        cell.font = Font(bold=True, color=HEAD_FG, size=9)
        cell.fill = PatternFill("solid", fgColor=HEAD)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = BORDER
    ws.row_dimensions[row].height = 28
    return row + 1


def _row(ws, row, values, formats=None, fill=None):
    for c, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=c, value=value)
        cell.font = Font(size=9, color=INK)
        cell.border = BORDER
        if formats and c - 1 < len(formats) and formats[c - 1]:
            cell.number_format = formats[c - 1]
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        if isinstance(value, str) and len(value) > 40:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    return row + 1


def _widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _kv(ws, row, items, span=6):
    for label, value in items:
        ws.cell(row=row, column=1, value=label).font = Font(size=9, color="52606D")
        cell = ws.cell(row=row, column=2, value=value)
        cell.font = Font(size=9, color=INK)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=span)
        row += 1
    return row


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------

def _readme(wb, result):
    ws = wb.create_sheet("README")
    r = _title(ws, f"Tank calibration — {result['config'].tank}", 1, 8)
    r = _sub(
        ws,
        "Values-only workbook. Python owns the fit; this workbook shows the "
        "adopted shell, the corrected record and the deliverables. The Audit "
        "sheet is the §5.6 fallback and is optional.",
        r,
        8,
    )
    r = _section(ws, "WHAT THIS WORKBOOK CONTAINS", r + 1)
    rows = [
        ("Settings", "Campaign constants: sigma_h, pour noise, nominal geometry, brim."),
        ("Input", "Every raw row, its flag and whether the fit trusted it."),
        ("Model", "Predicted pour, residual, mm-equivalent, sigma, z and drift per interval."),
        ("Fit", "Adopted shell, the six acceptance checks, lock cost, tilt test."),
        ("Diagnostics", "Noise split, telescoping blocks, multiple comparisons, drift shape."),
        ("AnomalyLog", "Object bands, dip pairs, single-sided events, watch items, unknowns."),
        ("Strapping", "Level to liquid volume, blocked-volume corrected, with ±sigma."),
        ("Commercial", "Fixed-interval chart, whole litres, extrapolated region labelled."),
        ("Charts", "The seven views of §6.6."),
        ("Audit", "Optional live formulas and the Excel Solver setup (§5.6)."),
        ("Reference", "Short method notes and the rule each sheet enforces."),
    ]
    r = _header(ws, r, ["Sheet", "Purpose"])
    for name, purpose in rows:
        r = _row(ws, r, [name, purpose])
    r += 1
    r = _section(ws, "RULES THAT BIND THIS FILE", r)
    rules = [
        ("1.1", "The raw file is never edited. Corrections are flagged in Input and AnomalyLog."),
        ("1.2", "A data-model gap is a finding, never averaged away."),
        ("1.3", "One authoritative table per tank. Superseded tables are marked, not deleted."),
        ("5.7", "A fit is adopted only when all six acceptance checks pass."),
        ("6.3", "Liquid volume = F(H) minus blocked volumes below H."),
        ("11", "Every generated workbook passes the formula gate."),
    ]
    r = _header(ws, r, ["Rule", "What it means here"])
    for rule, text in rules:
        r = _row(ws, r, [rule, text])
    _widths(ws, [18, 96])
    ws.freeze_panes = "A3"


def _settings(wb, result):
    cfg = result["config"]
    fit = result["fit"]
    ws = wb.create_sheet("Settings")
    r = _title(ws, "Settings", 1, 6)
    r = _sub(ws, "One set of numbers, used everywhere (§9.1).", r, 6)
    items = [
        ("Tank", cfg.tank),
        ("Raw file (immutable)", Path(cfg.raw).name),
        ("sigma_h (mm)", cfg.sigma_h),
        ("Pour noise rel", cfg.pour_rel),
        ("Pour noise abs (L)", cfg.pour_abs),
        ("Pour unit (L)", cfg.pour_unit if cfg.pour_unit is not None else "not recorded"),
        ("Nominal r (mm)", cfg.nominal_r),
        ("Nominal L (mm)", cfg.nominal_L),
        ("h0 mode", cfg.h0_mode),
        ("h0 value (mm)", cfg.h0_value),
        ("Brim reading (mm)", cfg.brim_reading if cfg.brim_reading is not None else fit.shell.brim()),
        ("Vcap (L)", fit.shell.capacity()),
        ("Adopted r (mm)", fit.shell.r),
        ("Adopted L (mm)", fit.shell.L),
        ("Adopted h0 (mm)", fit.shell.h0),
        ("RMSE (L/step)", fit.rmse),
        ("Trusted intervals", fit.n),
        ("Parameters", fit.p),
        ("Loss", fit.loss),
    ]
    r = _header(ws, r, ["Setting", "Value", "Note"])
    notes = {
        "sigma_h (mm)": "careful dipping 1.0; field conditions 1.5",
        "Pour noise rel": "from the can calibration, not a hope",
        "Pour unit (L)": "the grid pours live on (§3.10)",
        "h0 mode": "locked when the datum is physically set",
        "Brim reading (mm)": "neck entrance = shell crown (§5.3a)",
    }
    for label, value in items:
        r = _row(ws, r, [label, value, notes.get(label, "")], formats=[None, "0.000", None])
    _widths(ws, [28, 20, 60])
    ws.freeze_panes = "A3"


def _input(wb, result):
    ws = wb.create_sheet("Input")
    r = _title(ws, "Input — raw rows and their flags", 1, 7)
    r = _sub(
        ws,
        "The raw values are never edited. A corrected row carries its original "
        "value in the note and a flag with the rule and the magnitude (§1.1).",
        r,
        7,
    )
    r = _header(ws, r, ["Row", "Step (L)", "Height (mm)", "Note", "Flag", "Trusted", "Reason"])
    for row, iv in zip(result["rows"], [None] + result["intervals"]):
        step = row.step.value if row.step.kind == "known" else (row.step.raw or "?")
        trusted = "" if iv is None else ("yes" if iv.trusted else "no")
        reason = "" if iv is None else iv.reason
        fill = None
        if iv is not None and not iv.trusted:
            fill = BAND
        r = _row(
            ws,
            r,
            [row.line, step, row.height, row.note, "; ".join(row.flags), trusted, reason],
            formats=[None, "0.0", "0.0", None, None, None, None],
            fill=fill,
        )
    _widths(ws, [7, 12, 13, 46, 46, 9, 26])
    ws.freeze_panes = "A5"


def _series_sheet(wb, name, title, subtitle, series, result, *, raw):
    ws = wb.create_sheet(name)
    r = _title(ws, title, 1, 16)
    r = _sub(ws, subtitle, r, 16)
    r = _header(
        ws, r,
        ["i", "H_prev", "H_cur", "Step", "Predicted", "Residual", "m (L/mm)",
         "mm-equiv", "sigma", "z", "Drift", "Flag", "Books", "Pour/rise",
         "+sigma", "-sigma"],
    )
    ivs = {iv.row: iv for iv in result["intervals"]}
    shell = result["fit"].shell
    for k in range(len(series)):
        row = int(series.row[k])
        iv = ivs.get(row)
        m = float(shell.slope(series.H[k]))
        mm = series.resid[k] / m if m > 0 else ""
        pour_rise = series.s[k] / series.rise[k] if series.rise[k] > 0 else ""
        if raw:
            flag = "excluded" if series.excluded[k] else "raw"
            z_value = "" if series.excluded[k] else series.z[k]
        else:
            flag = iv.flag if iv else ""
            z_value = series.z[k]
        r = _row(
            ws, r,
            [row, series.h_prev[k], series.H[k], series.s[k], series.pred[k],
             series.resid[k], m, mm, series.sigma[k], z_value, series.drift[k],
             flag, series.books[k], pour_rise, series.sigma[k], -series.sigma[k]],
            formats=[None, "0.0", "0.0", "0.0", "0.00", "0.00", "0.0000",
                     "0.00", "0.00", "0.00", "0.00", None, "0.0", "0.0000",
                     "0.00", "0.00"],
        )
    _widths(ws, [5, 9, 9, 9, 11, 10, 9, 10, 8, 8, 10, 14, 10, 10, 9, 9])
    ws.freeze_panes = "A5"
    return ws


def _model(wb, result):
    cfg = result["config"]
    series = charts.build_series(
        result["rows"], result["fit"].shell,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
        heel_row=cfg.heel_row,
    )
    _series_sheet(
        wb, "Model", "Model — corrected interval series",
        "resid = step - (F(H_i) - F(H_i-1)). Negative: rise too cheap. "
        "Positive: rise too small (§2). Drift = books - F.",
        series, result, raw=False,
    )


def _raw_model(wb, result):
    cfg = result["config"]
    series = charts.build_series(
        result["raw_rows"], result["fit"].shell,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
        heel_row=cfg.heel_row,
    )
    _series_sheet(
        wb, "RawModel", "RawModel — raw interval series",
        "The same series before corrections. Excluded rows are flagged.",
        series, result, raw=True,
    )


def _fit_sheet(wb, result):
    fit = result["fit"]
    ws = wb.create_sheet("Fit")
    r = _title(ws, "Fit — adopted shell and acceptance", 1, 6)
    r = _sub(ws, "A fit is adopted only when all six checks of §5.7 hold.", r, 6)

    r = _section(ws, "ADOPTED SHELL", r)
    r = _header(ws, r, ["Parameter", "Value", "± (1σ)", "Unit", "Note"])
    rs = fit.param_sigma("r")
    ls = fit.param_sigma("L")
    hs = fit.param_sigma("h0")
    rows = [
        ("r", fit.shell.r, rs, "mm", "profile is the honest interval (§5.5)"),
        ("L", fit.shell.L, ls, "mm", "effective length"),
        ("h0", fit.shell.h0, hs, "mm", "datum offset"),
        ("Vcap", fit.shell.capacity(), None, "L", "pi r^2 L"),
        ("Brim B", result["brim"], None, "mm", "h0 + 2r"),
        ("RMSE", fit.rmse, None, "L/step", "sqrt(SSE/n)"),
        ("mm-equivalent", result["rmse_mm"], None, "mm", "should be near sqrt(2) sigma_h"),
    ]
    for name, value, sigma, unit, note in rows:
        r = _row(ws, r, [name, value, sigma if sigma is not None else "", unit, note],
                 formats=[None, "0.000", "0.000", None, None])

    r = _section(ws, "CONSTRAINTS", r + 1)
    r = _header(ws, r, ["Constraint", "Status", "Gap (L)", "Pour (L)", "Note"])
    c = result["constraint"]
    r = _row(ws, r, ["Brim G <= P", c["status"], c["gap"], c["pour"], c["note"]],
             formats=[None, None, "0.0", "0.0", None])
    r = _row(ws, r, ["Neck equality 2r + h0 = B", c["neck_status"], "", "", c["neck_note"]])

    if result.get("constrained") is not None:
        r = _section(ws, "FREE VS CONSTRAINED (§5.3a)", r + 1)
        r = _header(ws, r, ["Model", "r (mm)", "L (mm)", "h0 (mm)", "RMSE (L/step)", "Gap (L)"])
        free = result["free_fit"]
        con = result["constrained"]
        r = _row(ws, r, ["free", free.shell.r, free.shell.L, free.shell.h0, free.rmse, ""],
                 formats=[None, "0.00", "0.00", "0.00", "0.000", None])
        r = _row(ws, r, ["constrained", con.shell.r, con.shell.L, con.shell.h0, con.rmse, con.gap],
                 formats=[None, "0.00", "0.00", "0.00", "0.000", "0.0"])

    r = _section(ws, "SIX ACCEPTANCE CHECKS (§5.7)", r + 1)
    r = _sub(
        ws,
        "Overall: " + ("ACCEPTED" if result.get("accepted") else "NOT ACCEPTED — do not use for custody"),
        r,
        5,
    )
    r = _header(ws, r, ["#", "Check", "Result", "Pass", "Detail"])
    for i, item in enumerate(result["acceptance"], start=1):
        fill = GOOD if item["pass"] else BAD
        r = _row(ws, r, [i, item["check"], item["result"], "yes" if item["pass"] else "no", item["detail"]], fill=fill)

    r = _section(ws, "IDENTIFIABILITY", r + 1)
    r = _header(ws, r, ["Item", "Value", "", "", "Note"])
    prof = result["profile"]
    r = _row(ws, r, ["r profile", f"{prof['lo']:.1f} to {prof['hi']:.1f} mm", "", "",
                     "Delta-SSE = s^2; flat over " + f"{prof['flat_lo']:.1f}-{prof['flat_hi']:.1f} mm"])
    prof_l = result["profile_L"]
    r = _row(ws, r, ["L profile", f"{prof_l['lo']:.1f} to {prof_l['hi']:.1f} mm", "", "",
                     "Delta-SSE = s^2"])
    lock = result["lock"]
    if lock is None:
        r = _row(ws, r, ["h0 lock cost", "not applicable", "", "",
                         "h0 is locked by configuration"])
    else:
        r = _row(ws, r, ["h0 lock cost", f"{lock['delta_rmse']:+.3f} L/step", "", "",
                         f"F-test p={lock['p']:.3g}; {'lock rejected' if lock['reject_lock'] else 'lock acceptable'}"])
    tilt = result["tilt"]
    r = _row(ws, r, ["tilt test", f"eps={tilt['eps']:+.4f} mm/mm", "", "",
                     f"p={tilt['p']:.3g}; {'keep' if tilt['keep'] else 'not kept'}"])
    r = _row(ws, r, ["tape scale", "unidentifiable", "", "",
                     "volume table invariant; physical dimensions carry the error (§5.5)"])

    r = _section(ws, "BOOTSTRAP AND GLS (§5.5)", r + 1)
    b = result["bootstrap"]
    g = result["gls"]
    r = _header(ws, r, ["Parameter", "Bootstrap mean", "Bootstrap sd", "2.5%", "97.5%", "GLS sd"])
    for name in ("r", "L", "h0"):
        r = _row(ws, r, [name, b[name]["mean"], b[name]["sd"], b[name]["lo"], b[name]["hi"], g[name]],
                 formats=[None, "0.000", "0.000", "0.000", "0.000", "0.000"])
    _widths(ws, [26, 26, 16, 14, 60, 14])
    ws.freeze_panes = "A3"


def _diagnostics(wb, result):
    cfg = result["config"]
    ws = wb.create_sheet("Diagnostics")
    r = _title(ws, "Diagnostics", 1, 7)
    r = _sub(ws, "Uncertainty audit and detector views (§9, §6.6).", r, 7)

    r = _section(ws, "NOISE SPLIT (§9.5)", r)
    ns = result["noise_split"]
    r = _header(ws, r, ["Quantity", "Value", "Note"])
    if ns.get("ok"):
        for label, value, note in [
            ("lag-1 correlation", ns["rho1"], "negative when dip noise dominates"),
            ("sigma_dip (mm)", ns["sigma_h"], "method of moments"),
            ("sigma_pour (L)", ns["sigma_pour"], "the rest of the interval variance"),
            ("implied RMSE (L)", ns["implied_rmse"], "must equal the observed"),
            ("observed RMSE (L)", ns["observed_rmse"], "check"),
            ("configured sigma_h (mm)", cfg.sigma_h,
             "the value used everywhere; compare with the estimate above"),
        ]:
            r = _row(ws, r, [label, value, note], formats=[None, "0.000", None])
    else:
        r = _row(ws, r, ["not computed", ns.get("reason", ""), ""])

    r = _section(ws, "SENSITIVITY BATTERY (§8.3)", r + 1)
    bat = result["battery"]
    spread = bat["shell_spread"]
    r = _header(ws, r, ["Item", "Value", "Note"])
    r = _row(ws, r, ["battery runs", len(bat["runs"]), "loss x h0 x exclusion shapes"])
    r = _row(ws, r, ["r spread (mm)", f"{spread['r'][0]:.2f} to {spread['r'][1]:.2f}",
                     "how far the refit shapes move r"])
    r = _row(ws, r, ["L spread (mm)", f"{spread['L'][0]:.2f} to {spread['L'][1]:.2f}", ""])
    for u in bat["per_unknown"]:
        r = _row(
            ws, r,
            [f"unknown at interval {u['interval']}", f"range {u['range']:.1f} L",
             f"noise term {u['noise_term']:.1f} L; "
             + ("settled" if u["settled"] else "not settled")],
        )

    r = _section(ws, "TELESCOPING BLOCK TEST (§9.6)", r + 1)
    r = _header(ws, r, ["Block", "From (mm)", "To (mm)", "Sum (L)", "sigma (L)", "z", "Flag"])
    for b in result["telescoping"]:
        fill = BAD if b["flag"] != "ok" else None
        r = _row(ws, r, [b["block"], b["from_mm"], b["to_mm"], b["sum"], b["sigma"], b["z"], b["flag"]],
                 formats=[None, "0.0", "0.0", "0.0", "0.0", "0.00", None], fill=fill)

    r = _section(ws, "MULTIPLE COMPARISONS (§9.7)", r + 1)
    mc = result["multi"]
    r = _header(ws, r, ["Threshold", "Observed", "Expected", "Note"])
    r = _row(ws, r, ["|z| >= 2", mc["obs2"], mc["exp2"], "chance alone puts 0.05 n here"])
    r = _row(ws, r, ["|z| >= 3", mc["obs3"], mc["exp3"], "chance alone puts 0.003 n here"])

    r = _section(ws, "DRIFT SHAPE (§6.6)", r + 1)
    d = result["drift"]
    r = _header(ws, r, ["Quantity", "Value", "Note"])
    for label, value, note in [
        ("shape", d["shape"], "the residual locates; the drift remembers"),
        ("largest step (L)", d["jump"], f"at {d['jump_at_mm']:.0f} mm"),
        ("start (L)", d["start"], ""),
        ("end (L)", d["end"], ""),
    ]:
        r = _row(ws, r, [label, value, note])

    r = _section(ws, "PAIR SCATTER (§6.6)", r + 1)
    r = _header(ws, r, ["i", "z(i)", "z(i+1)", "Reading"])
    for p in result["pair_scatter"]:
        fill = BAD if "superposed" in p["kind"] else (WARN if "anti-diagonal" in p["kind"] else None)
        r = _row(ws, r, [p["i"], p["z1"], p["z2"], p["kind"]],
                 formats=[None, "0.00", "0.00", None], fill=fill)

    r = _section(ws, "CLOSURE AND QA", r + 1)
    cl = result["closure"]
    qa = result["qa"]
    r = _header(ws, r, ["Item", "Value", "Note"])
    r = _row(ws, r, ["closure diff (L)", cl["diff"], f"limit {cl['limit']:.1f} L; z={cl['z']:.2f}"])
    r = _row(ws, r, ["closure ok", "yes" if cl["ok"] else "no", "first pour + poured + blocked vs F(H)"])
    r = _row(ws, r, ["QA max |books - F| (L)", qa["max"], "over corrected rows"])
    r = _row(ws, r, ["QA mean (L)", qa["mean"], f"n={qa['n']}"])
    r = _row(ws, r, ["empty start", result["empty_start"]["resid"], result["empty_start"]["kind"]])

    if result.get("quantized"):
        r = _section(ws, "QUANTIZED POUR SEARCH (§6.2)", r + 1)
        r = _header(ws, r, ["Interval", "Best pour (L)", "Units", "Dip prev (mm)", "Dip cur (mm)", "chi2", "Baseline", "Decisive"])
        for q in result["quantized"]:
            b = q["best"]
            r = _row(
                ws, r,
                [q["interval"], b.pour, b.units, b.dip_prev_mm, b.dip_cur_mm,
                 b.chi2, q["baseline"].chi2, "yes" if q["decisive"] else "no"],
                formats=[None, "0.0", "+0;-0;0", "0.0", "0.0", "0.0", "0.0", None],
            )

    if result.get("blocking"):
        bl = result["blocking"]
        r = _section(ws, "INTERVAL BLOCKING (§7)", r + 1)
        r = _header(ws, r, ["Item", "Value", "Note"])
        r = _row(ws, r, ["blocks", bl["stats"]["n_blocks"], f"median rise {bl['stats']['median_rise_mm']:.0f} mm"])
        r = _row(ws, r, ["blocked r", bl["fit"].shell.r, f"delta {bl['delta_r']:+.2f} mm"])
        r = _row(ws, r, ["blocked L", bl["fit"].shell.L, f"delta {bl['delta_L']:+.2f} mm"])
        r = _row(ws, r, ["blocked h0", bl["fit"].shell.h0, f"delta {bl['delta_h0']:+.2f} mm"])
        r = _row(ws, r, ["RMSE", bl["fit"].rmse, "not comparable across grouped and ungrouped fits"])

    if result.get("correction_invariance"):
        inv = result["correction_invariance"]
        r = _section(ws, "CORRECTION INVARIANCE (§6.1-4)", r + 1)
        r = _header(ws, r, ["Quantity", "Delta", "Note"])
        r = _row(ws, r, ["r (mm)", inv["r"], "refit on the uncorrected rows"])
        r = _row(ws, r, ["L (mm)", inv["L"], ""])
        r = _row(ws, r, ["h0 (mm)", inv["h0"], ""])
        r = _row(ws, r, ["RMSE (L/step)", inv["rmse"], ""])
        r = _row(ws, r, ["moves a conclusion", "yes" if inv["moves_conclusion"] else "no",
                         "a correction must not move the geometry beyond its profile"])

    if result.get("lag"):
        r = _section(ws, "SETTLING LAG (§6.4)", r + 1)
        r = _header(ws, r, ["At (mm)", "Creep (mm)", "Minutes", "Verdict"])
        for item in result["lag"]:
            r = _row(ws, r, [item.get("at_mm"), item.get("creep_mm"), item.get("minutes"), item.get("verdict")],
                     formats=["0.0", "0.00", "0.0", None])

    _widths(ws, [28, 18, 16, 18, 14, 10, 52])
    ws.freeze_panes = "A3"


def _anomaly_log(wb, result):
    ws = wb.create_sheet("AnomalyLog")
    r = _title(ws, "Anomaly register", 1, 6)
    r = _sub(ws, "Every data-to-model gap, with its rule and its status (§6, §11).", r, 6)
    r = _header(ws, r, ["Kind", "Where (mm)", "Magnitude (L)", "Rule", "Status", "Discriminating test"])
    for item in result["register"]:
        fill = WARN if item["kind"] in ("watch item", "single-sided") else None
        r = _row(ws, r, [item["kind"], item["where_mm"], item["magnitude_l"], item["rule"], item["status"], item["test"]],
                 formats=[None, None, "0.00", None, None, None], fill=fill)
    _widths(ws, [22, 16, 14, 8, 58, 52])
    ws.freeze_panes = "A5"


def _strapping(wb, result):
    ws = wb.create_sheet("Strapping")
    r = _title(ws, "Authoritative strapping table", 1, 5)
    r = _sub(
        ws,
        "Level to liquid volume, blocked-volume corrected (§6.3). One table "
        "per tank at any time (§1.3). ±sigma includes parameter and dip noise.",
        r,
        5,
    )
    r = _header(ws, r, ["Level (mm)", "Liquid (L)", "To brim (L)", "±sigma (L)", "Flag", "Note"])
    for item in result["strapping"]:
        fill = WARN if "extrapolated" in item["flag"] else None
        if "brim-anchored" in item["flag"]:
            fill = NOTE
        r = _row(ws, r, [item["level_mm"], item["liquid_l"], item.get("to_brim_l", ""),
                         item["sigma_l"], item["flag"], ""],
                 formats=["0.0", "0.0", "0.0", "0.0", None, None], fill=fill)
    _widths(ws, [12, 14, 14, 12, 30, 30])
    ws.freeze_panes = "A5"


def _commercial(wb, result):
    ws = wb.create_sheet("Commercial")
    r = _title(ws, "Commercial chart", 1, 4)
    r = _sub(
        ws,
        "Fixed dip interval, whole litres, from the lowest verified dip to the "
        "brim. Below the lowest verified dip the row is labelled extrapolated.",
        r,
        4,
    )
    r = _header(ws, r, ["Level (mm)", "Volume (L)", "Validity", "Note"])
    for item in result["commercial"]:
        fill = WARN if item["validity"] == "extrapolated" else None
        if item["validity"] == "brim-anchored":
            fill = NOTE
        r = _row(ws, r, [item["level_mm"], item["volume_l"], item["validity"], item.get("note", "")],
                 formats=["0.0", "0", None, None], fill=fill)
    _widths(ws, [12, 14, 14, 40])
    ws.freeze_panes = "A5"


def _curve(wb, result):
    """Dense shell curve for the native charts."""
    ws = wb.create_sheet("Curve")
    r = _title(ws, "Shell curve", 1, 5)
    r = _sub(ws, "Dense F(H), slope and liquid volume. Data for the live charts.", r, 5)
    r = _header(ws, r, ["Level (mm)", "F(H) (L)", "m (L/mm)", "Liquid (L)"])
    fit = result["fit"]
    bands = result["bands"]
    brim = fit.shell.brim()
    step = 10.0
    h = 0.0
    while h < brim:
        liquid = float(fit.shell.volume(h)) - float(blocked_below(bands, h))
        r = _row(ws, r, [h, float(fit.shell.volume(h)), float(fit.shell.slope(h)), liquid],
                 formats=["0.0", "0.00", "0.0000", "0.00"])
        h += step
    r = _row(ws, r, [brim, float(fit.shell.volume(brim)), 0.0,
                     float(fit.shell.volume(brim)) - float(blocked_below(bands, brim))],
             formats=["0.0", "0.00", "0.0000", "0.00"])
    _widths(ws, [12, 12, 12, 12])
    ws.freeze_panes = "A5"


def _pairs(wb, result):
    ws = wb.create_sheet("Pairs")
    r = _title(ws, "Adjacent-pair scatter data", 1, 4)
    r = _sub(ws, "One point per adjacent interval pair (§6.6).", r, 4)
    r = _header(ws, r, ["i", "z(i)", "z(i+1)", "Reading"])
    for item in result["pair_scatter"]:
        r = _row(ws, r, [item["i"], item["z1"], item["z2"], item["kind"]],
                 formats=[None, "0.00", "0.00", None])
    _widths(ws, [6, 10, 10, 46])
    ws.freeze_panes = "A5"


def _raw_pairs(wb, result):
    cfg = result["config"]
    series = charts.build_series(
        result["raw_rows"], result["fit"].shell,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
        heel_row=cfg.heel_row,
    )
    ws = wb.create_sheet("RawPairs")
    r = _title(ws, "Raw adjacent-pair scatter data", 1, 4)
    r = _sub(ws, "One point per adjacent raw interval pair (§6.6).", r, 4)
    r = _header(ws, r, ["i", "z(i)", "z(i+1)", "Reading"])
    ok = (~series.excluded) & np.isfinite(series.z)
    z = series.z[ok]
    for i in range(len(z) - 1):
        r = _row(ws, r, [i + 1, float(z[i]), float(z[i + 1]), ""],
                 formats=[None, "0.00", "0.00", None])
    _widths(ws, [6, 10, 10, 46])
    ws.freeze_panes = "A5"


def _guides(wb, result):
    """Two-point series for the reference lines of the live charts."""
    ws = wb.create_sheet("Guides")
    r = _title(ws, "Guide series", 1, 4)
    r = _sub(ws, "Reference lines for the live charts. Each name is a series.", r, 4)
    r = _header(ws, r, ["Series", "x", "y"])
    brim = result["fit"].shell.brim()
    cap = result["fit"].shell.capacity()
    points = [
        ("identity", [(0.0, 0.0), (cap, cap)]),
        ("diag_main", [(-15.0, -15.0), (15.0, 15.0)]),
        ("diag_anti", [(-15.0, 15.0), (15.0, -15.0)]),
        ("box", [(-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0), (-2.0, -2.0)]),
        ("z+2", [(0.0, 2.0), (brim, 2.0)]),
        ("z-2", [(0.0, -2.0), (brim, -2.0)]),
        ("z+3", [(0.0, 3.0), (brim, 3.0)]),
        ("z-3", [(0.0, -3.0), (brim, -3.0)]),
        ("zero", [(0.0, 0.0), (brim, 0.0)]),
        ("brim", [(brim, 0.0), (brim, cap)]),
    ]
    rows = {}
    for name, pts in points:
        first = r
        for x, y in pts:
            r = _row(ws, r, [name, x, y], formats=[None, "0.0", "0.0"])
        rows[name] = (first, r - 1)
    _widths(ws, [14, 10, 10])
    return rows


def _scatter(ws, title, x_title, y_title, x_ref, y_ref, *, line=False, color="2563EB", width=14, height=8):
    chart = ScatterChart()
    chart.title = title
    chart.x_axis.title = x_title
    chart.y_axis.title = y_title
    chart.style = 13
    chart.width = width
    chart.height = height
    series = Series(y_ref, x_ref, title_from_data=True)
    if line:
        series.marker = Marker(symbol="none")
        series.graphicalProperties.line = LineProperties(solidFill=color, w=22000)
    else:
        series.marker = Marker(symbol="circle", size=5)
        series.graphicalProperties.line = LineProperties(noFill=True)
    chart.series.append(series)
    chart.legend = None
    return chart


def _ref(ws, col, first, last):
    return Reference(ws, min_col=col, min_row=first, max_row=last)


def _gref(ws, rows, col):
    first, last = rows
    return Reference(ws, min_col=col, min_row=first, max_row=last)


def _add_series(chart, x_ref, y_ref, title, color, *, marker="circle",
                filled=False, line=False, dash=None, width=22000):
    series = Series(y_ref, x_ref, title=title)
    if marker:
        series.marker = Marker(symbol=marker, size=5)
        if filled:
            series.marker.graphicalProperties = GraphicalProperties(solidFill=color)
        else:
            series.marker.graphicalProperties = GraphicalProperties(
                noFill=True, ln=LineProperties(solidFill=color)
            )
    else:
        series.marker = Marker(symbol="none")
    if line:
        series.graphicalProperties.line = LineProperties(solidFill=color, w=width)
        if dash:
            series.graphicalProperties.line.dashStyle = dash
    else:
        series.graphicalProperties.line = LineProperties(noFill=True)
    chart.series.append(series)
    return series


def _charts(wb, result, guides):
    """The seven views of §6.6 as live Excel charts (CHARTS.md grammar)."""
    ws = wb.create_sheet("Charts")
    r = _title(ws, "The seven views of §6.6 — live charts", 1, 12)
    r = _sub(
        ws,
        "Each chart reads Model, RawModel, Curve, Pairs or Guides. Raw is red, "
        "corrected is green, the model is blue. Consult the pair scatter last.",
        r,
        12,
    )
    model = wb["Model"]
    raw = wb["RawModel"]
    curve = wb["Curve"]
    pairs = wb["Pairs"]
    raw_pairs = wb["RawPairs"]
    guides_ws = wb["Guides"]
    n_model = model.max_row
    n_raw = raw.max_row
    n_curve = curve.max_row
    n_pairs = pairs.max_row
    n_raw_pairs = raw_pairs.max_row

    # 1. Strapping vs books
    c = ScatterChart()
    c.title = "Strapping vs books"
    c.x_axis.title = "Tape reading H (mm)"
    c.y_axis.title = "Cumulative volume (L)"
    c.style = 13
    c.width, c.height = 15, 9
    c.x_axis.delete = False
    c.y_axis.delete = False
    _add_series(c, _ref(curve, 1, 5, n_curve), _ref(curve, 2, 5, n_curve),
                "Fitted shell V(H)", charts.MODEL, marker=None, line=True)
    _add_series(c, _ref(raw, 3, 5, n_raw), _ref(raw, 13, 5, n_raw),
                "Raw books", charts.RAW, marker="circle")
    _add_series(c, _ref(model, 3, 5, n_model), _ref(model, 13, 5, n_model),
                "Corrected books", charts.COR, marker="square", filled=True)
    _add_series(c, _gref(guides_ws, guides["brim"], 2), _gref(guides_ws, guides["brim"], 3),
                "Brim", "808080", marker=None, line=True, dash="dash")
    ws.add_chart(c, "A4")

    # 2. Interval residuals
    c = ScatterChart()
    c.title = "Interval residuals"
    c.x_axis.title = "Tape reading H (mm)"
    c.y_axis.title = "Residual, obs - pred (L)"
    c.style = 13
    c.width, c.height = 15, 9
    c.x_axis.delete = False
    c.y_axis.delete = False
    _add_series(c, _ref(raw, 3, 5, n_raw), _ref(raw, 8, 5, n_raw),
                "Raw residual", charts.RAW, marker="circle")
    _add_series(c, _ref(model, 3, 5, n_model), _ref(model, 8, 5, n_model),
                "Corrected residual", charts.COR, marker="square", filled=True)
    _add_series(c, _ref(model, 3, 5, n_model), _ref(model, 15, 5, n_model),
                "+1 sigma", charts.MODEL, marker=None, line=True, dash="dash")
    _add_series(c, _ref(model, 3, 5, n_model), _ref(model, 16, 5, n_model),
                "-1 sigma", charts.MODEL, marker=None, line=True, dash="dash")
    _add_series(c, _gref(guides_ws, guides["zero"], 2), _gref(guides_ws, guides["zero"], 3),
                "zero", "808080", marker=None, line=True)
    ws.add_chart(c, "A22")

    # 3. Predicted vs recorded
    c = ScatterChart()
    c.title = "Predicted vs recorded"
    c.x_axis.title = "Recorded pour (L)"
    c.y_axis.title = "Predicted pour from the shell (L)"
    c.style = 13
    c.width, c.height = 12, 9
    c.x_axis.delete = False
    c.y_axis.delete = False
    _add_series(c, _ref(raw, 5, 5, n_raw), _ref(raw, 4, 5, n_raw),
                "Raw", charts.RAW, marker="circle")
    _add_series(c, _ref(model, 5, 5, n_model), _ref(model, 4, 5, n_model),
                "Corrected", charts.COR, marker="square", filled=True)
    _add_series(c, _gref(guides_ws, guides["identity"], 2), _gref(guides_ws, guides["identity"], 3),
                "y = x", "808080", marker=None, line=True)
    ws.add_chart(c, "A40")

    # 4. Slope profile
    c = ScatterChart()
    c.title = "Slope profile"
    c.x_axis.title = "Level midpoint (mm)"
    c.y_axis.title = "Slope (L per mm)"
    c.style = 13
    c.width, c.height = 15, 9
    c.x_axis.delete = False
    c.y_axis.delete = False
    _add_series(c, _ref(curve, 1, 5, n_curve), _ref(curve, 3, 5, n_curve),
                "Shell slope dV/dH", charts.MODEL, marker=None, line=True)
    _add_series(c, _ref(raw, 3, 5, n_raw), _ref(raw, 14, 5, n_raw),
                "Raw pour / rise", charts.RAW, marker="circle")
    _add_series(c, _ref(model, 3, 5, n_model), _ref(model, 14, 5, n_model),
                "Corrected pour / rise", charts.COR, marker="square", filled=True)
    ws.add_chart(c, "A58")

    # 5. Drift
    c = ScatterChart()
    c.title = "Drift: the running disagreement"
    c.x_axis.title = "Tape reading H (mm)"
    c.y_axis.title = "Drift, books - F (L)"
    c.style = 13
    c.width, c.height = 15, 9
    c.x_axis.delete = False
    c.y_axis.delete = False
    _add_series(c, _ref(raw, 3, 5, n_raw), _ref(raw, 11, 5, n_raw),
                "Raw", charts.RAW, marker="circle", line=True)
    _add_series(c, _ref(model, 3, 5, n_model), _ref(model, 11, 5, n_model),
                "Corrected", charts.COR, marker="square", filled=True, line=True)
    _add_series(c, _gref(guides_ws, guides["zero"], 2), _gref(guides_ws, guides["zero"], 3),
                "zero", "808080", marker=None, line=True)
    ws.add_chart(c, "A76")

    # 6. z alarms
    c = ScatterChart()
    c.title = "z alarms"
    c.x_axis.title = "Level (mm)"
    c.y_axis.title = "z = resid / sigma"
    c.style = 13
    c.width, c.height = 15, 9
    c.x_axis.delete = False
    c.y_axis.delete = False
    _add_series(c, _ref(raw, 3, 5, n_raw), _ref(raw, 10, 5, n_raw),
                "Raw", charts.RAW, marker="circle")
    _add_series(c, _ref(model, 3, 5, n_model), _ref(model, 10, 5, n_model),
                "Corrected", charts.COR, marker="square", filled=True)
    for name, color, dash in (
        ("z+2", charts.CHECK, "dash"), ("z-2", charts.CHECK, "dash"),
        ("z+3", charts.RAW, "sysDot"), ("z-3", charts.RAW, "sysDot"),
    ):
        _add_series(c, _gref(guides_ws, guides[name], 2), _gref(guides_ws, guides[name], 3),
                    name, color, marker=None, line=True, dash=dash)
    ws.add_chart(c, "A94")

    # 7. Adjacent-pair scatter
    c = ScatterChart()
    c.title = "Adjacent-pair scatter"
    c.x_axis.title = "z(i)"
    c.y_axis.title = "z(i+1)"
    c.style = 13
    c.width, c.height = 12, 10
    c.x_axis.delete = False
    c.y_axis.delete = False
    c.x_axis.scaling.min = -15
    c.x_axis.scaling.max = 15
    c.y_axis.scaling.min = -15
    c.y_axis.scaling.max = 15
    _add_series(c, _ref(raw_pairs, 2, 5, n_raw_pairs), _ref(raw_pairs, 3, 5, n_raw_pairs),
                "Raw pairs", charts.RAW, marker="circle")
    _add_series(c, _ref(pairs, 2, 5, n_pairs), _ref(pairs, 3, 5, n_pairs),
                "Corrected pairs", charts.COR, marker="square", filled=True)
    for name in ("diag_main", "diag_anti", "box"):
        _add_series(c, _gref(guides_ws, guides[name], 2), _gref(guides_ws, guides[name], 3),
                    name, charts.MODEL, marker=None, line=True,
                    dash="dash" if name == "box" else None)
    ws.add_chart(c, "A112")
    _widths(ws, [100])
    return ws


def _audit(wb, result):
    """Optional live-formula sheet and Solver setup (§5.6)."""
    ws = wb.create_sheet("Audit")
    r = _title(ws, "Audit — live formulas and Excel Solver (§5.6)", 1, 10)
    r = _sub(
        ws,
        "The shipped values are authoritative. This sheet reproduces the "
        "difference fit so a reviewer can check it by hand. Solver is an audit "
        "aid, not the source of truth.",
        r,
        10,
    )
    fit = result["fit"]
    cfg = result["config"]
    ws["A4"] = "r (mm)"
    ws["B4"] = fit.shell.r
    ws["A5"] = "L (mm)"
    ws["B5"] = fit.shell.L
    ws["A6"] = "h0 (mm)"
    ws["B6"] = fit.shell.h0
    ws["A7"] = "sigma_h (mm)"
    ws["B7"] = cfg.sigma_h
    ws["A8"] = "pour rel"
    ws["B8"] = cfg.pour_rel
    ws["A9"] = "pour abs (L)"
    ws["B9"] = cfg.pour_abs
    ws["A10"] = "Objective SSE"

    hdr = ["i", "H_prev", "H_cur", "Step", "h_prev", "A_prev", "h_cur", "A_cur",
           "Predicted", "Residual", "m", "mm-equiv", "sigma", "z"]
    for c, text in enumerate(hdr, start=1):
        cell = ws.cell(row=14, column=c, value=text)
        cell.font = Font(bold=True, color=HEAD_FG, size=9)
        cell.fill = PatternFill("solid", fgColor=HEAD)

    row = 15
    for iv in result["intervals"]:
        if not iv.known or not iv.trusted:
            continue
        ws.cell(row=row, column=1, value=iv.idx)
        ws.cell(row=row, column=2, value=iv.h_prev)
        ws.cell(row=row, column=3, value=iv.h_cur)
        ws.cell(row=row, column=4, value=iv.s)
        ws.cell(row=row, column=5, value=f"=MIN(MAX(B{row}-$B$6,0),2*$B$4)")
        ws.cell(row=row, column=6, value=(
            f"=$B$4^2*ACOS(MAX(-1,MIN(1,($B$4-E{row})/$B$4)))"
            f"-($B$4-E{row})*SQRT(MAX(0,2*$B$4*E{row}-E{row}^2))"
        ))
        ws.cell(row=row, column=7, value=f"=MIN(MAX(C{row}-$B$6,0),2*$B$4)")
        ws.cell(row=row, column=8, value=(
            f"=$B$4^2*ACOS(MAX(-1,MIN(1,($B$4-G{row})/$B$4)))"
            f"-($B$4-G{row})*SQRT(MAX(0,2*$B$4*G{row}-G{row}^2))"
        ))
        ws.cell(row=row, column=9, value=f"=$B$5*(H{row}-F{row})/1E6")
        ws.cell(row=row, column=10, value=f"=D{row}-I{row}")
        ws.cell(row=row, column=11, value=f"=2*$B$5*SQRT(MAX(0,2*$B$4*G{row}-G{row}^2))/1E6")
        ws.cell(row=row, column=12, value=f"=IF(K{row}=0,\"\",J{row}/K{row})")
        ws.cell(row=row, column=13, value=(
            f"=SQRT((K{row}*$B$7*SQRT(2))^2+($B$8*D{row}+$B$9)^2)"
        ))
        ws.cell(row=row, column=14, value=f"=IF(M{row}=0,\"\",J{row}/M{row})")
        row += 1

    last = row - 1
    ws["B10"] = (
        f"=SUMPRODUCT(J15:J{last},J15:J{last})" if last >= 15 else "=0"
    )
    r = row + 2
    r = _section(ws, "SOLVER SETUP", r)
    steps = [
        "1. Data > Solver.",
        "2. Set Objective: $B$10. To: Min.",
        "3. By Changing Variable Cells: $B$4:$B$6.",
        "4. Add constraint: $B$4 >= 0.6*nominal r; $B$4 <= 1.4*nominal r.",
        "5. Add constraint: $B$5 >= 0.7*nominal L; $B$5 <= 1.3*nominal L.",
        "6. Add constraint: $B$6 >= -80; $B$6 <= 80.",
        "7. Select GRG Nonlinear. Solve. Keep the Solver solution.",
        "8. Compare with the shipped values on Fit. They must agree.",
    ]
    for text in steps:
        r = _row(ws, r, [text])
    _widths(ws, [8, 10, 10, 10, 10, 12, 10, 12, 12, 11, 9, 10, 10, 8])
    ws.freeze_panes = "A15"
    return ws


def _reference(wb):
    ws = wb.create_sheet("Reference")
    r = _title(ws, "Reference", 1, 6)
    r = _sub(ws, "Short notes. The methodology file is the authority.", r, 6)
    items = [
        ("Residual", "resid = step - (F(H_i) - F(H_i-1)). Negative: rise too cheap. Positive: rise too small."),
        ("Action bar", "Candidate: |resid| >= 3 mm-equiv and |z| >= 3. Watch: >= 1.5 mm or |z| >= 2."),
        ("Pair rule", "Two adjacent intervals, opposite signs, each at the bar, net <= 15 % of the sum."),
        ("Object", "Once submerged, displacement is constant; difference residuals return to zero."),
        ("Liquid", "liquid(H) = F(H) - blocked volumes below H. Never quote raw F as liquid."),
        ("Unknown pours", "x = F(H_i) - F(H_i-1) - known_base. Never fitted."),
        ("Closure", "first pour + poured + blocked below H = F(H), within 3 sigma sqrt(n)."),
        ("Blocking", "Merge small pours for fitting only; block boundaries stay fit points."),
        ("Tape scale", "Unidentifiable from pour/level data. The volume table is invariant."),
        ("Tilt", "Not absorbed by r. Test it or record it as a limitation."),
    ]
    r = _header(ws, r, ["Term", "Meaning"])
    for term, text in items:
        r = _row(ws, r, [term, text])
    _widths(ws, [18, 100])
    ws.freeze_panes = "A5"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _certificate(wb, header):
    """Customer-facing header sheet (§11)."""
    ws = wb.create_sheet("Certificate", 0)
    r = _title(ws, header["title"], 1, 6)
    r = _sub(ws, header["subtitle"], r, 6)
    r = _section(ws, "Identification", r, 6)
    r = _kv(ws, r, header["identification"], span=6)
    r = _section(ws, "Adopted shell", r, 6)
    r = _kv(ws, r, header["shell"], span=6)
    for title, text in (
        ("Datum", header["datum"]),
        ("Basis", header["basis"]),
        ("Uncertainty", header["uncertainty"]),
    ):
        r = _section(ws, title, r, 6)
        cell = ws.cell(row=r, column=1, value=text)
        cell.font = Font(size=9, color=INK)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        ws.row_dimensions[r].height = 44
        r += 1
    r = _section(ws, "Validity", r, 6)
    r = _header(ws, r, ["Region", "Level", "Status"])
    for row in header["validity"]:
        r = _row(ws, r, list(row))
    r = _section(ws, "Quality", r, 6)
    r = _kv(ws, r, header["quality"], span=6)
    r = _section(ws, "Anomalies", r, 6)
    r = _header(ws, r, ["Item", "Where", "Effect"])
    for row in header["anomalies"]:
        r = _row(ws, r, list(row))
    r = _section(ws, "Limitations", r, 6)
    for line in header["limitations"]:
        cell = ws.cell(row=r, column=1, value=f"- {line}")
        cell.font = Font(size=9, color=INK)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        r += 1
    r = _section(ws, "Files", r, 6)
    cell = ws.cell(row=r, column=1, value=", ".join(header["files"]))
    cell.font = Font(size=9, color=INK)
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _widths(ws, [24, 22, 36, 14, 14, 14])
    ws.freeze_panes = "A4"


def build_workbook(
    path: str | Path,
    result: dict,
    *,
    audit_sheet: bool = True,
    header: dict | None = None,
) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    if header:
        _certificate(wb, header)
    _readme(wb, result)
    _settings(wb, result)
    _input(wb, result)
    _model(wb, result)
    _raw_model(wb, result)
    _fit_sheet(wb, result)
    _diagnostics(wb, result)
    _anomaly_log(wb, result)
    _strapping(wb, result)
    _commercial(wb, result)
    _curve(wb, result)
    _pairs(wb, result)
    _raw_pairs(wb, result)
    guides = _guides(wb, result)
    _charts(wb, result, guides)
    if audit_sheet:
        _audit(wb, result)
    _reference(wb)
    path = Path(path)
    wb.save(path)
    return path

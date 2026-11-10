"""Deliverables: shell record, strapping table, commercial chart, register (§11)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .data import Interval
from .diagnostics import blocked_below
from .diagnostics import to_brim as to_brim_l
from .fit import FitResult, cov3
from .geometry import Shell


def volume_grad(shell: Shell, H, d: float = 1e-2):
    """dF/dr, dF/dL, dF/dh0 by central differences."""
    r, L, h0 = shell.r, shell.L, shell.h0
    H = np.asarray(H, dtype=float)
    fr = (Shell(r + d, L, h0).volume(H) - Shell(r - d, L, h0).volume(H)) / (2 * d)
    fl = (Shell(r, L + d, h0).volume(H) - Shell(r, L - d, h0).volume(H)) / (2 * d)
    fh = (Shell(r, L, h0 + d).volume(H) - Shell(r, L, h0 - d).volume(H)) / (2 * d)
    return np.array([fr, fl, fh])


def table_sigma(shell: Shell, H, fit: FitResult, sigma_h: float) -> np.ndarray:
    """Volume uncertainty from parameter covariance plus dip noise."""
    g = volume_grad(shell, H)
    C = cov3(fit)
    H = np.atleast_1d(np.asarray(H, dtype=float))
    if C is None:
        model_var = np.zeros(H.shape)
    else:
        model_var = np.einsum("in,ij,jn->n", g, C, g)
    dip = np.asarray(shell.slope(H), dtype=float) * sigma_h
    return np.sqrt(np.maximum(model_var, 0.0) + dip ** 2)


def strapping_table(
    shell: Shell,
    fit: FitResult,
    *,
    bands: list[dict],
    lowest_verified: float,
    highest_verified: float | None = None,
    step_mm: float = 10.0,
    sigma_h: float = 1.5,
    start_mm: float = 0.0,
) -> list[dict]:
    """Level -> liquid volume, blocked-volume corrected, with ±sigma and flags."""
    brim = shell.brim()
    levels = np.arange(start_mm, brim + 1e-9, step_mm)
    if len(levels) == 0 or levels[-1] < brim:
        levels = np.append(levels, brim)
    sig = table_sigma(shell, levels, fit, sigma_h)
    out = []
    for h, s in zip(levels, sig):
        liquid = float(shell.volume(h)) - float(blocked_below(bands, h))
        flag = "verified" if h >= lowest_verified else "extrapolated"
        if highest_verified is not None and h > highest_verified:
            flag = "brim-anchored"
        for band in bands:
            if float(band["low"]) <= h <= float(band["high"]):
                flag += "; object band"
        out.append(
            {
                "level_mm": float(h),
                "liquid_l": liquid,
                "to_brim_l": float(to_brim_l(shell, h, bands)),
                "sigma_l": float(s),
                "flag": flag,
            }
        )
    return out


def commercial_chart(
    shell: Shell,
    *,
    bands: list[dict],
    lowest_verified: float,
    highest_verified: float | None = None,
    step_mm: float = 10.0,
    start_mm: float = 0.0,
    shell_accepted: bool = True,
) -> list[dict]:
    """Fixed-interval chart, whole litres, extrapolated region labelled (§11)."""
    brim = shell.brim()
    levels = np.arange(start_mm, brim + 1e-9, step_mm)
    if len(levels) == 0 or levels[-1] < brim:
        levels = np.append(levels, brim)
    out = []
    for h in levels:
        liquid = float(shell.volume(h)) - float(blocked_below(bands, h))
        validity = "verified" if h >= lowest_verified else "extrapolated"
        if highest_verified is not None and h > highest_verified:
            validity = "brim-anchored"
        out.append(
            {
                "level_mm": float(h),
                "volume_l": round(liquid),
                "validity": validity,
                "note": (
                    "shell accepted (§5.7)"
                    if shell_accepted
                    else "SHELL NOT ACCEPTED — do not use for custody"
                ),
            }
        )
    return out


def qa_agreement(
    intervals,
    shell: Shell,
    *,
    bands: list[dict],
    heel: float,
    estimates: list[dict] | None = None,
) -> dict:
    """max |books - F| over corrected rows (§11).

    Unknown pours enter at their back-predicted value, so the number is
    comparable across a campaign with gaps.
    """
    trusted = [iv for iv in intervals if iv.trusted]
    if not trusted:
        return {"max": float("nan"), "mean": float("nan"), "n": 0}
    h_last = trusted[-1].h_cur
    est = {u["interval"]: u for u in (estimates or [])}
    books = float(heel)
    diffs = []
    for iv in intervals:
        if iv.h_cur > h_last:
            continue
        if iv.known:
            books += float(iv.s)
        elif iv.idx in est:
            books += float(est[iv.idx].get("total", est[iv.idx]["x"]))
        else:
            continue
        diffs.append(abs(books + float(blocked_below(bands, iv.h_cur)) - float(shell.volume(iv.h_cur))))
    if not diffs:
        return {"max": float("nan"), "mean": float("nan"), "n": 0}
    return {
        "max": float(max(diffs)),
        "mean": float(sum(diffs) / len(diffs)),
        "n": len(diffs),
    }


def datum_statement(
    shell: Shell,
    *,
    h0_mode: str,
    lock: dict | None,
    v0: float,
) -> str:
    if h0_mode == "locked":
        cost = "locked by configuration"
    elif lock:
        cost = f"{lock['delta_rmse']:+.3f} L/step (F-test p={lock['p']:.3g})"
    else:
        cost = "not tested"
    text = (
        f"h0 = {shell.h0:.1f} mm ({'locked' if h0_mode == 'locked' else 'fitted'}; "
        f"lock cost {cost})"
    )
    if abs(v0) > 0.5:
        text += f"; V(0) = {v0:.1f} L below tape zero"
    return text


def anomaly_register(
    *,
    bands: list[dict],
    pairs: list,
    singles: list[Interval],
    watch: list[Interval],
    unknowns: list[dict],
    corrections: list,
    quantized: list[dict] | None = None,
) -> list[dict]:
    """Every data-to-model gap, with its status (§11)."""
    out = []
    for band in bands:
        out.append(
            {
                "kind": "object band",
                "where_mm": f"{band['low']:g}-{band['high']:g}",
                "magnitude_l": float(band.get("displacement", band.get("litres", 0.0)) or 0.0),
                "rule": "6.3",
                "status": "declared; excluded from fit; subtracted from liquid volume",
                "test": band.get("test", "repeat pour, inspect, or pump-out audit"),
            }
        )
    for p in pairs:
        out.append(
            {
                "kind": "dip pair" if p.actionable else "dip pair (marginal)",
                "where_mm": f"{p.shared_height:.0f}",
                "magnitude_l": p.net,
                "rule": "6.1",
                "status": (
                    f"correct {p.shared_height:.0f} -> {p.corrected_dip:.1f} mm"
                    if p.actionable
                    else "suspect; re-dip or grouped refit"
                ),
                "test": "re-dip the shared level; refit must not move a conclusion",
            }
        )
    qmap = {q["interval"]: q for q in (quantized or [])}
    for iv in singles:
        status = "OBJECT? or POUR?; not separable from one pass"
        test = "repeat pour, pour-unit grid search, inspect, pump-out audit"
        q = qmap.get(iv.idx)
        if q:
            b = q["best"]
            status = (
                f"grid search: pour {b.pour:.0f} L ({b.units:+d} units), "
                f"dips {b.dip_prev_mm:+.1f}/{b.dip_cur_mm:+.1f} mm, "
                f"chi2 {b.chi2:.1f} vs {q['baseline'].chi2:.1f}"
                + (" (decisive)" if q["decisive"] else " (not decisive)")
            )
            test = "confirm with a repeat pour; then apply both corrections"
        out.append(
            {
                "kind": "single-sided",
                "where_mm": f"{iv.h_prev:.0f}-{iv.h_cur:.0f}",
                "magnitude_l": iv.resid,
                "rule": "6.2",
                "status": status,
                "test": test,
            }
        )
    for iv in watch:
        out.append(
            {
                "kind": "watch item",
                "where_mm": f"{iv.h_prev:.0f}-{iv.h_cur:.0f}",
                "magnitude_l": iv.resid,
                "rule": "6.5",
                "status": "recorded, not corrected, not excluded",
                "test": "none: audit trail",
            }
        )
    for u in unknowns:
        out.append(
            {
                "kind": "unknown pour",
                "where_mm": f"{u['from_mm']:.0f}-{u['to_mm']:.0f}",
                "magnitude_l": u["x"],
                "rule": "8.1",
                "status": (
                    f"back-predicted {u.get('total', u['x']):.1f} L "
                    f"({u['base']:g} known + {u['x']:.1f} unknown) ± {2 * u['sigma']:.1f} L; not fitted"
                    if u.get("base")
                    else f"back-predicted {u['x']:.1f} ± {2 * u['sigma']:.1f} L; not fitted"
                ),
                "test": "sensitivity battery (§8.3)",
            }
        )
    for c in corrections:
        out.append(
            {
                "kind": "correction",
                "where_mm": f"row {c.row}",
                "magnitude_l": c.magnitude,
                "rule": c.rule,
                "status": c.note or "flagged correction",
                "test": "refit invariance (§6.1-4)",
            }
        )
    return out


def shell_record(
    *,
    tank: str,
    fit: FitResult,
    sigma_h: float,
    brim: float,
    max_liquid_l: float,
    heel_l: float,
    heel_kind: str,
    datum: str,
    constraint: str,
    blocked: float,
    corrected_dips: int,
    watch_count: int,
    unknown_text: str,
    authoritative: str,
    rmse_mm: float,
    r_sigma: float | None = None,
    l_sigma: float | None = None,
) -> str:
    s = fit.shell
    rs = r_sigma if r_sigma is not None else fit.param_sigma("r")
    ls = l_sigma if l_sigma is not None else fit.param_sigma("L")
    rs_text = f"{rs:.1f}" if rs is not None else "n/a"
    ls_text = f"{ls:.1f}" if ls is not None else "n/a"
    return (
        f"{tank} — adopted shell\n"
        f"  r = {s.r:.1f} ± {rs_text} mm    L = {s.L:.1f} ± {ls_text} mm    "
        f"h0 = {s.h0:.1f} mm ({'fitted' if 'h0' in fit.free else 'locked'})\n"
        f"  brim reading {brim:.0f} mm    Vcap {s.capacity():.1f} L    "
        f"max liquid {max_liquid_l:.1f} L\n"
        f"  heel {heel_l:.1f} L ({heel_kind})    datum cause: {datum}\n"
        f"  brim constraint: {constraint}\n"
        f"  RMSE {fit.rmse:.3f} L/step = {rmse_mm:.2f} mm-equiv    σh = {sigma_h:.2f} mm\n"
        f"  blocked volumes: {blocked:.1f} L    corrected dips: {corrected_dips}    "
        f"watch items: {watch_count}\n"
        f"  unknown pours: {unknown_text}\n"
        f"  authoritative file: {authoritative}\n"
    )


def table_header(result: dict, *, gate: dict | None = None) -> dict:
    """Customer-facing header for the strapping table (§11).

    One source of truth for the CSV comment block, the workbook Certificate
    sheet and the markdown report.
    """
    cfg = result["config"]
    fit = result["fit"]
    shell = fit.shell
    bands = result["bands"]
    lowest = float(result["lowest_verified"])
    highest = float(result.get("highest_verified", lowest))
    brim = float(shell.brim())
    checks = result["acceptance"]
    passed = sum(1 for c in checks if c["pass"])
    qa = result["qa"]
    closure = result["closure"]
    v0 = float(shell.volume(0.0))

    r_sigma = (result["profile"]["hi"] - result["profile"]["lo"]) / 2.0
    l_sigma = (result["profile_L"]["hi"] - result["profile_L"]["lo"]) / 2.0

    if bands:
        blocked = "; ".join(
            f"{float(b.get('displacement', b.get('litres', 0)) or 0.0):.1f} L at "
            f"{float(b['low']):g}-{float(b['high']):g} mm"
            for b in bands
        )
    else:
        blocked = "none declared"
    max_liquid = float(shell.capacity()) - sum(
        float(b.get("displacement", b.get("litres", 0)) or 0.0) for b in bands
    )

    identification = [
        ("Tank", cfg.tank),
        ("Site / tag", cfg.site or "—"),
        ("Calibration date", datetime.now(timezone.utc).date().isoformat()),
        ("Method", "Pour-and-dip difference fit, CALIBRATION_METHODOLOGY.md §5"),
        ("Table version", cfg.table_version),
        ("Authoritative file", f"{cfg.tank}_strapping.csv"),
        ("Supersedes", cfg.supersedes),
    ]
    shell_rows = [
        ("Radius r (mm)", f"{shell.r:.1f} ± {r_sigma:.1f}"),
        ("Length L (mm)", f"{shell.L:.1f} ± {l_sigma:.1f}"),
        (
            "Datum h0 (mm)",
            f"{shell.h0:.1f} ({'locked' if cfg.h0_mode == 'locked' else 'fitted'})",
        ),
        ("Crown level (mm)", f"{brim:.1f}"),
        ("Capacity Vcap (L)", f"{shell.capacity():.1f}"),
        ("Max liquid (L)", f"{max_liquid:.1f}"),
    ]
    datum = datum_statement(
        shell, h0_mode=cfg.h0_mode, lock=result.get("lock"), v0=v0,
    )
    basis = (
        "Liquid volume at level H = F(H) - blocked volumes below H. "
        f"Blocked volume: {blocked}. Level in mm; volume in litres."
    )
    uncertainty = (
        "The ± column is one standard deviation (1σ). It includes r, L, h0 "
        f"and one dip reading (σh = {cfg.sigma_h:.1f} mm). It does not include "
        "the object displacement, the extrapolated bottom, temperature or "
        "product correction, or tape-scale error. For a 95% interval, "
        "multiply by 2."
    )
    validity = [
        ("Bottom", f"0-{lowest:.1f} mm", "extrapolated"),
        ("Verified", f"{lowest:.1f}-{highest:.1f} mm", "backed by dips"),
    ]
    if highest < brim - 1e-9:
        validity.append(
            ("Top", f"{highest:.1f}-{brim:.1f} mm", "brim-anchored; no dip")
        )
    quality = [
        ("RMSE", f"{fit.rmse:.3f} L/step = {result['rmse_mm']:.2f} mm-equiv"),
        (
            "QA max abs(books - F)",
            f"{qa['max']:.1f} L over {qa['n']} rows (mean {qa['mean']:.1f} L)",
        ),
        (
            "Closure",
            f"{closure['diff']:+.1f} L against a {closure['limit']:.1f} L limit",
        ),
        ("Acceptance", f"{passed} of {len(checks)} checks pass"),
    ]
    if gate is not None:
        quality.append(
            (
                "Formula gate",
                f"{gate.get('formulas', 0)} formulas, "
                f"{len(gate.get('errors', []))} problems",
            )
        )
    else:
        quality.append(("Formula gate", "run `calib gate` before issue"))

    anomalies = []
    for item in result["register"]:
        magnitude = item.get("magnitude_l")
        if item.get("kind") == "correction":
            magnitude_text = (
                f"{float(magnitude):+.1f} mm" if magnitude is not None else ""
            )
        else:
            magnitude_text = (
                f"{float(magnitude):.1f} L" if magnitude is not None else ""
            )
        effect = f"{magnitude_text} — {item.get('status', '')}".strip(" —")
        anomalies.append(
            (
                str(item.get("kind", "")),
                str(item.get("where_mm", "")),
                effect,
            )
        )

    limitations = [
        "Static tilt not tested." if not cfg.tilt_test else "Static tilt tested; see report.",
        "Tape scale is unidentifiable from pour and level data.",
        "Object error and pour error are not separable from one pass.",
        "r is an effective mean; ovality and bulging are not modelled.",
        "Bottom shape is absorbed by h0; the heel is an estimate unless sounded.",
    ]
    files = [
        f"{cfg.tank}_raw.csv",
        f"{cfg.tank}_corrected.csv",
        f"{cfg.tank}_strapping.csv",
        f"{cfg.tank}_commercial.csv",
        f"{cfg.tank}_anomaly_register.csv",
        f"{cfg.tank}_shell_record.txt",
        f"{cfg.tank}_presets.json",
        f"{cfg.tank}_report.md",
        f"{cfg.tank}_workbook.xlsx",
    ]
    return {
        "title": f"{cfg.tank} — tank calibration certificate",
        "subtitle": "Strapping table header and delivery notes (§11).",
        "identification": identification,
        "shell": shell_rows,
        "datum": datum,
        "basis": basis,
        "uncertainty": uncertainty,
        "validity": validity,
        "quality": quality,
        "anomalies": anomalies,
        "limitations": limitations,
        "files": files,
    }


def _comment_wrap(prefix: str, text: str, width: int = 120) -> list[str]:
    """Wrap a long header paragraph into readable CSV comment lines."""
    words = str(text).split()
    if not words:
        return [prefix.rstrip()]
    lines = []
    current = prefix
    for word in words:
        candidate = current + word if current == prefix else current + " " + word
        if len(candidate) > width and current != prefix:
            lines.append(current)
            current = "#   " + word
        else:
            current = candidate
    lines.append(current)
    return lines


def header_lines(header: dict) -> list[str]:
    """Render the table header as CSV comment lines."""
    out = [f"# {header['title']}", "#"]
    out.append("# Identification")
    for label, value in header["identification"]:
        out.append(f"#   {label}: {value}")
    out.append("#")
    out.append("# Adopted shell")
    for label, value in header["shell"]:
        out.append(f"#   {label}: {value}")
    out.append("#")
    for label, text in (
        ("Datum", header["datum"]),
        ("Basis", header["basis"]),
        ("Uncertainty", header["uncertainty"]),
    ):
        out.extend(_comment_wrap(f"# {label}: ", text))
    out.append("#")
    out.append("# Validity")
    for region, span, status in header["validity"]:
        out.append(f"#   {region}: {span} — {status}")
    out.append("#")
    out.append("# Quality")
    for label, value in header["quality"]:
        out.append(f"#   {label}: {value}")
    out.append("#")
    out.append("# Anomalies")
    for kind, where, effect in header["anomalies"]:
        out.append(f"#   {kind} | {where} | {effect}")
    out.append("#")
    out.append("# Limitations")
    for line in header["limitations"]:
        out.append(f"#   - {line}")
    out.append("#")
    out.append("# Files: " + ", ".join(header["files"]))
    out.append("# ---")
    return out


def write_csv(
    path: str | Path,
    rows: list[dict],
    fieldnames: list[str] | None = None,
    header: dict | None = None,
) -> None:
    path = Path(path)
    if not rows:
        path.write_text(
            "\n".join(header_lines(header)) + "\n" if header else "",
            encoding="utf-8",
        )
        return
    names = fieldnames or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as fh:
        if header:
            for line in header_lines(header):
                fh.write(line + "\n")
        writer = csv.DictWriter(fh, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in names})


def write_text(path: str | Path, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")

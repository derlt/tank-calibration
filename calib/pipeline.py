"""End-to-end pipeline: raw file to every deliverable of §11."""

from __future__ import annotations

import json
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from . import charts, diagnostics, report, unknowns
from .blocking import block_intervals, blocking_report
from .config import Config, load_config
from .data import (
    Interval,
    Step,
    apply_corrections,
    build_intervals,
    mark_trusted,
    read_raw,
    write_corrected,
)
from .fit import (
    FitResult,
    empty_start_check,
    fit_constrained,
    fit_difference,
    gls_fit,
    lock_cost,
    overflow_direction,
    parametric_bootstrap,
    profile_param,
    profile_r,
    tilt_test,
)
from .geometry import Shell
from .quantized import quantized_pour_search
from .workbook import build_workbook


def _band_with_displacement(bands: list[dict], intervals: list[Interval]) -> list[dict]:
    out = []
    for band in bands:
        item = dict(band)
        item["displacement"] = diagnostics.band_displacement(band, intervals)
        out.append(item)
    return out


def _resolve_overflow(
    cfg: Config,
    rows,
    intervals: list[Interval],
    shell: Shell,
) -> tuple[list, list[Interval], dict | None]:
    """Apply §5.3a's second direction: an overflow pour is a claim, not data."""
    if cfg.overflow_pour is None:
        return rows, intervals, None
    overflow = [iv for iv in intervals if iv.h_cur > shell.brim()]
    if not overflow:
        return rows, intervals, None
    iv = overflow[-1]
    info = overflow_direction(shell, iv.h_prev, cfg.overflow_pour, cfg.vent_volume)
    info["h_last"] = iv.h_prev
    info["h_overflow"] = iv.h_cur
    if info["could_fill"]:
        return rows, intervals, info
    # The pour cannot fill the gap: back-predict x = G and treat the row as unknown.
    row = rows[iv.row]
    row.flags.append(
        f"pour treated as unknown: recorded {cfg.overflow_pour:g} L cannot fill "
        f"G={info['gap']:.1f} L (§5.3a)"
    )
    row.step = Step("unknown", raw="?")
    new_intervals = build_intervals(rows)
    info["back_predicted"] = info["gap"]
    info["action"] = "row pour replaced by unknown; height kept"
    return rows, new_intervals, info


def run(config_path: str | Path, outdir: str | Path, *, make_charts: bool = True) -> dict:
    cfg = load_config(config_path)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    raw_rows = read_raw(cfg.raw)
    rows = apply_corrections(raw_rows, cfg.corrections)
    intervals = build_intervals(rows)

    brim = cfg.brim_reading if cfg.brim_reading is not None else (
        cfg.h0_value + 2.0 * cfg.nominal_r
    )
    mark_trusted(intervals, brim=brim, object_bands=cfg.object_bands, excluded_rows=cfg.excluded_interval_rows)

    # -- pass 1: free fit on the nominal brim --------------------------
    free = fit_difference(
        intervals, cfg.nominal,
        h0_mode=cfg.h0_mode, h0_value=cfg.h0_value,
        multistart=True,
    )

    # -- object displacement from the first residuals -----------------
    diagnostics.apply_model(
        intervals, free.shell,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
    )
    bands = _band_with_displacement(cfg.object_bands, intervals)

    # -- refine the brim from the fit, then refit ---------------------
    if cfg.brim_reading is None:
        brim = free.shell.brim()
        mark_trusted(intervals, brim=brim, object_bands=cfg.object_bands, excluded_rows=cfg.excluded_interval_rows)
        free = fit_difference(
            intervals, cfg.nominal,
            h0_mode=cfg.h0_mode, h0_value=cfg.h0_value,
            multistart=True,
        )

    # -- overflow consistency -----------------------------------------
    rows, intervals, overflow = _resolve_overflow(cfg, rows, intervals, free.shell)
    if overflow and overflow.get("action"):
        mark_trusted(intervals, brim=brim, object_bands=cfg.object_bands, excluded_rows=cfg.excluded_interval_rows)
        free = fit_difference(
            intervals, cfg.nominal,
            h0_mode=cfg.h0_mode, h0_value=cfg.h0_value,
            multistart=True,
        )
        diagnostics.apply_model(
            intervals, free.shell,
            sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
        )
        bands = _band_with_displacement(cfg.object_bands, intervals)

    # -- Huber comparison (§5.2) --------------------------------------
    resid_scale = float(np.median([
        abs(iv.resid) for iv in intervals if iv.known and math.isfinite(iv.resid)
    ]))
    sigma_scale = float(np.median([
        iv.sigma for iv in intervals if iv.trusted and math.isfinite(iv.sigma)
    ]))
    f_scale = max(resid_scale, sigma_scale)
    huber = fit_difference(
        intervals, cfg.nominal,
        loss="huber", f_scale=f_scale,
        h0_mode=cfg.h0_mode, h0_value=cfg.h0_value,
        multistart=True,
    )

    # -- constrained fit (§5.3a) --------------------------------------
    constraint = {
        "status": "not applicable",
        "gap": None,
        "pour": cfg.overflow_pour,
        "note": "no overflow pour recorded",
        "neck_status": "not tested",
        "neck_note": "",
    }
    adopted = free
    constrained = None
    if cfg.overflow_pour is not None:
        constrained = fit_constrained(
            intervals, cfg.nominal,
            start=free,
            gap_pour=cfg.overflow_pour,
            brim_reading=cfg.brim_reading,
            neck=cfg.neck_equality,
            h0_mode=cfg.h0_mode,
            h0_value=cfg.h0_value,
        )
        h_star = max(iv.h_cur for iv in intervals if iv.trusted)
        free_gap = free.shell.capacity() - float(free.shell.volume(h_star))
        violates = free_gap > cfg.overflow_pour - cfg.vent_volume
        if constrained.binding or violates:
            adopted = constrained
            status = "binding" if constrained.binding else "violated by free fit: constrained adopted"
        else:
            status = "slack: free fit adopted"
        constraint = {
            "status": status,
            "gap": constrained.gap,
            "pour": cfg.overflow_pour,
            "note": f"free-fit gap {free_gap:.1f} L vs pour {cfg.overflow_pour:.1f} L",
            "neck_status": (
                "residual "
                + f"{constrained.neck_resid:+.2f} mm"
                if constrained.neck_resid is not None
                else "not tested"
            ),
            "neck_note": (
                "2r + h0 = B; the reading anchors the r-h0 trade (§5.3a)"
                if constrained.neck_resid is not None
                else ""
            ),
        }

    # -- identifiability (§5.5) ---------------------------------------
    profile = profile_r(intervals, cfg.nominal, adopted, h0_mode=cfg.h0_mode)
    profile_l = profile_param(
        intervals, cfg.nominal, adopted, name="L", span=50.0, step=5.0,
        h0_mode=cfg.h0_mode,
    )
    lock = lock_cost(intervals, cfg.nominal, adopted) if cfg.h0_mode == "fit" else None
    tilt = tilt_test(intervals, cfg.nominal, adopted) if cfg.tilt_test else {
        "shell": adopted.shell, "rmse": adopted.rmse, "delta_rmse": 0.0,
        "eps": 0.0, "f": 0.0, "p": 1.0, "plausible": True, "keep": False,
    }

    # -- uncertainty ---------------------------------------------------
    bootstrap = parametric_bootstrap(
        intervals, adopted,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
        n=cfg.bootstrap_n, seed=cfg.seed, h0_mode=cfg.h0_mode,
    )
    gls = gls_fit(
        intervals, cfg.nominal,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
        h0_mode=cfg.h0_mode,
    )

    # -- model, anomalies ---------------------------------------------
    diagnostics.apply_model(
        intervals, adopted.shell,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
    )
    bands = _band_with_displacement(cfg.object_bands, intervals)
    pairs = diagnostics.find_pairs(intervals, adopted.shell)
    singles = diagnostics.single_sided(intervals, pairs)
    watch = diagnostics.watch_items(intervals)

    # -- unknowns (§8) -------------------------------------------------
    unknown_ivs = [
        iv for iv in intervals
        if not iv.known and iv.h_cur <= adopted.shell.brim()
    ]
    estimates = unknowns.estimate_unknowns(
        intervals, adopted.shell,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
        bands=bands,
    )
    battery = unknowns.sensitivity_battery(
        intervals, cfg.nominal, unknown_ivs,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
        h0_mode=cfg.h0_mode,
        joint=None,
        suspect_rows={iv.row for iv in singles},
        bands=bands,
    )
    estimates = unknowns.widen_unknowns(estimates, battery)

    # -- audit numbers -------------------------------------------------
    heel = float(rows[0].step.value) if (cfg.heel_row and rows[0].step.known) else 0.0
    closure = diagnostics.closure(
        intervals, adopted.shell, bands,
        heel=heel, sigma_h=cfg.sigma_h,
        rel=cfg.pour_rel, abs_=cfg.pour_abs,
        estimates=estimates,
    )
    qa = report.qa_agreement(
        intervals, adopted.shell, bands=bands, heel=heel, estimates=estimates,
    )
    empty = empty_start_check(rows, adopted.shell, cfg.heel_row)
    mean_m = float(np.mean([iv.m for iv in intervals if iv.trusted]))
    sanity = diagnostics.sanity_rmse(adopted.rmse, mean_m, cfg.sigma_h)
    noise = diagnostics.noise_split(intervals)
    telescoping = diagnostics.telescoping_blocks(
        intervals, adopted.shell,
        sigma_h=cfg.sigma_h, rel=cfg.pour_rel, abs_=cfg.pour_abs,
    )
    multi = diagnostics.multiple_comparisons(intervals)
    drift = diagnostics.classify_drift(intervals)
    scatter = diagnostics.pair_scatter(intervals)

    quantized = []
    if cfg.pour_unit:
        for iv in singles:
            q = quantized_pour_search(
                intervals, adopted.shell, iv,
                pour_unit=cfg.pour_unit, sigma_h=cfg.sigma_h,
                rel=cfg.pour_rel, abs_=cfg.pour_abs,
            )
            if q.get("ok"):
                quantized.append(q)

    lag = []
    for item in cfg.lag_checks:
        readings = [(float(r[0]), float(r[1])) for r in item.get("readings", [])]
        lag.append({"at_mm": item.get("at_mm"), **diagnostics.lag_check(readings)})

    blocking = None
    if cfg.blocking.get("enabled"):
        blocks = block_intervals(
            intervals, sigma_h=cfg.sigma_h,
            target_rise_mm=cfg.blocking.get("target_rise_mm"),
        )
        bfit = fit_difference(
            blocks, cfg.nominal, h0_mode=cfg.h0_mode, h0_value=cfg.h0_value,
        )
        blocking = {
            "stats": blocking_report(blocks, cfg.sigma_h),
            "fit": bfit,
            "delta_r": bfit.shell.r - adopted.shell.r,
            "delta_L": bfit.shell.L - adopted.shell.L,
            "delta_h0": bfit.shell.h0 - adopted.shell.h0,
        }

    # -- acceptance (§5.7) ---------------------------------------------
    constraint_ok = True
    if constrained is not None:
        constraint_ok = (
            -1e-3 <= constrained.gap <= cfg.overflow_pour + 1e-3
        )
    acceptance = _acceptance(
        free, huber, profile, profile_l, bootstrap, closure, sanity,
        intervals, pairs, singles, bands, battery, constraint_ok, constraint,
    )

    # -- deliverables ---------------------------------------------------
    lowest = min(iv.h_cur for iv in intervals if iv.trusted)
    strapping = report.strapping_table(
        adopted.shell, adopted,
        bands=bands, lowest_verified=lowest,
        step_mm=float(cfg.strapping.get("step_mm", 10.0)),
        sigma_h=cfg.sigma_h,
        start_mm=float(cfg.strapping.get("start_mm", 0.0)),
    )
    accepted = all(c["pass"] for c in acceptance)
    commercial = report.commercial_chart(
        adopted.shell, bands=bands, lowest_verified=lowest,
        step_mm=float(cfg.strapping.get("step_mm", 10.0)),
        start_mm=float(cfg.strapping.get("start_mm", 0.0)),
        shell_accepted=accepted,
    )
    register = report.anomaly_register(
        bands=bands, pairs=pairs, singles=singles, watch=watch,
        unknowns=estimates, corrections=cfg.corrections,
        quantized=quantized,
    )
    if overflow and overflow.get("back_predicted") is not None:
        register.append(
            {
                "kind": "overflow back-prediction",
                "where_mm": f"{overflow.get('h_last', 0):.0f}",
                "magnitude_l": overflow["back_predicted"],
                "rule": "5.3a",
                "status": (
                    f"recorded pour {overflow['pour']:.1f} L cannot fill "
                    f"G={overflow['gap']:.1f} L; height is data, pour is a claim"
                ),
                "test": "re-dip the brim; confirm the vent volume",
            }
        )

    def _unknown_label(u):
        body = (
            f"{u['base']:g} + {u['x']:.1f}"
            if u.get("base")
            else f"{u['x']:.1f}"
        )
        return f"{body} ± {2 * u['sigma']:.1f} L at {u['to_mm']:.0f} mm"

    unknown_text = "; ".join(_unknown_label(u) for u in estimates) or "none"
    max_liq = diagnostics.max_liquid(adopted.shell, bands)
    record = report.shell_record(
        tank=cfg.tank,
        fit=adopted,
        sigma_h=cfg.sigma_h,
        brim=adopted.shell.brim(),
        max_liquid_l=max_liq,
        heel_l=float(rows[0].step.value) if (cfg.heel_row and rows[0].step.known) else 0.0,
        heel_kind="sounded" if (cfg.heel_row and rows[0].step.known) else "not sounded",
        datum=report.datum_statement(
            adopted.shell, h0_mode=cfg.h0_mode, lock=lock,
            v0=float(adopted.shell.volume(0.0)),
        ),
        constraint=f"{constraint['status']}"
        + (f" at G = {constraint['gap']:.1f} L" if constraint["gap"] is not None else ""),
        blocked=sum(float(b.get("displacement", 0.0)) for b in bands),
        corrected_dips=sum(1 for c in cfg.corrections if c.field == "height"),
        watch_count=len(watch),
        unknown_text=unknown_text,
        authoritative=f"{cfg.tank}_strapping.csv",
        rmse_mm=sanity["rmse_mm"],
        r_sigma=(profile["hi"] - profile["lo"]) / 2.0,
        l_sigma=(profile_l["hi"] - profile_l["lo"]) / 2.0,
    )

    result = {
        "config": cfg,
        "rows": rows,
        "raw_rows": raw_rows,
        "intervals": intervals,
        "fit": adopted,
        "free_fit": free,
        "huber": huber,
        "constrained": constrained,
        "constraint": constraint,
        "profile": profile,
        "profile_L": profile_l,
        "lock": lock,
        "tilt": tilt,
        "bootstrap": bootstrap,
        "gls": {
            "r": gls.param_sigma("r"),
            "L": gls.param_sigma("L"),
            "h0": gls.param_sigma("h0"),
        },
        "bands": bands,
        "pairs": pairs,
        "singles": singles,
        "watch": watch,
        "unknowns": estimates,
        "battery": battery,
        "closure": closure,
        "qa": qa,
        "empty_start": empty,
        "sanity": sanity,
        "noise_split": noise,
        "telescoping": telescoping,
        "multi": multi,
        "drift": drift,
        "pair_scatter": scatter,
        "quantized": quantized,
        "lag": lag,
        "blocking": blocking,
        "accepted": accepted,
        "acceptance": acceptance,
        "strapping": strapping,
        "commercial": commercial,
        "register": register,
        "shell_record": record,
        "rmse_mm": sanity["rmse_mm"],
        "brim": adopted.shell.brim(),
        "lowest_verified": lowest,
        "overflow": overflow,
    }

    invariance = None
    if cfg.corrections:
        try:
            raw_ivs = build_intervals(raw_rows)
            mark_trusted(
                raw_ivs, brim=brim, object_bands=cfg.object_bands,
                excluded_rows=cfg.excluded_interval_rows,
            )
            raw_fit = fit_difference(
                raw_ivs, cfg.nominal, h0_mode=cfg.h0_mode,
                h0_value=cfg.h0_value, multistart=False,
                x0={"r": adopted.shell.r, "L": adopted.shell.L, "h0": adopted.shell.h0},
            )
            invariance = {
                "r": raw_fit.shell.r - adopted.shell.r,
                "L": raw_fit.shell.L - adopted.shell.L,
                "h0": raw_fit.shell.h0 - adopted.shell.h0,
                "rmse": raw_fit.rmse - adopted.rmse,
                "moves_conclusion": bool(
                    abs(raw_fit.shell.r - adopted.shell.r)
                    > max((profile["hi"] - profile["lo"]) / 2.0, 1.0)
                ),
            }
        except Exception:  # the check is optional
            invariance = None

    result["correction_invariance"] = invariance

    if make_charts:
        result["charts"] = charts.all_charts(
            outdir / "charts",
            shell=adopted.shell,
            rows=rows,
            intervals=intervals,
            heel_row=cfg.heel_row,
            bands=bands,
            profile=profile,
        )
    else:
        result["charts"] = {}

    _write_artifacts(outdir, result)
    return result


def _acceptance(
    free: FitResult,
    huber: FitResult,
    profile: dict,
    profile_l: dict,
    bootstrap: dict,
    closure: dict,
    sanity: dict,
    intervals: list[Interval],
    pairs: list,
    singles: list[Interval],
    bands: list[dict],
    battery: dict,
    constraint_ok: bool,
    constraint: dict,
) -> list[dict]:
    checks = []

    ratio = sanity["ratio"]
    checks.append(
        {
            "check": "RMSE in mm-equivalent near sqrt(2) sigma_h",
            "result": f"{sanity['rmse_mm']:.2f} mm vs {sanity['target_mm']:.2f} mm (ratio {ratio:.2f})",
            "pass": 0.5 <= ratio <= 1.6,
            "detail": sanity["verdict"],
        }
    )

    candidates = [iv for iv in intervals if iv.flag == "candidate"]
    in_bands = [
        iv for iv in candidates
        if any(float(b["low"]) <= iv.h_cur <= float(b["high"]) for b in bands)
    ]
    disposition = set()
    for p in pairs:
        disposition.add(id(p.first))
        disposition.add(id(p.second))
    for iv in singles:
        disposition.add(id(iv))
    for iv in in_bands:
        disposition.add(id(iv))
    classified = len({id(iv) for iv in candidates} & disposition)
    checks.append(
        {
            "check": "every action-bar residual classified",
            "result": f"{len(candidates)} candidates; {classified} dispositions",
            "pass": classified >= len(candidates),
            "detail": "pair, single-sided, object band, or unknown pour",
        }
    )

    checks.append(
        {
            "check": "physical constraints satisfied and reported",
            "result": (
                constraint["status"]
                + (f" at G = {constraint['gap']:.1f} L" if constraint["gap"] is not None else "")
            ),
            "pass": bool(constraint_ok),
            "detail": "G <= P and G >= 0 enforced inside the fit; binding reported",
        }
    )

    checks.append(
        {
            "check": "closure identity within 3 sigma sqrt(n)",
            "result": f"diff {closure['diff']:+.1f} L, limit {closure['limit']:.1f} L",
            "pass": bool(closure["ok"]),
            "detail": "heel + poured + blocked vs F(H)",
        }
    )

    checks.append(
        {
            "check": "sensitivity battery moves no conclusion",
            "result": (
                f"{len(battery['runs'])} fits; "
                + ("unknowns settled" if battery["settled"] else "unknown range exceeds dip noise")
            ),
            "pass": bool(battery["settled"]),
            "detail": "range of every unknown compared with the level-noise term",
        }
    )

    tol_r = max((profile["hi"] - profile["lo"]) / 2.0, bootstrap["r"]["sd"] or 0.0)
    tol_l = max((profile_l["hi"] - profile_l["lo"]) / 2.0, bootstrap["L"]["sd"] or 0.0)
    # The loss comparison runs on the same (unconstrained) footing (§5.2).
    dr = abs(huber.shell.r - free.shell.r)
    dl = abs(huber.shell.L - free.shell.L)
    checks.append(
        {
            "check": "linear and Huber losses agree within uncertainty",
            "result": f"dr {dr:.2f} mm (tol {tol_r:.2f}), dL {dl:.2f} mm (tol {tol_l:.2f})",
            "pass": dr <= tol_r and dl <= tol_l,
            "detail": "adopt the linear fit unless Huber moves a parameter beyond its profile",
        }
    )
    return checks


def _write_artifacts(outdir: Path, result: dict) -> None:
    cfg: Config = result["config"]
    tank = cfg.tank

    # Raw: a byte copy only.  The source file is never touched (§1.1).
    shutil.copyfile(cfg.raw, outdir / f"{tank}_raw.csv")
    write_corrected(outdir / f"{tank}_corrected.csv", result["rows"])

    report.write_csv(outdir / f"{tank}_strapping.csv", result["strapping"])
    report.write_csv(outdir / f"{tank}_commercial.csv", result["commercial"])
    report.write_csv(outdir / f"{tank}_anomaly_register.csv", result["register"])
    report.write_text(outdir / f"{tank}_shell_record.txt", result["shell_record"])

    presets = {
        "tank": tank,
        "adopted": {
            "r": result["fit"].shell.r,
            "L": result["fit"].shell.L,
            "h0": result["fit"].shell.h0,
            "brim": result["fit"].shell.brim(),
            "capacity": result["fit"].shell.capacity(),
        },
        "noise": {
            "sigma_h": cfg.sigma_h,
            "pour_rel": cfg.pour_rel,
            "pour_abs": cfg.pour_abs,
        },
        "bands": result["bands"],
        "constraint": result["constraint"],
        "authoritative_file": f"{tank}_strapping.csv",
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (outdir / f"{tank}_presets.json").write_text(
        json.dumps(presets, indent=2), encoding="utf-8"
    )

    build_workbook(outdir / f"{tank}_workbook.xlsx", result, audit_sheet=True)
    (outdir / f"{tank}_report.md").write_text(_markdown(result), encoding="utf-8")


def _markdown(result: dict) -> str:
    cfg: Config = result["config"]
    checks = result["acceptance"]
    lines = [
        f"# {cfg.tank} — calibration report",
        "",
        "```",
        result["shell_record"].rstrip(),
        "```",
        "",
        "## Acceptance (§5.7)",
        "",
        "| # | Check | Result | Pass |",
        "|---|---|---|---|",
    ]
    for i, c in enumerate(checks, start=1):
        lines.append(f"| {i} | {c['check']} | {c['result']} | {'yes' if c['pass'] else 'NO'} |")
    lines += [
        "",
        "## Unknown pours (§8)",
        "",
        "| interval | at (mm) | known base (L) | total (L) | ±2σ (L) | settled |",
        "|---|---|---|---|---|---|",
    ]
    for u in result["unknowns"]:
        lines.append(
            f"| {u['interval']} | {u['to_mm']:.0f} | {u.get('base', 0):g} | "
            f"{u.get('total', u['x']):.1f} | {2 * u['sigma']:.1f} | "
            f"{'yes' if u.get('settled', True) else 'no'} |"
        )
    lines += [
        "",
        "## Anomaly register",
        "",
        "| kind | where | magnitude (L) | rule | status |",
        "|---|---|---|---|---|",
    ]
    for item in result["register"]:
        lines.append(
            f"| {item['kind']} | {item['where_mm']} | {item['magnitude_l']:.1f} | "
            f"{item['rule']} | {item['status']} |"
        )
    lines += [
        "",
        "## Limitations (§12)",
        "",
        "- Static tilt: " + (
            ("tested and kept" if result["tilt"]["keep"] else "tested and not kept")
            if cfg.tilt_test
            else "not tested (recorded as a limitation)"
        ),
        "- Tape scale: unidentifiable from pour/level data; the volume table is invariant.",
        "- Object vs pour error: not separable from one pass.",
        "- Ovality and bulging: r is an effective mean.",
        "- Bottom shape: h0 absorbs part of it; the heel is an estimate unless sounded.",
        "",
    ]
    return "\n".join(lines)

"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .data import apply_corrections, build_intervals, mark_trusted, read_raw
from .field import FieldValidator
from .fit import fit_difference, fit_joint
from .formula_gate import gate_workbook
from .geometry import Shell
from .pipeline import run
from .scaffold import infer_config, preflight, tank_stem, write_config


def _cmd_fit(args) -> int:
    out = args.out or str(Path(args.config).with_suffix("")) + "_out"
    result = run(args.config, out, make_charts=not args.no_charts)
    print(result["shell_record"])
    print(f"artifacts: {Path(out).resolve()}")
    for c in result["acceptance"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['check']}: {c['result']}")
    gate = result.get("gate")
    if gate:
        print(f"  formula gate: {gate['formulas']} formulas, {len(gate['errors'])} problems")
    accepted = all(c["pass"] for c in result["acceptance"])
    gated = not gate or gate["ok"]
    return 0 if accepted and gated else 2


def _load_presets(path: str) -> tuple[Shell, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    a = data["adopted"]
    shell = Shell(float(a["r"]), float(a["L"]), float(a["h0"]))
    return shell, data


def _parse_pour_line(line: str) -> tuple[float | None, float] | None:
    """Parse one 'step,height' entry.  None means: not readable, try again.

    A blank step is an unknown pour.  Semicolons are accepted as separators.
    """
    parts = [p.strip() for p in line.replace(";", ",").split(",")]
    if len(parts) < 2 or not parts[1]:
        return None
    try:
        step = None if parts[0] in ("", "?", "x") else float(parts[0])
        h = float(parts[1])
    except ValueError:
        return None
    return step, h


def _cmd_init(args) -> int:
    raw = Path(args.raw)
    if not raw.exists():
        raise ValueError(f"raw file not found: {raw}")

    r, L = args.r, args.L
    if args.interactive and (r is None or L is None):
        if r is None:
            r = float(input("internal radius r, mm: ").strip())
        if L is None:
            L = float(input("internal shell length L, mm: ").strip())
    if r is None or L is None:
        raise ValueError(
            "give --r and --L (internal radius and length, mm), or use --interactive"
        )

    tank = args.tank
    site = args.site
    sigma_h = args.sigma_h
    unit = args.pour_unit
    brim = args.brim
    overflow = args.overflow_pour
    heel = args.heel

    if args.interactive:
        base, _ = infer_config(
            raw, r=r, L=L, tank=tank, site=site, sigma_h=sigma_h
        )
        tank = input(f"tank name [{base['tank']}]: ").strip() or base["tank"]
        sigma_h = _ask_float("dip sigma_h, mm", sigma_h)
        unit = _ask_float("pour unit, L (blank = inferred)", base.get("pour_unit"))
        brim = _ask_float("brim reading, mm (blank = fit refines it)", brim)
        overflow = _ask_float(
            "overflow pour, L (blank = inferred)",
            base.get("brim", {}).get("overflow_pour"),
        )
        site = input(f"site [{site}]: ").strip() or site
        heel = _ask_bool("first row is a heel", base["heel_row"])

    data, warnings = infer_config(
        raw,
        r=r,
        L=L,
        tank=tank,
        site=site,
        sigma_h=sigma_h,
        pour_unit=unit,
        brim=brim,
        overflow_pour=overflow,
        heel_row=heel,
    )
    out = Path(args.out) if args.out else raw.with_name(tank_stem(raw) + ".json")
    write_config(out, data, force=args.force, raw_path=raw)
    cfg = load_config(out)

    print(f"wrote {out}")
    print(f"  tank      {cfg.tank}")
    print(f"  raw       {cfg.raw}")
    print(f"  nominal   r={cfg.nominal_r:g} L={cfg.nominal_L:g} mm")
    print(f"  sigma_h   {cfg.sigma_h:g} mm")
    if cfg.pour_unit:
        print(f"  pour_unit {cfg.pour_unit:g} L")
    if cfg.brim_reading is not None:
        print(f"  brim      {cfg.brim_reading:g} mm")
    if cfg.overflow_pour is not None:
        print(f"  overflow  {cfg.overflow_pour:g} L")
    if cfg.heel_row:
        print("  heel_row  true")
    if warnings:
        print("warnings:")
        for w in warnings:
            print(f"  - {w}")
    outdir = out.parent / f"{cfg.tank}_out"
    print(f"\nnext: calib fit {out} -o {outdir}")
    return 0


def _cmd_check(args) -> int:
    report = preflight(args.config)
    cfg = report["config"]
    print(f"{args.config}")
    print(f"  tank       {cfg.tank}")
    print(f"  raw        {cfg.raw} ({report['rows']} rows)")
    print(f"  nominal    r={cfg.nominal_r:g} L={cfg.nominal_L:g} mm")
    print(f"  sigma_h    {cfg.sigma_h:g} mm")
    print(f"  pour_unit  {f'{cfg.pour_unit:g} L' if cfg.pour_unit else 'not set'}")
    h0 = cfg.h0_mode if cfg.h0_mode == "fit" else f"locked at {cfg.h0_value:g} mm"
    print(f"  h0         {h0}")
    brim = (
        f"{cfg.brim_reading:g} mm"
        if cfg.brim_reading is not None
        else f"from the fit ({report['brim']:g} mm nominal)"
    )
    print(f"  brim       {brim}")
    print(f"  bootstrap  {cfg.bootstrap_n} draws, seed {cfg.seed}")
    print()
    print(f"intervals: {report['trusted']} trusted of {report['intervals']}")
    for item in report["untrusted"]:
        print(f"  row {item['row']:>3}  {item['reason']}")
    if cfg.excluded_rows:
        rows = ", ".join(str(r) for r in sorted(cfg.excluded_rows))
        print(f"excluded rows: {rows}")
    if report["unknown_pours"]:
        print(f"unknown pours: {len(report['unknown_pours'])}")
        for item in report["unknown_pours"]:
            print(f"  row {item['row']:>3}  {item['raw']}")
    if report["corrections"]:
        print(f"corrections: {len(report['corrections'])}")
        for c in report["corrections"]:
            print(
                f"  row {c['row']:>3}  {c['field']} -> {c['value']:g}  "
                f"({c['rule']}, {c['magnitude']:+g})"
            )
    if report["warnings"]:
        print("warnings:")
        for w in report["warnings"]:
            print(f"  - {w}")
    if report["trusted"] == 0:
        print(
            "calib: error: no trusted intervals; the fit cannot run",
            file=sys.stderr,
        )
        return 2
    return 0


def _ask_float(prompt: str, default: float | None) -> float | None:
    shown = "" if default is None else f"{default:g}"
    text = input(f"{prompt} [{shown}]: ").strip()
    return default if not text else float(text)


def _ask_bool(prompt: str, default: bool) -> bool:
    shown = "Y/n" if default else "y/N"
    text = input(f"{prompt}? [{shown}]: ").strip().lower()
    if not text:
        return default
    return text in ("y", "yes", "true", "1")


def _cmd_field(args) -> int:
    shell, presets = _load_presets(args.presets)
    noise = presets.get("noise", {})
    validator = FieldValidator(
        shell,
        sigma_h=float(noise.get("sigma_h", 1.5)),
        rel=float(noise.get("pour_rel", 0.005)),
        abs_=float(noise.get("pour_abs", 3.0)),
        bands=presets.get("bands", []),
    )

    if args.interactive:
        print(f"Field check for {presets.get('tank', 'tank')} — shell r={shell.r:.1f} L={shell.L:.1f} h0={shell.h0:.1f}")
        print("Enter: step,height   (blank step = unknown pour).  q to quit.")
        h_prev = float(input("start height (mm): ").strip() or 0.0)
        validator.levels = [h_prev]
        # The tank already holds F(start); the closure counts it (§9.3).
        validator.heel = float(validator.shell.volume(h_prev))
        while True:
            line = input("pour: ").strip()
            if line.lower() in ("q", "quit", "exit", ""):
                break
            parsed = _parse_pour_line(line)
            if parsed is None:
                print(f"  cannot read {line!r}; enter: step,height   (q to quit)")
                continue
            step, h = parsed
            v = validator.check(step, h_prev, h)
            print(f"  {v.flag:10s} resid={v.resid if v.resid is None else round(v.resid, 1)} "
                  f"z={v.z if v.z is None else round(v.z, 1)}  {v.message}")
            if v.advice:
                print(f"  -> {v.advice}")
            h_prev = h
        s = validator.summary(validator.history)
        print(f"\ncounts: {s['counts']}")
        print(f"closure: {s['closure']}")
        for d in s["detector"]:
            print(f"detector: pair {d['i']}/{d['i'] + 1} z=({d['z1']:+.1f},{d['z2']:+.1f}) {d['kind']}")
        if s.get("advisor"):
            print(f"advisor: {s['advisor']['advice']}")
        return 1 if any(v.flag in ("ALARM", "DRIFT") for v in validator.history) else 0

    if not args.csv:
        print("field: give a CSV or --interactive", file=sys.stderr)
        return 2
    rows = read_raw(args.csv)
    verdicts = validator.run(rows)
    if args.json:
        print(json.dumps([v.__dict__ for v in verdicts], indent=2, default=str))
    else:
        print(f"{'row':>4} {'H (mm)':>8} {'step':>7} {'resid':>8} {'mm':>7} {'z':>6}  flag")
        for v in verdicts:
            step = "" if v.step is None else f"{v.step:.0f}"
            resid = "" if v.resid is None else f"{v.resid:+.1f}"
            mm = "" if v.mm is None else f"{v.mm:+.1f}"
            z = "" if v.z is None else f"{v.z:+.1f}"
            print(f"{v.row:>4} {v.h_cur:>8.0f} {step:>7} {resid:>8} {mm:>7} {z:>6}  {v.flag}")
            if v.advice:
                print(f"       -> {v.advice}")
        s = validator.summary(verdicts)
        print(f"\ncounts: {s['counts']}")
        print(f"closure: {s['closure']}")
        for d in s["detector"]:
            print(f"detector: pair {d['i']}/{d['i'] + 1} z=({d['z1']:+.1f},{d['z2']:+.1f}) {d['kind']}")
        if s.get("advisor"):
            print(f"advisor: {s['advisor']['advice']}")
    return 1 if any(v.flag in ("ALARM", "DRIFT") for v in verdicts) else 0


def _cmd_joint(args) -> int:
    """Fit one common r with separate lengths (§5.4)."""
    configs = [load_config(p) for p in args.configs]
    campaigns = []
    for cfg in configs:
        rows = apply_corrections(read_raw(cfg.raw), cfg.corrections)
        ivs = build_intervals(rows)
        brim = cfg.brim_reading if cfg.brim_reading is not None else cfg.h0_value + 2 * cfg.nominal_r
        mark_trusted(ivs, brim=brim, object_bands=cfg.object_bands, excluded_rows=cfg.excluded_interval_rows)
        if cfg.brim_reading is None:
            # Refine the brim from a free fit, exactly as the pipeline does,
            # so both tools trust the same intervals for the same tank.
            free = fit_difference(
                ivs, cfg.nominal, h0_mode=args.h0, h0_value=cfg.h0_value,
                multistart=True,
            )
            brim = free.shell.brim()
            mark_trusted(
                ivs, brim=brim, object_bands=cfg.object_bands,
                excluded_rows=cfg.excluded_interval_rows,
            )
        campaigns.append((ivs, cfg.nominal))

    joint = fit_joint(campaigns, common_r=True, h0_mode=args.h0)
    separate = [
        fit_difference(ivs, nom, h0_mode=args.h0, multistart=False)
        for ivs, nom in campaigns
    ]
    print(f"common r = {joint.shell.r:.2f} mm")
    for cfg, (_, _), f in zip(configs, campaigns, separate):
        print(f"  {cfg.tank:12s} L = {f.shell.L:8.2f} mm   RMSE {f.rmse:6.3f} L/step")
    print(f"joint RMSE {joint.rmse:.3f} L/step over {joint.n} intervals")
    penalty = joint.rmse - sum(f.rmse for f in separate) / len(separate)
    print(f"RMSE penalty {penalty:+.3f} L/step; adopt only if negligible")
    if args.json:
        print(json.dumps({
            "r": joint.shell.r,
            "lengths": joint.params.get("lengths"),
            "rmse": joint.rmse,
            "penalty": penalty,
        }, indent=2))
    return 0


def _cmd_gate(args) -> int:
    result = gate_workbook(args.workbook)
    print(f"{result['file']}: {result['formulas']} formulas, {len(result['errors'])} problems")
    for e in result["errors"][:50]:
        print(f"  {e['sheet']}!{e['cell']}: {e['problem']}  {e['formula']}")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="calib",
        description="Horizontal-tank calibration: fit, diagnostics, field check, workbook.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_fit = sub.add_parser("fit", help="run the full pipeline for one tank")
    p_fit.add_argument("config", help="campaign JSON")
    p_fit.add_argument("-o", "--out", help="output directory")
    p_fit.add_argument("--no-charts", action="store_true")
    p_fit.set_defaults(func=_cmd_fit)

    p_init = sub.add_parser("init", help="write a campaign JSON from a raw CSV")
    p_init.add_argument("raw", help="raw pour/level CSV")
    p_init.add_argument(
        "-o", "--out", help="output JSON (default: <tank>.json beside the CSV)"
    )
    p_init.add_argument("--r", type=float, help="internal radius, mm")
    p_init.add_argument("--L", type=float, help="internal shell length, mm")
    p_init.add_argument("--tank", help="tank name (default: CSV stem)")
    p_init.add_argument("--site", default="", help="site line for the certificate")
    p_init.add_argument(
        "--sigma-h", type=float, default=1.5, dest="sigma_h", help="dip sigma, mm"
    )
    p_init.add_argument(
        "--pour-unit", type=float, dest="pour_unit", help="pour increment, L"
    )
    p_init.add_argument("--brim", type=float, help="brim reading, mm")
    p_init.add_argument(
        "--overflow-pour", type=float, dest="overflow_pour", help="overflow pour, L"
    )
    p_init.add_argument(
        "--heel",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="the first row is a heel (default: infer)",
    )
    p_init.add_argument("--interactive", action="store_true")
    p_init.add_argument("--force", action="store_true", help="replace an existing JSON")
    p_init.set_defaults(func=_cmd_init)

    p_check = sub.add_parser("check", help="validate a campaign JSON without a fit")
    p_check.add_argument("config", help="campaign JSON")
    p_check.set_defaults(func=_cmd_check)

    p_field = sub.add_parser("field", help="validate pours against an adopted shell")
    p_field.add_argument("presets", help="*_presets.json written by fit")
    p_field.add_argument("csv", nargs="?", help="pour/level CSV")
    p_field.add_argument("--interactive", action="store_true")
    p_field.add_argument("--json", action="store_true")
    p_field.set_defaults(func=_cmd_field)

    p_joint = sub.add_parser("joint", help="fit one common r across tanks (§5.4)")
    p_joint.add_argument("configs", nargs="+", help="campaign JSON files")
    p_joint.add_argument("--h0", choices=["fit", "locked"], default="fit")
    p_joint.add_argument("--json", action="store_true")
    p_joint.set_defaults(func=_cmd_joint)

    p_gate = sub.add_parser("gate", help="run the formula gate on a workbook")
    p_gate.add_argument("workbook")
    p_gate.set_defaults(func=_cmd_gate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError, KeyError, IndexError, RuntimeError, EOFError) as exc:
        print(f"calib: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("calib: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

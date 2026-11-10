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


def _cmd_fit(args) -> int:
    out = args.out or str(Path(args.config).with_suffix("")) + "_out"
    result = run(args.config, out, make_charts=not args.no_charts)
    print(result["shell_record"])
    print(f"artifacts: {Path(out).resolve()}")
    for c in result["acceptance"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['check']}: {c['result']}")
    return 0 if all(c["pass"] for c in result["acceptance"]) else 2


def _load_presets(path: str) -> tuple[Shell, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    a = data["adopted"]
    shell = Shell(float(a["r"]), float(a["L"]), float(a["h0"]))
    return shell, data


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
        while True:
            line = input("pour: ").strip()
            if line.lower() in ("q", "quit", "exit", ""):
                break
            parts = [p.strip() for p in line.replace(";", ",").split(",")]
            step = None if parts[0] in ("", "?", "x") else float(parts[0])
            h = float(parts[1])
            v = validator.check(step, h_prev, h)
            print(f"  {v.flag:10s} resid={v.resid if v.resid is None else round(v.resid, 1)} "
                  f"z={v.z if v.z is None else round(v.z, 1)}  {v.message}")
            if v.advice:
                print(f"  -> {v.advice}")
            h_prev = h
        s = validator.summary(validator.history)
        print(f"\nclosure: {s['closure']}")
        return 0

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
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Unknown pours: back-prediction, one sigma formula, sensitivity battery (§8).

The unknown never enters the fit, so it cannot pull the geometry.  One
formula serves every unknown row.
"""

from __future__ import annotations

import math

import numpy as np

from .data import Interval
from .diagnostics import blocked_below
from .fit import fit_difference, fit_joint
from .geometry import Shell


def back_predict(
    shell: Shell,
    h_prev: float,
    h_cur: float,
    base: float = 0.0,
    bands: list[dict] | None = None,
) -> float:
    """x = F(H_i) - F(H_{i-1}) - known_base (§8.1).

    When the interval crosses a declared object band, the newly submerged
    displacement is not liquid and is removed (§6.3).
    """
    dv = float(shell.volume(h_cur) - shell.volume(h_prev))
    if bands:
        dv -= float(blocked_below(bands, h_cur)) - float(blocked_below(bands, h_prev))
    return dv - float(base)


def sigma_x(
    m: float,
    sigma_h: float,
    rel: float,
    base: float,
    abs_: float,
) -> float:
    """One uncertainty formula for every unknown (§8.2)."""
    return math.sqrt((math.sqrt(2.0) * m * sigma_h) ** 2 + (rel * base + abs_) ** 2)


def estimate_unknowns(
    intervals: list[Interval],
    shell: Shell,
    *,
    sigma_h: float,
    rel: float,
    abs_: float,
    bands: list[dict] | None = None,
) -> list[dict]:
    out = []
    brim = shell.brim()
    for iv in intervals:
        if iv.known or iv.h_cur > brim:
            # Above the brim the reading is vent-column height, not shell
            # level; §5.3a handles that row as an overflow, not an unknown.
            continue
        x = back_predict(shell, iv.h_prev, iv.h_cur, iv.base, bands)
        m = float(shell.slope(iv.h_cur))
        sx = sigma_x(m, sigma_h, rel, iv.base, abs_)
        out.append(
            {
                "interval": iv.idx,
                "row": iv.row + 1,
                "from_mm": iv.h_prev,
                "to_mm": iv.h_cur,
                "base": iv.base,
                "x": x,
                "total": x + iv.base,
                "sigma": sx,
                "lo": x - 2.0 * sx,
                "hi": x + 2.0 * sx,
                "kind": "partial" if iv.base else "unknown",
            }
        )
    return out


def sensitivity_battery(
    intervals: list[Interval],
    nominal: dict,
    unknowns: list[Interval],
    *,
    sigma_h: float,
    rel: float,
    abs_: float,
    h0_mode: str = "fit",
    joint: list[tuple[list[Interval], dict]] | None = None,
    suspect_rows: set[int] | None = None,
    bounds: dict | None = None,
    bands: list[dict] | None = None,
) -> dict:
    """Refit under the §8.3 battery and report the range of every unknown."""
    suspect_rows = suspect_rows or set()
    runs = []
    values: dict[int, list[float]] = {iv.idx: [] for iv in unknowns}

    for loss in ("linear", "huber"):
        for h0m in ("locked", "fit"):
            for r_mode in ("free", "common"):
                for exclude in (False, True):
                    if r_mode == "common" and not joint:
                        continue
                    data = list(intervals)
                    if exclude and suspect_rows:
                        data = [
                            iv for iv in data
                            if not (iv.trusted and iv.row in suspect_rows)
                        ]
                    try:
                        if r_mode == "common" and joint:
                            f = fit_joint(
                                [(data, nominal), *joint[1:]],
                                common_r=True,
                                h0_mode=h0m,
                                bounds=bounds,
                            )
                        else:
                            scale_resid = [
                                abs(iv.resid) for iv in data
                                if iv.known and math.isfinite(iv.resid)
                            ]
                            f = fit_difference(
                                data, nominal, loss=loss, h0_mode=h0m,
                                bounds=bounds, multistart=False,
                                f_scale=(
                                    float(np.median(scale_resid))
                                    if scale_resid else None
                                ),
                            )
                    except Exception:  # noqa: S112 - a failed battery run is skipped
                        continue
                    runs.append(
                        {
                            "loss": loss,
                            "h0": h0m,
                            "r": r_mode,
                            "exclude": exclude,
                            "params": dict(f.params),
                            "rmse": f.rmse,
                        }
                    )
                    for iv in unknowns:
                        values[iv.idx].append(
                            back_predict(f.shell, iv.h_prev, iv.h_cur, iv.base, bands)
                        )

    per_unknown = []
    for iv in unknowns:
        vals = values[iv.idx]
        if not vals:
            continue
        arr = np.array(vals)
        m = float(Shell(nominal["r"], nominal["L"], 0.0).slope(iv.h_cur))
        noise_term = math.sqrt(2.0) * m * sigma_h
        per_unknown.append(
            {
                "interval": iv.idx,
                "row": iv.row + 1,
                "min": float(arr.min()),
                "max": float(arr.max()),
                "range": float(arr.max() - arr.min()),
                "noise_term": noise_term,
                "settled": bool((arr.max() - arr.min()) <= noise_term),
                "n_runs": len(arr),
            }
        )

    rs = [r["params"].get("r") for r in runs if r["params"].get("r") is not None]
    ls = [r["params"].get("L") for r in runs if r["params"].get("L") is not None]
    return {
        "runs": runs,
        "per_unknown": per_unknown,
        "shell_spread": {
            "r": (min(rs), max(rs)) if rs else (float("nan"), float("nan")),
            "L": (min(ls), max(ls)) if ls else (float("nan"), float("nan")),
        },
        "settled": all(u["settled"] for u in per_unknown) if per_unknown else True,
    }


def widen_unknowns(estimates: list[dict], battery: dict) -> list[dict]:
    """Widen the formula sigma by the fit-shape spread (§8.2, §8.3)."""
    spread = {u["interval"]: u for u in battery.get("per_unknown", [])}
    out = []
    for est in estimates:
        item = dict(est)
        b = spread.get(est["interval"])
        if b:
            extra = b["range"] / 2.0
            item["sigma"] = math.sqrt(est["sigma"] ** 2 + extra ** 2)
            item["lo"] = item["x"] - 2.0 * item["sigma"]
            item["hi"] = item["x"] + 2.0 * item["sigma"]
            item["battery_range"] = b["range"]
            item["settled"] = b["settled"]
        out.append(item)
    return out

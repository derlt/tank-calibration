"""Quantized-pour grid search (§6.2, §3.10).

A single-sided residual has two live hypotheses: an object, or a
mis-recorded pour.  When pours live on a unit grid, searching that grid while
letting the shared dips move under a dip-noise prior decomposes a superposed
pour + dip error that the pair rule alone cannot.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import Interval
from .diagnostics import interval_sigma
from .geometry import Shell


@dataclass
class Candidate:
    units: int
    pour: float
    dip_prev_mm: float
    dip_cur_mm: float
    chi2: float
    resid: list[float]

    @property
    def penalty(self) -> float:
        return self.chi2


def quantized_pour_search(
    intervals: list[Interval],
    shell: Shell,
    suspect: Interval,
    *,
    pour_unit: float,
    sigma_h: float,
    rel: float,
    abs_: float,
    dip_span: float = 3.0,
    dip_step: float = 0.5,
    units: int = 4,
) -> dict:
    """Rank pour-on-grid and dip-shift combinations by penalised chi-square."""
    data = [iv for iv in intervals if iv.trusted]
    pos = next((k for k, iv in enumerate(data) if iv.idx == suspect.idx), None)
    if pos is None:
        return {"ok": False, "reason": "suspect interval is not trusted"}
    window = data[max(0, pos - 1): pos + 2]
    if suspect.s is None:
        return {"ok": False, "reason": "suspect pour is unknown, not mis-recorded"}

    shifts = np.arange(-dip_span, dip_span + 1e-9, dip_step)
    best: list[Candidate] = []
    baseline = None

    for k in range(-units, units + 1):
        pour = float(suspect.s) + k * pour_unit
        if pour <= 0:
            continue
        for d_prev in shifts:
            for d_cur in shifts:
                chi2 = 0.0
                resids = []
                for iv in window:
                    h_prev = iv.h_prev
                    h_cur = iv.h_cur
                    s = iv.s
                    if iv.idx == suspect.idx:
                        h_prev += d_prev
                        h_cur += d_cur
                        s = pour
                    elif iv.idx == suspect.idx - 1:
                        h_cur += d_prev
                    elif iv.idx == suspect.idx + 1:
                        h_prev += d_cur
                    pred = float(shell.volume(h_cur) - shell.volume(h_prev))
                    resid = float(s) - pred
                    m = float(shell.slope(h_cur))
                    sig = interval_sigma(m, float(s), sigma_h, rel, abs_)
                    chi2 += (resid / sig) ** 2 if sig > 0 else 0.0
                    resids.append(resid)
                chi2 += (d_prev / sigma_h) ** 2 + (d_cur / sigma_h) ** 2
                cand = Candidate(k, pour, float(d_prev), float(d_cur), chi2, resids)
                if k == 0 and d_prev == 0.0 and d_cur == 0.0:
                    baseline = cand
                best.append(cand)

    best.sort(key=lambda c: c.chi2)
    top = best[0]
    runner = best[1] if len(best) > 1 else None
    return {
        "ok": True,
        "interval": suspect.idx,
        "at_mm": suspect.h_cur,
        "unit": pour_unit,
        "best": top,
        "runner_up": runner,
        "baseline": baseline,
        "improvement": (
            baseline.chi2 - top.chi2 if baseline is not None else float("nan")
        ),
        "decisive": bool(
            runner is None or (runner.chi2 - top.chi2) >= 4.0
        ),
        "grid": {"dip_span_mm": dip_span, "dip_step_mm": dip_step, "units": units},
    }

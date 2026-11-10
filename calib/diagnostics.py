"""Residual diagnostics, anomaly classification and uncertainty audit (§6, §9).

One action bar for every tank.  One residual convention.  The residual
locates an error; the drift remembers it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from .data import Interval
from .geometry import Shell

ACTION_MM = 3.0
WATCH_MM = 1.5
ACTION_Z = 3.0
WATCH_Z = 2.0
PAIR_NET = 0.15


def classify(mm_equiv: float, z: float) -> str:
    """Action bar of §6: candidate, watch, or noise."""
    if abs(mm_equiv) >= ACTION_MM and abs(z) >= ACTION_Z:
        return "candidate"
    if abs(mm_equiv) >= WATCH_MM or abs(z) >= WATCH_Z:
        return "watch"
    return "ok"


def apply_model(
    intervals: list[Interval],
    shell: Shell,
    *,
    sigma_h: float,
    rel: float,
    abs_: float,
    books_start: float | None = None,
) -> None:
    """Fill pred, resid, slope, sigma, z, flag and drift on every interval.

    ``books_start`` is the liquid already on the books at the first level
    (§9.3).  The drift is anchored so that ``drift_k = books_k - F(H_k)``:
    it starts at the first pour's residual and carries an unknown pour at
    the shell's predicted rise for that interval (its residual is zero by
    construction, §8.1).  ``None`` keeps the plain running residual sum.
    """
    for iv in intervals:
        if not iv.known:
            iv.pred = float(shell.volume(iv.h_cur) - shell.volume(iv.h_prev))
            iv.resid = float("nan")
            iv.m = float(shell.slope(iv.h_cur))
            iv.mm_equiv = float("nan")
            iv.sigma = float("nan")
            iv.z = float("nan")
            iv.flag = "unknown pour"
            continue
        pred = float(shell.volume(iv.h_cur) - shell.volume(iv.h_prev))
        iv.pred = pred
        iv.resid = float(iv.s) - pred
        iv.m = float(shell.slope(iv.h_cur))
        iv.mm_equiv = iv.resid / iv.m if iv.m > 0 else float("nan")
        iv.sigma = interval_sigma(iv.m, iv.s, sigma_h, rel, abs_)
        iv.z = iv.resid / iv.sigma if iv.sigma > 0 else float("nan")
        iv.flag = classify(iv.mm_equiv, iv.z) if iv.trusted else (iv.reason or "excluded")

    anchor = 0.0
    if books_start is not None and intervals:
        anchor = books_start - float(shell.volume(intervals[0].h_prev))
    running = anchor
    for iv in intervals:
        if iv.known and math.isfinite(iv.resid):
            running += iv.resid
        # An unknown pour keeps the drift flat: back-prediction makes its
        # residual zero by construction, and a gap must not read as a leak.
        iv.drift = running


def interval_sigma(m: float, s: float, sigma_h: float, rel: float, abs_: float) -> float:
    """Per-interval sigma (§9.2): dip term plus pour term."""
    return math.sqrt((m * sigma_h * math.sqrt(2.0)) ** 2 + (rel * s + abs_) ** 2)


def residual_meaning(resid: float) -> str:
    """The two signs of §2, in one line each."""
    if resid < 0:
        return "rise too cheap: solid displaced liquid, or pour under-recorded"
    if resid > 0:
        return "rise too small: leak, film, trapped air, or pour over-recorded"
    return "no residual"


# ---------------------------------------------------------------------------
# Pair rule (§6.1)
# ---------------------------------------------------------------------------

@dataclass
class PairFinding:
    first: Interval
    second: Interval
    shared_height: float
    resid_first: float
    resid_second: float
    net: float
    net_ratio: float
    m: float
    delta_mm: float
    corrected_dip: float
    balanced: bool
    marginal: bool

    @property
    def actionable(self) -> bool:
        return self.balanced


def find_pairs(intervals: list[Interval], shell: Shell) -> list[PairFinding]:
    """Adjacent intervals with opposite, balanced, candidate residuals."""
    out: list[PairFinding] = []
    for a, b in pairwise(intervals):
        if not (a.trusted and b.trusted):
            continue
        if a.flag != "candidate" or b.flag != "candidate":
            continue
        if a.resid * b.resid >= 0:
            continue
        net = a.resid + b.resid
        total = abs(a.resid) + abs(b.resid)
        ratio = abs(net) / total if total else float("inf")
        m = float(shell.slope(a.h_cur))
        delta = (b.resid - a.resid) / (2.0 * m) if m > 0 else float("nan")
        out.append(
            PairFinding(
                first=a,
                second=b,
                shared_height=a.h_cur,
                resid_first=a.resid,
                resid_second=b.resid,
                net=net,
                net_ratio=ratio,
                m=m,
                delta_mm=delta,
                corrected_dip=a.h_cur - delta,
                balanced=ratio <= PAIR_NET,
                marginal=PAIR_NET < ratio <= 0.25,
            )
        )
    return out


def single_sided(intervals: list[Interval], pairs: list[PairFinding]) -> list[Interval]:
    """Candidates with no partner (§6.2)."""
    used = set()
    for p in pairs:
        used.add(id(p.first))
        used.add(id(p.second))
    return [iv for iv in intervals if iv.flag == "candidate" and id(iv) not in used]


def watch_items(intervals: list[Interval]) -> list[Interval]:
    """Isolated 1.5-3 mm items: recorded, never corrected (§6.5)."""
    return [iv for iv in intervals if iv.flag == "watch"]


# ---------------------------------------------------------------------------
# Object bookkeeping (§6.3)
# ---------------------------------------------------------------------------

def band_displacement(band: dict, intervals: list[Interval]) -> float:
    """Displacement in a declared band.

    If the band carries an explicit volume, use it.  Otherwise the net
    residual over the band is the displaced volume (a rise that came too
    cheap).  ``d`` is the displacement in that band, not necessarily the
    object's total volume (§6.3).
    """
    if band.get("litres") is not None:
        return float(band["litres"])
    lo, hi = float(band["low"]), float(band["high"])
    total = 0.0
    for iv in intervals:
        if not iv.known or not math.isfinite(iv.resid):
            continue
        if iv.h_cur >= lo and iv.h_prev <= hi:
            total += iv.resid
    return -total


def blocked_below(bands: list[dict], heights: np.ndarray | float) -> np.ndarray | float:
    """Sum of blocked volumes fully below each height."""
    heights = np.asarray(heights, dtype=float)
    total = np.zeros_like(heights)
    for band in bands:
        d = float(band.get("displacement", band.get("litres", 0.0)) or 0.0)
        total = total + np.where(heights >= float(band["high"]), d, 0.0)
    return float(total) if np.ndim(heights) == 0 else total


def blocked_above(bands: list[dict], heights: np.ndarray | float) -> np.ndarray | float:
    heights = np.asarray(heights, dtype=float)
    total = np.zeros_like(heights)
    for band in bands:
        d = float(band.get("displacement", band.get("litres", 0.0)) or 0.0)
        total = total + np.where(heights <= float(band["low"]), d, 0.0)
    return float(total) if np.ndim(heights) == 0 else total


def liquid_volume(shell: Shell, height: float, bands: list[dict]) -> float:
    """Liquid volume, with blocked volumes removed (§6.3)."""
    return float(shell.volume(height)) - float(blocked_below(bands, height))


def to_brim(shell: Shell, height: float, bands: list[dict]) -> float:
    return shell.capacity() - float(shell.volume(height)) - float(blocked_above(bands, height))


def max_liquid(shell: Shell, bands: list[dict]) -> float:
    return shell.capacity() - sum(
        float(b.get("displacement", b.get("litres", 0.0)) or 0.0) for b in bands
    )


# ---------------------------------------------------------------------------
# Closure (§9.3)
# ---------------------------------------------------------------------------

def closure(
    intervals: list[Interval],
    shell: Shell,
    bands: list[dict],
    *,
    books_start: float,
    start_sigma: float = 0.0,
    sigma_h: float,
    rel: float,
    abs_: float,
    estimates: list[dict] | None = None,
) -> dict:
    """books_start + sum poured + sum blocked below H versus F(H) (§9.3).

    ``books_start`` is the first row's pour: recorded when known,
    back-predicted ``F(H_0)`` when not.  Only liquid that entered the shell
    counts: overflow pours are excluded, and an unknown pour enters at its
    back-predicted value.
    """
    data = [iv for iv in intervals if iv.trusted]
    if not data:
        return {"lhs": 0.0, "rhs": 0.0, "diff": float("nan"), "sigma": float("nan"),
                "z": float("nan"), "limit": float("nan"), "ok": False, "n": 0}
    h_last = data[-1].h_cur
    poured = 0.0
    var = float(start_sigma) ** 2
    by_idx = {u["interval"]: u for u in (estimates or [])}
    n_unknown = 0
    n_known = 0
    # The books include every pour below H, trusted or not: trust is about
    # the fit, not about what was poured.
    for iv in intervals:
        if iv.h_cur > h_last:
            continue
        if iv.known:
            poured += float(iv.s)
            var += (rel * float(iv.s) + abs_) ** 2
            n_known += 1
            continue
        est = by_idx.get(iv.idx)
        if est is None:
            continue
        poured += float(est.get("total", est["x"]))
        var += float(est["sigma"]) ** 2
        n_unknown += 1
    blocked = float(blocked_below(bands, h_last))
    lhs = books_start + poured + blocked
    rhs = float(shell.volume(h_last))
    diff = lhs - rhs
    m = float(shell.slope(h_last))
    var += (m * sigma_h) ** 2
    sigma = math.sqrt(var)
    n = n_known + n_unknown
    return {
        "lhs": lhs,
        "rhs": rhs,
        "diff": diff,
        "sigma": sigma,
        "z": diff / sigma if sigma > 0 else float("nan"),
        "limit": 3.0 * sigma * math.sqrt(max(n, 1)),
        "ok": abs(diff) <= 3.0 * sigma * math.sqrt(max(n, 1)),
        "n": n,
        "h_last": h_last,
    }


def sanity_rmse(fit_rmse: float, mean_slope: float, sigma_h: float) -> dict:
    """RMSE in mm-equivalent should land near sqrt(2) * sigma_h (§9.4)."""
    mm = fit_rmse / mean_slope if mean_slope > 0 else float("nan")
    target = math.sqrt(2.0) * sigma_h
    ratio = mm / target if target > 0 else float("nan")
    verdict = "ok"
    if ratio > 1.5:
        verdict = "too large: find the structure before quoting"
    elif ratio < 0.6:
        verdict = "too small: sigma_h is over-conservative"
    return {"rmse_mm": mm, "target_mm": target, "ratio": ratio, "verdict": verdict}


# ---------------------------------------------------------------------------
# Noise split (§9.5)
# ---------------------------------------------------------------------------

def noise_split(intervals: list[Interval]) -> dict:
    """Split interval noise into dip and pour parts by lag-1 covariance.

    Adjacent residuals share a dip, so Cov(r_i, r_{i+1}) = -(m sigma_h)^2 and
    Var(r) = 2 (m sigma_h)^2 + sigma_pour^2.
    """
    data = [iv for iv in intervals if iv.trusted and math.isfinite(iv.resid)]
    if len(data) < 4:
        return {"ok": False, "reason": "too few intervals"}
    r = np.array([iv.resid for iv in data])
    var = float(np.var(r, ddof=1))
    # Only intervals that share a dip carry the negative lag-1 covariance.
    pairs = [
        (data[i], data[i + 1])
        for i in range(len(data) - 1)
        if data[i].row + 1 == data[i + 1].row
    ]
    if len(pairs) < 2:
        return {"ok": False, "reason": "too few contiguous pairs"}
    cov1 = float(np.mean([a.resid * b.resid for a, b in pairs]))
    m2 = float(np.mean([a.m * b.m for a, b in pairs]))
    dip_var = max(-cov1, 0.0)
    sigma_h = math.sqrt(dip_var / m2) if m2 > 0 else float("nan")
    pour_var = max(var - 2.0 * dip_var, 0.0)
    implied = math.sqrt(var)
    return {
        "ok": True,
        "rho1": cov1 / var if var > 0 else float("nan"),
        "sigma_h": sigma_h,
        "sigma_pour": math.sqrt(pour_var),
        "var": var,
        "implied_rmse": implied,
        "observed_rmse": float(np.sqrt(np.mean(r * r))),
        "n": len(data),
    }


# ---------------------------------------------------------------------------
# Telescoping block test (§9.6)
# ---------------------------------------------------------------------------

def telescoping_blocks(
    intervals: list[Interval],
    shell: Shell,
    *,
    sigma_h: float,
    rel: float,
    abs_: float,
    n_blocks: int = 3,
) -> list[dict]:
    """Block sums: interior dips cancel, only the two boundary dips remain.

    A block must be contiguous.  An unknown pour or an excluded band breaks
    the chain, so each contiguous run is tested on its own.
    """
    data = [iv for iv in intervals if iv.trusted and math.isfinite(iv.resid)]
    if len(data) < n_blocks:
        return []
    runs: list[list[Interval]] = []
    current: list[Interval] = []
    for iv in data:
        if current and iv.idx != current[-1].idx + 1:
            runs.append(current)
            current = []
        current.append(iv)
    if current:
        runs.append(current)

    out = []
    for run_i, run in enumerate(runs, start=1):
        if len(run) < n_blocks:
            continue
        chunks = np.array_split(np.arange(len(run)), n_blocks)
        for k, idx in enumerate(chunks):
            block = [run[i] for i in idx]
            if len(block) < 2:
                continue
            total = sum(iv.s for iv in block) - (
                float(shell.volume(block[-1].h_cur)) - float(shell.volume(block[0].h_prev))
            )
            m1 = float(shell.slope(block[0].h_prev))
            m2 = float(shell.slope(block[-1].h_cur))
            var = (m1 * m1 + m2 * m2) * sigma_h ** 2 + sum(
                (rel * iv.s + abs_) ** 2 for iv in block
            )
            sigma = math.sqrt(var)
            out.append(
                {
                    "block": k + 1,
                    "run": run_i,
                    "from_mm": block[0].h_prev,
                    "to_mm": block[-1].h_cur,
                    "sum": total,
                    "sigma": sigma,
                    "z": total / sigma if sigma > 0 else float("nan"),
                    "flag": "systematic" if abs(total) > 3.0 * sigma else "ok",
                }
            )
    return out


# ---------------------------------------------------------------------------
# Multiple comparisons (§9.7)
# ---------------------------------------------------------------------------

def multiple_comparisons(intervals: list[Interval]) -> dict:
    z = np.array([iv.z for iv in intervals if iv.trusted and math.isfinite(iv.z)])
    n = len(z)
    return {
        "n": n,
        "obs2": int(np.sum(np.abs(z) >= 2.0)),
        "exp2": 0.05 * n,
        "obs3": int(np.sum(np.abs(z) >= 3.0)),
        "exp3": 0.003 * n,
    }


# ---------------------------------------------------------------------------
# Detector views (§6.6)
# ---------------------------------------------------------------------------

def pair_scatter(intervals: list[Interval]) -> list[dict]:
    """Every adjacent trusted pair as (z_i, z_{i+1}), classified (§6.6)."""
    data = [iv for iv in intervals if iv.trusted and math.isfinite(iv.z)]
    out = []
    for a, b in pairwise(data):
        z1, z2 = a.z, b.z
        if abs(z1) <= 2.0 and abs(z2) <= 2.0:
            kind = "central cloud"
        elif abs(z1 + z2) <= 1.0 and abs(z1) > 2.0 and abs(z2) > 2.0:
            kind = "anti-diagonal: shared-dip misread"
        elif (abs(z1) > 2.0 and abs(z2) < 1.0) or (abs(z2) > 2.0 and abs(z1) < 1.0):
            kind = "single-sided event"
        elif z1 * z2 > 0 and abs(z1) > 2.0 and abs(z2) > 2.0:
            kind = "diagonal chain: persistent effect"
        else:
            kind = "off both diagonals: superposed errors, decompose"
        out.append({"i": a.idx, "z1": z1, "z2": z2, "kind": kind})
    return out


def classify_drift(intervals: list[Interval]) -> dict:
    """Name the drift shape (§6.6).  The residual locates, the drift remembers."""
    data = [iv for iv in intervals if math.isfinite(iv.drift)]
    if len(data) < 3:
        return {"shape": "too short", "detail": ""}
    d = np.array([iv.drift for iv in data])
    steps = np.diff(d)
    noise = float(np.nanmedian(np.abs(steps))) or 1e-9
    biggest = int(np.argmax(np.abs(steps)))
    jump = float(steps[biggest])
    before = float(np.mean(d[: biggest + 1])) if biggest >= 0 else 0.0
    after = float(np.mean(d[biggest + 1:])) if biggest + 1 < len(d) else 0.0
    end = float(d[-1])
    start = float(d[0])
    span = float(np.max(d) - np.min(d))
    if span <= 2.0 * noise * math.sqrt(len(d)):
        shape = "flat wobble: honest noise"
    elif abs(end - start) <= 1.5 * noise and abs(jump) > 3.0 * noise:
        shape = "one-point spike that returns: one misread dip"
    elif abs(after - before) > 3.0 * noise and abs(end - start) > 3.0 * noise:
        monotone = np.all(np.diff(d) >= -noise) or np.all(np.diff(d) <= noise)
        shape = (
            "ramp that never returns: persistent effect, audit before refitting"
            if monotone
            else "single step then flat: one-off event"
        )
    elif abs(jump) > 3.0 * noise and abs(end - start) > 3.0 * noise:
        shape = "dip then return: settling lag"
    else:
        shape = "mixed: inspect the residual chart"
    return {
        "shape": shape,
        "jump": jump,
        "jump_at_mm": data[biggest].h_cur if biggest < len(data) else float("nan"),
        "start": start,
        "end": end,
        "span": span,
        "noise": noise,
    }


def lag_check(dips: list[tuple[float, float]]) -> dict:
    """Repeat static dips: creep between readings means a lag (§6.4)."""
    if len(dips) < 2:
        return {"ok": False, "reason": "need two readings"}
    (t1, h1), (t2, h2) = dips[0], dips[-1]
    creep = h2 - h1
    return {
        "ok": abs(creep) < 1.0,
        "creep_mm": creep,
        "minutes": t2 - t1,
        "verdict": "settled" if abs(creep) < 1.0 else "creeping: correct the reading time, not the level",
    }

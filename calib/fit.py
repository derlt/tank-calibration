"""Bound-constrained difference fit, robust loss, constraints, profiles (§5).

The default fit minimises the interval residuals

    resid_i = s_i - (F(H_i) - F(H_{i-1}))

over the trusted set.  Differences cancel a wrong first pour and an unknown
start volume (§5.1).  A wrong dip at a shared level still shows up in two
adjacent intervals, which is what the pair rule of §6.1 exploits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, stats

from .data import Interval
from .geometry import Shell

DEFAULT_BOUNDS = {
    "r": (0.6, 1.4),  # multipliers of nominal
    "L": (0.7, 1.3),
    "h0": (-80.0, 80.0),  # mm
    "eps": (-0.02, 0.02),  # mm/mm
}


@dataclass
class FitResult:
    shell: Shell
    params: dict
    sse: float
    rmse: float
    n: int
    p: int
    loss: str = "linear"
    cov: np.ndarray | None = None
    success: bool = True
    message: str = ""
    starts: int = 1
    constrained: bool = False
    binding: bool = False
    gap: float | None = None
    neck_resid: float | None = None
    free: list[str] = field(default_factory=list)
    residuals: np.ndarray = field(default_factory=lambda: np.array([]))

    @property
    def sigma2(self) -> float:
        return self.sse / max(self.n - self.p, 1)

    def param_sigma(self, name: str) -> float | None:
        """1-sigma for a free parameter; None when it was locked or not fitted."""
        if self.cov is None or name not in self.free:
            return None
        i = self.free.index(name)
        if i >= self.cov.shape[0]:
            return None
        return float(math.sqrt(max(self.cov[i, i], 0.0)))

    def summary(self) -> str:
        s = self.shell
        return (
            f"r={s.r:.2f} L={s.L:.2f} h0={s.h0:.2f} "
            f"RMSE={self.rmse:.3f} L/step n={self.n} p={self.p}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _arrays(intervals: list[Interval]):
    hp = np.array([iv.h_prev for iv in intervals], dtype=float)
    hc = np.array([iv.h_cur for iv in intervals], dtype=float)
    s = np.array([iv.s if iv.s is not None else np.nan for iv in intervals], dtype=float)
    return hp, hc, s


def _bounds(nominal: dict, bounds: dict | None):
    b = dict(DEFAULT_BOUNDS)
    if bounds:
        b.update(bounds)
    return {
        "r": (b["r"][0] * nominal["r"], b["r"][1] * nominal["r"]),
        "L": (b["L"][0] * nominal["L"], b["L"][1] * nominal["L"]),
        "h0": tuple(b["h0"]),
        "eps": tuple(b["eps"]),
    }


def _free_names(tilt: bool, h0_mode: str, fixed: dict | None):
    names = ["r", "L"]
    if h0_mode != "locked":
        names.append("h0")
    if tilt:
        names.append("eps")
    fixed = dict(fixed or {})
    if h0_mode == "locked" and "h0" not in fixed:
        fixed["h0"] = 0.0
    return [n for n in names if n not in fixed], fixed


def _make_fun(intervals, free, fixed, tilt):
    hp, hc, s = _arrays(intervals)

    def fun(x):
        p = dict(fixed)
        p.update({name: float(v) for name, v in zip(free, x)})
        shell = Shell(p["r"], p["L"], p["h0"], p.get("eps", 0.0))
        pred = shell.volume(hc) - shell.volume(hp)
        return s - pred

    return fun


def _start_grid(nominal, bounds, free, multistart):
    if not multistart:
        x0 = []
        for name in free:
            if name == "r":
                x0.append(nominal["r"])
            elif name == "L":
                x0.append(nominal["L"])
            elif name == "h0":
                x0.append(0.0)
            else:
                x0.append(0.0)
        return [np.array(x0, dtype=float)]

    r_vals = [0.85, 0.95, 1.0, 1.05, 1.15]
    l_vals = [0.85, 1.0, 1.15]
    h_vals = [-40.0, 0.0, 40.0]
    starts = []
    for rm in r_vals:
        for lm in l_vals:
            for h0 in h_vals:
                x = []
                for name in free:
                    if name == "r":
                        x.append(nominal["r"] * rm)
                    elif name == "L":
                        x.append(nominal["L"] * lm)
                    elif name == "h0":
                        lo, hi = bounds["h0"]
                        x.append(min(max(h0, lo + 1e-6), hi - 1e-6))
                    else:
                        x.append(0.0)
                starts.append(np.array(x, dtype=float))
    return starts


def _covariance(res, n, p):
    try:
        j = res.jac
        if j is None:
            return None
        jtj = j.T @ j
        cov = np.linalg.inv(jtj) * (res.fun @ res.fun) / max(n - p, 1)
        return cov
    except np.linalg.LinAlgError:
        return None


# ---------------------------------------------------------------------------
# Difference fit (§5.1, §5.2)
# ---------------------------------------------------------------------------

def fit_difference(
    intervals: list[Interval],
    nominal: dict,
    *,
    loss: str = "linear",
    h0_mode: str = "fit",
    h0_value: float = 0.0,
    tilt: bool = False,
    f_scale: float | None = None,
    multistart: bool = True,
    bounds: dict | None = None,
    fixed: dict | None = None,
    x0: dict | None = None,
) -> FitResult:
    """Fit (r, L, h0) on interval differences.

    ``fixed`` pins any parameter, e.g. ``{"r": 944.0}`` for the profile.
    """
    data = [iv for iv in intervals if iv.trusted]
    if len(data) < 3:
        raise ValueError("need at least three trusted intervals to fit three parameters")
    b = _bounds(nominal, bounds)
    free, fixed = _free_names(tilt, h0_mode, fixed)
    if h0_mode == "locked" and "h0" not in fixed:
        fixed["h0"] = h0_value

    lb = np.array([b[name][0] for name in free], dtype=float)
    ub = np.array([b[name][1] for name in free], dtype=float)
    if np.any(lb >= ub):
        raise ValueError(f"empty bounds for {free}")

    fun = _make_fun(data, free, fixed, tilt)

    if x0:
        starts = [np.array([x0.get(n, (lb[i] + ub[i]) / 2) for i, n in enumerate(free)], dtype=float)]
    else:
        starts = _start_grid(nominal, b, free, multistart)

    best = None
    for start in starts:
        start = np.clip(start, lb + 1e-9, ub - 1e-9)
        try:
            res = optimize.least_squares(
                fun,
                start,
                bounds=(lb, ub),
                loss=loss,
                f_scale=(f_scale if f_scale and loss != "linear" else 1.0),
                max_nfev=4000,
                xtol=1e-12,
                ftol=1e-12,
                gtol=1e-12,
            )
        except Exception:  # noqa: S112 - a failed start is a skipped start
            continue
        r = fun(res.x)
        sse = float(r @ r)
        score = sse if loss == "linear" else float(res.cost) * 2.0
        if best is None or score < best[0]:
            best = (score, res, sse, r)

    if best is None:
        raise RuntimeError("all fit starts failed")

    _, res, sse, r = best
    p = dict(fixed)
    p.update({name: float(v) for name, v in zip(free, res.x)})
    p.setdefault("eps", 0.0)
    n = len(data)
    npar = len(free)
    shell = Shell(p["r"], p["L"], p["h0"], p.get("eps", 0.0))
    cov = _covariance(res, n, npar) if loss == "linear" else None
    return FitResult(
        shell=shell,
        params={k: p[k] for k in ("r", "L", "h0", "eps") if k in p},
        sse=sse,
        rmse=math.sqrt(sse / n),
        n=n,
        p=npar,
        loss=loss,
        cov=cov,
        success=bool(res.success),
        message=str(res.message),
        starts=len(starts),
        free=free,
        residuals=r,
    )


# ---------------------------------------------------------------------------
# Physical constraints (§5.3a)
# ---------------------------------------------------------------------------

def fit_constrained(
    intervals: list[Interval],
    nominal: dict,
    *,
    start: FitResult,
    gap_pour: float,
    brim_reading: float | None = None,
    neck: bool = False,
    bounds: dict | None = None,
    h0_mode: str = "fit",
    h0_value: float = 0.0,
) -> FitResult:
    """Refit with ``G = Vcap - F(H*) <= P`` and the optional neck equality.

    The constraint is enforced inside the fit, never after it (§5.3a).  A
    binding constraint is reported; an unconstrained fit that violates it is
    a bug, not a result.  ``h0_mode="locked"`` holds the datum at ``h0_value``.
    """
    data = [iv for iv in intervals if iv.trusted]
    hp, hc, s = _arrays(data)
    h_star = float(np.max(hc))
    b = _bounds(nominal, bounds)
    r_nom, l_nom = nominal["r"], nominal["L"]
    locked = h0_mode == "locked"
    free = ["r", "L"] + ([] if locked else ["h0"])

    def unpack(u):
        r = r_nom * (1.0 + u[0])
        L = l_nom * (1.0 + u[1])
        h0 = float(h0_value) if locked else float(u[2])
        return r, L, h0

    def sse(u):
        r, L, h0 = unpack(u)
        shell = Shell(r, L, h0)
        pred = shell.volume(hc) - shell.volume(hp)
        resid = s - pred
        return float(resid @ resid)

    def gap0(u):
        r, L, h0 = unpack(u)
        shell = Shell(r, L, h0)
        return shell.capacity() - float(shell.volume(h_star))

    def gap(u):
        return gap0(u) - gap_pour

    def neck_fun(u):
        r, _, h0 = unpack(u)
        return 2.0 * r + h0 - float(brim_reading)

    # G <= P (the pour can fill the gap) and G >= 0 (the shell is not overfilled).
    cons = [
        {"type": "ineq", "fun": lambda u: -gap(u)},
        {"type": "ineq", "fun": lambda u: gap0(u)},
    ]
    if neck and brim_reading is not None:
        cons.append({"type": "eq", "fun": neck_fun})

    u0 = [start.shell.r / r_nom - 1.0, start.shell.L / l_nom - 1.0]
    if not locked:
        u0.append(start.shell.h0)
    bnds = [
        (b["r"][0] / r_nom - 1.0, b["r"][1] / r_nom - 1.0),
        (b["L"][0] / l_nom - 1.0, b["L"][1] / l_nom - 1.0),
    ]
    if not locked:
        bnds.append(b["h0"])

    res = optimize.minimize(
        sse,
        np.array(u0, dtype=float),
        method="SLSQP",
        bounds=bnds,
        constraints=cons,
        options={"maxiter": 2000, "ftol": 1e-12},
    )
    if not res.success:
        # Penalty fallback: the same physics, no SLSQP.
        lam = 1e4

        def penalised(u):
            g = max(0.0, gap(u))
            under = max(0.0, -gap0(u))
            out = sse(u) + lam * g * g + lam * under * under
            if neck and brim_reading is not None:
                out += lam * neck_fun(u) ** 2
            return out

        res = optimize.minimize(
            penalised, np.array(u0, dtype=float), method="L-BFGS-B", bounds=bnds,
            options={"maxiter": 5000, "ftol": 1e-14},
        )

    r, L, h0 = unpack(res.x)
    shell = Shell(r, L, h0)
    pred = shell.volume(hc) - shell.volume(hp)
    resid = s - pred
    sse_val = float(resid @ resid)

    # Numeric covariance in the free parameters.  When the constraint binds
    # this is the unconstrained covariance, an approximation reported as such.
    cov = None
    try:
        p0 = np.array(res.x, dtype=float)
        step = np.array([0.5 / r_nom, 0.5 / l_nom] + ([] if locked else [0.1]))
        scale = np.array([r_nom, l_nom] + ([] if locked else [1.0]))
        jac = np.zeros((len(s), len(free)))
        for k in range(len(free)):
            dp = np.zeros(len(free))
            dp[k] = step[k]
            plus = Shell(*unpack(p0 + dp))
            minus = Shell(*unpack(p0 - dp))
            jac[:, k] = (
                (s - (plus.volume(hc) - plus.volume(hp)))
                - (s - (minus.volume(hc) - minus.volume(hp)))
            ) / (2.0 * step[k])
        cov_u = np.linalg.inv(jac.T @ jac) * sse_val / max(len(s) - len(free), 1)
        cov = np.diag(scale) @ cov_u @ np.diag(scale)
    except np.linalg.LinAlgError:
        cov = None
    g = shell.capacity() - float(shell.volume(h_star))
    neck_resid = (2.0 * r + h0 - float(brim_reading)) if (neck and brim_reading is not None) else None
    binding = g >= gap_pour - 1e-6 * max(1.0, gap_pour)

    return FitResult(
        shell=shell,
        params={"r": r, "L": L, "h0": h0},
        sse=sse_val,
        rmse=math.sqrt(sse_val / len(data)),
        n=len(data),
        p=len(free),
        loss="linear",
        success=bool(res.success),
        message=str(res.message),
        constrained=True,
        binding=binding,
        gap=g,
        neck_resid=neck_resid,
        cov=cov,
        free=free,
        residuals=resid,
    )


def overflow_direction(
    shell: Shell,
    h_last: float,
    pour: float,
    vent_volume: float = 0.0,
) -> dict:
    """Interpret an overflow pour (§5.3a).

    Returns the gap, whether the pour could fill it, and the back-predicted
    pour when the field says the tank reached the brim but the pour cannot
    have filled the gap.
    """
    gap = shell.capacity() - float(shell.volume(h_last))
    could_fill = gap <= pour - vent_volume
    return {
        "gap": gap,
        "pour": pour,
        "could_fill": could_fill,
        "back_predicted": gap if not could_fill else None,
        "constraint": "G <= P" if could_fill else "G > P: treat pour as unknown",
    }


# ---------------------------------------------------------------------------
# Joint fit (§5.4)
# ---------------------------------------------------------------------------

def fit_joint(
    campaigns: list[tuple[list[Interval], dict]],
    *,
    common_r: bool = True,
    h0_mode: str = "fit",
    bounds: dict | None = None,
) -> FitResult:
    """Fit one common r with separate lengths (§5.4)."""
    groups = [[iv for iv in ivs if iv.trusted] for ivs, _ in campaigns]
    if any(len(g) < 3 for g in groups):
        raise ValueError("each tank needs at least three trusted intervals")

    names = ["r"] + [f"L{i + 1}" for i in range(len(groups))]
    if h0_mode != "locked":
        names.append("h0")
    mult = dict(DEFAULT_BOUNDS)
    if bounds:
        mult.update(bounds)
    r_ref = float(np.mean([nom["r"] for _, nom in campaigns]))
    lb = [mult["r"][0] * r_ref]
    ub = [mult["r"][1] * r_ref]
    for _, nom in campaigns:
        lb.append(mult["L"][0] * nom["L"])
        ub.append(mult["L"][1] * nom["L"])
    if h0_mode != "locked":
        lb.append(mult["h0"][0])
        ub.append(mult["h0"][1])

    def fun(x):
        r = x[0]
        h0 = x[-1] if h0_mode != "locked" else 0.0
        out = []
        for i, (ivs, _) in enumerate(campaigns):
            L = x[1 + i]
            shell = Shell(r, L, h0)
            hp, hc, s = _arrays(ivs)
            out.append(s - (shell.volume(hc) - shell.volume(hp)))
        return np.concatenate(out)

    x0 = [r_ref]
    x0 += [nom["L"] for _, nom in campaigns]
    if h0_mode != "locked":
        x0.append(0.0)
    res = optimize.least_squares(
        fun, np.array(x0, float), bounds=(lb, ub), max_nfev=8000,
        xtol=1e-12, ftol=1e-12, gtol=1e-12,
    )
    r = float(res.x[0])
    L1 = float(res.x[1])
    h0 = float(res.x[-1]) if h0_mode != "locked" else 0.0
    resid = fun(res.x)
    sse = float(resid @ resid)
    n = len(resid)
    return FitResult(
        shell=Shell(r, L1, h0),
        params={"r": r, "L": L1, "h0": h0, "lengths": [float(v) for v in res.x[1:1 + len(groups)]]},
        sse=sse,
        rmse=math.sqrt(sse / n),
        n=n,
        p=len(res.x),
        cov=_covariance(res, n, len(res.x)),
        success=bool(res.success),
        message=str(res.message),
        free=names,
        residuals=resid,
    )


# ---------------------------------------------------------------------------
# Identifiability: r profile, lock cost, tilt test (§5.5)
# ---------------------------------------------------------------------------

def profile_param(
    intervals: list[Interval],
    nominal: dict,
    fitted: FitResult,
    *,
    name: str = "r",
    span: float = 10.0,
    step: float = 1.0,
    h0_mode: str = "fit",
    bounds: dict | None = None,
) -> dict:
    """RMSE profile of one parameter, with the others refitted (§5.5).

    The one-sigma interval is where ``SSE(param) - SSE_min <= s^2``.
    """
    centre = float(fitted.params[name])
    grid = np.arange(centre - span, centre + span + 1e-9, step)
    b = _bounds(nominal, bounds)
    lo_b, hi_b = b[name]
    grid = grid[(grid >= lo_b) & (grid <= hi_b)]
    others = {
        k: v for k, v in fitted.params.items()
        if k in ("r", "L", "h0") and k != name
    }
    rmses = []
    for value in grid:
        try:
            f = fit_difference(
                intervals, nominal, h0_mode=h0_mode, multistart=False,
                bounds=bounds, fixed={name: float(value)}, x0=others,
            )
            rmses.append(f.rmse)
        except Exception:  # a failed profile point is missing data
            rmses.append(np.nan)
    rmses = np.array(rmses, dtype=float)
    ok = np.isfinite(rmses)
    if not ok.any():
        return {"param": name, "grid": [], "rmse": [], "best": float("nan"),
                "threshold": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "flat_lo": float("nan"), "flat_hi": float("nan"), "span": span}
    best = float(np.nanmin(rmses))
    s2 = fitted.sigma2
    threshold = math.sqrt(best * best + s2 / max(fitted.n, 1))
    inside = grid[ok][rmses[ok] <= threshold]
    flat = grid[ok][rmses[ok] <= best * 1.01]
    return {
        "param": name,
        "grid": grid.tolist(),
        "rmse": rmses.tolist(),
        "best": best,
        "threshold": float(threshold),
        "lo": float(inside.min()) if len(inside) else float("nan"),
        "hi": float(inside.max()) if len(inside) else float("nan"),
        "flat_lo": float(flat.min()) if len(flat) else float("nan"),
        "flat_hi": float(flat.max()) if len(flat) else float("nan"),
        "span": span,
    }


def profile_r(
    intervals: list[Interval],
    nominal: dict,
    fitted: FitResult,
    *,
    span: float = 10.0,
    step: float = 1.0,
    h0_mode: str = "fit",
    bounds: dict | None = None,
) -> dict:
    return profile_param(
        intervals, nominal, fitted, name="r", span=span, step=step,
        h0_mode=h0_mode, bounds=bounds,
    )


def lock_cost(
    intervals: list[Interval],
    nominal: dict,
    fitted: FitResult,
    *,
    bounds: dict | None = None,
) -> dict:
    """Cost of locking h0 = 0, in L/step, with an F-test (§5.5)."""
    locked = fit_difference(
        intervals, nominal, h0_mode="locked", h0_value=0.0,
        bounds=bounds, multistart=False,
        x0={"r": fitted.shell.r, "L": fitted.shell.L},
    )
    delta = locked.rmse - fitted.rmse
    df1, df2 = 1, max(fitted.n - fitted.p, 1)
    f_stat = ((locked.sse - fitted.sse) / df1) / (fitted.sse / df2)
    p_value = float(stats.f.sf(max(f_stat, 0.0), df1, df2))
    return {
        "locked_shell": locked.shell,
        "locked_rmse": locked.rmse,
        "delta_rmse": delta,
        "f": float(f_stat),
        "p": p_value,
        "reject_lock": p_value < 0.05,
    }


def tilt_test(
    intervals: list[Interval],
    nominal: dict,
    fitted: FitResult,
    *,
    bounds: dict | None = None,
) -> dict:
    """Add one tilt parameter; keep it only if RMSE drops materially (§5.5)."""
    tilted = fit_difference(
        intervals, nominal, tilt=True, bounds=bounds, multistart=False,
        x0={"r": fitted.shell.r, "L": fitted.shell.L, "h0": fitted.shell.h0, "eps": 0.0},
    )
    df1 = 1
    df2 = max(tilted.n - tilted.p, 1)
    f_stat = ((fitted.sse - tilted.sse) / df1) / (tilted.sse / df2)
    p_value = float(stats.f.sf(max(f_stat, 0.0), df1, df2))
    plausible = abs(tilted.shell.eps) <= 0.02
    return {
        "shell": tilted.shell,
        "rmse": tilted.rmse,
        "delta_rmse": tilted.rmse - fitted.rmse,
        "eps": tilted.shell.eps,
        "f": float(f_stat),
        "p": p_value,
        "plausible": plausible,
        "keep": bool(p_value < 0.05 and plausible and tilted.rmse < fitted.rmse),
    }


def empty_start_check(rows, shell: Shell, heel_row: bool) -> dict:
    """Report the first row's residual (§5.3b).  Never leave it silent.

    With a heel row, the check is the first pour from the heel:
    ``s_1 - (F(H_1) - F(H_heel))``.  Without one, it is the first fill from
    empty: ``s_1 - F(H_1)``.
    """
    if heel_row:
        if len(rows) < 2:
            return {"row": 1, "height": rows[0].height, "resid": None,
                    "kind": "heel row without a first pour"}
        heel, first = rows[0], rows[1]
        if not first.step.known:
            return {"row": 2, "height": first.height, "resid": None,
                    "kind": "unknown first pour"}
        f_prev = float(shell.volume(heel.height))
        f_cur = float(shell.volume(first.height))
        resid = float(first.step.value) - (f_cur - f_prev)
        return {
            "row": 2,
            "height": first.height,
            "poured": float(first.step.value),
            "F": f_cur,
            "F_heel": f_prev,
            "heel_height": heel.height,
            "resid": resid,
            "kind": "first pour from heel",
        }

    row0 = rows[0]
    f0 = float(shell.volume(row0.height))
    if not row0.step.known:
        return {"row": 1, "height": row0.height, "resid": None, "kind": "unknown first pour"}
    resid = float(row0.step.value) - f0
    return {
        "row": 1,
        "height": row0.height,
        "poured": float(row0.step.value),
        "F": f0,
        "resid": resid,
        "kind": "empty start",
    }


# ---------------------------------------------------------------------------
# Uncertainty: bootstrap and GLS (§5.5, §9)
# ---------------------------------------------------------------------------

def parametric_bootstrap(
    intervals: list[Interval],
    fitted: FitResult,
    *,
    sigma_h: float,
    rel: float,
    abs_: float,
    n: int = 200,
    seed: int = 0,
    h0_mode: str = "fit",
) -> dict:
    """Parametric bootstrap with fresh dip and pour noise (§5.5)."""
    data = [iv for iv in intervals if iv.trusted]
    rng = np.random.default_rng(seed)
    # One dip-noise draw per recorded level, keyed by file row.  This keeps a
    # shared dip shared, and keeps a gap (object band, unknown pour) a gap.
    n_rows = max(iv.row for iv in data) + 1
    draws = {name: [] for name in ("r", "L", "h0")}

    for _ in range(n):
        delta = rng.normal(0.0, sigma_h, size=n_rows)
        sim = []
        for iv in data:
            s_sim = iv.s + rng.normal(0.0, rel * abs(iv.s) + abs_)
            sim.append(
                Interval(
                    idx=iv.idx,
                    row=iv.row,
                    s=float(s_sim),
                    known=True,
                    base=0.0,
                    h_prev=iv.h_prev + delta[iv.row - 1],
                    h_cur=iv.h_cur + delta[iv.row],
                )
            )
        try:
            f = fit_difference(
                sim, {"r": fitted.shell.r, "L": fitted.shell.L},
                h0_mode=h0_mode, multistart=False,
                x0={"r": fitted.shell.r, "L": fitted.shell.L, "h0": fitted.shell.h0},
            )
        except Exception:  # noqa: S112 - a failed start is a skipped start
            continue
        for name, values in draws.items():
            values.append(f.params.get(name, 0.0))

    out = {}
    for name, vals in draws.items():
        arr = np.array(vals, dtype=float)
        out[name] = {
            "mean": float(arr.mean()) if len(arr) else float("nan"),
            "sd": float(arr.std(ddof=1)) if len(arr) > 1 else float("nan"),
            "lo": float(np.percentile(arr, 2.5)) if len(arr) else float("nan"),
            "hi": float(np.percentile(arr, 97.5)) if len(arr) else float("nan"),
            "n": len(arr),
        }
    out["draws"] = {k: list(map(float, v)) for k, v in draws.items()}
    return out


def gls_fit(
    intervals: list[Interval],
    nominal: dict,
    *,
    sigma_h: float,
    rel: float,
    abs_: float,
    h0_mode: str = "fit",
    bounds: dict | None = None,
) -> FitResult:
    """Generalised least squares with the per-dip covariance (§5.5, §9.5).

    Adjacent residuals share a dip, so their errors are correlated.  Ignoring
    that correlation makes naive (J'J)^-1 errors run about 40 % large; GLS
    reproduces the parametric bootstrap.
    """
    data = [iv for iv in intervals if iv.trusted]
    n = len(data)
    hp, hc, s = _arrays(data)
    b = _bounds(nominal, bounds)
    free, fixed = _free_names(False, h0_mode, None)
    lb = np.array([b[name][0] for name in free])
    ub = np.array([b[name][1] for name in free])

    # Initial slopes from the nominal shell.
    nom_shell = Shell(nominal["r"], nominal["L"], 0.0)
    m_cur = nom_shell.slope(hc)
    m_prev = nom_shell.slope(hp)
    var = (m_cur * m_cur + m_prev * m_prev) * sigma_h ** 2 + (rel * s + abs_) ** 2
    cov = np.diag(var)
    for i in range(n - 1):
        # Only contiguous intervals share a dip.
        if data[i].row + 1 == data[i + 1].row:
            cov[i, i + 1] = cov[i + 1, i] = -(m_cur[i] ** 2) * sigma_h ** 2

    try:
        chol = np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        chol = np.linalg.cholesky(cov + np.eye(n) * 1e-9)

    fun = _make_fun(data, free, fixed, False)

    def whitened(x):
        return np.linalg.solve(chol, fun(x))

    res = optimize.least_squares(
        whitened, np.array([nominal["r"], nominal["L"], 0.0][: len(free)]),
        bounds=(lb, ub), max_nfev=4000, xtol=1e-12, ftol=1e-12, gtol=1e-12,
    )
    p = dict(fixed)
    p.update({name: float(v) for name, v in zip(free, res.x)})
    p.setdefault("eps", 0.0)
    shell = Shell(p["r"], p["L"], p["h0"])
    raw = fun(res.x)
    sse = float(raw @ raw)

    # Covariance in the whitened metric is the correct GLS covariance.
    try:
        j = res.jac
        cov_p = np.linalg.inv(j.T @ j)
    except np.linalg.LinAlgError:
        cov_p = None

    return FitResult(
        shell=shell,
        params={k: p[k] for k in ("r", "L", "h0", "eps") if k in p},
        sse=sse,
        rmse=math.sqrt(sse / n),
        n=n,
        p=len(free),
        loss="gls",
        cov=cov_p,
        success=bool(res.success),
        message=str(res.message),
        free=free,
        residuals=raw,
    )


def cov3(fit: FitResult) -> np.ndarray | None:
    """Covariance of (r, L, h0), with zeros for any locked parameter."""
    if fit.cov is None:
        return None
    names = ["r", "L", "h0"]
    out = np.zeros((3, 3))
    for i, n1 in enumerate(fit.free):
        if n1 not in names:
            continue
        for j, n2 in enumerate(fit.free):
            if n2 in names:
                out[names.index(n1), names.index(n2)] = fit.cov[i, j]
    return out

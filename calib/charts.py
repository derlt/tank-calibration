"""Chart layer for CHARTS.md.

Raw data, corrected data and the fitted model on one canvas.  The sign
convention is the methodology one: ``resid = obs - pred``, ``z = resid / sigma``
and ``drift = books - F``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .data import Row
from .geometry import Shell

MODEL = "#1a6fa8"
RAW = "#d62728"
COR = "#2ca02c"
EXCL = "#9467bd"
CHECK = "#ff9f1c"
OBJECT = "#ff7f0e"
LOSS = "#1f77b4"
LEAK = "#8c564b"
ZERO = "0.3"
GREY = "0.6"

ANN = dict(fontsize=9, arrowprops=dict(arrowstyle="->", color="0.3"))


@dataclass
class Series:
    """One table (raw or corrected) reduced to chart-ready arrays."""

    H: np.ndarray
    h_prev: np.ndarray
    mid: np.ndarray
    row: np.ndarray
    s: np.ndarray
    pred: np.ndarray
    resid: np.ndarray
    sigma: np.ndarray
    z: np.ndarray
    books: np.ndarray
    drift: np.ndarray
    rise: np.ndarray
    excluded: np.ndarray
    heel: float = 0.0

    def __len__(self) -> int:
        return len(self.H)


def _empty() -> Series:
    z = np.array([], dtype=float)
    return Series(z, z, z, np.array([], dtype=int), z, z, z, z, z, z, z, z, np.array([], dtype=bool))


def build_series(
    rows: list[Row],
    shell: Shell,
    *,
    sigma_h: float,
    rel: float,
    abs_: float,
    heel_row: bool,
    books_start: float | None = None,
) -> Series:
    """Reduce a table to the arrays every chart reads.

    The books start with the first row's pour: recorded when known,
    back-predicted ``F(H_0)`` when not (§9.3).  An unknown pour advances the
    books by the shell's predicted rise for that interval, so the drift
    series stays comparable across a gap and equals the interval drift of §2.
    """
    if not rows:
        return _empty()
    brim = shell.brim()
    first = rows[0]
    if books_start is None:
        books_start = (
            float(first.step.value)
            if first.step.known
            else float(shell.volume(first.height))
        )
    heel = books_start if heel_row else 0.0
    books = books_start

    out = {k: [] for k in ("H", "h_prev", "mid", "row", "s", "pred", "resid", "sigma", "z", "books", "drift", "rise", "excluded")}
    for i in range(1, len(rows)):
        step = rows[i].step
        h_prev = float(rows[i - 1].height)
        h_cur = float(rows[i].height)
        pred = float(shell.volume(h_cur) - shell.volume(h_prev))
        if not step.known:
            books += step.base + pred
            continue
        s = float(step.value)
        resid = s - pred
        m = float(shell.slope(h_cur))
        sigma = math.sqrt((m * sigma_h * math.sqrt(2.0)) ** 2 + (rel * s + abs_) ** 2)
        z = resid / sigma if sigma > 0 else float("nan")
        books += s
        rise = h_cur - h_prev
        out["H"].append(h_cur)
        out["h_prev"].append(h_prev)
        out["mid"].append(0.5 * (h_prev + h_cur))
        out["row"].append(i)
        out["s"].append(s)
        out["pred"].append(pred)
        out["resid"].append(resid)
        out["sigma"].append(sigma)
        out["z"].append(z)
        out["books"].append(books)
        out["drift"].append(books - float(shell.volume(h_cur)))
        out["rise"].append(rise)
        out["excluded"].append(bool(h_cur > brim or rise <= 0))

    return Series(
        H=np.array(out["H"], dtype=float),
        h_prev=np.array(out["h_prev"], dtype=float),
        mid=np.array(out["mid"], dtype=float),
        row=np.array(out["row"], dtype=int),
        s=np.array(out["s"], dtype=float),
        pred=np.array(out["pred"], dtype=float),
        resid=np.array(out["resid"], dtype=float),
        sigma=np.array(out["sigma"], dtype=float),
        z=np.array(out["z"], dtype=float),
        books=np.array(out["books"], dtype=float),
        drift=np.array(out["drift"], dtype=float),
        rise=np.array(out["rise"], dtype=float),
        excluded=np.array(out["excluded"], dtype=bool),
        heel=heel,
    )


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def _raw_pts(ax, x, y, label=None, ms=5):
    ax.plot(x, y, "o", ms=ms, mfc="none", mec=RAW, mew=1.3, label=label)


def _cor_pts(ax, x, y, label=None, ms=4):
    ax.plot(x, y, "s", ms=ms, color=COR, label=label)


def _model_line(ax, x, y, label=None, lw=2.2):
    ax.plot(x, y, "-", color=MODEL, lw=lw, label=label)


def _finish(ax, xlabel, ylabel, title, legend=None, grid=0.3):
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(alpha=grid)
    ax.tick_params(labelsize=8)
    if legend:
        ax.legend(loc=legend, fontsize=8, frameon=False)


def _ann(ax, text, xy, dx=8, dy=10):
    ax.annotate(text, xy=xy, xytext=(dx, dy), textcoords="offset points", **ANN)


def _save(fig, path, *, suptitle=False, dpi=160):
    if suptitle:
        fig.tight_layout(rect=(0, 0, 1, 0.96))
    else:
        fig.tight_layout()
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)
    return str(path)


def _xmax(shell: Shell, raw: Series, cor: Series) -> float:
    vals = [shell.brim()]
    if len(raw):
        vals.append(float(np.nanmax(raw.H)))
    if len(cor):
        vals.append(float(np.nanmax(cor.H)))
    return max(vals) * 1.02


# ---------------------------------------------------------------------------
# C1 + C2
# ---------------------------------------------------------------------------

def panel_strapping(ax, raw: Series, cor: Series, shell: Shell, bands: list[dict]):
    brim = shell.brim()
    hs = np.linspace(0.0, brim, 500)
    _model_line(ax, hs, shell.volume(hs), "Fitted shell V(H)")
    if len(raw):
        _raw_pts(ax, raw.H, raw.books, "Raw books")
    if len(cor):
        _cor_pts(ax, cor.H, cor.books, "Corrected books")
    ax.axvline(brim, color="0.5", ls="--", lw=1)
    ax.text(brim, 0.02 * shell.capacity(), f"brim {brim:.0f}", rotation=90,
            color="0.4", va="bottom", ha="right", fontsize=8)
    for band in bands:
        ax.axvspan(float(band["low"]), float(band["high"]), color=OBJECT, alpha=0.08)

    if len(raw) and raw.heel > 0:
        _ann(ax, f"heel {raw.heel:.0f} L", (raw.h_prev[0], raw.heel))
    if len(raw):
        k = int(np.nanargmax(np.abs(raw.resid)))
        _ann(ax, f"{raw.resid[k]:+.0f} L", (raw.H[k], raw.books[k]))

    ax.set_xlim(0.0, _xmax(shell, raw, cor))
    _finish(ax, "Tape reading H (mm)", "Cumulative volume (L)",
            "1. Strapping curve vs cumulative books", "upper left")


def panel_residuals(ax, raw: Series, cor: Series):
    if len(cor):
        ax.fill_between(cor.mid, -cor.sigma, cor.sigma, color=MODEL, alpha=0.12, label="±1σ")
    if len(raw):
        _raw_pts(ax, raw.mid, raw.resid, "Raw table")
    if len(cor):
        _cor_pts(ax, cor.mid, cor.resid, "Corrected")
    if len(raw) and raw.excluded.any():
        ax.plot(raw.mid[raw.excluded], raw.resid[raw.excluded], "x", ms=8,
                color=EXCL, mew=2, label="Excluded / overflow")
    ax.axhline(0, color=ZERO, lw=1)

    vals = []
    if len(raw):
        vals.append(np.abs(raw.resid))
    if len(cor):
        vals.append(np.abs(cor.resid))
        vals.append(3.0 * cor.sigma)
    lim = float(np.nanmax(np.concatenate(vals))) * 1.15 if vals else 10.0
    lim = max(lim, 10.0)
    ax.set_ylim(-lim, lim)

    if len(raw):
        k = int(np.nanargmax(np.abs(raw.resid)))
        _ann(ax, f"{raw.resid[k]:+.0f} L", (raw.mid[k], raw.resid[k]))
    _finish(ax, "Tape reading H (mm)", "Residual, obs − pred (L)",
            "2. Residual per interval", "upper left")


# ---------------------------------------------------------------------------
# C3 - C6
# ---------------------------------------------------------------------------

def panel_predicted(ax, raw: Series, cor: Series):
    vals = []
    for s in (raw, cor):
        if len(s):
            vals.extend([float(np.nanmax(s.s)), float(np.nanmax(s.pred))])
    lim = max(vals) * 1.05 if vals else 1.0
    ax.plot([0, lim], [0, lim], color=GREY, lw=1, label="y = x")
    if len(raw):
        _raw_pts(ax, raw.s, raw.pred, "Raw")
    if len(cor):
        _cor_pts(ax, cor.s, cor.pred, "Corrected")

    # Fix arrows: pair by file row, draw only where the point moved.
    if len(raw) and len(cor):
        by_row = {int(r): i for i, r in enumerate(cor.row)}
        for i, r in enumerate(raw.row):
            j = by_row.get(int(r))
            if j is None:
                continue
            if abs(raw.pred[i] - cor.pred[j]) < 1.0 and abs(raw.s[i] - cor.s[j]) < 1.0:
                continue
            ax.annotate("", xy=(cor.s[j], cor.pred[j]), xytext=(raw.s[i], raw.pred[i]),
                        arrowprops=dict(arrowstyle="->", color=MODEL, lw=1.2, alpha=0.6))

    if len(raw):
        gap = np.abs(raw.pred - raw.s)
        k = int(np.nanargmax(gap))
        _ann(ax, f"resid {raw.s[k] - raw.pred[k]:+.0f} L", (raw.s[k], raw.pred[k]))

    ax.set_xlim(0.0, lim)
    ax.set_ylim(0.0, lim)
    _finish(ax, "Recorded pour (L)", "Predicted pour from the shell (L)",
            "3. Predicted vs recorded pour", "upper left")


def panel_slope(ax, raw: Series, cor: Series, shell: Shell):
    brim = shell.brim()
    hs = np.linspace(0.0, brim, 500)
    _model_line(ax, hs, shell.slope(hs), "Shell slope dV/dH")
    if len(raw):
        ok = raw.rise > 0
        _raw_pts(ax, raw.mid[ok], raw.s[ok] / raw.rise[ok], "Raw pour / rise")
    if len(cor):
        ok = cor.rise > 0
        _cor_pts(ax, cor.mid[ok], cor.s[ok] / cor.rise[ok], "Corrected pour / rise")
    _finish(ax, "Level midpoint (mm)", "Slope (L per mm)",
            "4. Slope profile", "upper left")


def panel_drift(ax, raw: Series, cor: Series):
    if len(raw):
        ax.plot(raw.H, raw.drift, "-o", color=RAW, lw=1, ms=5, mfc="none",
                mec=RAW, mew=1.3, label="Raw")
    if len(cor):
        ax.plot(cor.H, cor.drift, "-s", color=COR, lw=1, ms=4, label="Corrected")
    ax.axhline(0, color=ZERO, lw=1)

    if len(raw):
        _ann(ax, f"start {raw.drift[0]:+.0f} L", (raw.H[0], raw.drift[0]))
        steps = np.diff(raw.drift)
        if len(steps):
            k = int(np.nanargmax(np.abs(steps)))
            _ann(ax, f"{steps[k]:+.0f} L", (raw.H[k + 1], raw.drift[k + 1]))
        _ann(ax, f"end {raw.drift[-1]:+.0f} L", (raw.H[-1], raw.drift[-1]), dx=-40)

    _finish(ax, "Tape reading H (mm)", "Drift, books − F (L)",
            "5. Drift: the running disagreement", "upper left")


def panel_z(ax, raw: Series, cor: Series):
    if len(raw):
        ok = ~raw.excluded
        _raw_pts(ax, raw.H[ok], raw.z[ok], "Raw")
    if len(cor):
        ok = ~cor.excluded
        _cor_pts(ax, cor.H[ok], cor.z[ok], "Corrected")
    ax.axhline(0, color=ZERO, lw=1)
    for y in (2, -2):
        ax.axhline(y, color=CHECK, ls="--", lw=1)
    for y in (3, -3):
        ax.axhline(y, color=RAW, ls=":", lw=1.2)

    if len(raw):
        ok = ~raw.excluded
        if ok.any():
            z = np.where(ok, raw.z, np.nan)
            k = int(np.nanargmax(np.abs(z)))
            _ann(ax, f"z = {raw.z[k]:+.1f}", (raw.H[k], raw.z[k]))
    _finish(ax, "Level (mm)", "z = resid / σ", "6. z alarms", "upper left")


# ---------------------------------------------------------------------------
# C7 + C8
# ---------------------------------------------------------------------------

def panel_pairs(ax, raw: Series, cor: Series):
    L = 15.0
    ax.plot([-L, L], [-L, L], color=MODEL, lw=1, alpha=0.6)
    ax.plot([-L, L], [L, -L], color=MODEL, lw=1, alpha=0.6)
    ax.add_patch(plt.Rectangle((-2, -2), 4, 4, fill=False, ls="--", ec=CHECK, lw=1))
    ax.axhline(0, color="0.85", lw=0.8)
    ax.axvline(0, color="0.85", lw=0.8)

    if len(raw) > 1:
        mask = (~raw.excluded[:-1]) & (~raw.excluded[1:])
        _raw_pts(ax, raw.z[:-1][mask], raw.z[1:][mask], "Raw pairs", ms=4)
    if len(cor) > 1:
        mask = (~cor.excluded[:-1]) & (~cor.excluded[1:])
        _cor_pts(ax, cor.z[:-1][mask], cor.z[1:][mask], "Corrected pairs", ms=3.5)

    ax.plot([-8], [8], "^", color=EXCL, ms=8, label="dip +5 mm")
    ax.plot([8], [-8], "v", color=EXCL, ms=8, label="dip −5 mm")
    ax.plot([-10], [0], "D", color=OBJECT, ms=7, label="object 120 L")
    ax.plot([10], [0], "D", color=LOSS, ms=7, label="short pour 200 L")
    ax.plot([6], [6], "*", color=LEAK, ms=11, label="leak 60 L/interval")

    ax.set_xlim(-L, L)
    ax.set_ylim(-L, L)
    _finish(ax, "z[i]", "z[i+1]", "A. Adjacent-pair detector", "upper left")


def panel_drift_shapes(ax):
    x = np.arange(1, 41)
    rng = np.random.default_rng(3)
    noise = np.cumsum(rng.normal(0.0, 3.0, 40))
    spike = np.zeros(40)
    spike[15] = 45.0
    loss = np.where(x >= 20, 60.0, 0.0)
    obj = np.where(x >= 20, -60.0, 0.0)
    leak = np.where(x >= 10, (x - 10) * 2.5, 0.0)
    lag = np.zeros(40)
    lag[12:18] = [0.0, 12.0, 28.0, 30.0, 18.0, 0.0]

    curves = [
        ("honest noise", noise, "0.5"),
        ("misread dip", spike, EXCL),
        ("one-off loss", loss, RAW),
        ("object", obj, OBJECT),
        ("active leak", leak, LEAK),
        ("settling lag", lag, LOSS),
    ]
    for label, y, color in curves:
        ax.plot(x, y, lw=1.5, color=color, label=label)
    ax.axhline(0, color=ZERO, lw=1)
    _finish(ax, "Interval number", "Drift (L)", "B. Drift-shape reference", "upper left")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def panel_profile(ax, profile: dict):
    name = profile.get("param", "r")
    ax.plot(profile["grid"], profile["rmse"], color=MODEL, lw=2.0)
    ax.axhline(profile["threshold"], color=CHECK, ls="--", lw=1)
    if math.isfinite(profile["lo"]):
        ax.axvspan(profile["lo"], profile["hi"], color=MODEL, alpha=0.12)
    _finish(ax, f"{name} (mm)", "RMSE (L/step)", f"{name} profile", None)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def _single(path, panel, args, figsize=(7.0, 4.5)):
    fig, ax = plt.subplots(figsize=figsize)
    panel(ax, *args)
    return _save(fig, path)


def main_pair(path, raw, cor, shell, bands):
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11.5, 9.5), sharex=True,
        gridspec_kw={"height_ratios": [1.5, 1]},
    )
    fig.suptitle("Tank calibration — strapping and residuals", fontsize=12)
    panel_strapping(ax1, raw, cor, shell, bands)
    panel_residuals(ax2, raw, cor)
    ax2.set_xlim(ax1.get_xlim())
    return _save(fig, path, suptitle=True)


def gallery(path, raw, cor, shell):
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 11))
    fig.suptitle("Calibration diagnostics — record, shape, drift, significance", fontsize=12)
    panel_predicted(axes[0, 0], raw, cor)
    panel_slope(axes[0, 1], raw, cor, shell)
    panel_drift(axes[1, 0], raw, cor)
    panel_z(axes[1, 1], raw, cor)
    return _save(fig, path, suptitle=True)


def detector(path, raw, cor):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 7.2))
    fig.suptitle("Failure-mode detector", fontsize=12)
    panel_pairs(ax1, raw, cor)
    panel_drift_shapes(ax2)
    return _save(fig, path, suptitle=True)


def all_charts(
    outdir: str | Path,
    *,
    shell: Shell,
    rows: list[Row],
    raw_rows: list[Row],
    heel_row: bool,
    bands: list[dict],
    sigma_h: float,
    rel: float,
    abs_: float,
    profile: dict | None = None,
) -> dict:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    raw = build_series(raw_rows, shell, sigma_h=sigma_h, rel=rel, abs_=abs_, heel_row=heel_row)
    cor = build_series(rows, shell, sigma_h=sigma_h, rel=rel, abs_=abs_, heel_row=heel_row)

    paths = {
        "strapping": _single(outdir / "01_strapping.png", panel_strapping, (raw, cor, shell, bands)),
        "residuals": _single(outdir / "02_residuals.png", panel_residuals, (raw, cor)),
        "predicted": _single(outdir / "03_predicted_vs_recorded.png", panel_predicted, (raw, cor), (6.0, 5.2)),
        "slope": _single(outdir / "04_slope_profile.png", panel_slope, (raw, cor, shell)),
        "drift": _single(outdir / "05_drift.png", panel_drift, (raw, cor)),
        "z": _single(outdir / "06_z_alarms.png", panel_z, (raw, cor)),
        "pair": _single(outdir / "07_pair_scatter.png", panel_pairs, (raw, cor), (6.5, 6.0)),
    }
    paths["main_pair"] = main_pair(outdir / "pour_fit.png", raw, cor, shell, bands)
    paths["gallery"] = gallery(outdir / "pour_fit_views.png", raw, cor, shell)
    paths["detector"] = detector(outdir / "anomaly_detector.png", raw, cor)
    if profile:
        paths["profile"] = _single(outdir / "08_r_profile.png", panel_profile, (profile,), (6.0, 4.0))

    fig, axes = plt.subplots(2, 4, figsize=(16, 8))
    for ax in axes.ravel():
        ax.axis("off")
    for ax, key in zip(axes.ravel(), ["strapping", "residuals", "predicted", "slope", "drift", "z", "pair"]):
        ax.imshow(plt.imread(paths[key]))
        ax.axis("off")
    fig.tight_layout()
    combined = outdir / "00_all_views.png"
    fig.savefig(combined, dpi=110, facecolor="white")
    plt.close(fig)
    paths["combined"] = str(combined)
    return paths

"""The seven diagnostic views of §6.6, plus the r profile (§5.5)."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .data import Interval, Row
from .geometry import Shell

INK = "#1f2933"
MUTED = "#7b8794"
GRID = "#e4e7eb"
BLUE = "#2563eb"
RED = "#dc2626"
GREEN = "#059669"
AMBER = "#d97706"


def _style(ax, title, xlabel, ylabel):
    ax.set_title(title, fontsize=11, color=INK, loc="left", pad=8)
    ax.set_xlabel(xlabel, fontsize=9, color=MUTED)
    ax.set_ylabel(ylabel, fontsize=9, color=MUTED)
    ax.grid(True, color=GRID, linewidth=0.7)
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)


def _save(fig, path):
    path = Path(path)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
    return str(path)


def chart_strapping(path, shell: Shell, rows: list[Row], *, heel_row: bool, bands: list[dict]):
    fig, ax = plt.subplots(figsize=(7, 4.2))
    brim = shell.brim()
    hs = np.linspace(0, brim, 400)
    vol = np.array([float(shell.volume(h)) for h in hs])
    ax.plot(hs, vol, color=BLUE, linewidth=2, label="adopted shell F(H)")

    heel = float(rows[0].step.value) if (heel_row and rows[0].step.known) else 0.0
    books = heel
    xs, ys = [], []
    for row in rows[1 if heel_row else 0:]:
        if not row.step.known:
            continue
        books += float(row.step.value)
        xs.append(row.height)
        ys.append(books)
    ax.plot(xs, ys, "o", color=RED, markersize=3.5, label="cumulative books")

    for band in bands:
        ax.axvspan(float(band["low"]), float(band["high"]), color=AMBER, alpha=0.15)

    _style(ax, "Strapping vs books", "tape reading H (mm)", "volume (L)")
    ax.legend(frameon=False, fontsize=8)
    return _save(fig, path)


def chart_residuals(path, intervals: list[Interval]):
    data = [iv for iv in intervals if iv.known and math.isfinite(iv.resid)]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    h = [iv.h_cur for iv in data]
    r = [iv.mm_equiv for iv in data]
    colors = [RED if iv.flag == "candidate" else (AMBER if iv.flag == "watch" else MUTED) for iv in data]
    ax.bar(h, r, width=8, color=colors)
    ax.axhline(0, color=INK, linewidth=0.8)
    for y, style in ((3, "--"), (-3, "--"), (1.5, ":"), (-1.5, ":")):
        ax.axhline(y, color=MUTED, linestyle=style, linewidth=0.8)
    _style(ax, "Interval residuals", "level H (mm)", "residual (mm-equivalent)")
    return _save(fig, path)


def chart_predicted_vs_recorded(path, intervals: list[Interval]):
    data = [iv for iv in intervals if iv.known and math.isfinite(iv.resid)]
    fig, ax = plt.subplots(figsize=(5.2, 4.6))
    s = [iv.s for iv in data]
    p = [iv.pred for iv in data]
    ax.plot([0, max(s + p) * 1.05], [0, max(s + p) * 1.05], color=MUTED, linewidth=1)
    ax.plot(p, s, "o", color=BLUE, markersize=3.5)
    _style(ax, "Predicted vs recorded", "predicted pour (L)", "recorded pour (L)")
    return _save(fig, path)


def chart_slope_profile(path, shell: Shell, intervals: list[Interval]):
    data = [iv for iv in intervals if iv.known and iv.rise > 0]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    brim = shell.brim()
    hs = np.linspace(0, brim, 400)
    ax.plot(hs, shell.slope(hs), color=BLUE, linewidth=2, label="shell slope m(H)")
    ax.plot(
        [iv.h_cur for iv in data],
        [iv.s / iv.rise for iv in data],
        "o",
        color=RED,
        markersize=3.5,
        label="pour / rise",
    )
    _style(ax, "Slope profile", "level H (mm)", "L/mm")
    ax.legend(frameon=False, fontsize=8)
    return _save(fig, path)


def chart_drift(path, intervals: list[Interval]):
    data = [iv for iv in intervals if math.isfinite(iv.drift)]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot([iv.h_cur for iv in data], [iv.drift for iv in data], color=RED, linewidth=1.8)
    ax.axhline(0, color=INK, linewidth=0.8)
    _style(ax, "Drift: the running disagreement", "level H (mm)", "cumulative residual (L)")
    return _save(fig, path)


def chart_z_alarms(path, intervals: list[Interval]):
    data = [iv for iv in intervals if iv.known and math.isfinite(iv.z)]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot([iv.h_cur for iv in data], [iv.z for iv in data], "o", color=BLUE, markersize=3.5)
    for y, color, style in ((2, AMBER, "--"), (-2, AMBER, "--"), (3, RED, "-"), (-3, RED, "-")):
        ax.axhline(y, color=color, linestyle=style, linewidth=0.9)
    _style(ax, "z alarms", "level H (mm)", "z")
    return _save(fig, path)


def chart_pair_scatter(path, intervals: list[Interval]):
    data = [iv for iv in intervals if iv.trusted and math.isfinite(iv.z)]
    fig, ax = plt.subplots(figsize=(5.4, 5.0))
    z1 = [iv.z for iv in data[:-1]]
    z2 = [iv.z for iv in data[1:]]
    lim = max(4.0, max([abs(v) for v in z1 + z2] + [3.0]) * 1.15)
    ax.plot([-lim, lim], [lim, -lim], color=MUTED, linewidth=0.8, linestyle="--")
    ax.plot([-lim, lim], [-lim, lim], color=MUTED, linewidth=0.8, linestyle=":")
    ax.axhline(0, color=GRID, linewidth=0.8)
    ax.axvline(0, color=GRID, linewidth=0.8)
    ax.scatter(z1, z2, s=18, color=BLUE)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    _style(ax, "Adjacent-pair scatter", "z(i)", "z(i+1)")
    return _save(fig, path)


def chart_profile(path, profile: dict):
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(profile["grid"], profile["rmse"], color=BLUE, linewidth=1.8)
    ax.axhline(profile["threshold"], color=AMBER, linestyle="--", linewidth=0.9)
    if math.isfinite(profile["lo"]):
        ax.axvspan(profile["lo"], profile["hi"], color=BLUE, alpha=0.08)
    _style(ax, f"{profile.get('param', 'r')} profile", f"{profile.get('param', 'r')} (mm)", "RMSE (L/step)")
    return _save(fig, path)


def all_charts(
    outdir: str | Path,
    *,
    shell: Shell,
    rows: list[Row],
    intervals: list[Interval],
    heel_row: bool,
    bands: list[dict],
    profile: dict | None = None,
) -> dict:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {
        "strapping": chart_strapping(outdir / "01_strapping.png", shell, rows, heel_row=heel_row, bands=bands),
        "residuals": chart_residuals(outdir / "02_residuals.png", intervals),
        "predicted": chart_predicted_vs_recorded(outdir / "03_predicted_vs_recorded.png", intervals),
        "slope": chart_slope_profile(outdir / "04_slope_profile.png", shell, intervals),
        "drift": chart_drift(outdir / "05_drift.png", intervals),
        "z": chart_z_alarms(outdir / "06_z_alarms.png", intervals),
        "pair": chart_pair_scatter(outdir / "07_pair_scatter.png", intervals),
    }
    if profile:
        paths["profile"] = chart_profile(outdir / "08_r_profile.png", profile)

    # One combined sheet for the report.
    fig, axes = plt.subplots(2, 4, figsize=(16, 8))
    for ax in axes.ravel():
        ax.axis("off")
    for ax, key in zip(axes.ravel(), ["strapping", "residuals", "predicted", "slope", "drift", "z", "pair"]):
        img = plt.imread(paths[key])
        ax.imshow(img)
        ax.axis("off")
    fig.tight_layout()
    combined = outdir / "00_all_views.png"
    fig.savefig(combined, dpi=110, facecolor="white")
    plt.close(fig)
    paths["combined"] = str(combined)
    return paths

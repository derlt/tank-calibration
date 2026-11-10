"""Live field protocol: per-pour z-test against the adopted shell (§10).

The field tool must carry the adopted, constrained shell — the same presets
that were written by the fit (§11).  It never refits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .data import Interval, Row, read_raw
from .diagnostics import blocked_below, interval_sigma, pair_scatter, residual_meaning
from .geometry import Shell


@dataclass
class Verdict:
    row: int
    step: float | None
    h_prev: float
    h_cur: float
    resid: float | None = None
    mm: float | None = None
    sigma: float | None = None
    z: float | None = None
    flag: str = "OK"
    message: str = ""
    advice: str = ""
    drift: float = 0.0
    unknown: dict | None = None
    closure: dict | None = None


class FieldValidator:
    """Validate pours one at a time against a fixed shell."""

    def __init__(
        self,
        shell: Shell,
        *,
        sigma_h: float = 1.5,
        rel: float = 0.005,
        abs_: float = 3.0,
        bands: list[dict] | None = None,
        pour_unit: float | None = None,
    ):
        self.shell = shell
        self.sigma_h = sigma_h
        self.rel = rel
        self.abs_ = abs_
        self.bands = bands or []
        self.pour_unit = pour_unit
        self.drift = 0.0
        self.n = 0
        self.poured = 0.0
        self.heel = 0.0
        self.history: list[Verdict] = []
        self.levels: list[float] = []

    # -- one pour ------------------------------------------------------
    def check(
        self,
        step: float | None,
        h_prev: float,
        h_cur: float,
        row: int = 0,
        base: float = 0.0,
    ) -> Verdict:
        v = Verdict(row=row, step=step, h_prev=h_prev, h_cur=h_cur)
        brim = self.shell.brim()
        if h_cur > brim:
            v.flag = "OVERFLOW"
            v.message = (
                f"above brim {brim:.0f} mm: the reading is vent-column height, "
                "not shell level; record it for the brim constraint"
            )
            self.history.append(v)
            return v

        pred = float(self.shell.volume(h_cur) - self.shell.volume(h_prev))
        pred -= float(blocked_below(self.bands, h_cur)) - float(blocked_below(self.bands, h_prev))
        m = float(self.shell.slope(h_cur))
        v.mm = None

        if step is None:
            x = pred - base
            sx = math.sqrt(
                (math.sqrt(2.0) * m * self.sigma_h) ** 2 + (self.rel * base + self.abs_) ** 2
            )
            total = base + x
            v.unknown = {
                "x": x, "base": base, "total": total,
                "sigma": sx, "lo": total - 2 * sx, "hi": total + 2 * sx,
            }
            v.flag = "UNKNOWN"
            label = f"{base:g} + {x:.1f}" if base else f"{x:.1f}"
            v.message = f"pour unknown: back-predicted {label} ± {2 * sx:.1f} L"
            v.resid = 0.0
            v.z = 0.0
            self.n += 1
            self.poured += total
            self.history.append(v)
            self.levels.append(h_cur)
            return v

        resid = step - pred
        sigma = interval_sigma(m, step, self.sigma_h, self.rel, self.abs_)
        z = resid / sigma if sigma > 0 else float("nan")
        mm = resid / m if m > 0 else float("nan")
        v.resid, v.sigma, v.z, v.mm = resid, sigma, z, mm
        self.drift += resid
        self.n += 1
        self.poured += step

        v.flag = "OK"
        v.message = "within noise"
        if abs(z) >= 3.0 and abs(mm) >= 3.0:
            v.flag = "ALARM"
            v.message = (
                f"resid {resid:+.1f} L ({mm:+.1f} mm-equiv, z={z:+.1f}): "
                + residual_meaning(resid)
            )
            v.advice = (
                "stop; re-dip both endpoints. If confirmed: "
                + ("OBJECT? (solid in this band)" if resid < 0 else "POUR? or LOSS?")
                + "; run a discriminating test before believing either"
            )
        elif abs(z) >= 2.0:
            v.flag = "CHECK"
            v.message = f"resid {resid:+.1f} L (z={z:+.1f}): re-dip both endpoints after settling"
        elif abs(mm) >= 3.0:
            v.flag = "CHECK"
            v.message = f"resid {resid:+.1f} L ({mm:+.1f} mm-equiv): re-dip"

        # DIP-PAIR: the shared dip of the previous pour and this one.
        if len(self.history) >= 1:
            prev = self.history[-1]
            if (
                prev.resid is not None
                and prev.mm is not None
                and v.mm is not None
                and prev.resid * resid < 0
                and abs(prev.mm) >= 3.0
                and abs(v.mm) >= 3.0
                and abs(prev.z) >= 3.0
                and abs(v.z) >= 3.0
            ):
                total = abs(prev.resid) + abs(resid)
                net = abs(prev.resid + resid)
                if total > 0 and net / total <= 0.15:
                    delta = (resid - prev.resid) / (2.0 * m) if m > 0 else float("nan")
                    v.flag = "DIP-PAIR"
                    v.message = (
                        f"shared dip {h_prev:.0f} mm likely misread by {delta:+.1f} mm "
                        f"(net {net:.1f} L of {total:.1f} L)"
                    )
                    v.advice = f"re-dip that one level; corrected reading ≈ {h_prev - delta:.1f} mm"

        # BRIM-WARN
        gap = self.shell.capacity() - float(self.shell.volume(h_cur))
        if gap < 0.05 * self.shell.capacity() or (brim - h_cur) < 60.0:
            if v.flag == "OK":
                v.flag = "BRIM-WARN"
            brim_text = f"gap {gap:.0f} L ({brim - h_cur:.0f} mm to brim): halve the next pour"
            v.advice = (v.advice + "; " if v.advice else "") + brim_text

        # DRIFT
        if abs(self.drift) > 3.0 * sigma * math.sqrt(max(self.n, 1)):
            if v.flag in ("OK", "CHECK"):
                v.flag = "DRIFT"
            drift_text = (
                f"running residual {self.drift:+.1f} L beyond 3σ√n: stop and audit "
                "(tilt? can size? leak?)"
            )
            v.advice = (v.advice + "; " if v.advice else "") + drift_text

        v.closure = self.closure(h_cur)
        self.history.append(v)
        self.levels.append(h_cur)
        return v

    # -- helpers -------------------------------------------------------
    def closure(self, h: float) -> dict:
        blocked = sum(
            float(b.get("displacement", b.get("litres", 0.0)) or 0.0)
            for b in self.bands
            if h >= float(b["high"])
        )
        lhs = self.heel + self.poured + blocked
        rhs = float(self.shell.volume(h))
        return {"lhs": lhs, "rhs": rhs, "diff": lhs - rhs}

    def advisor(self, h: float) -> dict:
        m = float(self.shell.slope(h))
        target = 30.0 * m
        floor = 10.0 * m
        brim = self.shell.brim()
        gap = self.shell.capacity() - float(self.shell.volume(h))
        advice = f"next pour ≈ {target:.0f} L (30 mm rise)"
        if self.pour_unit:
            units = max(1, round(target / self.pour_unit))
            advice += f" ≈ {units} × {self.pour_unit:g} L"
        if gap < 0.05 * self.shell.capacity():
            advice += "; gap small: halve it"
        return {
            "slope": m,
            "target": target,
            "floor": floor,
            "ceiling": 100.0 * m,
            "advice": advice,
            "brim_mm": brim - h,
        }

    def run(self, rows: list[Row]) -> list[Verdict]:
        if not rows:
            return []
        first = rows[0]
        self.heel = float(first.step.value) if first.step.known else 0.0
        self.levels = [first.height]
        self.history = []
        self.drift = 0.0
        self.n = 0
        self.poured = 0.0
        out = []
        for i in range(1, len(rows)):
            row = rows[i]
            step = row.step.value if row.step.known else None
            base = row.step.base if row.step.kind == "partial" else 0.0
            out.append(self.check(step, rows[i - 1].height, row.height, row=i + 1, base=base))
        return out

    def summary(self, verdicts: list[Verdict]) -> dict:
        counts: dict[str, int] = {}
        for v in verdicts:
            counts[v.flag] = counts.get(v.flag, 0) + 1
        ivs = []
        for v in verdicts:
            if v.z is None or v.resid is None:
                continue
            iv = Interval(v.row, v.row, v.step, True, 0.0, v.h_prev, v.h_cur, trusted=True)
            iv.resid = v.resid
            iv.z = v.z
            iv.mm_equiv = v.mm if v.mm is not None else 0.0
            iv.flag = "candidate" if v.flag in ("ALARM", "DIP-PAIR") else "ok"
            ivs.append(iv)
        detector = [p for p in pair_scatter(ivs) if p["kind"] != "central cloud"]
        return {
            "pours": len(verdicts),
            "counts": counts,
            "drift": self.drift,
            "closure": self.closure(self.levels[-1]) if self.levels else None,
            "detector": detector,
            "advisor": self.advisor(self.levels[-1]) if self.levels else None,
            "shell": self.shell,
        }


def validate_file(path, shell: Shell, **kwargs) -> tuple[list[Verdict], dict]:
    rows = read_raw(path)
    v = FieldValidator(shell, **kwargs)
    verdicts = v.run(rows)
    return verdicts, v.summary(verdicts)

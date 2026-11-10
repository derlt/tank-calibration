"""Interval blocking for small pours (§7).

Merge adjacent trusted intervals so that dip noise stops dominating the
signal.  Block boundaries stay fit points; the empirical table keeps every
raw row.  RMSE is not comparable across grouped and ungrouped fits.
"""

from __future__ import annotations

from .data import Interval


def block_intervals(
    intervals: list[Interval],
    *,
    sigma_h: float = 1.5,
    target_rise_mm: float | None = None,
    floor_mm: float | None = None,
    ceiling_mm: float = 100.0,
) -> list[Interval]:
    """Merge adjacent trusted intervals into blocks (§7.2)."""
    target = target_rise_mm if target_rise_mm is not None else 20.0 * sigma_h
    floor = floor_mm if floor_mm is not None else 10.0 * sigma_h

    blocks: list[Interval] = []
    current: list[Interval] = []

    def flush():
        if not current:
            return
        first, last = current[0], current[-1]
        blocks.append(
            Interval(
                idx=first.idx,
                row=last.row,
                s=sum(iv.s for iv in current),
                known=True,
                base=0.0,
                h_prev=first.h_prev,
                h_cur=last.h_cur,
                trusted=True,
                reason="blocked " + ",".join(str(iv.idx) for iv in current),
            )
        )
        current.clear()

    for iv in intervals:
        if not (iv.trusted and iv.known):
            flush()
            # Accident/unknown rows stay solo at their native rise (§7.2).
            blocks.append(iv)
            continue
        if current:
            prospective = iv.h_cur - current[0].h_prev
            current_rise = current[-1].h_cur - current[0].h_prev
            if prospective > ceiling_mm and current_rise >= floor:
                flush()
        current.append(iv)
        rise = current[-1].h_cur - current[0].h_prev
        if rise >= target:
            flush()
    flush()
    return blocks


def blocking_report(blocks: list[Interval], sigma_h: float) -> dict:
    rises = [b.h_cur - b.h_prev for b in blocks if b.trusted]
    return {
        "n_blocks": len(blocks),
        "n_trusted": len(rises),
        "median_rise_mm": float(sorted(rises)[len(rises) // 2]) if rises else float("nan"),
        "floor_mm": 10.0 * sigma_h,
        "target_mm": 20.0 * sigma_h,
        "note": "RMSE is not comparable across grouped and ungrouped fits (§7.2)",
    }

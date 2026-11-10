"""Geometry of a horizontal, flat-ended circular cylinder (§4).

All lengths are millimetres, all volumes litres.  The shell is described by
three parameters:

    r   radius of the circular section
    L   effective shell length
    h0  datum offset: true depth h = H - h0, where H is the tape reading

An optional static tilt ``eps`` (mm of depth change per mm along the axis) is
used only by the tilt test of §5.5.  It is zero for the adopted model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _arr(h):
    return np.asarray(h, dtype=float)


def clip_depth(h, r):
    """Clip a depth to the physically meaningful band [0, 2r]."""
    return np.clip(_arr(h), 0.0, 2.0 * float(r))


def area(h, r):
    """Cross-section area of a circular segment, mm² (§4)."""
    r = float(r)
    hc = clip_depth(h, r)
    return (
        r * r * np.arccos(np.clip((r - hc) / r, -1.0, 1.0))
        - (r - hc) * np.sqrt(np.maximum(2.0 * r * hc - hc * hc, 0.0))
    )


def volume(H, r, L, h0):
    """Shell volume below tape reading H, litres (§4)."""
    return float(L) * area(_arr(H) - float(h0), r) / 1e6


def capacity(r, L):
    """Full shell capacity, litres."""
    return np.pi * float(r) ** 2 * float(L) / 1e6


def brim_reading(h0, r):
    """Tape reading at the shell crown, mm: B = h0 + 2r."""
    return float(h0) + 2.0 * float(r)


def slope(H, r, L, h0):
    """Local slope dF/dH, litres per mm (§4)."""
    r = float(r)
    h = clip_depth(_arr(H) - float(h0), r)
    return 2.0 * float(L) * np.sqrt(np.maximum(2.0 * r * h - h * h, 0.0)) / 1e6


def _gauss_legendre(n=64):
    return np.polynomial.legendre.leggauss(n)


def volume_tilted(H, r, L, h0, eps, n=64):
    """Volume of a shell with a linear tilt along its axis (§5.5).

    The liquid surface is horizontal.  With the tape at mid-length, the depth
    at axial position x is ``H - h0 - eps * (x - L/2)``.
    """
    x, w = _gauss_legendre(n)
    xs = 0.5 * float(L) * (x + 1.0)
    ws = 0.5 * float(L) * w
    H = _arr(H)
    depth = H[..., None] - float(h0) - float(eps) * (xs - 0.5 * float(L))
    out = np.sum(ws * area(depth, r), axis=-1) / 1e6
    return float(out) if np.ndim(H) == 0 else out


@dataclass(frozen=True)
class Shell:
    """A fitted or nominal shell, with the derived quantities of §4."""

    r: float
    L: float
    h0: float
    eps: float = 0.0

    # -- model ---------------------------------------------------------
    def volume(self, H):
        if self.eps == 0.0:
            return volume(H, self.r, self.L, self.h0)
        return volume_tilted(H, self.r, self.L, self.h0, self.eps)

    def slope(self, H):
        if self.eps == 0.0:
            return slope(H, self.r, self.L, self.h0)
        # The closed form is flat-shell only; differentiate the tilted volume.
        d = 1e-3
        H = _arr(H)
        return (self.volume(H + d) - self.volume(H - d)) / (2.0 * d)

    def capacity(self):
        return capacity(self.r, self.L)

    def brim(self):
        return brim_reading(self.h0, self.r)

    def as_params(self):
        return (self.r, self.L, self.h0) if self.eps == 0.0 else (self.r, self.L, self.h0, self.eps)

    def with_params(self, p):
        if len(p) == 3:
            return Shell(float(p[0]), float(p[1]), float(p[2]))
        return Shell(float(p[0]), float(p[1]), float(p[2]), float(p[3]))

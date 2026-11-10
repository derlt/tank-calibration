"""Horizontal-tank calibration from pour/level data.

Python owns the fit and the uncertainty.  Excel shows the result.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tank-calibration")
except PackageNotFoundError:  # pragma: no cover - source tree without an install
    __version__ = "0.0.0"

from .config import Config, load_config
from .data import (
    Correction,
    Interval,
    Row,
    apply_corrections,
    build_intervals,
    read_raw,
)
from .field import FieldValidator
from .fit import FitResult, fit_difference
from .geometry import Shell
from .pipeline import run

__all__ = [
    "Config",
    "Correction",
    "FieldValidator",
    "FitResult",
    "Interval",
    "Row",
    "Shell",
    "apply_corrections",
    "build_intervals",
    "fit_difference",
    "load_config",
    "read_raw",
    "run",
]

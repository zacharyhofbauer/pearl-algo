"""
NQ Intraday Strategy Module

Clean, minimal strategy module for NQ (Nasdaq-100 E-mini Futures) intraday trading.
Decoupled from worker pool architecture, designed for async-first execution.
"""

from __future__ import annotations

# Import version from main package
from pearlalgo import __version__

__all__ = ["__version__"]

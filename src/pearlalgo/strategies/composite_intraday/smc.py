"""
SMC compatibility surface for the composite intraday bundle.

This wrapper exists only so the canonical strategy bundle can call the retained
legacy implementation without importing it directly everywhere else.
"""

from __future__ import annotations

from pearlalgo.trading_bots import smc_signals as legacy


def check_signal(*args, **kwargs):
    return legacy._check_smc_signal(*args, **kwargs)

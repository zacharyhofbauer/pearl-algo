"""
SMC compatibility surface for the composite intraday bundle.
"""

from __future__ import annotations

from pearlalgo.trading_bots import smc_signals as legacy


def check_signal(*args, **kwargs):
    return legacy._check_smc_signal(*args, **kwargs)

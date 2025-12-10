"""
Options Module - Swing-trade scanning for equity options.

Provides:
- Options scanner for broad-market equity scanning
- Options chain filtering
- Options-specific strategies
- Equity universe management
"""

from pearlalgo.options.universe import EquityUniverse
from pearlalgo.options.chain_filter import OptionsChainFilter
from pearlalgo.options.swing_scanner import OptionsSwingScanner
from pearlalgo.options.strategies import swing_momentum_strategy

__all__ = [
    "EquityUniverse",
    "OptionsChainFilter",
    "OptionsSwingScanner",
    "swing_momentum_strategy",
]

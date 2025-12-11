"""
Options Trading Module

Provides options scanning, signal generation, and strategy execution
for equity options swing trading.
"""

from .universe import EquityUniverse
from .swing_scanner import OptionsSwingScanner
from .strategy import OptionsStrategy
from .signal_generator import OptionsSignalGenerator

__all__ = [
    "EquityUniverse",
    "OptionsSwingScanner",
    "OptionsStrategy",
    "OptionsSignalGenerator",
]

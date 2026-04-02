"""
VWAP 2SD helpers for the composite intraday bundle.

The live VWAP 2SD implementation still resides in the compatibility core and
is invoked by that engine to preserve parity.
"""

SIGNAL_SOURCE = "vwap_2sd"
ENTRY_TRIGGER = "vwap_2sd_reversion"

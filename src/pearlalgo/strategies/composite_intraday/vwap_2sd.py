"""
VWAP 2SD helpers for the composite intraday bundle.

The live VWAP 2SD implementation still resides in the compatibility core and
is invoked by that engine to preserve parity.

Do not add new VWAP 2SD logic here while this remains a bridge module.
"""

SIGNAL_SOURCE = "vwap_2sd"
ENTRY_TRIGGER = "vwap_2sd_reversion"

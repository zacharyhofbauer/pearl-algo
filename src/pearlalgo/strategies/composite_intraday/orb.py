"""
ORB helpers for the composite intraday bundle.

The live ORB implementation still resides in the compatibility core and is
invoked by that engine to preserve parity.

Do not add new ORB logic here while this remains a bridge module.
"""

SIGNAL_SOURCE = "orb"
ENTRY_TRIGGER = "orb_breakout"

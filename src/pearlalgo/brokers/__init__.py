"""Broker abstraction layer."""

import warnings

# Import all brokers
from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.brokers.paper_broker import PaperBroker
from pearlalgo.brokers.mock_broker import MockBroker

# Import IBKR broker (deprecated)
try:
    from pearlalgo.brokers.ibkr_broker import IBKRBroker
    __all__ = ["Broker", "BrokerConfig", "PaperBroker", "MockBroker", "IBKRBroker"]
except ImportError:
    __all__ = ["Broker", "BrokerConfig", "PaperBroker", "MockBroker"]

# Warn if IBKR is imported
def __getattr__(name):
    if name == "IBKRBroker":
        warnings.warn(
            "IBKRBroker is deprecated. Use PaperBroker instead. "
            "See IBKR_DEPRECATION_NOTICE.md for migration guide.",
            DeprecationWarning,
            stacklevel=2
        )
        from pearlalgo.brokers.ibkr_broker import IBKRBroker
        return IBKRBroker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

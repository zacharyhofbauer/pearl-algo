"""
DISABLED FUTURES MODULE

This module contains futures-related code that has been disabled while 
futures API is unavailable. The system now focuses exclusively on equity options
(QQQ, SPY) for intraday and swing trading.

RE-ENABLEMENT PROCESS:
When 
1. Review this module for any updates needed
2. Re-enable futures worker in continuous_service.py
3. Update signal_router.py to route futures signals
4. Update risk_manager_agent.py to handle futures risk
5. Update config.yaml to add futures worker configuration
6. Test futures data ingestion and signal generation
7. See docs/FUTURES_RE_ENABLEMENT.md for detailed steps

DO NOT DELETE THIS MODULE - It will be needed when futures trading is re-enabled.
"""

# Flag to indicate this module is disabled
DISABLED_FUTURES_MODULE = True

# Futures-specific constants (preserved for future use)
FUTURES_SYMBOLS = ["ES", "NQ", "MES", "MNQ"]
FUTURES_CONTRACT_FORMATS = {
    "ES": "ESU5",  # Example: ESU5 = ES September 2025
    "NQ": "NQU5",  # Example: NQU5 = NQ September 2025
}

# Futures-specific configuration (preserved for future use)
FUTURES_CONFIG = {
    "symbols": ["ES", "NQ"],
    "interval": 60,  # seconds
    "strategy": "intraday_swing",
    "max_risk_per_trade": 0.02,  # 2%
    "volatility_target": {
        "min": 0.005,  # 0.5%
        "max": 0.01,   # 1.0%
    },
}

# Placeholder classes and functions (to be implemented when re-enabled)
class FuturesIntradayScanner:
    """
    DISABLED: Futures intraday scanner.
    
    This class would scan futures contracts (ES, NQ) for intraday trading
    opportunities. Currently disabled while .
    """
    pass


class FuturesSignalTracker:
    """
    DISABLED: Futures signal tracker.
    
    This class would track active futures positions and generate exit signals.
    Currently disabled while .
    """
    pass


class FuturesExitSignalGenerator:
    """
    DISABLED: Futures exit signal generator.
    
    This class would generate exit signals for futures positions based on
    stop loss, take profit, and time-based exits.
    Currently disabled while .
    """
    pass


def get_active_futures_contract(symbol: str) -> str:
    """
    DISABLED: Get active futures contract for a symbol.
    
    Args:
        symbol: Futures symbol (e.g., "ES", "NQ")
        
    Returns:
        Active contract symbol (e.g., "ESU5")
        
    Note: This function is disabled while .
    """
    raise NotImplementedError(
        "Futures contract resolution is disabled. "
        "Re-enable when ."
    )


def is_futures_symbol(symbol: str) -> bool:
    """
    DISABLED: Check if symbol is a futures contract.
    
    Args:
        symbol: Trading symbol
        
    Returns:
        True if futures, False otherwise
        
    Note: This function is disabled while .
    """
    return False  # Always return False while disabled

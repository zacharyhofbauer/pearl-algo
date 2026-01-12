"""
Custom Indicators Module

Provides a framework for porting PineScript indicators to Python and integrating
them as both rule-based signals and features for the learning system.

Usage:
    from pearlalgo.strategies.nq_intraday.indicators import get_enabled_indicators
    
    indicators = get_enabled_indicators(config)
    for ind in indicators:
        df = ind.calculate(df)
        features = ind.as_features(df.iloc[-1])
        signal = ind.generate_signal(df.iloc[-1], df)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from pearlalgo.strategies.nq_intraday.indicators.base import IndicatorBase
from pearlalgo.strategies.nq_intraday.indicators.supply_demand_zones import SupplyDemandZones
from pearlalgo.strategies.nq_intraday.indicators.power_channel import PowerChannel
from pearlalgo.strategies.nq_intraday.indicators.smart_money_divergence import SmartMoneyDivergence
from pearlalgo.strategies.nq_intraday.indicators.tbt_chartprime import TBTChartPrime

# Registry of available indicators
INDICATOR_REGISTRY: Dict[str, Type[IndicatorBase]] = {
    "supply_demand_zones": SupplyDemandZones,
    "power_channel": PowerChannel,
    "smart_money_divergence": SmartMoneyDivergence,
    "tbt_chartprime": TBTChartPrime,
}


def get_enabled_indicators(config: Optional[Dict] = None) -> List[IndicatorBase]:
    """
    Get list of enabled indicator instances based on configuration.
    
    Args:
        config: Configuration dictionary with 'indicators.enabled' list
        
    Returns:
        List of instantiated indicator objects
    """
    if config is None:
        config = {}
    
    indicators_config = config.get("indicators", {})
    enabled_names = indicators_config.get("enabled", list(INDICATOR_REGISTRY.keys()))
    
    indicators = []
    for name in enabled_names:
        if name in INDICATOR_REGISTRY:
            try:
                indicator_config = indicators_config.get(name, {})
                indicator = INDICATOR_REGISTRY[name](config=indicator_config)
                indicators.append(indicator)
            except Exception as e:
                # Log but don't fail - indicator loading should be best-effort
                import logging
                logging.getLogger(__name__).warning(f"Failed to load indicator {name}: {e}")
    
    return indicators


def get_indicator(name: str, config: Optional[Dict] = None) -> Optional[IndicatorBase]:
    """
    Get a single indicator instance by name.
    
    Args:
        name: Indicator name (must be in INDICATOR_REGISTRY)
        config: Optional configuration for the indicator
        
    Returns:
        Indicator instance or None if not found
    """
    if name not in INDICATOR_REGISTRY:
        return None
    
    return INDICATOR_REGISTRY[name](config=config or {})


__all__ = [
    "IndicatorBase",
    "SupplyDemandZones",
    "PowerChannel",
    "SmartMoneyDivergence",
    "TBTChartPrime",
    "INDICATOR_REGISTRY",
    "get_enabled_indicators",
    "get_indicator",
]



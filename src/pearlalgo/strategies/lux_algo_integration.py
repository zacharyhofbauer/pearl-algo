"""
Lux Algo Bots Integration Layer

Integrates Lux Algo Chart Prime style automated trading bots with the existing
PEARLalgo NQ trading system. Allows seamless deployment of complete trading
strategies alongside the current unified strategy.

This integration enables:
- Multiple bot deployment and management
- Bot performance tracking and comparison
- Configuration-based bot selection
- Compatibility with existing signal processing pipeline
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
import json
from pathlib import Path

from pearlalgo.utils.logger import logger
from pearlalgo.config.config_loader import load_service_config

from .lux_algo_bots import (
    LuxAlgoBot,
    BotConfig,
    create_bot,
    TrendFollowerBot,
    BreakoutBot,
    MeanReversionBot,
)


class LuxAlgoBotManager:
    """
    Manager for Lux Algo Chart Prime style trading bots.

    Integrates multiple automated bots with the existing PEARLalgo system,
    similar to how Lux Algo manages their AI-generated strategies.
    """

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path("config")
        self.bots: Dict[str, LuxAlgoBot] = {}
        self.bot_configs: Dict[str, Dict[str, Any]] = {}

        # Load bot configurations
        self._load_bot_configs()

        logger.info(f"LuxAlgoBotManager initialized with {len(self.bots)} bots")

    def _load_bot_configs(self) -> None:
        """Load bot configurations from config files."""
        try:
            # Load service config to get bot settings
            service_config = load_service_config(validate=False) or {}

            # Look for lux_algo_bots configuration
            lux_algo_config = service_config.get('lux_algo_bots', {})

            if not lux_algo_config.get('enabled', False):
                logger.info("Lux Algo bots disabled in configuration")
                return

            # Get bot configurations
            bots_config = lux_algo_config.get('bots', {})

            for bot_name, bot_config in bots_config.items():
                if not bot_config.get('enabled', False):
                    continue

                try:
                    # Create bot configuration
                    config = BotConfig(
                        name=bot_name,
                        description=bot_config.get('description', ''),
                        symbol=bot_config.get('symbol', 'MNQ'),
                        timeframe=bot_config.get('timeframe', '5m'),
                        max_positions=bot_config.get('max_positions', 1),
                        risk_per_trade=bot_config.get('risk_per_trade', 0.01),
                        stop_loss_pct=bot_config.get('stop_loss_pct', 0.005),
                        take_profit_pct=bot_config.get('take_profit_pct', 0.01),
                        min_confidence=bot_config.get('min_confidence', 0.6),
                        parameters=bot_config.get('parameters', {}),
                        enable_alerts=bot_config.get('enable_alerts', True),
                        webhook_url=bot_config.get('webhook_url'),
                    )

                    # Create and register bot
                    bot_class_name = bot_config.get('bot_class', f"{bot_name}Bot")
                    bot = create_bot(bot_class_name, config)

                    self.bots[bot_name] = bot
                    self.bot_configs[bot_name] = bot_config

                    logger.info(f"Loaded bot: {bot_name} ({bot_class_name})")

                except Exception as e:
                    logger.error(f"Failed to load bot {bot_name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to load bot configurations: {e}")

    def analyze_with_bots(self, market_data: Dict) -> List[Dict]:
        """
        Analyze market data with all active Lux Algo bots.

        Returns signals in the format expected by the existing signal processing pipeline.
        """
        if not self.bots:
            return []

        all_signals = []

        for bot_name, bot in self.bots.items():
            try:
                bot_signals = bot.analyze(market_data)

                # Convert Lux Algo signals to PEARLalgo format
                for signal in bot_signals:
                    pearl_signal = self._convert_to_pearl_format(signal, bot_name)
                    all_signals.append(pearl_signal)

            except Exception as e:
                logger.error(f"Error analyzing with bot {bot_name}: {e}")
                continue

        logger.debug(f"Generated {len(all_signals)} signals from {len(self.bots)} Lux Algo bots")
        return all_signals

    def _convert_to_pearl_format(self, lux_signal: Any, bot_name: str) -> Dict:
        """
        Convert Lux Algo bot signal to PEARLalgo signal format.

        This ensures compatibility with the existing signal processing pipeline.
        """
        return {
            "type": f"lux_algo_{lux_signal.bot_name.lower()}",
            "direction": lux_signal.direction,
            "confidence": lux_signal.confidence,
            "entry_price": lux_signal.entry_price,
            "stop_loss": lux_signal.stop_loss,
            "take_profit": lux_signal.take_profit,
            "reason": lux_signal.reason,
            "bot_name": lux_signal.bot_name,
            "bot_version": lux_signal.bot_version,
            "indicators_used": lux_signal.indicators_used,
            "features": lux_signal.features,
            "risk_reward_ratio": lux_signal.risk_reward_ratio,
            "position_size_pct": lux_signal.position_size_pct,
            "signal_id": lux_signal.signal_id,
            "timestamp": lux_signal.timestamp.isoformat(),
            # Additional metadata for tracking
            "lux_algo_bot": True,
            "strategy_type": self.bots[bot_name].strategy_type,
        }

    def update_bot_signal_status(self, bot_name: str, signal_id: str,
                               status: str, execution_price: Optional[float] = None,
                               exit_price: Optional[float] = None) -> None:
        """Update signal status for a specific bot."""
        if bot_name in self.bots:
            self.bots[bot_name].update_signal_status(
                signal_id, status, execution_price, exit_price
            )

    def get_bot_performance(self, bot_name: Optional[str] = None) -> Dict[str, Any]:
        """Get performance metrics for bots."""
        if bot_name and bot_name in self.bots:
            return self.bots[bot_name].get_performance_report()

        # Return performance for all bots
        return {
            bot_name: bot.get_performance_report()
            for bot_name, bot in self.bots.items()
        }

    def get_active_bots(self) -> List[str]:
        """Get list of active bot names."""
        return list(self.bots.keys())

    def enable_bot(self, bot_name: str) -> bool:
        """Enable a specific bot."""
        if bot_name in self.bots:
            self.bots[bot_name].is_active = True
            logger.info(f"Enabled bot: {bot_name}")
            return True
        return False

    def disable_bot(self, bot_name: str) -> bool:
        """Disable a specific bot."""
        if bot_name in self.bots:
            self.bots[bot_name].is_active = False
            logger.info(f"Disabled bot: {bot_name}")
            return True
        return False

    def reload_bot_configs(self) -> None:
        """Reload bot configurations from config files."""
        logger.info("Reloading Lux Algo bot configurations...")
        self.bots.clear()
        self.bot_configs.clear()
        self._load_bot_configs()

    def create_default_config(self) -> Dict[str, Any]:
        """
        Create a default configuration template for Lux Algo bots.

        This shows users how to configure the bots in their config.yaml
        """
        return {
            "lux_algo_bots": {
                "enabled": True,
                "bots": {
                    "trend_follower": {
                        "enabled": True,
                        "description": "Trend-following bot using moving averages and momentum",
                        "bot_class": "TrendFollowerBot",
                        "symbol": "MNQ",
                        "timeframe": "5m",
                        "max_positions": 1,
                        "risk_per_trade": 0.01,
                        "stop_loss_pct": 0.005,
                        "take_profit_pct": 0.01,
                        "min_confidence": 0.7,
                        "enable_alerts": True,
                        "parameters": {
                            "min_trend_strength": 25.0,
                            "max_pullback_pct": 0.02,
                            "momentum_threshold": 0.005
                        }
                    },
                    "breakout_trader": {
                        "enabled": True,
                        "description": "Breakout bot trading consolidation breakouts",
                        "bot_class": "BreakoutBot",
                        "symbol": "MNQ",
                        "timeframe": "5m",
                        "max_positions": 1,
                        "risk_per_trade": 0.01,
                        "stop_loss_pct": 0.008,
                        "take_profit_pct": 0.015,
                        "min_confidence": 0.75,
                        "enable_alerts": True,
                        "parameters": {
                            "min_pattern_strength": 0.6,
                            "require_volume_confirmation": True,
                            "min_momentum_acceleration": 0.001
                        }
                    },
                    "mean_reverter": {
                        "enabled": False,  # Disabled by default as it's more risky
                        "description": "Mean reversion bot using oscillator analysis",
                        "bot_class": "MeanReversionBot",
                        "symbol": "MNQ",
                        "timeframe": "5m",
                        "max_positions": 1,
                        "risk_per_trade": 0.008,  # Lower risk for mean reversion
                        "stop_loss_pct": 0.003,
                        "take_profit_pct": 0.008,
                        "min_confidence": 0.8,
                        "enable_alerts": True,
                        "parameters": {
                            "min_mr_strength": 0.7,
                            "require_divergence": False,
                            "max_hold_bars": 10
                        }
                    }
                }
            }
        }


# Global bot manager instance
lux_algo_manager = LuxAlgoBotManager()


def get_lux_algo_manager() -> LuxAlgoBotManager:
    """Get the global Lux Algo bot manager instance."""
    return lux_algo_manager
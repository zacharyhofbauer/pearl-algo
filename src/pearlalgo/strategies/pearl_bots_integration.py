"""
PEARL Automated Bots Integration Layer

Integrates PEARL automated trading bots with the existing PEARLalgo NQ trading system.
Allows seamless deployment of complete trading strategies alongside existing systems.

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

from .pearl_bots import (
    PearlBot,
    BotConfig,
    create_bot,
    TrendFollowerBot,
    BreakoutBot,
    MeanReversionBot,
)


class PearlBotManager:
    """
    Manager for PEARL automated trading bots.

    Integrates multiple automated bots with the existing PEARLalgo system,
    providing coordinated deployment and performance monitoring.
    """

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path("config")
        self.bots: Dict[str, PearlBot] = {}
        self.bot_configs: Dict[str, Dict[str, Any]] = {}

        # Load bot configurations
        self._load_bot_configs()

        logger.info(f"PearlBotManager initialized with {len(self.bots)} bots")

    def _load_bot_configs(self) -> None:
        """Load bot configurations from config files."""
        try:
            # Load service config to get bot settings
            service_config = load_service_config(validate=False) or {}

            # Look for PEARL bot configuration (legacy alias: lux_algo_bots)
            pearl_bots_config = service_config.get("pearl_bots") or service_config.get("lux_algo_bots") or {}

            if not pearl_bots_config.get("enabled", False):
                logger.info("PEARL bots disabled in configuration")
                return

            # Get bot configurations
            bots_config = pearl_bots_config.get("bots", {})

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

        logger.debug(f"Generated {len(all_signals)} signals from {len(self.bots)} PEARL bots")
        return all_signals

    def _convert_to_pearl_format(self, lux_signal: Any, bot_name: str) -> Dict:
        """
        Convert Lux Algo bot signal to PEARLalgo signal format.

        This ensures compatibility with the existing signal processing pipeline.
        """
        # Compute risk/reward in the same shape expected by SignalPolicy + signal generator.
        rr = 0.0
        try:
            entry = float(getattr(lux_signal, "entry_price", 0.0) or 0.0)
            stop = float(getattr(lux_signal, "stop_loss", 0.0) or 0.0)
            target = float(getattr(lux_signal, "take_profit", 0.0) or 0.0)
            direction = str(getattr(lux_signal, "direction", "long") or "long").lower()
            if entry > 0 and stop > 0 and target > 0:
                if direction == "long":
                    risk = entry - stop
                    reward = target - entry
                else:
                    risk = stop - entry
                    reward = entry - target
                if risk > 0:
                    rr = float(reward / risk)
        except Exception:
            rr = 0.0

        mtf_alignment_score = 0.0
        try:
            feats = getattr(lux_signal, "features", {}) or {}
            if isinstance(feats, dict):
                mtf_alignment_score = float(feats.get("mtf_alignment_score", 0.0) or 0.0)
        except Exception:
            mtf_alignment_score = 0.0

        # Prefer configured bot key for later status updates.
        bot_cfg = self.bot_configs.get(bot_name, {}) or {}
        symbol = str(bot_cfg.get("symbol") or getattr(getattr(self.bots.get(bot_name), "config", None), "symbol", "") or "MNQ")
        timeframe = str(bot_cfg.get("timeframe") or getattr(getattr(self.bots.get(bot_name), "config", None), "timeframe", "") or "")

        return {
            "type": f"pearl_bot_{bot_name}",
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": lux_signal.direction,
            "confidence": lux_signal.confidence,
            "entry_price": lux_signal.entry_price,
            "stop_loss": lux_signal.stop_loss,
            "take_profit": lux_signal.take_profit,
            "risk_reward": rr,
            "mtf_alignment_score": mtf_alignment_score,
            "reason": lux_signal.reason,
            "bot_name": lux_signal.bot_name,
            "pearl_bot_key": bot_name,
            "bot_version": lux_signal.bot_version,
            "indicators_used": lux_signal.indicators_used,
            "features": lux_signal.features,
            "risk_reward_ratio": lux_signal.risk_reward_ratio,
            "position_size_pct": lux_signal.position_size_pct,
            "signal_id": lux_signal.signal_id,
            "timestamp": lux_signal.timestamp.isoformat(),
            # Additional metadata for tracking
            "pearl_bot": True,
            # Backward compatibility (deprecated)
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
        return [name for name, bot in self.bots.items() if bool(getattr(bot, "is_active", True))]

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
        logger.info("Reloading PEARL bot configurations...")
        self.bots.clear()
        self.bot_configs.clear()
        self._load_bot_configs()

    def create_default_config(self) -> Dict[str, Any]:
        """
        Create a default configuration template for PEARL bots.

        This shows users how to configure the bots in their config.yaml
        """
        return {
            "pearl_bots": {
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
                    "composite": {
                        "enabled": False,
                        "description": "Composite bot combining trend/breakout/reversal/BOS with multi-timeframe context",
                        "bot_class": "CompositeBot",
                        "symbol": "MNQ",
                        "timeframe": "1m",
                        "max_positions": 1,
                        "risk_per_trade": 0.01,
                        "stop_loss_pct": 0.006,
                        "take_profit_pct": 0.012,
                        "min_confidence": 0.70,
                        "enable_alerts": True,
                        "parameters": {
                            "timeframes": ["1m", "5m", "15m", "1h", "4h"],
                            "max_candidates": 1,
                            "require_mtf_alignment": True,
                            "indicators": {
                                "enabled": [
                                    "power_channel",
                                    "tbt_chartprime",
                                    "supply_demand_zones",
                                    "smart_money_divergence",
                                ]
                            },
                        },
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
pearl_bot_manager = PearlBotManager()


def get_pearl_bot_manager() -> PearlBotManager:
    """Get the global PEARL bot manager instance."""
    return pearl_bot_manager
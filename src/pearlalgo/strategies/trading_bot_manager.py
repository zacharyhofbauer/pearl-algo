"""
Trading Bot Manager integration layer.

Integrates a single, all-in-one AutoBot with the agent signal pipeline.
This enforces one decision stream at runtime and avoids signal merging.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.utils.logger import logger

from .pearl_bots import (
    BotConfig,
    BreakoutBot,
    MeanReversionBot,
    TradingBot,
    TrendFollowerBot,
    create_bot,
)


class TradingBotManager:
    """
    Manager for a single active trading bot (AutoBot).

    Ensures only the selected trading bot is instantiated and evaluated.
    """

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path("config")
        self.bot: Optional[TradingBot] = None
        self.bot_config: Dict[str, Any] = {}
        self.selected_name: Optional[str] = None

        # Load trading bot configuration
        self._load_trading_bot()

        if self.bot is not None:
            logger.info(f"TradingBotManager initialized with bot={self.selected_name}")
        else:
            logger.info("TradingBotManager initialized with no active bot")

    def _load_trading_bot(self) -> None:
        """Load the selected trading bot from config."""
        try:
            service_config = load_service_config(validate=False) or {}
            trading_bot_cfg = service_config.get("trading_bot") or {}

            if not trading_bot_cfg.get("enabled", False):
                logger.info("Trading bot disabled in configuration")
                return

            selected = trading_bot_cfg.get("selected")
            available = trading_bot_cfg.get("available", {}) or {}
            if not isinstance(available, dict) or not selected or selected not in available:
                logger.warning("trading_bot config missing selected/available; no bot loaded")
                return

            selected_cfg = available.get(selected) or {}
            if not selected_cfg.get("enabled", False):
                logger.warning(f"Selected trading bot is disabled: {selected}")
                return

            # Ensure bot implementations are imported (registry side-effects)
            _ = (TrendFollowerBot, BreakoutBot, MeanReversionBot)

            bot_class_name = selected_cfg.get("class") or selected_cfg.get("bot_class") or selected
            params = selected_cfg.get("parameters", {})

            config = BotConfig(
                name=str(selected),
                description=str(selected_cfg.get("description", "")),
                symbol=str(selected_cfg.get("symbol", "MNQ")),
                timeframe=str(selected_cfg.get("timeframe", "5m")),
                max_positions=int(selected_cfg.get("max_positions", 1) or 1),
                risk_per_trade=float(selected_cfg.get("risk_per_trade", 0.01) or 0.01),
                stop_loss_pct=float(selected_cfg.get("stop_loss_pct", 0.005) or 0.005),
                take_profit_pct=float(selected_cfg.get("take_profit_pct", 0.01) or 0.01),
                min_confidence=float(selected_cfg.get("min_confidence", 0.6) or 0.6),
                parameters=params if isinstance(params, dict) else {},
                enable_alerts=bool(selected_cfg.get("enable_alerts", True)),
                webhook_url=selected_cfg.get("webhook_url"),
            )

            self.selected_name = str(selected)
            self.bot_config = selected_cfg
            self.bot = create_bot(str(bot_class_name), config)

            logger.info(f"Loaded trading bot: {self.selected_name} ({bot_class_name})")
        except Exception as e:
            logger.error(f"Failed to load trading bot configuration: {e}")

    def analyze(self, market_data: Dict) -> List[Dict]:
        """
        Analyze market data with the selected trading bot.

        Returns signals in the format expected by the existing signal processing pipeline.
        """
        if self.bot is None:
            return []

        try:
            bot_signals = self.bot.analyze(market_data)
        except Exception as e:
            logger.error(f"Error analyzing with trading bot {self.selected_name}: {e}")
            return []

        signals = [self._convert_to_signal_format(signal) for signal in bot_signals]
        logger.debug(f"Generated {len(signals)} signals from trading bot {self.selected_name}")
        return signals

    def _convert_to_signal_format(self, bot_signal: Any) -> Dict:
        """
        Convert a bot signal to the agent signal dict shape.

        This ensures compatibility with the existing signal processing pipeline.
        """
        rr = 0.0
        try:
            entry = float(getattr(bot_signal, "entry_price", 0.0) or 0.0)
            stop = float(getattr(bot_signal, "stop_loss", 0.0) or 0.0)
            target = float(getattr(bot_signal, "take_profit", 0.0) or 0.0)
            direction = str(getattr(bot_signal, "direction", "long") or "long").lower()
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
            feats = getattr(bot_signal, "features", {}) or {}
            if isinstance(feats, dict):
                mtf_alignment_score = float(feats.get("mtf_alignment_score", 0.0) or 0.0)
        except Exception:
            mtf_alignment_score = 0.0

        bot_cfg = self.bot_config or {}
        symbol = str(
            bot_cfg.get("symbol")
            or getattr(getattr(self.bot, "config", None), "symbol", "")
            or "MNQ"
        )
        timeframe = str(
            bot_cfg.get("timeframe")
            or getattr(getattr(self.bot, "config", None), "timeframe", "")
            or ""
        )
        bot_name = self.selected_name or getattr(self.bot, "name", "trading_bot")

        return {
            "type": f"trading_bot_{bot_name}",
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": bot_signal.direction,
            "confidence": bot_signal.confidence,
            "entry_price": bot_signal.entry_price,
            "stop_loss": bot_signal.stop_loss,
            "take_profit": bot_signal.take_profit,
            "risk_reward": rr,
            "mtf_alignment_score": mtf_alignment_score,
            "reason": bot_signal.reason,
            "bot_name": bot_signal.bot_name,
            "trading_bot_key": bot_name,
            "bot_version": bot_signal.bot_version,
            "indicators_used": bot_signal.indicators_used,
            "features": bot_signal.features,
            "risk_reward_ratio": bot_signal.risk_reward_ratio,
            "position_size_pct": bot_signal.position_size_pct,
            "signal_id": bot_signal.signal_id,
            "timestamp": bot_signal.timestamp.isoformat(),
            # Additional metadata for tracking
            "trading_bot": True,
            "strategy_type": getattr(self.bot, "strategy_type", ""),
        }

    def update_bot_signal_status(
        self,
        bot_name: str,
        signal_id: str,
        status: str,
        execution_price: Optional[float] = None,
        exit_price: Optional[float] = None,
    ) -> None:
        """Update signal status for the selected bot."""
        if self.bot is not None and bot_name == self.selected_name:
            self.bot.update_signal_status(signal_id, status, execution_price, exit_price)

    def get_bot_performance(self, bot_name: Optional[str] = None) -> Dict[str, Any]:
        """Get performance metrics for the trading bot."""
        if self.bot is None:
            return {}
        if bot_name and bot_name != self.selected_name:
            return {}
        return {self.selected_name or "trading_bot": self.bot.get_performance_report()}

    def get_active_bots(self) -> List[str]:
        """Get list of active bot names (single bot)."""
        if self.bot is None or not self.selected_name:
            return []
        return [self.selected_name] if bool(getattr(self.bot, "is_active", True)) else []

    def enable_bot(self, bot_name: str) -> bool:
        """Enable the selected bot (no-op for others)."""
        if self.bot is not None and bot_name == self.selected_name:
            self.bot.is_active = True
            logger.info(f"Enabled trading bot: {bot_name}")
            return True
        return False

    def disable_bot(self, bot_name: str) -> bool:
        """Disable the selected bot (no-op for others)."""
        if self.bot is not None and bot_name == self.selected_name:
            self.bot.is_active = False
            logger.info(f"Disabled trading bot: {bot_name}")
            return True
        return False

    def reload_bot_configs(self) -> None:
        """Reload trading bot configuration from config files."""
        logger.info("Reloading trading bot configuration...")
        self.bot = None
        self.bot_config = {}
        self.selected_name = None
        self._load_trading_bot()

    def create_default_config(self) -> Dict[str, Any]:
        """Create a default configuration template for `trading_bot`."""
        return {
            "trading_bot": {
                "enabled": True,
                "selected": "PearlAutoBot",
                "available": {
                    "PearlAutoBot": {
                        "class": "PearlAutoBot",
                        "enabled": True,
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
                    }
                },
            }
        }


# Global trading bot manager instance
trading_bot_manager = TradingBotManager()


def get_trading_bot_manager() -> TradingBotManager:
    """Get the global trading bot manager instance."""
    return trading_bot_manager


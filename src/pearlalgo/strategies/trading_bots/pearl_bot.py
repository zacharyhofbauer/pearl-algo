"""
PearlBot - Main production trading bot

Replaces NQIntradayStrategy with a TradingBot implementation.
Integrates all nq_intraday components (scanner, signal_generator, indicators, etc.)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.config.config_loader import load_service_config

# Import nq_intraday components (will be moved/refactored later)
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.scanner import NQScanner
from pearlalgo.strategies.nq_intraday.signal_generator import NQSignalGenerator
from pearlalgo.strategies.nq_intraday.indicators import get_enabled_indicators

from .bot_template import (
    BotConfig,
    TradeSignal,
    IndicatorSuite,
    TradingBot,
    register_bot,
)


class PearlBotIndicatorSuite(IndicatorSuite):
    """Indicator suite for PearlBot - wraps nq_intraday indicators."""

    def __init__(self, config: Optional[NQIntradayConfig] = None):
        self.config = config or NQIntradayConfig()
        indicators_config = getattr(self.config, "indicators", None) or {}
        cfg_for_loader = {"indicators": indicators_config} if indicators_config else None
        self._indicators = get_enabled_indicators(cfg_for_loader)

    def calculate_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate indicator signals."""
        if df.empty:
            return {}

        df_work = df.copy()
        df_work.columns = [c.lower() for c in df_work.columns]

        signals = {}
        for ind in self._indicators:
            try:
                df_work = ind.calculate(df_work)
                latest = df_work.iloc[-1]
                ind_feats = ind.as_features(latest, df_work)
                if ind_feats:
                    signals.update(ind_feats)
            except Exception as e:
                logger.debug(f"PearlBot indicator {ind.name} failed: {e}")

        return signals

    def get_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Extract numeric features."""
        return self.calculate_signals(df)


class PearlBot(TradingBot):
    """
    PearlBot - Main production trading bot.
    
    Replaces NQIntradayStrategy. Integrates scanner, signal generator,
    and all nq_intraday components into a TradingBot interface.
    """

    def __init__(self, config: BotConfig):
        super().__init__(config)
        
        # Convert BotConfig to NQIntradayConfig for compatibility
        nq_config = self._bot_config_to_nq_config(config)
        
        # Load service config for scanner/signal_generator
        service_config = load_service_config(validate=False) or {}
        
        # Initialize nq_intraday components
        self.nq_config = nq_config
        self.scanner = NQScanner(config=nq_config, service_config=service_config)
        self.signal_generator = NQSignalGenerator(config=nq_config, scanner=self.scanner)
        
        # Initialize indicator suite
        self._indicator_suite = PearlBotIndicatorSuite(config=nq_config)

    def _bot_config_to_nq_config(self, bot_config: BotConfig) -> NQIntradayConfig:
        """Convert BotConfig to NQIntradayConfig."""
        # Start with defaults
        nq_config = NQIntradayConfig()
        
        # Map BotConfig fields to NQIntradayConfig
        if hasattr(bot_config, "symbol"):
            nq_config.symbol = bot_config.symbol
        if hasattr(bot_config, "timeframe"):
            nq_config.timeframe = bot_config.timeframe
        
        # Map parameters if they exist
        if isinstance(bot_config.parameters, dict):
            if "lookback_periods" in bot_config.parameters:
                nq_config.lookback_periods = bot_config.parameters["lookback_periods"]
            if "min_volume" in bot_config.parameters:
                nq_config.min_volume = bot_config.parameters["min_volume"]
            if "indicators" in bot_config.parameters:
                nq_config.indicators = bot_config.parameters["indicators"]
        
        return nq_config

    @property
    def name(self) -> str:
        return "PearlBot"

    @property
    def description(self) -> str:
        return "PearlBot: Main production trading bot with full nq_intraday integration"

    @property
    def strategy_type(self) -> str:
        return "intraday"

    def get_indicator_suite(self) -> IndicatorSuite:
        return self._indicator_suite

    def generate_signal_logic(
        self, df: pd.DataFrame, indicators: Dict[str, Any]
    ) -> Optional[TradeSignal]:
        """
        Generate signal using nq_intraday signal generator.
        
        Note: This method is called by TradingBot.analyze(), but PearlBot
        overrides analyze() to use the full nq_intraday pipeline instead.
        """
        # This method signature is required by TradingBot, but we override analyze()
        # to use the nq_intraday pipeline directly
        return None

    def analyze(self, market_data: Dict) -> List[Dict]:
        """
        Main analysis method - uses nq_intraday signal generator.
        
        Returns List[Dict] for compatibility with service.py.
        Also updates internal TradeSignal state for TradingBot interface.
        """
        if not self.is_active:
            return []

        try:
            # Use nq_intraday signal generator (returns List[Dict])
            dict_signals = self.signal_generator.generate(market_data)
            
            # Convert Dict signals to TradeSignal objects for internal state
            trade_signals = []
            for sig_dict in dict_signals:
                try:
                    trade_signal = self._dict_to_trade_signal(sig_dict)
                    if trade_signal:
                        trade_signals.append(trade_signal)
                except Exception as e:
                    logger.debug(f"Error converting signal to TradeSignal: {e}")
                    continue

            # Update bot state
            if trade_signals:
                self.active_signals.extend(trade_signals)
                self.signal_history.extend(trade_signals)
                self.last_analysis_time = datetime.now(timezone.utc)

            # Return Dict format for service.py compatibility
            return dict_signals

        except Exception as e:
            logger.error(f"PearlBot analyze error: {e}", exc_info=True)
            return []
    
    def analyze_as_trade_signals(self, market_data: Dict) -> List[TradeSignal]:
        """
        Analyze and return TradeSignal objects (TradingBot interface).
        
        Use this when you need TradeSignal objects instead of Dict format.
        """
        if not self.is_active:
            return []

        try:
            dict_signals = self.signal_generator.generate(market_data)
            trade_signals = []
            for sig_dict in dict_signals:
                try:
                    trade_signal = self._dict_to_trade_signal(sig_dict)
                    if trade_signal:
                        trade_signals.append(trade_signal)
                except Exception as e:
                    logger.debug(f"Error converting signal to TradeSignal: {e}")
                    continue

            if trade_signals:
                self.active_signals.extend(trade_signals)
                self.signal_history.extend(trade_signals)
                self.last_analysis_time = datetime.now(timezone.utc)

            return trade_signals

        except Exception as e:
            logger.error(f"PearlBot analyze_as_trade_signals error: {e}", exc_info=True)
            return []

    def _dict_to_trade_signal(self, sig_dict: Dict[str, Any]) -> Optional[TradeSignal]:
        """Convert nq_intraday signal Dict to TradeSignal object."""
        try:
            direction = str(sig_dict.get("direction", "")).lower()
            if direction not in ["long", "short"]:
                return None

            confidence = float(sig_dict.get("confidence", 0.0))
            entry_price = float(sig_dict.get("entry_price", 0.0))
            stop_loss = float(sig_dict.get("stop_loss", 0.0))
            take_profit = float(sig_dict.get("take_profit", 0.0))

            if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
                return None

            # Build reason string
            reason_parts = []
            if sig_dict.get("type"):
                reason_parts.append(f"Type: {sig_dict.get('type')}")
            if sig_dict.get("reason"):
                reason_parts.append(str(sig_dict.get("reason")))
            if sig_dict.get("scenario"):
                reason_parts.append(f"Scenario: {sig_dict.get('scenario')}")
            reason = "\n".join(reason_parts) if reason_parts else "PearlBot signal"

            # Extract indicators used
            indicators_used = []
            if sig_dict.get("type"):
                indicators_used.append(str(sig_dict.get("type")))
            if sig_dict.get("indicators"):
                if isinstance(sig_dict.get("indicators"), list):
                    indicators_used.extend(sig_dict.get("indicators"))
                else:
                    indicators_used.append(str(sig_dict.get("indicators")))

            # Calculate risk/reward ratio
            risk = abs(entry_price - stop_loss)
            reward = abs(take_profit - entry_price)
            risk_reward = reward / risk if risk > 0 else 0.0

            # Extract features
            features = {}
            for key in ["regime", "quality_score", "volume_pressure", "order_flow"]:
                if key in sig_dict:
                    val = sig_dict[key]
                    if isinstance(val, (int, float)):
                        features[key] = float(val)
                    elif isinstance(val, dict):
                        # Flatten dict features
                        for k, v in val.items():
                            if isinstance(v, (int, float)):
                                features[f"{key}_{k}"] = float(v)

            # Get position size
            position_size_pct = float(sig_dict.get("position_size_pct", 0.01))
            if "position_size" in sig_dict:
                # Convert contracts to percentage if needed
                pass  # Keep default for now

            # Market regime info
            market_regime = None
            regime_confidence = 0.0
            if isinstance(sig_dict.get("regime"), dict):
                regime_dict = sig_dict.get("regime", {})
                market_regime = str(regime_dict.get("type", ""))
                regime_confidence = float(regime_dict.get("confidence", 0.0))

            trade_signal = TradeSignal(
                direction=direction,
                confidence=confidence,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                bot_name=self.name,
                bot_version=self.config.version,
                reason=reason,
                indicators_used=indicators_used,
                features=features,
                risk_reward_ratio=risk_reward,
                position_size_pct=position_size_pct,
                market_regime=market_regime,
                regime_confidence=regime_confidence,
            )

            return trade_signal

        except Exception as e:
            logger.error(f"Error converting signal dict: {e}", exc_info=True)
            return None
    
    def get_config(self) -> NQIntradayConfig:
        """Get strategy configuration (for compatibility with service.py)."""
        return self.nq_config


# Register the bot
register_bot(PearlBot)

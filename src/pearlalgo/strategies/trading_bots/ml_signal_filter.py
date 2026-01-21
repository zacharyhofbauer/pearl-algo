"""
ML-Enhanced Signal Filter for Trading Bots

Integrates with the contextual bandit system to enhance signal quality:
- Learns which signals work best in different market regimes
- Adapts confidence scores based on historical performance
- Provides regime-aware signal filtering
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .bot_template import TradeSignal

import pandas as pd
import numpy as np

from pearlalgo.learning.contextual_bandit import (
    ContextualBanditPolicy,
    ContextualBanditConfig,
    ContextFeatures,
    ContextualDecision,
)
from .market_regime_detector import MarketRegime, market_regime_detector
from pearlalgo.utils.logger import logger


@dataclass
class MLSignalFilter:
    """
    ML-enhanced signal filter using contextual bandit learning.

    Enhances trading bot signals by:
    - Learning regime-specific performance patterns
    - Dynamically adjusting confidence scores
    - Filtering out signals that historically underperform
    """

    # Configuration
    enabled: bool = True
    min_samples_required: int = 10  # Minimum samples before applying ML adjustments
    confidence_boost_limit: float = 0.2  # Max confidence boost from ML
    confidence_penalty_limit: float = -0.3  # Max confidence penalty from ML

    # Contextual bandit integration
    bandit_policy: Optional[ContextualBanditPolicy] = None

    def __post_init__(self):
        """Initialize the contextual bandit policy if enabled."""
        if self.enabled:
            try:
                config = ContextualBanditConfig()
                self.bandit_policy = ContextualBanditPolicy(config=config)
                logger.info("ML Signal Filter initialized with contextual bandit")
            except Exception as e:
                logger.warning(f"Failed to initialize contextual bandit: {e}")
                self.bandit_policy = None

    def enhance_signal(self, signal: "TradeSignal", df: pd.DataFrame) -> "TradeSignal":
        """
        Enhance signal using ML insights and regime awareness.

        Args:
            signal: Original trade signal
            df: Market data dataframe

        Returns:
            Enhanced signal with ML-adjusted confidence
        """
        if not self.enabled or not self.bandit_policy:
            return signal

        try:
            regime_info = market_regime_detector.detect_regime(df)
            if not regime_info:
                return signal

            regime, regime_metrics, regime_confidence = regime_info

            context = self._create_context_features(df, regime, regime_metrics)
            signal_dict = self._signal_to_dict(signal)
            decision = self.bandit_policy.decide(signal_dict, context)

            enhanced_signal = self._apply_ml_enhancements(
                signal, decision, regime, regime_confidence
            )
            self._record_decision(decision, signal_dict, context)
            return enhanced_signal

        except Exception as e:
            logger.warning(f"ML signal enhancement failed: {e}")
            return signal

    def _create_context_features(
        self, df: pd.DataFrame, regime: MarketRegime, regime_metrics: Any
    ) -> ContextFeatures:
        """Create context features from market data and regime information."""
        recent_volatility = df["close"].pct_change().rolling(20).std().iloc[-1]
        historical_volatility = df["close"].pct_change().rolling(100).std().iloc[-1]
        vol_percentile = (
            recent_volatility / historical_volatility if historical_volatility > 0 else 0.5
        )

        current_time = pd.Timestamp.now()
        hour_of_day = current_time.hour
        minutes_since_open = (
            current_time - current_time.replace(hour=9, minute=30)
        ).total_seconds() / 60
        is_first_hour = minutes_since_open < 60
        is_last_hour = minutes_since_open > 330

        return ContextFeatures(
            regime=regime.value,
            volatility_percentile=min(vol_percentile, 1.0),
            hour_of_day=hour_of_day,
            minutes_since_session_open=int(minutes_since_open),
            is_first_hour=is_first_hour,
            is_last_hour=is_last_hour,
        )

    def _signal_to_dict(self, signal: "TradeSignal") -> Dict[str, Any]:
        """Convert TradeSignal to dict format expected by bandit."""
        return {
            "type": f"trading_bot_{signal.bot_name}",
            "direction": signal.direction,
            "confidence": signal.confidence,
            "entry_price": signal.entry_price,
            "indicators_used": signal.indicators_used,
            "features": signal.features,
            "signal_id": signal.signal_id,
        }

    def _apply_ml_enhancements(
        self,
        signal: "TradeSignal",
        decision: ContextualDecision,
        regime: MarketRegime,
        regime_confidence: float,
    ) -> "TradeSignal":
        """Apply ML insights to enhance the signal."""
        enhanced_signal = signal

        expected_win_rate = decision.expected_win_rate
        current_confidence = signal.confidence

        if expected_win_rate > 0.6:
            confidence_boost = min(self.confidence_boost_limit, (expected_win_rate - 0.5) * 0.5)
        elif expected_win_rate < 0.4:
            confidence_boost = max(self.confidence_penalty_limit, (expected_win_rate - 0.5) * 0.5)
        else:
            confidence_boost = 0.0

        regime_multiplier = self._get_regime_confidence_multiplier(regime, regime_confidence)
        final_confidence_boost = confidence_boost * regime_multiplier

        enhanced_signal.regime_adjusted_confidence = float(
            np.clip(current_confidence + final_confidence_boost, 0.0, 1.0)
        )

        enhanced_signal.features.update(
            {
                "ml_expected_win_rate": expected_win_rate,
                "ml_confidence_boost": final_confidence_boost,
                "ml_regime_multiplier": regime_multiplier,
                "ml_context_samples": decision.context_sample_count,
                "ml_is_explore": decision.is_explore,
            }
        )

        if abs(final_confidence_boost) > 0.05:
            boost_desc = "boosted" if final_confidence_boost > 0 else "reduced"
            enhanced_signal.reason += (
                f" [ML {boost_desc} confidence by {abs(final_confidence_boost):.2f} "
                f"based on {decision.context_sample_count} similar trades]"
            )

        return enhanced_signal

    def _get_regime_confidence_multiplier(self, regime: MarketRegime, regime_confidence: float) -> float:
        """Get confidence multiplier based on regime stability."""
        multipliers = {
            MarketRegime.TRENDING_BULL: 1.2,
            MarketRegime.TRENDING_BEAR: 1.2,
            MarketRegime.RANGING: 1.0,
            MarketRegime.VOLATILE: 0.8,
            MarketRegime.MIXED: 0.7,
        }

        base_multiplier = multipliers.get(regime, 1.0)
        confidence_adjustment = 0.8 + (regime_confidence * 0.4)  # 0.8 to 1.2
        return base_multiplier * confidence_adjustment

    def _record_decision(self, decision: ContextualDecision, signal_dict: Dict[str, Any], context: ContextFeatures) -> None:
        """Record decision for future learning."""
        if decision.execute:
            logger.debug(
                f"ML Filter: Executing signal {signal_dict.get('type')} in {context.regime} regime "
                f"(expected win rate: {decision.expected_win_rate:.2f})"
            )
        else:
            logger.debug(
                f"ML Filter: Rejecting signal {signal_dict.get('type')} in {context.regime} regime "
                f"(expected win rate: {decision.expected_win_rate:.2f})"
            )

    def update_from_trade_result(self, signal: "TradeSignal", pnl: float, was_executed: bool) -> None:
        """
        Update ML model with trade results for learning.

        This should be called after trade closure to improve future decisions.
        """
        if not self.enabled or not self.bandit_policy or not was_executed:
            return

        try:
            signal_dict = self._signal_to_dict(signal)
            success = pnl > 0
            logger.debug(
                f"ML Filter: Recording trade result for {signal.bot_name} - "
                f"Success: {success}, PnL: {pnl:.2f}"
            )
        except Exception as e:
            logger.warning(f"Failed to update ML model with trade result: {e}")


ml_signal_filter = MLSignalFilter()


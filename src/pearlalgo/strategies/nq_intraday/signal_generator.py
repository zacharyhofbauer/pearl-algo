"""
NQ Intraday Signal Generator

Generates trading signals from scanner results with validation and filtering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from pearlalgo.utils.logger import logger

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.scanner import NQScanner
from pearlalgo.strategies.nq_intraday.signal_quality import SignalQualityScorer

# Central policy layer (v2.1): single place for allow/deny rules (min_conf, min_rr, regime/session)
try:
    from pearlalgo.policy.signal_policy import SignalPolicy
    POLICY_AVAILABLE = True
except Exception:
    POLICY_AVAILABLE = False
    SignalPolicy = None  # type: ignore

# Feature engineering for ML integration (optional)
try:
    from pearlalgo.learning.feature_engineer import FeatureEngineer, FeatureConfig
    FEATURE_ENGINEER_AVAILABLE = True
except ImportError:
    FEATURE_ENGINEER_AVAILABLE = False
    FeatureEngineer = None  # type: ignore
    FeatureConfig = None  # type: ignore

# ML signal filter (optional - v2.0 adaptive risk management)
try:
    from pearlalgo.learning.ml_signal_filter import (
        MLSignalFilter,
        MLFilterConfig,
        get_ml_signal_filter,
    )
    ML_FILTER_AVAILABLE = True
except ImportError:
    ML_FILTER_AVAILABLE = False
    MLSignalFilter = None  # type: ignore
    MLFilterConfig = None  # type: ignore
    get_ml_signal_filter = None  # type: ignore

# Adaptive position sizing (optional - v2.0 adaptive risk management)
try:
    from pearlalgo.strategies.nq_intraday.adaptive_sizing import (
        AdaptivePositionSizer,
        get_adaptive_position_sizer,
    )
    ADAPTIVE_SIZING_AVAILABLE = True
except ImportError:
    ADAPTIVE_SIZING_AVAILABLE = False
    AdaptivePositionSizer = None  # type: ignore
    get_adaptive_position_sizer = None  # type: ignore


@dataclass
class SignalDiagnostics:
    """Per-cycle diagnostics for signal generation.
    
    Tracks why signals were or weren't generated for observability.
    """
    
    # Counts
    raw_signals: int = 0
    validated_signals: int = 0
    actionable_signals: int = 0  # A-tier (meets standard thresholds)
    explore_signals: int = 0     # B-tier (looser thresholds, clearly labeled)
    duplicates_filtered: int = 0
    stop_cap_applied: int = 0  # Signals where stop was capped
    session_scaling_applied: int = 0  # Signals with session-based position scaling
    
    # Rejection reasons
    rejected_market_hours: bool = False  # Filtered by market hours gate
    rejected_confidence: int = 0  # Below min_confidence
    rejected_risk_reward: int = 0  # Below min_risk_reward
    rejected_quality_scorer: int = 0  # Failed quality score threshold
    rejected_order_book: int = 0  # Filtered by order book imbalance
    rejected_invalid_prices: int = 0  # Invalid entry/stop/target prices
    rejected_regime_filter: int = 0  # Filtered by regime/session filter
    rejected_ml_filter: int = 0  # Filtered by ML signal filter (v2.0)
    adaptive_sizing_applied: int = 0  # Signals with adaptive sizing (v2.0)
    
    # Scanner gate reasons (from NQScanner.get_gate_reasons())
    scanner_gate_reasons: List[str] = field(default_factory=list)
    regime_filter_reasons: List[str] = field(default_factory=list)  # Reasons for regime filter rejections
    
    # Context
    market_hours_checked: bool = False
    order_book_available: bool = False
    timestamp: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for state persistence."""
        return {
            "raw_signals": self.raw_signals,
            "validated_signals": self.validated_signals,
            "actionable_signals": self.actionable_signals,
            "explore_signals": self.explore_signals,
            "duplicates_filtered": self.duplicates_filtered,
            "stop_cap_applied": self.stop_cap_applied,
            "session_scaling_applied": self.session_scaling_applied,
            "rejected_market_hours": self.rejected_market_hours,
            "rejected_confidence": self.rejected_confidence,
            "rejected_risk_reward": self.rejected_risk_reward,
            "rejected_quality_scorer": self.rejected_quality_scorer,
            "rejected_order_book": self.rejected_order_book,
            "rejected_invalid_prices": self.rejected_invalid_prices,
            "rejected_regime_filter": self.rejected_regime_filter,
            "rejected_ml_filter": self.rejected_ml_filter,
            "adaptive_sizing_applied": self.adaptive_sizing_applied,
            "scanner_gate_reasons": self.scanner_gate_reasons,
            "regime_filter_reasons": self.regime_filter_reasons,
            "market_hours_checked": self.market_hours_checked,
            "order_book_available": self.order_book_available,
            "timestamp": self.timestamp,
        }
    
    def format_compact(self) -> str:
        """
        Format as compact string for Telegram dashboard.
        
        Returns a one-line summary like:
        "Raw: 3 → Valid: 1 | Filtered: 1 dup, 1 conf"
        
        Or for gated scans:
        "Gated: Low volume (42 < 100)"
        """
        if self.rejected_market_hours:
            return "Session closed"
        
        if self.raw_signals == 0:
            # Show scanner gate reasons if available (more informative than "No patterns")
            if self.scanner_gate_reasons:
                # Show first gate reason (most relevant, typically volume or volatility)
                reason = self.scanner_gate_reasons[0]
                # Truncate long reasons for compact display
                if len(reason) > 50:
                    reason = reason[:47] + "..."
                return f"Gated: {reason}"
            return "No patterns detected"
        
        parts = []
        
        # Main flow
        parts.append(f"Raw: {self.raw_signals}")
        if self.validated_signals > 0:
            suffix = ""
            if self.explore_signals > 0 or self.actionable_signals > 0:
                # Compact A/B breakdown (keeps dashboard readable)
                suffix = f" (A{self.actionable_signals}/B{self.explore_signals})"
            parts.append(f"→ Valid: {self.validated_signals}{suffix}")
        
        # Rejections
        rejections = []
        if self.duplicates_filtered > 0:
            rejections.append(f"{self.duplicates_filtered} dup")
        if self.rejected_confidence > 0:
            rejections.append(f"{self.rejected_confidence} conf")
        if self.rejected_risk_reward > 0:
            rejections.append(f"{self.rejected_risk_reward} R:R")
        if self.rejected_quality_scorer > 0:
            rejections.append(f"{self.rejected_quality_scorer} qual")
        if self.rejected_order_book > 0:
            rejections.append(f"{self.rejected_order_book} OB")
        if self.rejected_invalid_prices > 0:
            rejections.append(f"{self.rejected_invalid_prices} price")
        if self.rejected_regime_filter > 0:
            rejections.append(f"{self.rejected_regime_filter} regime")
        
        if rejections:
            parts.append(f"| Filtered: {', '.join(rejections)}")
        
        # Note stop cap applications
        if self.stop_cap_applied > 0:
            parts.append(f"| {self.stop_cap_applied} stop-capped")
        
        # Note session scaling applications
        if self.session_scaling_applied > 0:
            parts.append(f"| {self.session_scaling_applied} session-scaled")
        
        return " ".join(parts)
    
    def format_detailed(self) -> str:
        """
        Format as detailed multi-line string for dashboard diagnostics section.
        
        Returns a multi-line summary with all gate reasons and rejection counts.
        """
        lines = []
        
        if self.rejected_market_hours:
            lines.append("Session closed (outside market hours)")
            return "\n".join(lines)
        
        # Signal flow
        lines.append(f"Scanner: {self.raw_signals} raw signals")
        if self.validated_signals > 0:
            lines.append(
                f"Validated: {self.validated_signals} signals "
                f"(A-tier: {self.actionable_signals}, B-tier: {self.explore_signals})"
            )
        
        # Scanner gate reasons (if no raw signals)
        if self.raw_signals == 0 and self.scanner_gate_reasons:
            lines.append("Gate reasons:")
            for reason in self.scanner_gate_reasons[:3]:  # Limit to 3 for brevity
                lines.append(f"  • {reason}")
        
        # Rejection breakdown (if any raw signals)
        if self.raw_signals > 0:
            rejections = []
            if self.rejected_confidence > 0:
                rejections.append(f"Confidence: {self.rejected_confidence}")
            if self.rejected_risk_reward > 0:
                rejections.append(f"R:R ratio: {self.rejected_risk_reward}")
            if self.rejected_quality_scorer > 0:
                rejections.append(f"Quality score: {self.rejected_quality_scorer}")
            if self.rejected_order_book > 0:
                rejections.append(f"Order book: {self.rejected_order_book}")
            if self.rejected_invalid_prices > 0:
                rejections.append(f"Invalid prices: {self.rejected_invalid_prices}")
            if self.duplicates_filtered > 0:
                rejections.append(f"Duplicates: {self.duplicates_filtered}")
            if self.rejected_regime_filter > 0:
                rejections.append(f"Regime filter: {self.rejected_regime_filter}")
            
            if rejections:
                lines.append("Filtered out:")
                for rej in rejections:
                    lines.append(f"  • {rej}")
        
        # Note stop cap applications
        if self.stop_cap_applied > 0:
            lines.append(f"Stop-capped: {self.stop_cap_applied} signals")
        
        # Note session scaling applications
        if self.session_scaling_applied > 0:
            lines.append(f"Session-scaled: {self.session_scaling_applied} signals")
        
        return "\n".join(lines) if lines else "No diagnostic data"


class NQSignalGenerator:
    """Signal generator for MNQ intraday strategy.

    Processes scanner results and generates validated trading signals.
    """

    def __init__(
        self,
        config: Optional[NQIntradayConfig] = None,
        scanner: Optional[NQScanner] = None,
    ):
        """Initialize signal generator.

        Args:
            config: Configuration instance (optional)
            scanner: Scanner instance (optional, creates new if not provided)
        """
        self.config = config or NQIntradayConfig()

        # Load signal configuration early so the scanner can initialize adaptive modules
        # (adaptive stops, market depth, etc.) with the canonical config source.
        service_config = load_service_config()

        self.scanner = scanner or NQScanner(config=self.config, service_config=service_config)
        # Quality scorer: Lower threshold (0.45) to allow more signals in quiet regimes
        # Your 7W/9L ~44% win rate is profitable with proper R:R, so 0.55 was too strict
        # Lower threshold (0.20) to bootstrap outcome tracking - historical data is broken (all "unknown")
        # Once outcome tracking is fixed, can raise back to 0.45
        self.quality_scorer = SignalQualityScorer(min_edge_threshold=0.20)

        # Load signal configuration
        signal_settings = service_config.get("signals", {})

        # Central policy (allow/deny) - keeps signal_generator rules from drifting.
        self._policy: Optional["SignalPolicy"] = None
        if POLICY_AVAILABLE and SignalPolicy is not None:
            try:
                self._policy = SignalPolicy(service_config)
            except Exception:
                self._policy = None

        # Track recent signals to avoid duplicates
        self._recent_signals: List[Dict] = []
        self._signal_window_seconds = signal_settings.get("duplicate_window_seconds", 300)
        self._min_confidence = signal_settings.get("min_confidence", 0.50)
        self._min_risk_reward = signal_settings.get("min_risk_reward", 1.5)
        self._duplicate_price_threshold_pct = (
            signal_settings.get("duplicate_price_threshold_pct", 0.5) / 100.0
        )
        
        # Restore recent signals from file on startup (if available)
        self._restore_recent_signals_from_file()
        
        # Composite quality score filter (NO CAPS - purely quality-driven)
        quality_score_settings = signal_settings.get("quality_score", {}) or {}
        self._quality_score_enabled = bool(quality_score_settings.get("enabled", False))
        self._quality_score_threshold = float(quality_score_settings.get("threshold", 0.85))
        quality_factors = quality_score_settings.get("factors", {}) or {}
        self._quality_confidence_weight = float(quality_factors.get("confidence_weight", 0.30))
        self._quality_risk_reward_weight = float(quality_factors.get("risk_reward_weight", 0.25))
        self._quality_regime_alignment_weight = float(quality_factors.get("regime_alignment_weight", 0.20))
        self._quality_volume_profile_weight = float(quality_factors.get("volume_profile_weight", 0.15))
        self._quality_mtf_alignment_weight = float(quality_factors.get("mtf_alignment_weight", 0.10))
        
        # Swing trade detection
        swing_settings = service_config.get("swing_trading", {}) or {}
        self._swing_trading_enabled = bool(swing_settings.get("enabled", False))
        self._swing_min_confidence = float(swing_settings.get("min_confidence", 0.90))
        self._swing_min_target_points = float(swing_settings.get("min_target_points", 30))
        self._swing_min_mtf_alignment = float(swing_settings.get("min_mtf_alignment", 0.80))
        self._swing_min_volume_ratio = float(swing_settings.get("min_volume_ratio", 1.2))
        
        # Stop-cap configuration (risk control)
        # If > 0, caps stop distance in points and scales target to preserve RR
        self._max_stop_points = signal_settings.get("max_stop_points", 0.0)
        
        # Target RR ratio from risk config (for stop-cap target scaling)
        risk_settings = service_config.get("risk", {}) or {}
        self._take_profit_risk_reward = risk_settings.get("take_profit_risk_reward", 1.5)

        # Per-signal-type position sizing overrides (do NOT change trade count; min contracts stays >= 1).
        # Use-case: keep a signal family enabled but cap its size hard.
        self._signal_type_size_multipliers: Dict[str, float] = (
            risk_settings.get("signal_type_size_multipliers", {}) or {}
        )
        self._signal_type_max_contracts: Dict[str, int] = (
            risk_settings.get("signal_type_max_contracts", {}) or {}
        )
        
        # Per-signal-type regime/session filters
        # Format: { "signal_type": { "allowed_regimes": [...], "disallowed_regimes": [...], ... } }
        self._regime_filters: Dict = signal_settings.get("regime_filters", {})

        # Optional: "Opportunity tier" mode for 24h futures (Asia/London/NY).
        # A-tier = current strict filters; B-tier = looser thresholds but clearly labeled as Explore.
        explore_settings = signal_settings.get("explore", {})
        if not isinstance(explore_settings, dict):
            explore_settings = {}
        self._explore_enabled = bool(explore_settings.get("enabled", False))
        self._explore_min_confidence = float(
            explore_settings.get("min_confidence", max(0.0, float(self._min_confidence) - 0.05))
        )
        self._explore_min_risk_reward = float(
            explore_settings.get("min_risk_reward", max(0.0, float(self._min_risk_reward) - 0.2))
        )
        self._explore_include_quality_rejects = bool(explore_settings.get("include_quality_rejects", True))
        self._explore_bypass_regime_filters = bool(explore_settings.get("bypass_regime_filters", False))
        self._explore_max_signals_per_hour = int(explore_settings.get("max_signals_per_hour", 0))  # 0 = unlimited
        self._explore_emitted_times: List[datetime] = []

        # Per-cycle diagnostics for observability
        self.last_diagnostics: Optional[SignalDiagnostics] = None

        # Feature engineer for ML integration (optional)
        self._feature_engineer: Optional["FeatureEngineer"] = None
        self._feature_engineer_enabled = False
        
        learning_settings = service_config.get("learning", {}) or {}
        if FEATURE_ENGINEER_AVAILABLE and learning_settings.get("feature_engineer_enabled", False):
            try:
                feature_config_dict = learning_settings.get("features", {}) or {}
                feature_config = FeatureConfig.from_dict(feature_config_dict)
                self._feature_engineer = FeatureEngineer(config=feature_config)
                self._feature_engineer_enabled = True
                logger.info("Feature engineer enabled for ML signal features")
            except Exception as e:
                logger.warning(f"Could not initialize feature engineer: {e}")
                self._feature_engineer = None

        # ML Signal Filter (v2.0 adaptive risk management)
        self._ml_filter: Optional["MLSignalFilter"] = None
        self._ml_filter_enabled = False
        self._ml_filter_mode: str = "shadow"  # "shadow" (score-only) or "live" (can block)
        self._ml_require_lift_to_block: bool = True
        
        ml_filter_settings = service_config.get("ml_filter", {}) or {}
        if ML_FILTER_AVAILABLE and ml_filter_settings.get("enabled", False):
            try:
                self._ml_filter = get_ml_signal_filter(service_config)
                self._ml_filter_enabled = True
                # Mode defaults to shadow for safety (score-only; see MLFilterConfig).
                try:
                    self._ml_filter_mode = str(ml_filter_settings.get("mode", "shadow") or "shadow").lower()
                except Exception:
                    self._ml_filter_mode = "shadow"
                if self._ml_filter_mode not in ("shadow", "live"):
                    self._ml_filter_mode = "shadow"
                self._ml_require_lift_to_block = bool(ml_filter_settings.get("require_lift_to_block", True))
                logger.info("ML signal filter enabled")
            except Exception as e:
                logger.warning(f"Could not initialize ML signal filter: {e}")
                self._ml_filter = None

        # Paper-mode detection (used for ML gating in paper-only operation).
        execution_settings = service_config.get("execution", {}) or {}
        exec_enabled = bool(execution_settings.get("enabled", False))
        exec_mode = str(execution_settings.get("mode", "") or "").lower()
        self._paper_mode = (not exec_enabled) or (exec_mode in ("dry_run", "paper", "paper_only"))
        
        # Adaptive Position Sizer (v2.0 adaptive risk management)
        self._adaptive_sizer: Optional["AdaptivePositionSizer"] = None
        self._adaptive_sizing_enabled = False
        
        adaptive_sizing_settings = service_config.get("adaptive_sizing", {}) or {}
        if ADAPTIVE_SIZING_AVAILABLE and adaptive_sizing_settings.get("enabled", False):
            try:
                self._adaptive_sizer = get_adaptive_position_sizer(service_config)
                self._adaptive_sizing_enabled = True
                logger.info("Adaptive position sizer enabled")
            except Exception as e:
                logger.warning(f"Could not initialize adaptive sizer: {e}")
                self._adaptive_sizer = None
        
        logger.info(
            "NQSignalGenerator initialized (max_stop_points=%.1f, regime_filters=%d types, "
            "feature_engineer=%s, ml_filter=%s, adaptive_sizing=%s, quality_score=%s, swing_trading=%s, paper_mode=%s)",
            self._max_stop_points,
            len(self._regime_filters),
            "enabled" if self._feature_engineer_enabled else "disabled",
            "enabled" if self._ml_filter_enabled else "disabled",
            "enabled" if self._adaptive_sizing_enabled else "disabled",
            "enabled" if self._quality_score_enabled else "disabled",
            "enabled" if self._swing_trading_enabled else "disabled",
            "yes" if self._paper_mode else "no",
        )

    def _calculate_composite_quality_score(self, signal: Dict, market_data: Dict) -> float:
        """Calculate composite quality score combining multiple factors.
        
        Args:
            signal: Signal dictionary
            market_data: Market data dictionary with df and context
            
        Returns:
            Composite quality score (0.0 to 1.0)
        """
        if not self._quality_score_enabled:
            return 1.0  # If disabled, don't filter
        
        # Factor 1: Confidence (0-1, normalized)
        confidence = float(signal.get("confidence", 0.0))
        confidence_score = min(1.0, confidence)  # Already 0-1
        
        # Factor 2: Risk:Reward ratio (normalize to 0-1, assume max R:R is 5.0)
        risk_reward = float(signal.get("risk_reward", 0.0))
        rr_score = min(1.0, risk_reward / 5.0)  # Normalize: 5.0 R:R = 1.0 score
        
        # Factor 3: Regime alignment (0-1)
        regime = signal.get("regime", {})
        regime_type = regime.get("type", "unknown") if isinstance(regime, dict) else "unknown"
        regime_favorability = regime.get("favorability", 0.5) if isinstance(regime, dict) else 0.5
        # Check if signal type is allowed in current regime
        signal_type = signal.get("type", "")
        allowed_regimes = self._regime_filters.get(signal_type, {}).get("allowed_regimes", [])
        if allowed_regimes and regime_type in allowed_regimes:
            regime_score = 1.0
        elif regime_favorability > 0.7:
            regime_score = 0.8
        elif regime_favorability > 0.5:
            regime_score = 0.6
        else:
            regime_score = 0.4
        
        # Factor 4: Volume profile confirmation (0-1)
        # Use volume ratio if available, otherwise default to 0.5
        volume_ratio = float(signal.get("volume_ratio", 1.0))
        if volume_ratio >= 1.5:
            volume_score = 1.0
        elif volume_ratio >= 1.2:
            volume_score = 0.8
        elif volume_ratio >= 1.0:
            volume_score = 0.6
        else:
            volume_score = 0.4
        
        # Factor 5: Multi-timeframe alignment (0-1)
        mtf_alignment = float(signal.get("mtf_alignment_score", 0.5))
        mtf_score = mtf_alignment  # Already 0-1
        
        # Weighted composite score
        composite_score = (
            confidence_score * self._quality_confidence_weight +
            rr_score * self._quality_risk_reward_weight +
            regime_score * self._quality_regime_alignment_weight +
            volume_score * self._quality_volume_profile_weight +
            mtf_score * self._quality_mtf_alignment_weight
        )
        
        return composite_score

    def _classify_trade_type(self, signal: Dict, market_data: Dict) -> str:
        """Classify trade as swing or scalp based on multiple factors.
        
        Args:
            signal: Signal dictionary
            market_data: Market data dictionary
            
        Returns:
            'swing' or 'scalp'
        """
        if not self._swing_trading_enabled:
            return "scalp"
        
        # Check all swing criteria
        confidence = float(signal.get("confidence", 0.0))
        if confidence < self._swing_min_confidence:
            return "scalp"
        
        # Calculate target points
        entry = float(signal.get("entry_price", 0))
        target = float(signal.get("take_profit", 0))
        if entry > 0 and target > 0:
            target_points = abs(target - entry)
        else:
            # Estimate from risk:reward
            stop = float(signal.get("stop_loss", 0))
            risk_points = abs(entry - stop) if entry > 0 and stop > 0 else 10.0
            risk_reward = float(signal.get("risk_reward", 1.5))
            target_points = risk_points * risk_reward
        
        if target_points < self._swing_min_target_points:
            return "scalp"
        
        # Check regime (must be trending)
        regime = signal.get("regime", {})
        regime_type = regime.get("type", "unknown") if isinstance(regime, dict) else "unknown"
        if regime_type not in ["trending_bullish", "trending_bearish"]:
            return "scalp"
        
        # Check MTF alignment
        mtf_alignment = float(signal.get("mtf_alignment_score", 0.0))
        if mtf_alignment < self._swing_min_mtf_alignment:
            return "scalp"
        
        # Check volume ratio
        volume_ratio = float(signal.get("volume_ratio", 1.0))
        if volume_ratio < self._swing_min_volume_ratio:
            return "scalp"
        
        # All criteria met - classify as swing
        return "swing"

    def generate(self, market_data: Dict) -> List[Dict]:
        """Generate trading signals from market data.

        Args:
            market_data: Dictionary with 'df' (DataFrame) and optionally 'latest_bar' (Dict)

        Returns:
            List of validated signal dictionaries
        """
        # Initialize diagnostics for this cycle
        diagnostics = SignalDiagnostics(
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        df = market_data.get("df")
        if df is None or df.empty:
            self.last_diagnostics = diagnostics
            return []

        # Drift guard (risk-off cooldown) adjustments, provided by the service.
        # This can temporarily tighten thresholds + reduce sizing when conditions degrade.
        drift_state = market_data.get("drift_guard") if isinstance(market_data, dict) else None
        drift_adj = {}
        drift_active = False
        try:
            if isinstance(drift_state, dict):
                drift_active = bool(drift_state.get("active", False))
                drift_adj = drift_state.get("adjustments", {}) if isinstance(drift_state.get("adjustments", {}), dict) else {}
        except Exception:
            drift_active = False
            drift_adj = {}

        try:
            eff_min_conf = float(self._min_confidence) + float(drift_adj.get("min_confidence_delta", 0.0) or 0.0)
        except Exception:
            eff_min_conf = float(self._min_confidence)
        try:
            eff_min_rr = float(self._min_risk_reward) + float(drift_adj.get("min_risk_reward_delta", 0.0) or 0.0)
        except Exception:
            eff_min_rr = float(self._min_risk_reward)
        try:
            drift_size_mult = float(drift_adj.get("size_multiplier", 1.0) or 1.0)
        except Exception:
            drift_size_mult = 1.0

        # Check market hours using the *bar timestamp* (critical for backtests).
        # If we don't pass a datetime, the scanner defaults to "now", which makes
        # backtests depend on current wall-clock time.
        dt = None
        latest_bar = market_data.get("latest_bar") if isinstance(market_data, dict) else None
        ts = latest_bar.get("timestamp") if isinstance(latest_bar, dict) else None
        if ts:
            try:
                dt = pd.to_datetime(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                dt = None
        if dt is None and isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0:
            # Fallback to latest dataframe timestamp
            try:
                dt = df.index[-1].to_pydatetime() if hasattr(df.index[-1], "to_pydatetime") else df.index[-1]
            except Exception:
                dt = None

        diagnostics.market_hours_checked = True
        if not self.scanner.is_market_hours(dt):
            diagnostics.rejected_market_hours = True
            self.last_diagnostics = diagnostics
            return []

        # Get multi-timeframe data
        df_5m = market_data.get("df_5m")
        df_15m = market_data.get("df_15m")

        # Scan for signals with MTF context and order book data
        raw_signals = self.scanner.scan(df, df_5m=df_5m, df_15m=df_15m, market_data=market_data)

        # Track raw signal count for diagnostics
        diagnostics.raw_signals = len(raw_signals)
        
        # Capture scanner gate reasons for "why no signals" diagnostics
        diagnostics.scanner_gate_reasons = self.scanner.get_gate_reasons()

        # Log raw signal count at INFO level for observability
        logger.info(f"Raw signals from scanner: {len(raw_signals)}")

        # Diagnostic logging: log raw signals
        if raw_signals:
            logger.debug(f"Raw signals generated: {len(raw_signals)}")
            for raw_signal in raw_signals:
                logger.debug(
                    "Raw signal: type=%s, direction=%s, confidence=%.3f, entry=%.2f",
                    raw_signal.get("type"),
                    raw_signal.get("direction"),
                    raw_signal.get("confidence", 0.0),
                    raw_signal.get("entry_price", 0.0),
                )

        # Get order book data for signal filtering
        latest_bar = market_data.get("latest_bar")
        order_book_available = (
            latest_bar
            and latest_bar.get("order_book")
            and latest_bar["order_book"].get("bids")
        )
        diagnostics.order_book_available = order_book_available

        # B-tier ("explore") anti-spam throttle: cap how many explore signals we emit per hour.
        # This is important for 24/7 futures where looser thresholds can otherwise flood Telegram.
        def _explore_has_capacity(now_utc: datetime) -> bool:
            if not self._explore_enabled:
                return False
            max_per_hour = int(self._explore_max_signals_per_hour or 0)
            if max_per_hour <= 0:
                return True
            # Keep only emissions within the last hour
            self._explore_emitted_times = [
                t for t in self._explore_emitted_times
                if (now_utc - t).total_seconds() < 3600
            ]
            return len(self._explore_emitted_times) < max_per_hour

        # Validate and filter signals
        validated_signals = []
        for signal in raw_signals:
            # Opportunity tier defaults per-signal (A-tier actionable unless promoted to B-tier explore)
            opportunity_tier = "A"
            opportunity_reason = ""

            # Central policy gate (v2.1). This includes min_conf/min_rr + regime/session allow-lists.
            # We still preserve explore-mode behavior for near-misses.
            if self._policy is not None:
                decision = self._policy.evaluate(
                    signal,
                    min_confidence=eff_min_conf,
                    min_risk_reward=eff_min_rr,
                )
                if not decision.allowed:
                    # Explore-mode bypass for regime/session only (if enabled)
                    if (
                        self._explore_enabled
                        and getattr(self, "_explore_bypass_regime_filters", False)
                        and decision.reason in ("regime", "regime_forbidden", "session")
                    ):
                        opportunity_tier = "B"
                        opportunity_reason = str(decision.reason)
                    else:
                        if decision.reason in ("regime", "regime_forbidden", "session"):
                            diagnostics.rejected_regime_filter += 1
                            diagnostics.regime_filter_reasons.append(decision.reason)
                        elif decision.reason == "confidence":
                            diagnostics.rejected_confidence += 1
                        elif decision.reason == "risk_reward":
                            diagnostics.rejected_risk_reward += 1
                        continue
            else:
                # Legacy regime/session filter path
                regime_check = self._check_regime_filter(signal)
                if not regime_check["passed"]:
                    # Optionally bypass regime/session filters in explore mode (B-tier), with explicit labeling.
                    if self._explore_enabled and getattr(self, "_explore_bypass_regime_filters", False):
                        opportunity_tier = "B"
                        opportunity_reason = str(regime_check.get("reason", "regime_filter"))
                    else:
                        diagnostics.rejected_regime_filter += 1
                        diagnostics.regime_filter_reasons.append(regime_check.get("reason", "unknown"))
                        logger.debug(
                            "Signal filtered by regime: type=%s, reason=%s",
                            signal.get("type"),
                            regime_check.get("reason"),
                        )
                        continue
            
            # Apply order book filter if Level 2 data available
            if order_book_available:
                order_book_imbalance = latest_bar.get("imbalance", 0.0)
                signal_direction = signal.get("direction", "")

                # Filter signals based on order book alignment
                # Long signals need positive imbalance (more bids), short need negative (more asks)
                if signal_direction == "long" and order_book_imbalance < -0.2:
                    logger.debug(
                        "Signal filtered by order book: long signal rejected (imbalance: %.2f, strong ask pressure)",
                        order_book_imbalance,
                    )
                    diagnostics.rejected_order_book += 1
                    continue
                if signal_direction == "short" and order_book_imbalance > 0.2:
                    logger.debug(
                        "Signal filtered by order book: short signal rejected (imbalance: %.2f, strong bid pressure)",
                        order_book_imbalance,
                    )
                    diagnostics.rejected_order_book += 1
                    continue

            # Track validation result with rejection reason.
            # We primarily emit A-tier (strict), but can optionally promote near-misses into
            # B-tier ("explore") to surface more 24h opportunities (Asia/London/NY) with transparency.
            validation_result = self._validate_signal_with_reason(
                signal,
                min_confidence=eff_min_conf,
                min_risk_reward=eff_min_rr,
            )

            if not validation_result["valid"]:
                reason = str(validation_result.get("reason") or "unknown")

                # Attempt B-tier promotion for near-misses (confidence / R:R only)
                if self._explore_enabled and reason in ("confidence", "risk_reward"):
                    # Basic price + R:R validation (never promote invalid price geometry)
                    try:
                        conf_val = float(signal.get("confidence", 0.0) or 0.0)
                    except Exception:
                        conf_val = 0.0
                    try:
                        entry = float(signal.get("entry_price", 0.0) or 0.0)
                        stop = float(signal.get("stop_loss", 0.0) or 0.0)
                        target = float(signal.get("take_profit", 0.0) or 0.0)
                    except Exception:
                        entry, stop, target = 0.0, 0.0, 0.0

                    direction = str(signal.get("direction", "long") or "long").lower()
                    valid_prices = False
                    if entry > 0 and stop > 0 and target > 0:
                        if direction == "long":
                            valid_prices = (stop < entry < target)
                        else:
                            valid_prices = (target < entry < stop)

                    rr_val = 0.0
                    if valid_prices:
                        try:
                            if direction == "long":
                                risk = entry - stop
                                reward = target - entry
                            else:
                                risk = stop - entry
                                reward = entry - target
                            rr_val = (reward / risk) if risk > 0 else 0.0
                        except Exception:
                            rr_val = 0.0

                    passes_explore = (
                        valid_prices
                        and conf_val >= float(self._explore_min_confidence)
                        and rr_val >= float(self._explore_min_risk_reward)
                    )

                    if passes_explore:
                        # Throttle explore emissions to avoid flooding Telegram
                        now_utc = datetime.now(timezone.utc)
                        if _explore_has_capacity(now_utc):
                            new_reason = ""
                            if reason == "confidence":
                                new_reason = f"conf {conf_val:.2f} < {self._min_confidence:.2f}"
                            elif reason == "risk_reward":
                                new_reason = f"R:R {rr_val:.2f} < {self._min_risk_reward:.2f}"
                            else:
                                new_reason = reason
                            if opportunity_tier != "B":
                                opportunity_tier = "B"
                            if new_reason:
                                if opportunity_reason:
                                    if new_reason not in opportunity_reason:
                                        opportunity_reason = (opportunity_reason + "; " + new_reason)[:120]
                                else:
                                    opportunity_reason = new_reason
                        else:
                            # No capacity; treat as rejected for this cycle
                            if reason == "confidence":
                                diagnostics.rejected_confidence += 1
                            elif reason == "risk_reward":
                                diagnostics.rejected_risk_reward += 1
                            continue
                    else:
                        # Did not meet explore thresholds; count as rejected (A-tier)
                        if reason == "confidence":
                            diagnostics.rejected_confidence += 1
                        elif reason == "risk_reward":
                            diagnostics.rejected_risk_reward += 1
                        elif reason == "invalid_prices":
                            diagnostics.rejected_invalid_prices += 1
                        continue
                else:
                    # No explore promotion path; count as rejected (A-tier)
                    if reason == "confidence":
                        diagnostics.rejected_confidence += 1
                    elif reason == "risk_reward":
                        diagnostics.rejected_risk_reward += 1
                    elif reason == "invalid_prices":
                        diagnostics.rejected_invalid_prices += 1
                    continue

            validated_signal = self._format_signal(signal, market_data)

            # Attach drift guard context (compact) for transparency.
            if isinstance(drift_state, dict):
                try:
                    validated_signal["_drift_guard"] = {
                        "active": bool(drift_state.get("active", False)),
                        "until": drift_state.get("until"),
                        "reason": drift_state.get("reason"),
                        "adjustments": drift_adj,
                    }
                except Exception:
                    pass
            
            # Track stop-cap applications
            if validated_signal.get("_stop_cap_applied", False):
                diagnostics.stop_cap_applied += 1
            
            # Track session scaling applications
            if validated_signal.get("_session_scaling_applied", False):
                diagnostics.session_scaling_applied += 1

            # Apply order book confidence adjustment if available
            if order_book_available:
                order_book_imbalance = latest_bar.get("imbalance", 0.0)
                signal_direction = validated_signal.get("direction", "")
                current_confidence = validated_signal.get("confidence", 0.5)

                # Boost confidence when order book aligns with signal
                if signal_direction == "long" and order_book_imbalance > 0.15:
                    confidence_boost = min(0.10, order_book_imbalance * 0.3)
                    validated_signal["confidence"] = min(
                        1.0,
                        current_confidence + confidence_boost,
                    )
                    logger.debug(
                        "Order book confidence boost: +%.3f (imbalance: %.2f)",
                        confidence_boost,
                        order_book_imbalance,
                    )
                elif signal_direction == "short" and order_book_imbalance < -0.15:
                    confidence_boost = min(0.10, abs(order_book_imbalance) * 0.3)
                    validated_signal["confidence"] = min(
                        1.0,
                        current_confidence + confidence_boost,
                    )
                    logger.debug(
                        "Order book confidence boost: +%.3f (imbalance: %.2f)",
                        confidence_boost,
                        order_book_imbalance,
                    )

            if self._is_duplicate(validated_signal):
                diagnostics.duplicates_filtered += 1
                continue
                
            logger.debug(
                "Signal passed validation: type=%s, confidence=%.3f, entry=%.2f",
                validated_signal.get("type"),
                validated_signal.get("confidence", 0.0),
                validated_signal.get("entry_price", 0.0),
            )
            
            # Calculate composite quality score (NO CAPS - purely quality-driven)
            composite_quality_score = self._calculate_composite_quality_score(validated_signal, market_data)
            validated_signal["composite_quality_score"] = composite_quality_score
            
            # Apply composite quality score filter (NO LIMIT on how many pass)
            if self._quality_score_enabled and composite_quality_score < self._quality_score_threshold:
                logger.debug(
                    "Signal filtered by composite quality score: type=%s, score=%.3f < threshold=%.3f",
                    validated_signal.get("type"),
                    composite_quality_score,
                    self._quality_score_threshold,
                )
                diagnostics.rejected_quality_scorer += 1
                continue
            
            # Classify trade type (swing vs scalp)
            trade_type = self._classify_trade_type(validated_signal, market_data)
            validated_signal["trade_type"] = trade_type
            if trade_type == "swing":
                logger.debug(
                    "Swing trade detected: type=%s, confidence=%.3f, target_points=%.1f",
                    validated_signal.get("type"),
                    validated_signal.get("confidence", 0.0),
                    abs(float(validated_signal.get("take_profit", 0)) - float(validated_signal.get("entry_price", 0))),
                )
            
            # Score signal quality (always attach for transparency, even when we emit B-tier)
            quality_score = self.quality_scorer.score_signal(validated_signal)
            validated_signal["quality_score"] = quality_score

            should_send = bool(quality_score.get("should_send", True))
            if opportunity_tier == "A" and not should_send:
                # Optionally promote quality rejections into B-tier explore
                if self._explore_enabled and self._explore_include_quality_rejects:
                    now_utc = datetime.now(timezone.utc)
                    if _explore_has_capacity(now_utc):
                        new_reason = "quality reject"
                        try:
                            qv = quality_score.get("quality_score")
                            if qv is not None:
                                new_reason = f"quality reject (score {float(qv):.2f})"
                        except Exception:
                            new_reason = "quality reject"
                        if opportunity_tier != "B":
                            opportunity_tier = "B"
                        if new_reason:
                            if opportunity_reason:
                                if new_reason not in opportunity_reason:
                                    opportunity_reason = (opportunity_reason + "; " + new_reason)[:120]
                            else:
                                opportunity_reason = new_reason
                    else:
                        diagnostics.rejected_quality_scorer += 1
                        continue
                else:
                    diagnostics.rejected_quality_scorer += 1
                    continue

            # v2.0: Apply ML signal filter if enabled
            if self._ml_filter_enabled and self._ml_filter is not None:
                try:
                    # Build context for ML filter
                    ml_context = {
                        "regime": validated_signal.get("regime", {}),
                        "df": df,
                    }
                    should_execute, ml_prediction = self._ml_filter.should_execute(
                        validated_signal, ml_context
                    )
                    
                    # Attach ML prediction to signal for transparency
                    validated_signal["_ml_prediction"] = ml_prediction.to_dict()
                    validated_signal["_ml_mode"] = self._ml_filter_mode

                    # Live-blocking is gated two ways:
                    # 1) Config mode must be "live"
                    # 2) If require_lift_to_block is enabled, the service must assert ml_blocking_allowed=True
                    #    after measuring lift on your own outcomes (shadow A/B).
                    if self._ml_require_lift_to_block:
                        ml_blocking_allowed = bool(market_data.get("ml_blocking_allowed", False))
                    else:
                        ml_blocking_allowed = True

                    # Paper-only mode: allow ML to block for drawdown control.
                    ml_blocking_active = (
                        (self._ml_filter_mode == "live" and ml_blocking_allowed)
                        or self._paper_mode
                    )
                    validated_signal["_ml_blocking_allowed"] = bool(ml_blocking_allowed)
                    validated_signal["_ml_blocking_active"] = bool(ml_blocking_active)
                    validated_signal["_ml_would_block"] = bool(not should_execute)
                    validated_signal["_ml_paper_mode"] = bool(self._paper_mode)
                    
                    # Shadow mode: never block; only annotate.
                    # Live mode: can block, but only when lift has been proven (if enabled).
                    # Paper mode: can block immediately (no live orders placed).
                    if (not should_execute) and opportunity_tier == "A" and ml_blocking_active:
                        # ML filter rejected the signal
                        logger.debug(
                            "Signal filtered by ML: type=%s, win_prob=%.2f < threshold (paper_mode=%s)",
                            validated_signal.get("type"),
                            ml_prediction.win_probability,
                            self._paper_mode,
                        )
                        diagnostics.rejected_ml_filter += 1
                        continue
                    
                    logger.debug(
                        "ML prediction: type=%s, win_prob=%.2f, pass=%s",
                        validated_signal.get("type"),
                        ml_prediction.win_probability,
                        should_execute,
                    )
                except Exception as e:
                    logger.debug(f"ML filter failed (non-blocking): {e}")
            
            # v2.0: Apply adaptive position sizing if enabled
            if self._adaptive_sizing_enabled and self._adaptive_sizer is not None:
                try:
                    # Calculate stop distance for sizing
                    entry = float(validated_signal.get("entry_price", 0))
                    stop = float(validated_signal.get("stop_loss", 0))
                    stop_distance = abs(entry - stop) if entry > 0 and stop > 0 else 10.0
                    
                    sizing_context = {
                        "regime": validated_signal.get("regime", {}),
                    }
                    size_result = self._adaptive_sizer.calculate_position_size(
                        validated_signal, sizing_context, stop_distance
                    )
                    
                    # Attach sizing result to signal
                    validated_signal["position_size"] = size_result.contracts
                    validated_signal["_adaptive_sizing"] = size_result.to_dict()
                    diagnostics.adaptive_sizing_applied += 1
                    
                    logger.debug(
                        "Adaptive sizing: type=%s, contracts=%d (kelly=%.1f, factors: conf=%.2f, regime=%.2f)",
                        validated_signal.get("type"),
                        size_result.contracts,
                        size_result.kelly_optimal,
                        size_result.confidence_factor,
                        size_result.regime_factor,
                    )
                except Exception as e:
                    logger.debug(f"Adaptive sizing failed (non-blocking): {e}")

            # Drift guard sizing reduction (cooldown): apply AFTER adaptive sizing so it acts as a final brake.
            if drift_active and drift_size_mult != 1.0:
                try:
                    before = int(validated_signal.get("position_size", 0) or 0)
                    if before > 0:
                        after = max(1, int(round(before * drift_size_mult)))
                        if after != before:
                            validated_signal["_drift_position_size_before"] = before
                            validated_signal["_drift_size_multiplier"] = float(drift_size_mult)
                            validated_signal["position_size"] = after
                except Exception:
                    pass

            # Per-signal-type sizing overrides (keep signals enabled; scale risk instead of filtering trades).
            # Applied AFTER adaptive sizing and drift guard so it acts as a final, explicit brake.
            self._apply_signal_type_sizing_overrides(validated_signal)

            # Ensure risk_amount reflects any sizing overrides (adaptive sizing / drift guard).
            try:
                entry = float(validated_signal.get("entry_price", 0.0) or 0.0)
                stop = float(validated_signal.get("stop_loss", 0.0) or 0.0)
                tick_value = float(validated_signal.get("tick_value", getattr(self.config, "tick_value", 2.0)) or 2.0)
                ps = int(validated_signal.get("position_size", 0) or 0)
                if entry > 0 and stop > 0 and ps > 0:
                    risk_points = abs(entry - stop)
                    validated_signal["risk_amount"] = float(risk_points * tick_value * ps)
            except Exception:
                pass

            # Tag + emit signal (A-tier actionable or B-tier explore)
            if opportunity_tier == "B":
                now_utc = datetime.now(timezone.utc)
                if not _explore_has_capacity(now_utc):
                    # Throttle reached; drop explore signal silently this cycle
                    continue
                validated_signal["_opportunity_tier"] = "B"
                validated_signal["_opportunity_reason"] = opportunity_reason
                diagnostics.explore_signals += 1
                # Commit throttle slot (only when we actually emit)
                self._explore_emitted_times.append(now_utc)
            else:
                validated_signal["_opportunity_tier"] = "A"
                diagnostics.actionable_signals += 1

            validated_signals.append(validated_signal)
            self._recent_signals.append(validated_signal)

        # Clean up old signals from recent list
        self._cleanup_recent_signals()
        
        # Compute ML features for validated signals (optional)
        if self._feature_engineer_enabled and self._feature_engineer and validated_signals:
            try:
                self._compute_ml_features(validated_signals, market_data)
            except Exception as e:
                logger.debug(f"Feature computation failed (non-blocking): {e}")

        # Finalize diagnostics
        diagnostics.validated_signals = len(validated_signals)
        self.last_diagnostics = diagnostics

        if validated_signals:
            logger.info("Generated %d validated signal(s)", len(validated_signals))
        else:
            # Log diagnostics summary when no signals
            logger.debug(
                "Signal diagnostics: %s",
                diagnostics.format_compact(),
            )

        return validated_signals

    def _validate_signal(
        self,
        signal: Dict,
        *,
        min_confidence: Optional[float] = None,
        min_risk_reward: Optional[float] = None,
    ) -> bool:
        """Validate a signal meets criteria.

        Args:
            signal: Signal dictionary

        Returns:
            True if signal is valid
        """
        # Volatility-aware confidence floor: during high volatility expansion,
        # apply a floor to prevent valid structure-based signals from being
        # killed by confidence stacking penalties
        regime = signal.get("regime", {})
        volatility = regime.get("volatility", "normal")
        signal_confidence = signal.get("confidence", 0.0)
        atr_expansion = regime.get("atr_expansion", False)

        if volatility == "high" and atr_expansion:
            # Floor confidence at 0.48 during expansion (was 0.50 threshold)
            # This allows signals that get penalized down to 0.42-0.49 to still pass
            effective_confidence = max(signal_confidence, 0.48)
            if effective_confidence > signal_confidence:
                logger.debug(
                    "Volatility expansion: applying confidence floor 0.48 (original: %.3f, adjusted: %.3f)",
                    signal_confidence,
                    effective_confidence,
                )
                signal["confidence"] = effective_confidence
                signal_confidence = effective_confidence

        # Use caller-provided thresholds if present (e.g., drift guard cooldown)
        try:
            eff_min_conf = float(self._min_confidence if min_confidence is None else float(min_confidence))
        except Exception:
            eff_min_conf = float(self._min_confidence)
        try:
            eff_min_rr = float(self._min_risk_reward if min_risk_reward is None else float(min_risk_reward))
        except Exception:
            eff_min_rr = float(self._min_risk_reward)

        # Check confidence threshold
        confidence = signal_confidence
        if confidence < eff_min_conf:
            # Near-miss diagnostic logging: track signals that fail confidence threshold
            signal_type = signal.get("type", "unknown")
            logger.info(
                "NEAR_MISS: confidence_rejection | type=%s | confidence=%.3f | "
                "threshold=%.3f | gap=%.3f | volatility=%s | atr_expansion=%s",
                signal_type,
                confidence,
                eff_min_conf,
                eff_min_conf - confidence,
                volatility,
                atr_expansion,
            )
            logger.debug(
                "Signal context: entry=%.2f, regime=%s, indicators=%s",
                signal.get("entry_price", 0.0),
                regime.get("regime", "unknown"),
                signal.get("indicators", {}),
            )
            return False

        # Check entry price is valid
        entry_price = signal.get("entry_price")
        if not entry_price or entry_price <= 0:
            logger.info("Signal rejected: invalid entry_price %s", entry_price)
            return False

        # Check stop loss and take profit are valid
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if signal["direction"] == "long":
            if stop_loss and stop_loss >= entry_price:
                logger.info(
                    "Signal rejected: stop_loss %.2f >= entry %.2f (long)",
                    stop_loss,
                    entry_price,
                )
                return False
            if take_profit and take_profit <= entry_price:
                logger.info(
                    "Signal rejected: take_profit %.2f <= entry %.2f (long)",
                    take_profit,
                    entry_price,
                )
                return False
        else:  # short
            if stop_loss and stop_loss <= entry_price:
                logger.info(
                    "Signal rejected: stop_loss %.2f <= entry %.2f (short)",
                    stop_loss,
                    entry_price,
                )
                return False
            if take_profit and take_profit >= entry_price:
                logger.info(
                    "Signal rejected: take_profit %.2f >= entry %.2f (short)",
                    take_profit,
                    entry_price,
                )
                return False

        # Validate risk/reward ratio meets minimum
        if stop_loss and take_profit:
            if signal["direction"] == "long":
                risk = entry_price - stop_loss
                reward = take_profit - entry_price
            else:
                risk = stop_loss - entry_price
                reward = entry_price - take_profit

            if risk > 0:
                risk_reward = reward / risk
                if risk_reward < eff_min_rr:
                    # Near-miss diagnostic logging: track signals that fail R:R threshold
                    signal_type = signal.get("type", "unknown")
                    logger.info(
                        "NEAR_MISS: risk_reward_rejection | type=%s | risk_reward=%.2f:1 | "
                        "threshold=%.2f:1 | gap=%.2f | entry=%.2f | stop=%.2f | target=%.2f",
                        signal_type,
                        risk_reward,
                        eff_min_rr,
                        eff_min_rr - risk_reward,
                        entry_price,
                        stop_loss,
                        take_profit,
                    )
                    return False

        return True

    def _validate_signal_with_reason(
        self,
        signal: Dict,
        *,
        min_confidence: Optional[float] = None,
        min_risk_reward: Optional[float] = None,
    ) -> Dict:
        """Validate a signal and return rejection reason.

        Args:
            signal: Signal dictionary

        Returns:
            Dict with "valid" (bool) and "reason" (str) keys
        """
        # Volatility-aware confidence floor: during high volatility expansion,
        # apply a floor to prevent valid structure-based signals from being
        # killed by confidence stacking penalties
        regime = signal.get("regime", {})
        volatility = regime.get("volatility", "normal")
        signal_confidence = signal.get("confidence", 0.0)
        atr_expansion = regime.get("atr_expansion", False)

        if volatility == "high" and atr_expansion:
            effective_confidence = max(signal_confidence, 0.48)
            if effective_confidence > signal_confidence:
                signal["confidence"] = effective_confidence
                signal_confidence = effective_confidence

        # Use caller-provided thresholds if present (e.g., drift guard cooldown)
        try:
            eff_min_conf = float(self._min_confidence if min_confidence is None else float(min_confidence))
        except Exception:
            eff_min_conf = float(self._min_confidence)
        try:
            eff_min_rr = float(self._min_risk_reward if min_risk_reward is None else float(min_risk_reward))
        except Exception:
            eff_min_rr = float(self._min_risk_reward)

        # Check confidence threshold
        if signal_confidence < eff_min_conf:
            return {"valid": False, "reason": "confidence"}

        # Check entry price is valid
        entry_price = signal.get("entry_price")
        if not entry_price or entry_price <= 0:
            return {"valid": False, "reason": "invalid_prices"}

        # Check stop loss and take profit are valid
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if signal["direction"] == "long":
            if stop_loss and stop_loss >= entry_price:
                return {"valid": False, "reason": "invalid_prices"}
            if take_profit and take_profit <= entry_price:
                return {"valid": False, "reason": "invalid_prices"}
        else:  # short
            if stop_loss and stop_loss <= entry_price:
                return {"valid": False, "reason": "invalid_prices"}
            if take_profit and take_profit >= entry_price:
                return {"valid": False, "reason": "invalid_prices"}

        # Validate risk/reward ratio meets minimum
        if stop_loss and take_profit:
            if signal["direction"] == "long":
                risk = entry_price - stop_loss
                reward = take_profit - entry_price
            else:
                risk = stop_loss - entry_price
                reward = entry_price - take_profit

            if risk > 0:
                risk_reward = reward / risk
                if risk_reward < eff_min_rr:
                    return {"valid": False, "reason": "risk_reward"}

        return {"valid": True, "reason": None}

    def _check_regime_filter(self, signal: Dict) -> Dict:
        """Check if signal passes regime/session filter.
        
        Config-driven per-signal-type filtering based on market regime, volatility, and session.
        
        Args:
            signal: Signal dictionary with 'type' and 'regime' keys
            
        Returns:
            Dict with 'passed' (bool) and optional 'reason' (str)
        """
        signal_type = signal.get("type", "")
        
        # No filter configured for this signal type = pass
        filter_config = self._regime_filters.get(signal_type)
        if not filter_config:
            return {"passed": True}
        
        # Extract regime context from signal
        regime = signal.get("regime", {})
        if not isinstance(regime, dict):
            return {"passed": True}  # No regime context = pass
        
        current_regime = regime.get("regime", "unknown")
        current_volatility = regime.get("volatility", "normal")
        current_session = regime.get("session", "unknown")
        
        # Check allowed_regimes (whitelist)
        allowed_regimes = filter_config.get("allowed_regimes", [])
        if allowed_regimes and current_regime not in allowed_regimes:
            return {
                "passed": False,
                "reason": f"{signal_type}: regime '{current_regime}' not in allowed {allowed_regimes}",
            }
        
        # Check disallowed_regimes (blacklist)
        disallowed_regimes = filter_config.get("disallowed_regimes", [])
        if disallowed_regimes and current_regime in disallowed_regimes:
            return {
                "passed": False,
                "reason": f"{signal_type}: regime '{current_regime}' is disallowed",
            }
        
        # Check allowed_volatility (whitelist)
        allowed_volatility = filter_config.get("allowed_volatility", [])
        if allowed_volatility and current_volatility not in allowed_volatility:
            return {
                "passed": False,
                "reason": f"{signal_type}: volatility '{current_volatility}' not in allowed {allowed_volatility}",
            }
        
        # Check disallowed_volatility (blacklist)
        disallowed_volatility = filter_config.get("disallowed_volatility", [])
        if disallowed_volatility and current_volatility in disallowed_volatility:
            return {
                "passed": False,
                "reason": f"{signal_type}: volatility '{current_volatility}' is disallowed",
            }
        
        # Check allowed_sessions (whitelist)
        allowed_sessions = filter_config.get("allowed_sessions", [])
        if allowed_sessions and current_session not in allowed_sessions:
            return {
                "passed": False,
                "reason": f"{signal_type}: session '{current_session}' not in allowed {allowed_sessions}",
            }
        
        # Check disallowed_sessions (blacklist)
        disallowed_sessions = filter_config.get("disallowed_sessions", [])
        if disallowed_sessions and current_session in disallowed_sessions:
            return {
                "passed": False,
                "reason": f"{signal_type}: session '{current_session}' is disallowed",
            }
        
        return {"passed": True}

    def _format_signal(self, signal: Dict, market_data: Dict) -> Dict:
        """Format signal with additional metadata.

        Args:
            signal: Raw signal dictionary
            market_data: Market data context

        Returns:
            Formatted signal dictionary
        """
        formatted = signal.copy()

        # Add metadata
        formatted["symbol"] = self.config.symbol
        
        # Use bar timestamp in backtest mode for determinism; wall-clock otherwise.
        is_backtest = market_data.get("is_backtest", False)
        bar_ts = None
        if is_backtest:
            latest_bar = market_data.get("latest_bar")
            if latest_bar and latest_bar.get("timestamp"):
                bar_ts = latest_bar["timestamp"]
                # Normalize to ISO string if it's a datetime
                if hasattr(bar_ts, "isoformat"):
                    bar_ts = bar_ts.isoformat()
                elif isinstance(bar_ts, pd.Timestamp):
                    bar_ts = bar_ts.isoformat()
        formatted["timestamp"] = bar_ts if bar_ts else datetime.now(timezone.utc).isoformat()
        
        formatted["strategy"] = "nq_intraday"
        formatted["timeframe"] = self.config.timeframe

        # Calculate risk amount and expected hold time
        entry_price = signal.get("entry_price", 0.0)
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if entry_price > 0 and stop_loss:
            # MNQ: $2 per point. tick_value is MNQ-native in config.
            tick_value = getattr(self.config, "tick_value", 2.0)
            # Position sizing: respect strategy config (dynamic sizing) rather than using the
            # "max_position_size" cap as the default size.
            #
            # This keeps live behavior aligned with backtests (see backtest_adapter.py), and
            # makes sizing respond to confidence + winning_signal_types.
            try:
                confidence = float(signal.get("confidence", 0.0) or 0.0)
            except Exception:
                confidence = 0.0
            signal_type = str(signal.get("type") or "")

            position_size: int
            try:
                position_size = int(self.config.get_position_size(confidence, signal_type))
            except Exception:
                # Fallbacks (defensive): base_contracts -> min_position_size -> 1
                try:
                    position_size = int(getattr(self.config, "base_contracts", 0) or 0)
                except Exception:
                    position_size = 0
                if position_size <= 0:
                    try:
                        position_size = int(getattr(self.config, "min_position_size", 0) or 0)
                    except Exception:
                        position_size = 0
                if position_size <= 0:
                    position_size = 1

            # Enforce configured min/max bounds (if present)
            try:
                min_ps = int(getattr(self.config, "min_position_size", 1) or 1)
            except Exception:
                min_ps = 1
            try:
                max_ps = int(getattr(self.config, "max_position_size", position_size) or position_size)
            except Exception:
                max_ps = position_size
            if max_ps > 0:
                position_size = min(position_size, max_ps)
            position_size = max(min_ps, position_size)

            # Apply session-based position scaling (LANE B feature)
            # Reduces position size during quiet sessions (Tokyo, London) to manage risk.
            session_scaling_applied = False
            if getattr(self.config, "session_position_scaling_enabled", False):
                regime = signal.get("regime", {}) or {}
                current_session = regime.get("session", "").lower()
                
                if "tokyo" in current_session or "asia" in current_session:
                    multiplier = getattr(self.config, "session_tokyo_multiplier", 0.5)
                    original_size = position_size
                    position_size = max(1, int(position_size * multiplier))
                    session_scaling_applied = True
                    logger.debug(
                        f"Session position scaling (Tokyo): {original_size} -> {position_size} contracts "
                        f"(multiplier={multiplier})"
                    )
                elif "london" in current_session or "europe" in current_session:
                    multiplier = getattr(self.config, "session_london_multiplier", 0.5)
                    original_size = position_size
                    position_size = max(1, int(position_size * multiplier))
                    session_scaling_applied = True
                    logger.debug(
                        f"Session position scaling (London): {original_size} -> {position_size} contracts "
                        f"(multiplier={multiplier})"
                    )
                else:
                    # NY session or unknown - use full size (with configurable multiplier)
                    multiplier = getattr(self.config, "session_ny_multiplier", 1.0)
                    if multiplier != 1.0:
                        original_size = position_size
                        position_size = max(1, int(position_size * multiplier))
                        session_scaling_applied = True
                        logger.debug(
                            f"Session position scaling (NY): {original_size} -> {position_size} contracts "
                            f"(multiplier={multiplier})"
                        )
            
            # Mark if session scaling was applied (for diagnostics tracking)
            formatted["_session_scaling_applied"] = session_scaling_applied

            if signal["direction"] == "long":
                risk_points = abs(entry_price - stop_loss)
            else:
                risk_points = abs(stop_loss - entry_price)

            # Apply stop-cap if configured (risk control)
            # Caps stop distance in points and scales target to preserve RR ratio
            stop_cap_applied = False
            if self._max_stop_points > 0 and risk_points > self._max_stop_points:
                original_risk_points = risk_points
                risk_points = self._max_stop_points
                
                # Recalculate stop loss
                if signal["direction"] == "long":
                    stop_loss = entry_price - risk_points
                else:
                    stop_loss = entry_price + risk_points
                
                # Scale target to preserve RR ratio
                target_points = risk_points * self._take_profit_risk_reward
                if signal["direction"] == "long":
                    take_profit = entry_price + target_points
                else:
                    take_profit = entry_price - target_points
                
                # Update signal with capped values
                formatted["stop_loss"] = stop_loss
                formatted["take_profit"] = take_profit
                stop_cap_applied = True
                
                logger.debug(
                    "Stop-cap applied: %s | risk %.1f -> %.1f pts | stop %.2f -> %.2f | target %.2f -> %.2f",
                    signal.get("type"),
                    original_risk_points,
                    risk_points,
                    signal.get("stop_loss"),
                    stop_loss,
                    signal.get("take_profit"),
                    take_profit,
                )
            
            # Mark if stop-cap was applied (for diagnostics tracking)
            formatted["_stop_cap_applied"] = stop_cap_applied

            # Risk = points * tick_value * contracts
            risk_amount = risk_points * tick_value * position_size
            formatted["risk_amount"] = risk_amount
            formatted["position_size"] = position_size
            formatted["tick_value"] = tick_value

        # Expected hold time (prop firm style: quick scalps 5-15 min, swings 15-60 min)
        # For scalping with tighter stops, expect faster exits
        if self.config.stop_loss_atr_multiplier <= 1.5:
            formatted["expected_hold_minutes"] = 10  # Quick scalps
        else:
            formatted["expected_hold_minutes"] = 30  # Intraday swings

        # Add market context
        latest_bar = market_data.get("latest_bar")
        df = market_data.get("df")
        if latest_bar:
            formatted["market_data"] = {
                "price": latest_bar.get("close"),
                "volume": latest_bar.get("volume"),
                "bid": latest_bar.get("bid"),
                "ask": latest_bar.get("ask"),
            }
            # Add order book metrics if available
            if latest_bar.get("order_book") and latest_bar["order_book"].get("bids"):
                formatted["order_book"] = {
                    "imbalance": latest_bar.get("imbalance", 0.0),
                    "bid_depth": latest_bar.get("bid_depth", 0),
                    "ask_depth": latest_bar.get("ask_depth", 0),
                    "weighted_mid": latest_bar.get("weighted_mid"),
                    "data_level": latest_bar.get("_data_level", "unknown"),
                }

        # Add indicator values for context
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            formatted["indicators"] = {
                "rsi": float(latest.get("rsi", 0.0)) if "rsi" in latest else None,
                "atr": float(latest.get("atr", 0.0)) if "atr" in latest else None,
                "volume_ratio": float(latest.get("volume_ratio", 0.0)) if "volume_ratio" in latest else None,
                "macd_histogram": float(latest.get("macd_histogram", 0.0)) if "macd_histogram" in latest else None,
            }

        # Preserve custom indicator features for the learning system
        # These features are computed by custom indicators (supply/demand, power channel, divergences)
        if signal.get("custom_features"):
            formatted["custom_features"] = signal["custom_features"]
        
        # Preserve indicator metadata (from custom indicator signals)
        if signal.get("indicator_metadata"):
            formatted["indicator_metadata"] = signal["indicator_metadata"]

        return formatted

    def _is_duplicate(self, signal: Dict) -> bool:
        """Check if signal is a duplicate of a recent signal.

        Args:
            signal: Signal dictionary

        Returns:
            True if duplicate
        """
        signal_time = datetime.fromisoformat(
            signal.get("timestamp", datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")
        )
        signal_entry = signal.get("entry_price", 0.0)

        for recent in self._recent_signals:
            recent_time = datetime.fromisoformat(
                recent.get("timestamp", "").replace("Z", "+00:00")
            )
            time_diff = (signal_time - recent_time).total_seconds()
            recent_entry = recent.get("entry_price", 0.0)

            # Check if same type and direction within time window
            same_type = recent.get("type") == signal.get("type")
            same_direction = recent.get("direction") == signal.get("direction")
            within_time_window = time_diff < self._signal_window_seconds

            # Also check if price is too close (within threshold for same signal)
            price_close = False
            if recent_entry > 0 and signal_entry > 0:
                price_diff_pct = abs(signal_entry - recent_entry) / recent_entry
                price_close = price_diff_pct < self._duplicate_price_threshold_pct

            if same_type and same_direction and (within_time_window or price_close):
                return True

        return False

    def _restore_recent_signals_from_file(self) -> None:
        """Restore recent signals from signals file on startup."""
        try:
            from pearlalgo.utils.paths import ensure_state_dir, get_signals_file
            from pathlib import Path
            import json
            
            state_dir = ensure_state_dir()
            signals_file = get_signals_file(state_dir)
            
            if not signals_file.exists():
                return
            
            # Read recent signals from file (last 200 to cover duplicate window)
            now = datetime.now(timezone.utc)
            with open(signals_file, "r") as f:
                lines = f.readlines()
                for line in lines[-200:]:
                    try:
                        record = json.loads(line.strip())
                        signal = record.get("signal", {})
                        if not signal:
                            continue
                        
                        timestamp_str = signal.get("timestamp", "")
                        if not timestamp_str:
                            continue
                        
                        signal_time = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        )
                        time_diff = (now - signal_time).total_seconds()
                        
                        # Only include signals within the duplicate window
                        if time_diff < self._signal_window_seconds:
                            self._recent_signals.append(signal)
                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
            
            if self._recent_signals:
                logger.debug(
                    f"Restored {len(self._recent_signals)} recent signals from file "
                    f"for duplicate detection"
                )
        except Exception as e:
            logger.debug(f"Could not restore recent signals from file: {e}")

    def _cleanup_recent_signals(self) -> None:
        """Remove old signals from recent signals list."""
        now = datetime.now(timezone.utc)
        self._recent_signals = [
            s
            for s in self._recent_signals
            if (
                now
                - datetime.fromisoformat(s["timestamp"].replace("Z", "+00:00"))
            ).total_seconds()
            < self._signal_window_seconds
        ]

    def _apply_signal_type_sizing_overrides(self, validated_signal: Dict) -> None:
        """
        Apply per-signal-type position sizing overrides configured in `risk.*`.

        This is used for "Option A" style risk shaping: keep a signal family enabled
        but cap its size hard so it can't dominate PnL.

        Mutates `validated_signal` in-place.
        """
        try:
            sig_type = str(validated_signal.get("type") or validated_signal.get("signal_type") or "")
            if not sig_type:
                return

            # Allow base-key overrides like "sr_bounce" to cover sr_bounce_long/sr_bounce_short.
            base_key = sig_type
            if sig_type.endswith("_long") or sig_type.endswith("_short"):
                base_key = sig_type.rsplit("_", 1)[0]

            mult = None
            if isinstance(self._signal_type_size_multipliers, dict):
                mult = self._signal_type_size_multipliers.get(sig_type)
                if mult is None:
                    mult = self._signal_type_size_multipliers.get(base_key)

            cap = None
            if isinstance(self._signal_type_max_contracts, dict):
                cap = self._signal_type_max_contracts.get(sig_type)
                if cap is None:
                    cap = self._signal_type_max_contracts.get(base_key)

            before = int(validated_signal.get("position_size", 0) or 0)
            if before <= 0:
                before = 1

            after = before
            if mult is not None:
                try:
                    mult_f = float(mult)
                    if mult_f > 0:
                        after = max(1, int(round(before * mult_f)))
                        validated_signal["_risk_position_size_before"] = before
                        validated_signal["_risk_size_multiplier"] = float(mult_f)
                except Exception:
                    pass

            if cap is not None:
                try:
                    cap_i = int(cap)
                    if cap_i > 0:
                        after = max(1, min(after, cap_i))
                        validated_signal["_risk_max_contracts"] = int(cap_i)
                except Exception:
                    pass

            if after != before:
                validated_signal["_risk_position_size_after"] = after
                validated_signal["position_size"] = after
                logger.info(
                    "Signal type size override: %s %d → %d (mult=%s, cap=%s)",
                    sig_type, before, after, mult, cap,
                )
        except Exception:
            return
    
    def _compute_ml_features(self, signals: List[Dict], market_data: Dict) -> None:
        """
        Compute ML features for validated signals.
        
        Features are computed from market data and attached to each signal
        for use by the learning system (contextual bandit, ensemble scorer).
        
        Args:
            signals: List of validated signal dictionaries
            market_data: Market data context with 'df', 'df_5m', etc.
        """
        if not self._feature_engineer or not signals:
            return
        
        df = market_data.get("df")
        if df is None or df.empty:
            return
        
        # Get higher timeframe data for cross-TF features
        higher_tf_data = market_data.get("df_5m")
        
        # Get recent outcomes for sequential features (from performance tracker if available)
        recent_outcomes: List[Dict] = []
        # Note: recent_outcomes would need to be passed in from service.py
        # For now, we'll leave it empty - the learning loop can populate this
        
        for signal in signals:
            try:
                # Compute features
                feature_vector = self._feature_engineer.compute_features(
                    df=df,
                    signal=signal,
                    recent_outcomes=recent_outcomes,
                    higher_tf_data=higher_tf_data,
                    custom_features=signal.get("custom_features"),
                )
                
                # Attach features to signal
                if feature_vector and feature_vector.features:
                    signal["_ml_features"] = feature_vector.to_dict()
                    logger.debug(
                        f"Computed {feature_vector.num_features} ML features for signal {signal.get('type')}"
                    )
                    
            except Exception as e:
                logger.debug(f"Failed to compute features for signal: {e}")

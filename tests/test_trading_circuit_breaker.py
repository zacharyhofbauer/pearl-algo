"""Tests for Trading Circuit Breaker - Risk management module."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from pearlalgo.market_agent.trading_circuit_breaker import (
    CircuitBreakerDecision,
    TradingCircuitBreakerConfig,
    TradingCircuitBreaker,
    create_trading_circuit_breaker,
)


class TestCircuitBreakerDecision:
    """Test CircuitBreakerDecision dataclass."""

    def test_to_dict(self):
        """Test dictionary conversion."""
        decision = CircuitBreakerDecision(
            allowed=False,
            reason="consecutive_losses",
            severity="critical",
            details={"consecutive_losses": 5, "max_allowed": 5},
        )

        d = decision.to_dict()

        assert d["allowed"] is False
        assert d["reason"] == "consecutive_losses"
        assert d["severity"] == "critical"
        assert d["details"]["consecutive_losses"] == 5

    def test_default_values(self):
        """Test default values."""
        decision = CircuitBreakerDecision(allowed=True, reason="passed")

        assert decision.severity == "info"
        assert decision.details == {}


class TestTradingCircuitBreakerConfig:
    """Test TradingCircuitBreakerConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = TradingCircuitBreakerConfig()

        assert config.mode == "enforce"
        assert config.max_consecutive_losses == 5
        assert config.max_session_drawdown == 500.0
        assert config.max_daily_drawdown == 1000.0
        assert config.rolling_window_trades == 20
        assert config.min_rolling_win_rate == 0.30
        assert config.max_concurrent_positions == 5
        assert config.enable_direction_gating is True
        assert config.enable_regime_avoidance is False

    def test_custom_values(self):
        """Test custom configuration values."""
        config = TradingCircuitBreakerConfig(
            max_consecutive_losses=3,
            max_session_drawdown=200.0,
            enable_direction_gating=False,
        )

        assert config.max_consecutive_losses == 3
        assert config.max_session_drawdown == 200.0
        assert config.enable_direction_gating is False


class TestTradingCircuitBreakerInit:
    """Test TradingCircuitBreaker initialization."""

    def test_default_init(self):
        """Test initialization with defaults."""
        cb = TradingCircuitBreaker()

        assert cb.config.mode == "enforce"
        assert cb._consecutive_losses == 0
        assert cb._session_pnl == 0.0
        assert cb._daily_pnl == 0.0
        assert cb._cooldown_until is None

    def test_custom_config(self):
        """Test initialization with custom config."""
        config = TradingCircuitBreakerConfig(max_consecutive_losses=3)
        cb = TradingCircuitBreaker(config)

        assert cb.config.max_consecutive_losses == 3


class TestConsecutiveLosses:
    """Test consecutive loss limits."""

    def test_allows_signal_below_limit(self):
        """Test signal allowed when below loss limit."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_consecutive_losses=5,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        cb._consecutive_losses = 4

        decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is True

    def test_blocks_signal_at_limit(self):
        """Test signal blocked when at loss limit."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_consecutive_losses=5,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        cb._consecutive_losses = 5

        decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is False
        assert "consecutive_losses" in decision.reason

    def test_activates_cooldown(self):
        """Test cooldown is activated when limit reached."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_consecutive_losses=5,
            consecutive_loss_cooldown_minutes=30,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        cb._consecutive_losses = 5

        cb.should_allow_signal({"direction": "long"})

        assert cb._cooldown_until is not None
        assert cb._cooldown_reason == "consecutive_losses"


class TestSessionDrawdown:
    """Test session drawdown limits."""

    def test_allows_signal_above_limit(self):
        """Test signal allowed when P&L above drawdown limit."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_session_drawdown=500.0,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        cb._session_pnl = -400.0

        decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is True

    def test_blocks_signal_at_drawdown(self):
        """Test signal blocked when at drawdown limit."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_session_drawdown=500.0,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        cb._session_pnl = -500.0

        decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is False
        assert "session_drawdown" in decision.reason


class TestDailyDrawdown:
    """Test daily drawdown limits."""

    def test_blocks_at_daily_drawdown(self):
        """Test signal blocked at daily drawdown limit."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_daily_drawdown=1000.0,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        cb._daily_pnl = -1000.0

        decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is False
        assert "daily_drawdown" in decision.reason


class TestRollingWinRate:
    """Test rolling win rate filter."""

    def test_insufficient_data_allowed(self):
        """Test signal allowed with insufficient trade history."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            rolling_window_trades=20,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        # Add only 5 trades (less than window/2 = 10)
        for _ in range(5):
            cb._recent_trades.append({"is_win": False, "pnl": -10.0})

        decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is True

    def test_blocks_low_win_rate(self):
        """Test signal blocked when win rate too low."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            rolling_window_trades=20,
            min_rolling_win_rate=0.30,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        # Add 20 trades with only 4 wins (20% win rate < 30% threshold)
        for i in range(20):
            cb._recent_trades.append({"is_win": i < 4, "pnl": 10.0 if i < 4 else -10.0})

        decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is False
        assert "rolling_win_rate" in decision.reason


class TestPositionLimits:
    """Test position limits and clustering."""

    def test_blocks_max_positions(self):
        """Test signal blocked when max positions reached."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_concurrent_positions=3,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        active_positions = [
            {"entry_price": 100.0, "direction": "long"},
            {"entry_price": 101.0, "direction": "long"},
            {"entry_price": 102.0, "direction": "short"},
        ]

        decision = cb.should_allow_signal(
            {"direction": "long", "entry_price": 105.0},
            active_positions=active_positions,
        )

        assert decision.allowed is False
        assert "max_positions" in decision.reason

    def test_blocks_position_clustering(self):
        """Test signal blocked when too close to existing position."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_concurrent_positions=5,
            min_price_distance_pct=0.5,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        active_positions = [{"entry_price": 100.0, "direction": "long"}]

        # Entry at 100.3 is only 0.3% away from 100.0 (< 0.5% threshold)
        decision = cb.should_allow_signal(
            {"direction": "long", "entry_price": 100.3},
            active_positions=active_positions,
        )

        assert decision.allowed is False
        assert "position_clustering" in decision.reason

    def test_allows_opposite_direction_clustering(self):
        """Test opposite direction is allowed even when close."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_concurrent_positions=5,
            min_price_distance_pct=0.5,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        active_positions = [{"entry_price": 100.0, "direction": "long"}]

        # Opposite direction (short) should be allowed even if close
        decision = cb.should_allow_signal(
            {"direction": "short", "entry_price": 100.3},
            active_positions=active_positions,
        )

        assert decision.allowed is True


class TestVolatilityFilter:
    """Test volatility and chop filter."""

    def test_blocks_low_volatility(self):
        """Test signal blocked when volatility too low."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_volatility_filter=True,
            min_atr_ratio=0.8,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        market_data = {"atr_current": 0.5, "atr_average": 1.0}  # ratio = 0.5 < 0.8

        decision = cb.should_allow_signal({"direction": "long"}, market_data=market_data)

        assert decision.allowed is False
        assert "low_volatility" in decision.reason

    def test_blocks_extreme_volatility(self):
        """Test signal blocked when volatility too high."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_volatility_filter=True,
            max_atr_ratio=2.5,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        market_data = {"atr_current": 3.0, "atr_average": 1.0}  # ratio = 3.0 > 2.5

        decision = cb.should_allow_signal({"direction": "long"}, market_data=market_data)

        assert decision.allowed is False
        assert "extreme_volatility" in decision.reason

    def test_blocks_chop_detected(self):
        """Test signal blocked when chop detected from recent trades."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_volatility_filter=True,
            chop_detection_window=10,
            chop_win_rate_threshold=0.35,
            rolling_window_trades=20,  # Set higher than chop_detection_window
            min_rolling_win_rate=0.10,  # Set lower so rolling_win_rate check passes
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        # Add 10 trades with only 2 wins (20% < 35% threshold for chop detection)
        # But 20% > 10% for rolling_win_rate, so that check passes
        for i in range(10):
            cb._recent_trades.append({"is_win": i < 2, "pnl": 10.0 if i < 2 else -10.0})

        market_data = {"atr_current": 1.0, "atr_average": 1.0}  # Normal volatility

        decision = cb.should_allow_signal({"direction": "long"}, market_data=market_data)

        assert decision.allowed is False
        assert "chop_detected" in decision.reason


class TestSessionFilter:
    """Test session time-of-day filter."""

    def test_allows_overnight_session(self):
        """Test signal allowed during overnight session."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_session_filter=True,
            allowed_sessions=["overnight", "midday", "close"],
            enable_direction_gating=False,
        ))

        # Mock 8 PM ET (20:00) -> should be overnight session
        with patch.object(cb, '_get_current_session', return_value=("overnight", 20)):
            decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is True

    def test_blocks_morning_session(self):
        """Test signal blocked during morning session (not in allowed list)."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_session_filter=True,
            allowed_sessions=["overnight", "midday", "close"],
            enable_direction_gating=False,
        ))

        # Mock 8 AM ET -> should be morning session (not allowed)
        with patch.object(cb, '_get_current_session', return_value=("morning", 8)):
            decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is False
        assert "session_filtered" in decision.reason


class TestDirectionGating:
    """Test direction gating by market regime."""

    def test_allows_long_in_trending_up(self):
        """Test long signal allowed in trending_up regime."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_direction_gating=True,
            direction_gating_min_confidence=0.70,
            enable_session_filter=False,
        ))
        signal = {
            "direction": "long",
            "market_regime": {"regime": "trending_up", "confidence": 0.85},
        }

        decision = cb.should_allow_signal(signal)

        assert decision.allowed is True

    def test_blocks_short_in_trending_up(self):
        """Test short signal blocked in trending_up regime."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_direction_gating=True,
            direction_gating_min_confidence=0.70,
            enable_session_filter=False,
        ))
        signal = {
            "direction": "short",
            "market_regime": {"regime": "trending_up", "confidence": 0.85},
        }

        decision = cb.should_allow_signal(signal)

        assert decision.allowed is False
        assert "direction_gating" in decision.reason

    def test_allows_short_in_trending_down(self):
        """Test short signal allowed in trending_down regime."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_direction_gating=True,
            direction_gating_min_confidence=0.70,
            enable_session_filter=False,
        ))
        signal = {
            "direction": "short",
            "market_regime": {"regime": "trending_down", "confidence": 0.80},
        }

        decision = cb.should_allow_signal(signal)

        assert decision.allowed is True

    def test_blocks_short_in_ranging(self):
        """Test short signal blocked in ranging regime (conservative - long only)."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_direction_gating=True,
            direction_gating_min_confidence=0.70,
            enable_session_filter=False,
        ))
        signal = {
            "direction": "short",
            "market_regime": {"regime": "ranging", "confidence": 0.80},
        }

        decision = cb.should_allow_signal(signal)

        assert decision.allowed is False
        assert "direction_gating" in decision.reason

    def test_low_confidence_allows_both_directions(self):
        """Test low regime confidence allows both directions."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_direction_gating=True,
            direction_gating_min_confidence=0.70,
            enable_session_filter=False,
        ))
        # Confidence 0.50 < 0.70 threshold - regime treated as unknown
        signal = {
            "direction": "long",  # Long is default allowed in unknown regime
            "market_regime": {"regime": "trending_down", "confidence": 0.50},
        }

        decision = cb.should_allow_signal(signal)

        assert decision.allowed is True


class TestRegimeAvoidance:
    """Test regime avoidance (Phase 2)."""

    def test_blocks_ranging_regime(self):
        """Test signal blocked in ranging regime when enabled."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_regime_avoidance=True,
            blocked_regimes=["ranging", "volatile"],
            regime_avoidance_min_confidence=0.70,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        signal = {
            "direction": "long",
            "market_regime": {"regime": "ranging", "confidence": 0.80},
        }

        decision = cb.should_allow_signal(signal)

        assert decision.allowed is False
        assert "regime_avoidance" in decision.reason

    def test_shadow_mode_counts_would_block(self):
        """Test shadow mode counts would-have-blocked."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_regime_avoidance=False,  # Shadow mode
            blocked_regimes=["ranging", "volatile"],
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        signal = {
            "direction": "long",
            "market_regime": {"regime": "ranging", "confidence": 0.80},
        }

        initial_count = cb._would_have_blocked_regime
        cb.should_allow_signal(signal)

        assert cb._would_have_blocked_regime == initial_count + 1


class TestTriggerFilters:
    """Test trigger-based de-risking (Phase 3)."""

    def test_blocks_ema_cross_without_volume(self):
        """Test ema_cross blocked without volume confirmation."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_trigger_filters=True,
            ema_cross_require_volume=True,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        signal = {
            "direction": "long",
            "entry_trigger": "ema_cross",
            "volume_confirmed": False,
        }

        decision = cb.should_allow_signal(signal)

        assert decision.allowed is False
        assert "trigger_ema_cross_no_volume" in decision.reason

    def test_allows_ema_cross_with_volume(self):
        """Test ema_cross allowed with volume confirmation."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_trigger_filters=True,
            ema_cross_require_volume=True,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        signal = {
            "direction": "long",
            "entry_trigger": "ema_cross",
            "volume_confirmed": True,
        }

        decision = cb.should_allow_signal(signal)

        assert decision.allowed is True


class TestMLChopShield:
    """Test ML chop shield (Phase 4)."""

    def test_blocks_ml_fail_in_ranging(self):
        """Test ML FAIL signal blocked in ranging regime."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_ml_chop_shield=True,
            ml_min_scored_trades=50,
            ml_min_winrate_delta=0.15,
            ml_chop_shield_regimes=["ranging", "volatile"],
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        signal = {
            "direction": "long",
            "market_regime": {"regime": "ranging", "confidence": 0.80},
            "_ml_prediction": {"pass_filter": False},
        }
        ml_stats = {
            "scored_trades": 100,
            "pass_win_rate": 0.55,
            "fail_win_rate": 0.30,  # delta = 0.25 >= 0.15
        }

        decision = cb.should_allow_signal(signal, ml_stats=ml_stats)

        assert decision.allowed is False
        assert "ml_chop_shield" in decision.reason

    def test_allows_ml_pass_in_ranging(self):
        """Test ML PASS signal allowed in ranging regime."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_ml_chop_shield=True,
            ml_min_scored_trades=50,
            ml_min_winrate_delta=0.15,
            ml_chop_shield_regimes=["ranging", "volatile"],
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        signal = {
            "direction": "long",
            "market_regime": {"regime": "ranging", "confidence": 0.80},
            "_ml_prediction": {"pass_filter": True},
        }
        ml_stats = {
            "scored_trades": 100,
            "pass_win_rate": 0.55,
            "fail_win_rate": 0.30,
        }

        decision = cb.should_allow_signal(signal, ml_stats=ml_stats)

        assert decision.allowed is True

    def test_insufficient_scored_trades_allows(self):
        """Test insufficient scored trades allows signal."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_ml_chop_shield=True,
            ml_min_scored_trades=50,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        signal = {"direction": "long"}
        ml_stats = {"scored_trades": 30}  # < 50 required

        decision = cb.should_allow_signal(signal, ml_stats=ml_stats)

        assert decision.allowed is True


class TestTradeRecording:
    """Test trade result recording."""

    def test_record_winning_trade(self):
        """Test recording a winning trade."""
        cb = TradingCircuitBreaker()
        cb._consecutive_losses = 3

        cb.record_trade_result({"is_win": True, "pnl": 50.0})

        assert cb._consecutive_losses == 0
        assert cb._session_pnl == 50.0
        assert cb._daily_pnl == 50.0
        assert len(cb._recent_trades) == 1

    def test_record_losing_trade(self):
        """Test recording a losing trade."""
        cb = TradingCircuitBreaker()
        cb._consecutive_losses = 2

        cb.record_trade_result({"is_win": False, "pnl": -30.0})

        assert cb._consecutive_losses == 3
        assert cb._session_pnl == -30.0
        assert cb._daily_pnl == -30.0

    def test_trims_trade_history(self):
        """Test trade history is trimmed to max size."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            rolling_window_trades=20,
            chop_detection_window=10,
        ))

        # Add 100 trades (should be trimmed to 40 = max(20, 10) * 2)
        for i in range(100):
            cb.record_trade_result({"is_win": i % 2 == 0, "pnl": 10.0})

        assert len(cb._recent_trades) == 40


class TestResetMethods:
    """Test session and daily reset methods."""

    def test_reset_session(self):
        """Test session reset clears session state."""
        cb = TradingCircuitBreaker()
        cb._session_pnl = -200.0
        cb._consecutive_losses = 3

        cb.reset_session()

        assert cb._session_pnl == 0.0
        assert cb._consecutive_losses == 0

    def test_reset_daily(self):
        """Test daily reset clears all state."""
        cb = TradingCircuitBreaker()
        cb._session_pnl = -200.0
        cb._daily_pnl = -500.0
        cb._consecutive_losses = 3

        cb.reset_daily()

        assert cb._session_pnl == 0.0
        assert cb._daily_pnl == 0.0
        assert cb._consecutive_losses == 0


class TestCooldownManagement:
    """Test cooldown management."""

    def test_force_cooldown(self):
        """Test forcing a cooldown period."""
        cb = TradingCircuitBreaker()

        cb.force_cooldown("manual_intervention", 60)

        assert cb._is_in_cooldown()
        assert cb._cooldown_reason == "manual_intervention"

    def test_clear_cooldown(self):
        """Test clearing a cooldown."""
        cb = TradingCircuitBreaker()
        cb.force_cooldown("test", 60)

        cb.clear_cooldown()

        assert not cb._is_in_cooldown()
        assert cb._cooldown_reason is None

    def test_cooldown_blocks_signals(self):
        """Test signals blocked during cooldown."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        cb.force_cooldown("test", 60)

        decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is False
        assert "in_cooldown" in decision.reason

    def test_cooldown_auto_expires(self):
        """Test cooldown auto-expires after duration."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            auto_resume_after_cooldown=True,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        cb._cooldown_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        cb._cooldown_reason = "test"

        decision = cb.should_allow_signal({"direction": "long"})

        assert decision.allowed is True
        assert cb._cooldown_until is None


class TestGetStatus:
    """Test status reporting."""

    def test_get_status(self):
        """Test getting circuit breaker status."""
        cb = TradingCircuitBreaker()
        cb._consecutive_losses = 2
        cb._session_pnl = -100.0

        status = cb.get_status()

        assert status["enabled"] is True
        assert status["consecutive_losses"] == 2
        assert status["session_pnl"] == -100.0
        assert "rolling_win_rate" in status
        assert "direction_gating_enabled" in status


class TestValidateConfig:
    """Test configuration validation."""

    def test_valid_config(self):
        """Test valid configuration has no warnings."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(mode="enforce"))

        warnings = cb.validate_config()

        assert len(warnings) == 0

    def test_invalid_mode_warning(self):
        """Test invalid mode produces warning."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(mode="invalid"))

        warnings = cb.validate_config()

        assert any("mode" in w for w in warnings)

    def test_invalid_confidence_warning(self):
        """Test invalid confidence produces warning."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            enable_direction_gating=True,
            direction_gating_min_confidence=1.5,  # Invalid: > 1.0
        ))

        warnings = cb.validate_config()

        assert any("direction_gating_min_confidence" in w for w in warnings)


class TestFactoryFunction:
    """Test factory function."""

    def test_create_with_none(self):
        """Test factory with no config."""
        cb = create_trading_circuit_breaker(None)

        assert cb.config.mode == "enforce"
        assert cb.config.max_consecutive_losses == 5

    def test_create_with_config(self):
        """Test factory with custom config."""
        config = {
            "mode": "warn_only",
            "max_consecutive_losses": 3,
            "max_session_drawdown": 200.0,
            "enable_direction_gating": False,
        }

        cb = create_trading_circuit_breaker(config)

        assert cb.config.mode == "warn_only"
        assert cb.config.max_consecutive_losses == 3
        assert cb.config.max_session_drawdown == 200.0
        assert cb.config.enable_direction_gating is False


class TestWouldBlockTracking:
    """Test would-block telemetry tracking."""

    def test_record_would_block(self):
        """Test recording would-block decision."""
        cb = TradingCircuitBreaker()

        cb.record_would_block("test_reason")
        cb.record_would_block("test_reason")
        cb.record_would_block("other_reason")

        assert cb._would_block_total == 3
        assert cb._would_block_by_reason["test_reason"] == 2
        assert cb._would_block_by_reason["other_reason"] == 1


class TestBlockTracking:
    """Test block statistics tracking."""

    def test_tracks_blocks_by_reason(self):
        """Test blocks are tracked by reason."""
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(
            max_consecutive_losses=2,
            enable_session_filter=False,
            enable_direction_gating=False,
        ))
        cb._consecutive_losses = 5

        decision = cb.should_allow_signal({"direction": "long"})

        # First block should be for consecutive_losses
        assert decision.allowed is False
        assert cb._total_blocks == 1
        assert "consecutive_losses" in cb._blocks_by_reason

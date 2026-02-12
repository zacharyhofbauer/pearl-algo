"""
Edge-case tests for TradingCircuitBreaker (trading_circuit_breaker.py).

Covers:
- Volatility filter blocks when ATR ratio is extreme
- Chop detection blocks during low-winrate periods
- Cooldown recovery resumes trading after expiry
- Max concurrent positions respected
"""

from datetime import datetime, timezone, timedelta

import pytest

from pearlalgo.market_agent.trading_circuit_breaker import (
    TradingCircuitBreaker,
    TradingCircuitBreakerConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_breaker(**overrides) -> TradingCircuitBreaker:
    """Create a TradingCircuitBreaker with deterministic defaults."""
    defaults = dict(
        mode="enforce",
        max_consecutive_losses=5,
        consecutive_loss_cooldown_minutes=30,
        max_session_drawdown=500.0,
        max_daily_drawdown=1000.0,
        enable_volatility_filter=True,
        min_atr_ratio=0.8,
        max_atr_ratio=2.5,
        chop_detection_window=10,
        chop_win_rate_threshold=0.35,
        max_concurrent_positions=3,
        min_price_distance_pct=0.5,
        auto_resume_after_cooldown=True,
        # Disable time-based filters to avoid flaky results
        enable_session_filter=False,
        enable_direction_gating=False,
        enable_regime_avoidance=False,
        enable_trigger_filters=False,
        enable_ml_chop_shield=False,
        enable_tv_paper_eval_gate=False,
    )
    defaults.update(overrides)
    config = TradingCircuitBreakerConfig(**defaults)
    return TradingCircuitBreaker(config)


def _make_signal(**overrides) -> dict:
    """Create a minimal signal dict for testing."""
    sig = {
        "direction": "long",
        "entry_price": 17500.0,
        "stop_loss": 17480.0,
        "take_profit": 17540.0,
        "position_size": 1,
        "type": "momentum_ema_cross",
    }
    sig.update(overrides)
    return sig


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerEdgeCases:
    """Edge-case tests for TradingCircuitBreaker."""

    def test_volatility_filter_blocks_when_atr_ratio_too_high(self):
        """When the current ATR is > max_atr_ratio * average ATR, the
        volatility filter should block the signal."""
        cb = _make_breaker(
            enable_volatility_filter=True,
            max_atr_ratio=2.5,
        )

        signal = _make_signal()

        # ATR ratio = 30 / 10 = 3.0, which exceeds max_atr_ratio of 2.5
        market_data = {
            "atr_current": 30.0,
            "atr_average": 10.0,
        }

        decision = cb.should_allow_signal(
            signal,
            performance_stats=None,
            active_positions=[],
            market_data=market_data,
        )

        assert not decision.allowed, "Signal should be blocked when ATR ratio is extreme"
        assert "extreme_volatility" in decision.reason, (
            f"Expected 'extreme_volatility' in reason, got '{decision.reason}'"
        )
        assert decision.details.get("atr_ratio") == pytest.approx(3.0)

    def test_volatility_filter_blocks_when_atr_ratio_too_low(self):
        """When the current ATR is < min_atr_ratio * average ATR, the
        volatility filter should block (low volatility / chop)."""
        cb = _make_breaker(
            enable_volatility_filter=True,
            min_atr_ratio=0.8,
        )

        signal = _make_signal()

        # ATR ratio = 5 / 10 = 0.5, below min_atr_ratio of 0.8
        market_data = {
            "atr_current": 5.0,
            "atr_average": 10.0,
        }

        decision = cb.should_allow_signal(
            signal,
            performance_stats=None,
            active_positions=[],
            market_data=market_data,
        )

        assert not decision.allowed, "Signal should be blocked when ATR ratio is too low"
        assert "low_volatility" in decision.reason, (
            f"Expected 'low_volatility' in reason, got '{decision.reason}'"
        )

    def test_chop_detection_blocks_low_winrate_period(self):
        """When recent trade win rate in the chop window drops below
        threshold, signals should be blocked."""
        cb = _make_breaker(
            enable_volatility_filter=True,
            chop_detection_window=10,
            chop_win_rate_threshold=0.35,
            # Set high so consecutive-loss check doesn't fire first
            max_consecutive_losses=50,
            # Set rolling window large enough that 10 trades < window//2,
            # so the rolling win-rate check is skipped (insufficient data)
            # and we reach the chop detection in the volatility filter.
            rolling_window_trades=30,
        )

        # Populate trade history: 10 trades, only 2 wins (20% win rate).
        # Interleave wins to avoid triggering consecutive-loss check.
        results = [
            True, False, False, True, False,
            False, False, False, False, False,
        ]  # 2 wins, 8 losses = 20% WR
        for is_win in results:
            cb.record_trade_result({
                "is_win": is_win,
                "pnl": 50.0 if is_win else -30.0,
            })

        signal = _make_signal()

        # Provide neutral ATR data so ATR filter passes
        market_data = {
            "atr_current": 10.0,
            "atr_average": 10.0,
        }

        decision = cb.should_allow_signal(
            signal,
            performance_stats=None,
            active_positions=[],
            market_data=market_data,
        )

        assert not decision.allowed, "Signal should be blocked during choppy conditions"
        assert "chop_detected" in decision.reason, (
            f"Expected 'chop_detected' in reason, got '{decision.reason}'"
        )
        assert decision.details.get("recent_win_rate") == pytest.approx(0.2)

    def test_cooldown_recovery_resumes_trading(self):
        """After the cooldown period expires, signals should be allowed again."""
        cb = _make_breaker(
            auto_resume_after_cooldown=True,
            consecutive_loss_cooldown_minutes=30,
        )

        # Force a cooldown
        cb.force_cooldown("test_cooldown", minutes=1)

        signal = _make_signal()

        # Should be blocked during cooldown
        decision = cb.should_allow_signal(signal)
        assert not decision.allowed, "Signal should be blocked during cooldown"
        assert "in_cooldown" in decision.reason

        # Simulate cooldown expiry by backdating the cooldown_until
        cb._cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Should be allowed after cooldown expires
        decision = cb.should_allow_signal(signal)
        assert decision.allowed, (
            f"Signal should be allowed after cooldown expires; "
            f"got reason='{decision.reason}'"
        )

    def test_max_concurrent_positions_respected(self):
        """When the number of active positions equals max_concurrent_positions,
        new signals should be rejected."""
        cb = _make_breaker(max_concurrent_positions=3)

        signal = _make_signal(entry_price=18000.0)

        # Create 3 active positions (at max)
        active_positions = [
            {"entry_price": 17000.0, "direction": "long"},
            {"entry_price": 17200.0, "direction": "short"},
            {"entry_price": 17400.0, "direction": "long"},
        ]

        decision = cb.should_allow_signal(
            signal,
            performance_stats=None,
            active_positions=active_positions,
        )

        assert not decision.allowed, "Signal should be blocked at max positions"
        assert "max_positions" in decision.reason, (
            f"Expected 'max_positions' in reason, got '{decision.reason}'"
        )
        assert decision.details.get("active_positions") == 3
        assert decision.details.get("max_allowed") == 3

    def test_below_max_positions_allows_signal(self):
        """When below max_concurrent_positions, signals should be allowed
        (verifies the positive boundary condition)."""
        cb = _make_breaker(max_concurrent_positions=3)

        signal = _make_signal(entry_price=18000.0)

        # Only 2 active positions (below max of 3)
        active_positions = [
            {"entry_price": 17000.0, "direction": "long"},
            {"entry_price": 17200.0, "direction": "short"},
        ]

        decision = cb.should_allow_signal(
            signal,
            performance_stats=None,
            active_positions=active_positions,
        )

        assert decision.allowed, (
            f"Signal should be allowed when below max positions; "
            f"got reason='{decision.reason}'"
        )

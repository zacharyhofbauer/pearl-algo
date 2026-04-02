"""Integration smoke tests for circuit breaker filter chain.

Verifies that the full should_allow_signal() chain works correctly when
multiple filters are enabled simultaneously — matching production config.
"""

from datetime import datetime
from unittest.mock import patch

import pytest
import pytz

from pearlalgo.market_agent.trading_circuit_breaker import (
    TradingCircuitBreaker,
    TradingCircuitBreakerConfig,
)

_ET = pytz.timezone("America/New_York")


def _production_like_config(**overrides) -> TradingCircuitBreakerConfig:
    """Config matching production tradovate_paper.yaml settings."""
    defaults = dict(
        mode="enforce",
        # Hour filter — same hours as production
        enable_hour_filter=True,
        allowed_trading_hours_et=[1, 2, 3, 4, 9, 10, 11, 12, 13, 14, 15, 16, 18, 19, 20],
        # Weekday filter — Friday blocked
        blocked_weekdays=[4],
        # Short hour filter
        allowed_short_hours_et=[3, 4, 18, 21],
        kill_switch_short=False,
        # Drawdown/loss limits
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=30,
        max_session_drawdown=1800.0,
        max_daily_drawdown=99999.0,
        max_daily_profit=3000.0,
        max_concurrent_positions=5,
        # Direction gating ON
        enable_direction_gating=True,
        direction_gating_min_confidence=0.5,
        # Regime avoidance ON
        enable_regime_avoidance=True,
        blocked_regimes=["ranging", "volatile"],
        regime_avoidance_min_confidence=0.7,
        # Other filters OFF (matching production)
        enable_session_filter=False,
        enable_trigger_filters=False,
        enable_ml_chop_shield=False,
        enable_tv_paper_eval_gate=False,
        enable_volatility_filter=False,
        auto_resume_after_cooldown=True,
    )
    defaults.update(overrides)
    return TradingCircuitBreakerConfig(**defaults)


def _good_long_signal():
    """A long signal that should pass all filters in a trending_up regime."""
    return {
        "direction": "long",
        "type": "ema_cross",
        "confidence": 0.7,
        "market_regime": {
            "regime": "trending_up",
            "confidence": 0.8,
        },
    }


def _good_short_signal():
    """A short signal valid in trending_down during allowed short hours."""
    return {
        "direction": "short",
        "type": "ema_cross",
        "confidence": 0.7,
        "market_regime": {
            "regime": "trending_down",
            "confidence": 0.8,
        },
    }


def _fake_et_datetime(year=2026, month=3, day=31, hour=10, minute=0):
    """Create a timezone-aware ET datetime for mocking."""
    return datetime(year, month, day, hour, minute, 0, tzinfo=_ET)


class TestProductionConfigSmokeTests:
    """Smoke tests using production-like config with all filters enabled."""

    def test_reasonable_long_passes_on_tuesday_10am(self):
        """A good long signal on Tuesday at 10am ET in an uptrend should pass."""
        config = _production_like_config()
        cb = TradingCircuitBreaker(config)

        # Tuesday 2026-03-31 at 10am ET
        fake_now = _fake_et_datetime(2026, 3, 31, 10, 0)

        with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_good_long_signal())

        assert decision.allowed is True, f"Expected allowed but got blocked: {decision.reason} — {decision.details}"

    def test_signal_blocked_during_cooldown(self):
        """A signal during active cooldown should be blocked regardless of quality."""
        config = _production_like_config()
        cb = TradingCircuitBreaker(config)

        # Force cooldown
        cb.force_cooldown("test_cooldown", 30)

        decision = cb.should_allow_signal(_good_long_signal())

        assert decision.allowed is False
        assert "cooldown" in decision.reason.lower()

    def test_friday_blocked_regardless_of_signal_quality(self):
        """Even a perfect signal on Friday should be blocked (weekday filter)."""
        config = _production_like_config()
        cb = TradingCircuitBreaker(config)

        # Friday 2026-03-27 at 10am ET
        fake_now = _fake_et_datetime(2026, 3, 27, 10, 0)

        with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_good_long_signal())

        assert decision.allowed is False
        assert decision.reason == "weekday_filter"

    def test_short_at_disallowed_hour_blocked(self):
        """Short signal at 10am ET (not in [3,4,18,21]) should be blocked."""
        config = _production_like_config()
        cb = TradingCircuitBreaker(config)

        # Tuesday at 10am ET — short hour filter is inline in should_allow_signal,
        # so patch datetime in the main module
        fake_now = _fake_et_datetime(2026, 3, 31, 10, 0)

        with patch("pearlalgo.market_agent.trading_circuit_breaker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_good_short_signal())

        assert decision.allowed is False
        assert decision.reason == "short_hour_filter"

    def test_short_at_allowed_hour_in_downtrend_passes(self):
        """Short signal at 18:00 ET on Tuesday in trending_down should pass all filters."""
        config = _production_like_config()
        cb = TradingCircuitBreaker(config)

        # Tuesday at 6pm ET
        fake_now = _fake_et_datetime(2026, 3, 31, 18, 0)

        with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_filters_dt:
            with patch("pearlalgo.market_agent.trading_circuit_breaker.datetime") as mock_cb_dt:
                mock_filters_dt.now.return_value = fake_now
                mock_filters_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                mock_cb_dt.now.return_value = fake_now
                mock_cb_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                decision = cb.should_allow_signal(_good_short_signal())

        assert decision.allowed is True, f"Expected allowed but got blocked: {decision.reason} — {decision.details}"

    def test_profit_cap_blocks_after_target(self):
        """After hitting $3K daily profit, all signals should be blocked."""
        config = _production_like_config()
        cb = TradingCircuitBreaker(config)
        cb._daily_pnl = 3100.0

        # Mock time to an allowed hour so the hour filter doesn't block first
        fake_now = _fake_et_datetime(2026, 3, 31, 10, 0)

        with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_good_long_signal())

        assert decision.allowed is False
        assert decision.reason == "daily_profit_cap"


class TestFilterChainDoesNotDeadlock:
    """Verify that production config has at least one viable path for signals."""

    def test_at_least_one_long_path_exists(self):
        """There must be at least one (hour, weekday, regime) combo where a long passes."""
        config = _production_like_config()
        cb = TradingCircuitBreaker(config)

        # Try multiple combinations to find at least one that passes
        allowed_hours = config.allowed_trading_hours_et
        # Weekdays 0-6, with 4 (Friday) blocked
        allowed_weekdays = [d for d in range(7) if d not in config.blocked_weekdays]

        found_pass = False
        for weekday in allowed_weekdays:
            for hour in allowed_hours:
                # Build a fake datetime for this combo
                # Find a date matching this weekday
                from datetime import timedelta
                base = datetime(2026, 3, 30, hour, 0, 0, tzinfo=_ET)  # Monday
                # Shift to target weekday
                offset = (weekday - base.weekday()) % 7
                target = base + timedelta(days=offset)

                with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_dt:
                    mock_dt.now.return_value = target
                    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

                    signal = {
                        "direction": "long",
                        "type": "ema_cross",
                        "confidence": 0.7,
                        "market_regime": {"regime": "trending_up", "confidence": 0.8},
                    }
                    decision = cb.should_allow_signal(signal)
                    if decision.allowed:
                        found_pass = True
                        break
            if found_pass:
                break

        assert found_pass, (
            "DEADLOCK: No combination of (weekday, hour, regime=trending_up) passes "
            "the full filter chain with production config!"
        )

    def test_at_least_one_short_path_exists(self):
        """There must be at least one (hour, weekday) combo where a short in downtrend passes."""
        config = _production_like_config()
        cb = TradingCircuitBreaker(config)

        allowed_short_hours = config.allowed_short_hours_et
        allowed_weekdays = [d for d in range(7) if d not in config.blocked_weekdays]

        found_pass = False
        for weekday in allowed_weekdays:
            for hour in allowed_short_hours:
                from datetime import timedelta
                base = datetime(2026, 3, 30, hour, 0, 0, tzinfo=_ET)
                offset = (weekday - base.weekday()) % 7
                target = base + timedelta(days=offset)

                with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_filters_dt:
                    with patch("pearlalgo.market_agent.trading_circuit_breaker.datetime") as mock_cb_dt:
                        mock_filters_dt.now.return_value = target
                        mock_filters_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                        mock_cb_dt.now.return_value = target
                        mock_cb_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

                        signal = {
                            "direction": "short",
                            "type": "ema_cross",
                            "confidence": 0.7,
                            "market_regime": {"regime": "trending_down", "confidence": 0.8},
                        }
                        decision = cb.should_allow_signal(signal)
                        if decision.allowed:
                            found_pass = True
                            break
            if found_pass:
                break

        assert found_pass, (
            "DEADLOCK: No combination of (weekday, short_hour, regime=trending_down) passes "
            "the full filter chain with production config!"
        )

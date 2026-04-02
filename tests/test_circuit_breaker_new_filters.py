"""Tests for retired circuit-breaker time filters and advanced exit features.

Covers:
- Legacy time/day filters are inert in should_allow_signal()
- Daily profit cap (max_daily_profit)
- Max hold exit (AdvancedExitManager.check_max_hold_exit)
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pytz

from pearlalgo.market_agent.trading_circuit_breaker import (
    TradingCircuitBreaker,
    TradingCircuitBreakerConfig,
)
from pearlalgo.execution.advanced_exit_manager import AdvancedExitManager

_ET = pytz.timezone("America/New_York")


def _make_cb(**overrides) -> TradingCircuitBreaker:
    """Create a circuit breaker with sensible test defaults.

    Disables most filters so tests can isolate the one under test.
    """
    defaults = dict(
        mode="enforce",
        enable_session_filter=False,
        enable_direction_gating=False,
        enable_regime_avoidance=False,
        enable_trigger_filters=False,
        enable_tv_paper_eval_gate=False,
        enable_volatility_filter=False,
        enable_hour_filter=False,
        kill_switch_short=False,
        max_consecutive_losses=999,
        max_session_drawdown=999999.0,
        max_daily_drawdown=999999.0,
        max_daily_profit=0,  # disabled
        blocked_weekdays=[],
        allowed_short_hours_et=[],
    )
    defaults.update(overrides)
    config = TradingCircuitBreakerConfig(**defaults)
    return TradingCircuitBreaker(config)


def _long_signal(**overrides):
    """Minimal long signal dict."""
    sig = {"direction": "long", "type": "ema_cross", "confidence": 0.6}
    sig.update(overrides)
    return sig


def _short_signal(**overrides):
    """Minimal short signal dict."""
    sig = {"direction": "short", "type": "ema_cross", "confidence": 0.6}
    sig.update(overrides)
    return sig


# ============================================================================
# HOUR FILTER
# ============================================================================

class TestHourFilter:
    """Legacy hour filters no longer block signals."""

    def test_allows_signal_during_configured_hour(self):
        """Signal at hour 10 ET should pass when 10 is in allowed_trading_hours_et."""
        cb = _make_cb(enable_hour_filter=True, allowed_trading_hours_et=[9, 10, 11])
        fake_et = datetime(2026, 3, 31, 10, 30, 0, tzinfo=_ET)

        with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_dt:
            mock_dt.now.return_value = fake_et
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is True

    def test_blocks_signal_outside_configured_hours(self):
        """Signal at hour 5 ET should still pass despite old config."""
        cb = _make_cb(enable_hour_filter=True, allowed_trading_hours_et=[9, 10, 11])
        fake_et = datetime(2026, 3, 31, 5, 15, 0, tzinfo=_ET)

        with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_dt:
            mock_dt.now.return_value = fake_et
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is True

    def test_disabled_by_default(self):
        """When enable_hour_filter=False, all hours pass."""
        cb = _make_cb(enable_hour_filter=False, allowed_trading_hours_et=[9, 10])
        # Should pass regardless of time
        decision = cb.should_allow_signal(_long_signal())
        assert decision.allowed is True


# ============================================================================
# WEEKDAY FILTER
# ============================================================================

class TestWeekdayFilter:
    """Legacy weekday filters no longer block signals."""

    def test_blocks_friday(self):
        """Signal on Friday should still pass despite old blocked_weekdays config."""
        cb = _make_cb(blocked_weekdays=[4])
        # 2026-03-27 is a Friday
        fake_et = datetime(2026, 3, 27, 10, 0, 0, tzinfo=_ET)

        with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_dt:
            mock_dt.now.return_value = fake_et
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is True

    def test_allows_tuesday(self):
        """Signal on Tuesday (weekday=1) should pass when only Friday is blocked."""
        cb = _make_cb(blocked_weekdays=[4])
        # 2026-03-31 is a Tuesday
        fake_et = datetime(2026, 3, 31, 10, 0, 0, tzinfo=_ET)

        with patch("pearlalgo.market_agent.circuit_breaker_filters.datetime") as mock_dt:
            mock_dt.now.return_value = fake_et
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is True

    def test_empty_blocked_list_allows_all(self):
        """When blocked_weekdays is empty, all days pass (no datetime mock needed)."""
        cb = _make_cb(blocked_weekdays=[])
        decision = cb.should_allow_signal(_long_signal())
        assert decision.allowed is True


# ============================================================================
# SHORT HOUR FILTER
# ============================================================================

class TestShortHourFilter:
    """Legacy short-hour restrictions no longer block short signals."""

    _PATCH_TARGET = "pearlalgo.market_agent.trading_circuit_breaker.datetime"

    def test_allows_short_during_configured_hour(self):
        """Short at hour 18 ET should pass when 18 is in allowed_short_hours_et."""
        cb = _make_cb(allowed_short_hours_et=[3, 4, 18, 21])
        fake_et = datetime(2026, 3, 31, 18, 30, 0, tzinfo=_ET)

        with patch(self._PATCH_TARGET) as mock_dt:
            mock_dt.now.return_value = fake_et
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_short_signal())

        assert decision.allowed is True

    def test_blocks_short_outside_configured_hours(self):
        """Short at hour 10 ET should still pass despite old short-hour config."""
        cb = _make_cb(allowed_short_hours_et=[3, 4, 18, 21])
        fake_et = datetime(2026, 3, 31, 10, 0, 0, tzinfo=_ET)

        with patch(self._PATCH_TARGET) as mock_dt:
            mock_dt.now.return_value = fake_et
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_short_signal())

        assert decision.allowed is True

    def test_long_signal_ignores_short_hour_filter(self):
        """Long signals should not be affected by allowed_short_hours_et."""
        cb = _make_cb(allowed_short_hours_et=[3, 4, 18, 21])
        fake_et = datetime(2026, 3, 31, 10, 0, 0, tzinfo=_ET)

        with patch(self._PATCH_TARGET) as mock_dt:
            mock_dt.now.return_value = fake_et
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is True

    def test_empty_short_hours_allows_all_shorts(self):
        """When allowed_short_hours_et is empty and kill_switch_short=False, all shorts pass."""
        cb = _make_cb(allowed_short_hours_et=[], kill_switch_short=False)
        decision = cb.should_allow_signal(_short_signal())
        assert decision.allowed is True


# ============================================================================
# DAILY PROFIT CAP
# ============================================================================

class TestDailyProfitCap:
    """Test max_daily_profit circuit breaker."""

    def test_blocks_after_hitting_profit_target(self):
        """Trading should stop when daily_pnl >= max_daily_profit."""
        cb = _make_cb(max_daily_profit=3000.0)
        cb._daily_pnl = 3001.0

        decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is False
        assert decision.reason == "daily_profit_cap"
        assert decision.details["daily_pnl"] == 3001.0

    def test_allows_below_profit_target(self):
        """Trading should continue when daily_pnl < max_daily_profit."""
        cb = _make_cb(max_daily_profit=3000.0)
        cb._daily_pnl = 2999.0

        decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is True

    def test_disabled_when_zero(self):
        """When max_daily_profit=0, the cap is disabled."""
        cb = _make_cb(max_daily_profit=0)
        cb._daily_pnl = 99999.0

        decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is True

    def test_exactly_at_target_triggers(self):
        """Edge case: daily_pnl == max_daily_profit should trigger the cap."""
        cb = _make_cb(max_daily_profit=3000.0)
        cb._daily_pnl = 3000.0

        decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is False
        assert decision.reason == "daily_profit_cap"

    def test_negative_pnl_allows(self):
        """Losing day should never trigger profit cap."""
        cb = _make_cb(max_daily_profit=3000.0)
        cb._daily_pnl = -500.0

        decision = cb.should_allow_signal(_long_signal())

        assert decision.allowed is True


# ============================================================================
# MAX HOLD EXIT (AdvancedExitManager)
# ============================================================================

class TestMaxHoldExit:
    """Test AdvancedExitManager.check_max_hold_exit."""

    def _make_manager(self, max_duration_minutes=180, enabled=True):
        config = {
            "max_hold_exit": {
                "enabled": enabled,
                "max_duration_minutes": max_duration_minutes,
            },
        }
        return AdvancedExitManager(config)

    def test_triggers_after_max_duration(self):
        """Position held 181 min should trigger exit when limit is 180."""
        mgr = self._make_manager(max_duration_minutes=180)
        entry_time = datetime.now(_ET).replace(tzinfo=None) - timedelta(minutes=181)

        should_exit, reason = mgr.check_max_hold_exit({}, entry_time)

        assert should_exit is True
        assert "Max hold exit" in reason
        assert "180" in reason

    def test_allows_within_duration(self):
        """Position held 60 min should not trigger exit when limit is 180."""
        mgr = self._make_manager(max_duration_minutes=180)
        entry_time = datetime.now(_ET).replace(tzinfo=None) - timedelta(minutes=60)

        should_exit, reason = mgr.check_max_hold_exit({}, entry_time)

        assert should_exit is False
        assert reason == ""

    def test_disabled_does_not_trigger(self):
        """When max_hold_exit is disabled, even long-held positions pass."""
        mgr = self._make_manager(enabled=False)
        entry_time = datetime.now(_ET).replace(tzinfo=None) - timedelta(minutes=999)

        should_exit, reason = mgr.check_max_hold_exit({}, entry_time)

        assert should_exit is False

    def test_exactly_at_boundary_triggers(self):
        """Edge case: position held exactly max_duration_minutes should trigger."""
        mgr = self._make_manager(max_duration_minutes=180)
        entry_time = datetime.now(_ET).replace(tzinfo=None) - timedelta(minutes=180)

        should_exit, reason = mgr.check_max_hold_exit({}, entry_time)

        assert should_exit is True

    def test_timezone_aware_entry_time(self):
        """Entry time with tzinfo should still work (stripped to naive ET)."""
        mgr = self._make_manager(max_duration_minutes=10)
        entry_time = _ET.localize(datetime.now(_ET).replace(tzinfo=None) - timedelta(minutes=15))

        should_exit, reason = mgr.check_max_hold_exit({}, entry_time)

        assert should_exit is True

    def test_should_exit_runs_max_hold_first(self):
        """The should_exit() composite method checks max hold before other exits."""
        mgr = self._make_manager(max_duration_minutes=10)
        entry_time = datetime.now(_ET).replace(tzinfo=None) - timedelta(minutes=15)

        should_exit, reason = mgr.should_exit({}, 100.0, entry_time)

        assert should_exit is True
        assert "Max hold exit" in reason

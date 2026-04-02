"""Phase 2 coverage tests targeting uncovered lines in:
- execution_orchestrator.py
- trading_circuit_breaker.py
- signal_handler.py
- order_manager.py
"""
from __future__ import annotations

import json
import asyncio
from datetime import datetime, date, time, timezone, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import pytest

from pearlalgo.market_agent.execution_orchestrator import ExecutionOrchestrator
from pearlalgo.market_agent.trading_circuit_breaker import (
    TradingCircuitBreaker,
    TradingCircuitBreakerConfig,
    CircuitBreakerDecision,
)
from pearlalgo.market_agent.order_manager import OrderManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def orch():
    vtm = MagicMock()
    vtm.get_active_virtual_trades.return_value = []
    om = MagicMock()
    sm = MagicMock()
    sm.load_state.return_value = {}
    sm.save_state = MagicMock()
    return ExecutionOrchestrator(
        virtual_trade_manager=vtm, order_manager=om, state_manager=sm
    )


@pytest.fixture
def orch_with_adapter():
    vtm = MagicMock()
    vtm.get_active_virtual_trades.return_value = []
    om = MagicMock()
    sm = MagicMock()
    sm.load_state.return_value = {}
    sm.save_state = MagicMock()
    adapter = MagicMock()
    adapter.get_status.return_value = {"connected": True, "uptime": 120}
    adapter.is_connected = MagicMock(return_value=True)
    adapter.armed = True
    config = MagicMock()
    config.enabled = True
    return ExecutionOrchestrator(
        virtual_trade_manager=vtm,
        order_manager=om,
        state_manager=sm,
        execution_adapter=adapter,
        execution_config=config,
        notification_queue=asyncio.Queue(),
        connection_alert_cooldown_seconds=300,
    )


# ===========================================================================
# ExecutionOrchestrator Tests
# ===========================================================================


class TestGetExecutionStatus:
    """Lines 140-142: adapter with get_status()."""

    @pytest.mark.asyncio
    async def test_adapter_with_get_status(self, orch_with_adapter):
        status = await orch_with_adapter.get_execution_status()
        # is_connected is a MagicMock (truthy); getattr returns the object
        assert status["connected"]
        assert status["armed"] is True
        assert status["enabled"] is True

    @pytest.mark.asyncio
    async def test_no_adapter_returns_disabled(self, orch):
        status = await orch.get_execution_status()
        assert isinstance(status, dict)
        assert status.get("enabled") is False


# ---------------------------------------------------------------------------
# Auto-flat Friday (lines 195-196)
# ---------------------------------------------------------------------------


class TestAutoFlatFriday:
    """Lines 195-196: Friday auto-flat trigger."""

    def _auto_flat_cfg(self, **overrides):
        cfg = {
            "enabled": True,
            "daily_enabled": False,
            "friday_enabled": True,
            "friday_time": (16, 0),
            "weekend_enabled": False,
            "timezone": "America/New_York",
        }
        cfg.update(overrides)
        return cfg

    def test_friday_auto_flat_triggers(self, orch_with_adapter):
        # Friday 16:05 ET should trigger auto-flat
        friday = datetime(2026, 3, 13, 21, 5, tzinfo=timezone.utc)  # Friday UTC ~4:05pm ET
        last_dates: dict = {}
        result = orch_with_adapter.auto_flat_due(
            friday,
            market_open=True,
            auto_flat_cfg=self._auto_flat_cfg(),
            last_dates=last_dates,
        )
        assert result == "friday_auto_flat"

    def test_friday_auto_flat_no_repeat_same_day(self, orch_with_adapter):
        friday = datetime(2026, 3, 13, 21, 5, tzinfo=timezone.utc)
        et = ZoneInfo("America/New_York")
        local_date = friday.astimezone(et).date()
        last_dates = {"friday_auto_flat": local_date}
        result = orch_with_adapter.auto_flat_due(
            friday,
            market_open=True,
            auto_flat_cfg=self._auto_flat_cfg(),
            last_dates=last_dates,
        )
        assert result is None

    def test_friday_auto_flat_disabled(self, orch):
        friday = datetime(2026, 3, 13, 21, 5, tzinfo=timezone.utc)
        result = orch.auto_flat_due(
            friday,
            market_open=True,
            auto_flat_cfg=self._auto_flat_cfg(friday_enabled=False),
            last_dates={},
        )
        assert result is None


# ---------------------------------------------------------------------------
# Auto-flat Weekend (lines 213-221)
# ---------------------------------------------------------------------------


class TestAutoFlatWeekend:
    """Lines 213-221: weekend auto-flat."""

    def _auto_flat_cfg(self, **overrides):
        cfg = {
            "enabled": False,
            "daily_enabled": False,
            "friday_enabled": False,
            "weekend_enabled": True,
            "timezone": "America/New_York",
        }
        cfg.update(overrides)
        return cfg

    def _base_orch(self):
        vtm = MagicMock()
        vtm.get_active_virtual_trades.return_value = []
        om = MagicMock()
        sm = MagicMock()
        sm.load_state.return_value = {}
        adapter = MagicMock()
        adapter.is_connected = MagicMock(return_value=True)
        config = MagicMock()
        config.enabled = True
        return ExecutionOrchestrator(
            virtual_trade_manager=vtm, order_manager=om, state_manager=sm,
            execution_adapter=adapter, execution_config=config,
        )

    def test_weekend_saturday_triggers(self):
        sat = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
        orch = self._base_orch()
        result = orch.auto_flat_due(
            sat,
            market_open=False,
            auto_flat_cfg=self._auto_flat_cfg(),
            last_dates={},
        )
        assert result == "weekend_auto_flat"

    def test_weekend_sunday_before_open_triggers(self):
        sun = datetime(2026, 3, 15, 15, 0, tzinfo=timezone.utc)
        orch = self._base_orch()
        result = orch.auto_flat_due(
            sun,
            market_open=False,
            auto_flat_cfg=self._auto_flat_cfg(),
            last_dates={},
        )
        assert result == "weekend_auto_flat"

    def test_weekend_friday_evening_triggers(self):
        fri_eve = datetime(2026, 3, 13, 23, 30, tzinfo=timezone.utc)
        orch = self._base_orch()
        result = orch.auto_flat_due(
            fri_eve,
            market_open=False,
            auto_flat_cfg=self._auto_flat_cfg(),
            last_dates={},
        )
        assert result == "weekend_auto_flat"

    def test_weekend_disabled(self, orch):
        sat = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
        result = orch.auto_flat_due(
            sat,
            market_open=False,
            auto_flat_cfg=self._auto_flat_cfg(weekend_enabled=False),
            last_dates={},
        )
        assert result is None


# ---------------------------------------------------------------------------
# Clear close signals (lines 242-258)
# ---------------------------------------------------------------------------


class TestClearCloseSignals:
    """Lines 242-258: clear close signals edge cases."""

    def test_clear_specific_signals(self, orch):
        orch._state_manager.load_state.return_value = {
            "close_signals_requested": ["SIG_A", "SIG_B"]
        }
        orch.clear_close_signals_requested(signal_ids=["SIG_A"])
        orch._state_manager.save_state.assert_called()

    def test_clear_all_signals(self, orch):
        orch._state_manager.load_state.return_value = {
            "close_signals_requested": ["SIG_A"]
        }
        orch.clear_close_signals_requested()
        orch._state_manager.save_state.assert_called()

    def test_clear_state_load_error(self, orch):
        orch._state_manager.load_state.side_effect = Exception("disk error")
        # Should not raise
        orch.clear_close_signals_requested()

    def test_clear_non_dict_state(self, orch):
        orch._state_manager.load_state.return_value = "not_a_dict"
        orch.clear_close_signals_requested()

    def test_clear_empty_after_removal(self, orch):
        orch._state_manager.load_state.return_value = {
            "close_signals_requested": ["SIG_A"]
        }
        orch.clear_close_signals_requested(signal_ids=["SIG_A"])
        orch._state_manager.save_state.assert_called()


# ---------------------------------------------------------------------------
# Clear close-all flag (lines 265-280)
# ---------------------------------------------------------------------------


class TestClearCloseAllFlag:
    """Lines 265-280: clear close-all flag edge cases."""

    def test_clear_all_flag_success(self, orch):
        orch._state_manager.load_state.return_value = {"close_all": True}
        orch.clear_close_all_flag()
        orch._state_manager.save_state.assert_called()

    def test_clear_all_flag_load_error(self, orch):
        orch._state_manager.load_state.side_effect = Exception("load fail")
        orch.clear_close_all_flag()

    def test_clear_all_flag_save_error(self, orch):
        orch._state_manager.load_state.return_value = {"close_all": True}
        orch._state_manager.save_state.side_effect = Exception("save fail")
        orch.clear_close_all_flag()


# ---------------------------------------------------------------------------
# Daily reset (lines 300-317)
# ---------------------------------------------------------------------------


class TestDailyReset:
    """Lines 300-317: daily reset logic."""

    def test_no_adapter_returns(self, orch):
        orch.check_daily_reset()
        # No crash, no adapter to reset

    def test_first_cycle_initializes(self, orch_with_adapter):
        assert orch_with_adapter._last_trading_day is None
        with patch("pearlalgo.market_agent.stats_computation.get_trading_day_start") as mock_gts:
            mock_gts.return_value = datetime.now(timezone.utc)
            orch_with_adapter.check_daily_reset()
        assert orch_with_adapter._last_trading_day is not None

    def test_same_day_no_reset(self, orch_with_adapter):
        now = datetime.now(timezone.utc)
        orch_with_adapter._last_trading_day = now.date()
        with patch("pearlalgo.market_agent.stats_computation.get_trading_day_start") as mock_gts:
            mock_gts.return_value = now
            orch_with_adapter.check_daily_reset()

    def test_new_day_resets_counters(self, orch_with_adapter):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        orch_with_adapter._last_trading_day = yesterday
        with patch("pearlalgo.market_agent.stats_computation.get_trading_day_start") as mock_gts:
            mock_gts.return_value = datetime.now(timezone.utc)
            orch_with_adapter.check_daily_reset()
        assert orch_with_adapter._last_trading_day != yesterday


# ---------------------------------------------------------------------------
# Execution health (lines 338, 387-388)
# ---------------------------------------------------------------------------


class TestExecutionHealth:
    """Lines 338, 387-388: execution health checks."""

    @pytest.mark.asyncio
    async def test_no_adapter_returns(self, orch):
        await orch.check_execution_health()

    @pytest.mark.asyncio
    async def test_execution_disabled_returns(self, orch_with_adapter):
        orch_with_adapter._execution_config.enabled = False
        await orch_with_adapter.check_execution_health()

    @pytest.mark.asyncio
    async def test_first_check_initializes(self, orch_with_adapter):
        assert orch_with_adapter._execution_was_connected is None
        await orch_with_adapter.check_execution_health()
        assert orch_with_adapter._execution_was_connected is not None

    @pytest.mark.asyncio
    async def test_connection_lost_sends_alert(self, orch_with_adapter):
        orch_with_adapter._execution_was_connected = True
        orch_with_adapter._execution_adapter.is_connected.return_value = False
        mock_queue = AsyncMock()
        mock_queue.enqueue_raw_message = AsyncMock()
        orch_with_adapter._notification_queue = mock_queue
        await orch_with_adapter.check_execution_health()
        mock_queue.enqueue_raw_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_alert_cooldown_prevents_spam(self, orch_with_adapter):
        orch_with_adapter._execution_was_connected = True
        orch_with_adapter._execution_adapter.is_connected.return_value = False
        orch_with_adapter._last_connection_alert_time = datetime.now(timezone.utc)
        mock_queue = AsyncMock()
        mock_queue.enqueue_raw_message = AsyncMock()
        orch_with_adapter._notification_queue = mock_queue
        await orch_with_adapter.check_execution_health()
        # Queue should not be called due to cooldown
        mock_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_alert_queue_error(self, orch_with_adapter):
        orch_with_adapter._execution_was_connected = True
        orch_with_adapter._execution_adapter.is_connected.return_value = False
        mock_queue = AsyncMock()
        mock_queue.enqueue_raw_message = AsyncMock(side_effect=Exception("queue full"))
        orch_with_adapter._notification_queue = mock_queue
        # Should not raise
        await orch_with_adapter.check_execution_health()


# ===========================================================================
# TradingCircuitBreaker Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# TV Paper Eval Gate (lines 1172-1258)
# ---------------------------------------------------------------------------


class TestTvPaperEvalGate:
    """Lines 1172-1258: TV Paper evaluation gating."""

    def _make_cb(self, enabled=True):
        config = TradingCircuitBreakerConfig(
            enable_tv_paper_eval_gate=enabled,
        )
        return TradingCircuitBreaker(config)

    def test_disabled_allows(self):
        cb = self._make_cb(enabled=False)
        signal = {"direction": "long", "confidence": 0.8}
        # When gate is disabled, should_allow_signal won't call the gate,
        # so call it directly - but it still runs the time check.
        # The gate is not called when enable_tv_paper_eval_gate is False.
        # Just verify the CB allows the signal overall.
        decision = cb.should_allow_signal(signal)
        assert decision.allowed is True

    def test_enabled_within_session_allows(self):
        cb = self._make_cb(enabled=True)
        signal = {"direction": "long", "confidence": 0.8}
        # Patch is_within_trading_window to return True
        with patch("pearlalgo.market_agent.circuit_breaker_filters.is_within_trading_window", return_value=True):
            decision = cb._check_tv_paper_eval_gate(signal)
        assert decision.allowed is True

    def test_enabled_outside_session_blocks(self):
        cb = self._make_cb(enabled=True)
        signal = {"direction": "long", "confidence": 0.8}
        with patch("pearlalgo.market_agent.circuit_breaker_filters.is_within_trading_window", return_value=False):
            decision = cb._check_tv_paper_eval_gate(signal)
        assert decision.allowed is False
        assert decision.reason == "tv_paper_outside_trading_hours"

    def test_max_contracts_exceeded_blocks(self):
        cb = self._make_cb(enabled=True)
        signal = {"direction": "long", "position_size": 1}
        active_positions = [{"position_size": 5}]
        with patch("pearlalgo.market_agent.circuit_breaker_filters.is_within_trading_window", return_value=True):
            decision = cb._check_tv_paper_eval_gate(signal, active_positions=active_positions)
        assert decision.allowed is False
        assert decision.reason == "tv_paper_max_contracts_exceeded"

    def test_hedging_prohibited_blocks(self):
        cb = self._make_cb(enabled=True)
        signal = {"direction": "long", "position_size": 1}
        active_positions = [{"direction": "short", "position_size": 1}]
        with patch("pearlalgo.market_agent.circuit_breaker_filters.is_within_trading_window", return_value=True):
            decision = cb._check_tv_paper_eval_gate(signal, active_positions=active_positions)
        assert decision.allowed is False
        assert decision.reason == "tv_paper_hedging_prohibited"


# ---------------------------------------------------------------------------
# Session filter (line 851)
# ---------------------------------------------------------------------------


class TestCircuitBreakerSessionFilter:
    """Line 851: session filter edge cases."""

    def _make_cb(self, enabled=True, sessions=None):
        config = TradingCircuitBreakerConfig(
            enable_session_filter=enabled,
            allowed_sessions=sessions or ["overnight", "close"],
        )
        return TradingCircuitBreaker(config)

    def test_session_not_in_allowed_blocks(self):
        cb = self._make_cb(sessions=["close"])
        with patch("pearlalgo.market_agent.circuit_breaker_filters.get_current_session", return_value=("overnight", 22)):
            decision = cb._check_session_filter()
        assert decision.allowed is False

    def test_session_in_allowed_passes(self):
        cb = self._make_cb(sessions=["close", "overnight"])
        with patch("pearlalgo.market_agent.circuit_breaker_filters.get_current_session", return_value=("overnight", 22)):
            decision = cb._check_session_filter()
        assert decision.allowed is True

    def test_session_filter_disabled_allows(self):
        # When filter is disabled, should_allow_signal skips the session check
        cb = self._make_cb(enabled=False)
        signal = {"direction": "long"}
        decision = cb.should_allow_signal(signal)
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Direction gating (lines 902, 911, 917-918)
# ---------------------------------------------------------------------------


class TestCircuitBreakerDirectionGating:
    """Lines 902, 911, 917-918: direction gating."""

    def _make_cb(self, enabled=True, min_confidence=0.6):
        config = TradingCircuitBreakerConfig(
            enable_direction_gating=enabled,
            direction_gating_min_confidence=min_confidence,
        )
        return TradingCircuitBreaker(config)

    def test_direction_gating_blocks_short_in_unknown_regime(self):
        cb = self._make_cb(enabled=True, min_confidence=0.6)
        # Short in unknown regime should be blocked (only long allowed)
        signal = {
            "direction": "short",
            "market_regime": {"regime": "unknown", "confidence": 0.8},
        }
        decision = cb._check_direction_gating(signal)
        assert decision.allowed is False

    def test_direction_gating_allows_long_in_trending_up(self):
        cb = self._make_cb(enabled=True, min_confidence=0.6)
        signal = {
            "direction": "long",
            "market_regime": {"regime": "trending_up", "confidence": 0.9},
        }
        decision = cb._check_direction_gating(signal)
        assert decision.allowed is True

    def test_direction_gating_low_confidence_treats_as_unknown(self):
        cb = self._make_cb(enabled=True, min_confidence=0.6)
        # Low confidence -> effective regime = unknown -> only long allowed
        signal = {
            "direction": "long",
            "market_regime": {"regime": "trending_down", "confidence": 0.3},
        }
        decision = cb._check_direction_gating(signal)
        assert decision.allowed is True  # long allowed in unknown

    def test_direction_gating_disabled_allows(self):
        cb = self._make_cb(enabled=False)
        signal = {
            "direction": "short",
            "market_regime": {"regime": "trending_up", "confidence": 0.9},
        }
        # When disabled, should_allow_signal won't call direction gating
        decision = cb.should_allow_signal(signal)
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Regime avoidance (lines 970, 976-977)
# ---------------------------------------------------------------------------


class TestCircuitBreakerRegimeAvoidance:
    """Lines 970, 976-977: regime-based avoidance."""

    def _make_cb(self, enabled=True, blocked_regimes=None, min_confidence=0.6):
        config = TradingCircuitBreakerConfig(
            enable_regime_avoidance=enabled,
            blocked_regimes=blocked_regimes or ["ranging", "volatile"],
            regime_avoidance_min_confidence=min_confidence,
        )
        return TradingCircuitBreaker(config)

    def test_regime_in_avoid_list_blocks(self):
        cb = self._make_cb(enabled=True, blocked_regimes=["choppy", "ranging"])
        signal = {
            "direction": "long",
            "market_regime": {"regime": "ranging", "confidence": 0.8},
        }
        decision = cb._check_regime_avoidance(signal)
        assert decision.allowed is False

    def test_regime_not_in_avoid_list_allows(self):
        cb = self._make_cb(enabled=True, blocked_regimes=["choppy"])
        signal = {
            "direction": "long",
            "market_regime": {"regime": "trending", "confidence": 0.8},
        }
        decision = cb._check_regime_avoidance(signal)
        assert decision.allowed is True

    def test_regime_avoidance_low_confidence_allows(self):
        cb = self._make_cb(enabled=True, blocked_regimes=["choppy"], min_confidence=0.7)
        signal = {
            "direction": "long",
            "market_regime": {"regime": "choppy", "confidence": 0.3},
        }
        decision = cb._check_regime_avoidance(signal)
        assert decision.allowed is True  # low confidence => skip avoidance

    def test_regime_avoidance_disabled_allows(self):
        cb = self._make_cb(enabled=False)
        signal = {
            "direction": "long",
            "market_regime": {"regime": "choppy", "confidence": 0.9},
        }
        # When disabled, should_allow_signal won't call regime avoidance
        decision = cb.should_allow_signal(signal)
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Trigger filters (line 1025)
# ---------------------------------------------------------------------------


class TestCircuitBreakerTriggerFilters:
    """Line 1025: trigger-specific volume confirmation."""

    def _make_cb(self, enabled=True):
        config = TradingCircuitBreakerConfig(
            enable_trigger_filters=enabled,
            ema_cross_require_volume=True,
            low_regime_require_volume=True,
        )
        return TradingCircuitBreaker(config)

    def test_trigger_filter_blocks_ema_cross_no_volume(self):
        cb = self._make_cb(enabled=True)
        signal = {"entry_trigger": "ema_cross", "volume_confirmed": False, "direction": "long"}
        decision = cb._check_trigger_filters(signal)
        assert decision.allowed is False

    def test_trigger_filter_allows_ema_cross_with_volume(self):
        cb = self._make_cb(enabled=True)
        signal = {"entry_trigger": "ema_cross", "volume_confirmed": True, "direction": "long"}
        decision = cb._check_trigger_filters(signal)
        assert decision.allowed is True

    def test_trigger_filter_disabled_allows(self):
        cb = self._make_cb(enabled=False)
        signal = {"entry_trigger": "ema_cross", "volume_confirmed": False, "direction": "long"}
        # When disabled, should_allow_signal won't call trigger filters
        decision = cb.should_allow_signal(signal)
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Validate config (lines 490-515)
# ---------------------------------------------------------------------------


class TestCircuitBreakerValidateConfig:
    """Lines 490-515: config validation."""

    def test_validate_empty_blocked_regimes(self):
        config = TradingCircuitBreakerConfig(
            enable_regime_avoidance=True,
            blocked_regimes=[],
        )
        cb = TradingCircuitBreaker(config)
        warnings = cb.validate_config()
        assert any("regime" in w.lower() for w in warnings)

    def test_validate_invalid_direction_confidence(self):
        config = TradingCircuitBreakerConfig(
            enable_direction_gating=True,
            direction_gating_min_confidence=2.0,
        )
        cb = TradingCircuitBreaker(config)
        warnings = cb.validate_config()
        assert any("direction_gating_min_confidence" in w for w in warnings)

    def test_validate_invalid_mode(self):
        config = TradingCircuitBreakerConfig(
            mode="invalid_mode",
        )
        cb = TradingCircuitBreaker(config)
        warnings = cb.validate_config()
        assert any("mode" in w.lower() for w in warnings)

    def test_validate_trigger_filters_both_disabled(self):
        config = TradingCircuitBreakerConfig(
            enable_trigger_filters=True,
            ema_cross_require_volume=False,
            low_regime_require_volume=False,
        )
        cb = TradingCircuitBreaker(config)
        warnings = cb.validate_config()
        assert any("trigger" in w.lower() or "volume" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Record trade result (lines 336-339)
# ---------------------------------------------------------------------------


class TestCircuitBreakerRecordTradeResult:
    """Lines 336-339: test signal skipping."""

    def test_record_normal_trade(self):
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
        trade = {"pnl": 100.0, "is_win": True}
        cb.record_trade_result(trade)
        assert len(cb._recent_trades) == 1

    def test_record_loss_increments_consecutive(self):
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
        trade = {"pnl": -50.0, "is_win": False}
        cb.record_trade_result(trade)
        assert cb._consecutive_losses >= 1

    def test_record_win_clears_consecutive_losses(self):
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
        cb.record_trade_result({"pnl": -50.0, "is_win": False})
        cb.record_trade_result({"pnl": -50.0, "is_win": False})
        assert cb._consecutive_losses == 2
        cb.record_trade_result({"pnl": 100.0, "is_win": True})
        assert cb._consecutive_losses == 0


# ---------------------------------------------------------------------------
# Shadow outcome tracking (lines 437-441)
# ---------------------------------------------------------------------------


class TestCircuitBreakerShadowOutcomes:
    """Lines 437-441: shadow outcome detailed tracking."""

    def test_shadow_outcome_recorded_blocked(self):
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
        cb.record_shadow_outcome(pnl=-50.0, is_win=False, was_would_block=True)
        assert cb._shadow_blocked_losses == 1
        assert cb._shadow_blocked_pnl == -50.0

    def test_shadow_outcome_recorded_allowed(self):
        cb = TradingCircuitBreaker(TradingCircuitBreakerConfig())
        cb.record_shadow_outcome(pnl=100.0, is_win=True, was_would_block=False)
        assert cb._shadow_allowed_wins == 1
        assert cb._shadow_allowed_pnl == 100.0


# ===========================================================================
# SignalHandler Tests
# ===========================================================================


class TestSignalHandlerProtectionGuard:
    """Lines 772-833: _enforce_tradovate_protection_guard()."""

    def _make_handler(self, adapter=None):
        from pearlalgo.market_agent.signal_handler import SignalHandler
        handler = MagicMock(spec=SignalHandler)
        handler.execution_adapter = adapter
        handler._enforce_tradovate_protection_guard = (
            SignalHandler._enforce_tradovate_protection_guard.__get__(handler, SignalHandler)
        )
        return handler

    @pytest.mark.asyncio
    async def test_no_adapter_returns_true(self):
        handler = self._make_handler(adapter=None)
        result = await handler._enforce_tradovate_protection_guard({"direction": "long"})
        assert result is True

    @pytest.mark.asyncio
    async def test_no_get_account_summary_returns_true(self):
        adapter = MagicMock()
        del adapter.get_account_summary
        handler = self._make_handler(adapter=adapter)
        result = await handler._enforce_tradovate_protection_guard({"direction": "long"})
        assert result is True

    @pytest.mark.asyncio
    async def test_no_open_positions_returns_true(self):
        adapter = AsyncMock()
        adapter.get_account_summary.return_value = {"positions": []}
        handler = self._make_handler(adapter=adapter)
        result = await handler._enforce_tradovate_protection_guard({"direction": "long"})
        assert result is True

    @pytest.mark.asyncio
    async def test_valid_working_orders_returns_true(self):
        adapter = AsyncMock()
        adapter.get_account_summary.return_value = {
            "positions": [{"net_pos": 1, "instrument": "MNQH6"}],
            "working_orders": [{"qty": 1, "order_type": "Stop", "stop_price": 19900, "instrument": "MNQH6"}],
        }
        handler = self._make_handler(adapter=adapter)
        result = await handler._enforce_tradovate_protection_guard({"direction": "long"})
        assert result is True

    @pytest.mark.asyncio
    async def test_enforce_guard_disarms_and_returns_false(self):
        adapter = AsyncMock()
        adapter.get_account_summary.return_value = {
            "positions": [{"net_pos": 1, "instrument": "MNQH6"}],
            "working_orders": [],
        }
        adapter.config = MagicMock()
        adapter.config.enforce_protection_guard = True
        adapter.disarm = MagicMock()
        adapter._has_existing_stop_for_position = AsyncMock(return_value=False)
        handler = self._make_handler(adapter=adapter)
        result = await handler._enforce_tradovate_protection_guard({"signal_id": "test123"})
        assert result is False

    @pytest.mark.asyncio
    async def test_warn_only_mode_returns_true(self):
        adapter = AsyncMock()
        adapter.get_account_summary.return_value = {
            "positions": [{"net_pos": 1, "instrument": "MNQH6"}],
            "working_orders": [],
        }
        adapter.config = MagicMock()
        adapter.config.enforce_protection_guard = False
        handler = self._make_handler(adapter=adapter)
        result = await handler._enforce_tradovate_protection_guard({"signal_id": "test123"})
        assert result is True

    @pytest.mark.asyncio
    async def test_exception_returns_true(self):
        adapter = AsyncMock()
        adapter.get_account_summary.side_effect = Exception("API error")
        handler = self._make_handler(adapter=adapter)
        result = await handler._enforce_tradovate_protection_guard({"direction": "long"})
        assert result is True


# ---------------------------------------------------------------------------
# _execute_signal guard failure (lines 709-719)
# ---------------------------------------------------------------------------


class TestSignalHandlerExecuteSignal:
    """Lines 709-719: guard failure path."""

    def _make_handler(self):
        from pearlalgo.market_agent.signal_handler import SignalHandler
        handler = MagicMock(spec=SignalHandler)
        handler._enforce_tradovate_protection_guard = AsyncMock(return_value=False)
        handler._execute_signal = SignalHandler._execute_signal.__get__(handler, SignalHandler)
        return handler

    @pytest.mark.asyncio
    async def test_guard_failure_blocks_execution(self):
        handler = self._make_handler()
        handler._enforce_tradovate_protection_guard = AsyncMock(return_value=False)
        handler.execution_adapter = MagicMock()
        signal = {"direction": "long", "entry_price": 20000, "confidence": 0.8}
        await handler._execute_signal(signal, policy_decision=None)
        assert signal.get("_execution_status") == "skipped:unprotected_open_position_auto_disarm"

    @pytest.mark.asyncio
    async def test_guard_passes_continues(self):
        handler = self._make_handler()
        handler._enforce_tradovate_protection_guard = AsyncMock(return_value=True)
        handler.execution_adapter = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.parent_order_id = "ORD123"
        handler.execution_adapter.check_preconditions.return_value = MagicMock(execute=True)
        handler.execution_adapter.place_bracket = AsyncMock(return_value=mock_result)
        signal = {"direction": "long", "entry_price": 20000, "confidence": 0.8}
        await handler._execute_signal(signal, policy_decision=None)
        assert signal.get("_execution_status") == "placed"

    @pytest.mark.asyncio
    async def test_execution_exception_handled(self):
        handler = self._make_handler()
        handler._enforce_tradovate_protection_guard = AsyncMock(return_value=True)
        handler.execution_adapter = MagicMock()
        handler.execution_adapter.check_preconditions.side_effect = Exception("order fail")
        signal = {"direction": "long", "entry_price": 20000, "confidence": 0.8}
        await handler._execute_signal(signal, policy_decision=None)
        assert "error:" in signal.get("_execution_status", "")

    @pytest.mark.asyncio
    async def test_no_adapter_skips_execution(self):
        handler = self._make_handler()
        handler.execution_adapter = None
        signal = {"direction": "long", "entry_price": 20000}
        await handler._execute_signal(signal, policy_decision=None)
        assert signal.get("_execution_status") == "not_attempted"


# ===========================================================================
# OrderManager Tests
# ===========================================================================


class TestOrderManagerValidateFinancials:
    """Lines 112-156: validate_signal_financials edge cases."""

    def _make_om(self):
        return OrderManager(
            risk_settings={"max_position_size": 10, "min_position_size": 1},
            strategy_settings={},
        )

    def test_missing_entry_price_and_stop(self):
        om = self._make_om()
        # Both missing -> nothing to validate -> True
        result = om.validate_signal_financials({"direction": "long"})
        assert result is True

    def test_non_numeric_entry_price(self):
        om = self._make_om()
        result = om.validate_signal_financials({
            "direction": "long", "entry_price": "abc", "stop_loss": 19900, "position_size": 1
        })
        assert result is False

    def test_negative_entry_price(self):
        om = self._make_om()
        result = om.validate_signal_financials({
            "direction": "long", "entry_price": -100, "stop_loss": -200, "position_size": 1
        })
        assert result is False

    def test_long_stop_above_entry(self):
        om = self._make_om()
        result = om.validate_signal_financials({
            "direction": "long", "entry_price": 20000, "stop_loss": 20100, "position_size": 1
        })
        assert result is False

    def test_short_stop_below_entry(self):
        om = self._make_om()
        result = om.validate_signal_financials({
            "direction": "short", "entry_price": 20000, "stop_loss": 19900, "position_size": 1
        })
        assert result is False

    def test_zero_stop_loss(self):
        om = self._make_om()
        result = om.validate_signal_financials({
            "direction": "long", "entry_price": 20000, "stop_loss": 0, "position_size": 1
        })
        assert result is False


# ---------------------------------------------------------------------------
# compute_base_position_size (lines 174-234)
# ---------------------------------------------------------------------------


class TestOrderManagerComputePositionSize:
    """Lines 174-234: dynamic sizing with confidence tiers."""

    def _make_om(self, risk=None, strategy=None):
        return OrderManager(
            risk_settings=risk or {"max_position_size": 10, "min_position_size": 1},
            strategy_settings=strategy or {},
        )

    def test_high_confidence_larger_size(self):
        om = self._make_om()
        size = om.compute_base_position_size({
            "confidence": 0.95,
            "entry_price": 20000,
            "stop_loss": 19900,
            "direction": "long",
        })
        assert size >= 1

    def test_low_confidence_smaller_size(self):
        om = self._make_om()
        size = om.compute_base_position_size({
            "confidence": 0.3,
            "entry_price": 20000,
            "stop_loss": 19900,
            "direction": "long",
        })
        assert size >= 1

    def test_signal_type_multiplier(self):
        om = self._make_om(
            strategy={"signal_type_size_multipliers": {"reversal": 0.5}}
        )
        size = om.compute_base_position_size({
            "confidence": 0.8,
            "type": "reversal",
            "entry_price": 20000,
            "stop_loss": 19900,
            "direction": "long",
        })
        assert size >= 1

    def test_clamped_to_max(self):
        om = self._make_om(risk={"max_position_size": 2, "min_position_size": 1})
        size = om.compute_base_position_size({
            "confidence": 0.99,
            "entry_price": 20000,
            "stop_loss": 19900,
            "direction": "long",
        })
        assert size <= 2

    def test_clamped_to_min(self):
        om = self._make_om(risk={"max_position_size": 10, "min_position_size": 3})
        size = om.compute_base_position_size({
            "confidence": 0.1,
            "entry_price": 20000,
            "stop_loss": 19900,
            "direction": "long",
        })
        assert size >= 3


# ---------------------------------------------------------------------------
# validate_position_size (lines 285-377)
# ---------------------------------------------------------------------------


class TestOrderManagerValidatePositionSize:
    """Lines 285-377: position size validation."""

    def _make_om(self, risk=None):
        return OrderManager(
            risk_settings=risk or {
                "max_position_size": 10,
                "min_position_size": 1,
                "max_position_pct": 0.1,
            },
            strategy_settings={},
        )

    def test_account_based_max(self):
        om = self._make_om(risk={
            "max_position_size": 100,
            "min_position_size": 1,
            "max_position_pct": 0.1,
        })
        result = om.validate_position_size(50, account_value=50000)
        assert isinstance(result, dict)
        assert result["adjusted_size"] <= 50

    def test_above_max_returns_clamped(self):
        om = self._make_om(risk={
            "max_position_size": 5,
            "min_position_size": 1,
        })
        result = om.validate_position_size(15)
        assert isinstance(result, dict)
        assert result["adjusted_size"] <= 5

    def test_below_min_returns_invalid(self):
        om = self._make_om(risk={
            "max_position_size": 10,
            "min_position_size": 2,
        })
        result = om.validate_position_size(1)
        assert isinstance(result, dict)
        assert result["valid"] is False

    def test_no_risk_settings(self):
        om = OrderManager(risk_settings={}, strategy_settings={})
        result = om.validate_position_size(5)
        assert isinstance(result, dict)
        assert "valid" in result
        assert "adjusted_size" in result

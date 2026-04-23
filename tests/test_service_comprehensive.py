"""
Comprehensive tests for MarketAgentService — targeting the largest uncovered line ranges.

Covers: init/config, position sizing, virtual trade management, auto-flat logic,
adaptive cadence, velocity mode, MTF trends, status snapshots, pearl insights,
data quality, heartbeat, close-all flows, ML delegation, and OS signal handling.
"""

from __future__ import annotations

import asyncio
import json
import signal as signal_module
import pytest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Minimal service config to avoid YAML load from disk
# ---------------------------------------------------------------------------
MINIMAL_SERVICE_CONFIG = {
    "service": {
        "scan_interval": 30,
        "status_update_interval": 900,
        "dashboard_chart_interval": 3600,
        "connection_failure_alert_interval": 600,
        "data_quality_alert_interval": 300,
        "state_save_interval": 10,
        "adaptive_cadence_enabled": False,
        "velocity_mode_enabled": False,
        "cadence_mode": "fixed",
        "enable_new_bar_gating": True,
    },
    "circuit_breaker": {
        "max_consecutive_errors": 10,
        "max_data_fetch_errors": 5,
        "max_connection_failures": 10,
    },
    "trading_circuit_breaker": {"enabled": False},
    "data": {
        "stale_data_threshold_minutes": 10,
        "buffer_size": 100,
    },
    "signals": {},
    "risk": {},
    "strategy": {},
    "telegram": {},
    "telegram_ui": {},
    "auto_flat": {},
    "storage": {"sqlite_enabled": False},
    "challenge": {},
    "execution": {"enabled": False},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_data_provider():
    from tests.mock_data_provider import MockDataProvider
    return MockDataProvider(
        simulate_delayed_data=False,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )


@pytest.fixture
def service(mock_data_provider, tmp_path):
    with patch(
        "pearlalgo.market_agent.service.load_service_config",
        return_value=MINIMAL_SERVICE_CONFIG.copy(),
    ):
        from pearlalgo.market_agent.service import MarketAgentService
        svc = MarketAgentService(
            data_provider=mock_data_provider,
            state_dir=tmp_path,
        )
    return svc


@pytest.fixture
def service_with_auto_flat(mock_data_provider, tmp_path):
    cfg = MINIMAL_SERVICE_CONFIG.copy()
    cfg["auto_flat"] = {
        "enabled": True,
        "daily_enabled": True,
        "friday_enabled": True,
        "weekend_enabled": True,
        "timezone": "America/New_York",
        "notify": True,
        "daily_time": "15:55",
        "friday_time": "16:55",
    }
    with patch(
        "pearlalgo.market_agent.service.load_service_config",
        return_value=cfg,
    ):
        from pearlalgo.market_agent.service import MarketAgentService
        svc = MarketAgentService(
            data_provider=mock_data_provider,
            state_dir=tmp_path,
        )
    return svc


@pytest.fixture
def service_adaptive(mock_data_provider, tmp_path):
    cfg = MINIMAL_SERVICE_CONFIG.copy()
    cfg["service"] = {
        **cfg["service"],
        "adaptive_cadence_enabled": True,
        "velocity_mode_enabled": True,
        "scan_interval_active_seconds": 5,
        "scan_interval_idle_seconds": 30,
        "scan_interval_market_closed_seconds": 300,
        "scan_interval_paused_seconds": 60,
        "scan_interval_velocity_seconds": 1.5,
        "velocity_atr_expansion_threshold": 1.20,
        "velocity_volume_spike_threshold": 2.0,
    }
    with patch(
        "pearlalgo.market_agent.service.load_service_config",
        return_value=cfg,
    ):
        from pearlalgo.market_agent.service import MarketAgentService
        svc = MarketAgentService(
            data_provider=mock_data_provider,
            state_dir=tmp_path,
        )
    return svc


def _make_signal(**overrides) -> dict:
    sig = {
        "signal_id": "test_signal_001",
        "type": "long_entry",
        "direction": "long",
        "entry_price": 17500.0,
        "stop_loss": 17450.0,
        "take_profit": 17600.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "generated",
        "confidence": 0.75,
    }
    sig.update(overrides)
    return sig


def _make_df(n=50, base_price=17500.0, freq="1min", include_atr=False, include_volume=True):
    """Helper to build an OHLCV DataFrame."""
    now = datetime.now(timezone.utc)
    idx = pd.date_range(now - timedelta(minutes=n), periods=n, freq=freq, tz=timezone.utc)
    close = base_price + np.cumsum(np.random.randn(n) * 2.0)
    df = pd.DataFrame({
        "open": close + np.random.randn(n) * 0.5,
        "high": close + abs(np.random.randn(n) * 1.5),
        "low": close - abs(np.random.randn(n) * 1.5),
        "close": close,
    }, index=idx)
    if include_volume:
        df["volume"] = np.abs(np.random.randn(n) * 1000 + 5000).astype(int)
    if include_atr:
        df["atr"] = abs(np.random.randn(n) * 3 + 5)
    return df


# ===========================================================================
# 1. _compute_base_position_size (lines 775-836)
# ===========================================================================

class TestComputeBasePositionSize:
    def test_returns_existing_position_size(self, service):
        sig = _make_signal(position_size=3)
        result = service._compute_base_position_size(sig)
        assert result == 3

    def test_returns_existing_position_size_float(self, service):
        sig = _make_signal(position_size=2.7)
        result = service._compute_base_position_size(sig)
        assert result == 2

    def test_returns_minimum_1_for_zero_existing(self, service):
        sig = _make_signal(position_size=0)
        result = service._compute_base_position_size(sig)
        assert result >= 1

    def test_default_base_contracts(self, service):
        sig = _make_signal()
        sig.pop("position_size", None)
        result = service._compute_base_position_size(sig)
        assert result >= 1

    def test_dynamic_sizing_high_confidence(self, service):
        service._strategy_settings = {
            "enable_dynamic_sizing": True,
            "base_contracts": 1,
            "high_conf_contracts": 2,
            "max_conf_contracts": 3,
            "high_conf_threshold": 0.8,
            "max_conf_threshold": 0.9,
        }
        sig = _make_signal(confidence=0.85)
        sig.pop("position_size", None)
        result = service._compute_base_position_size(sig)
        assert result == 2

    def test_dynamic_sizing_max_confidence(self, service):
        service._strategy_settings = {
            "enable_dynamic_sizing": True,
            "base_contracts": 1,
            "high_conf_contracts": 2,
            "max_conf_contracts": 3,
            "high_conf_threshold": 0.8,
            "max_conf_threshold": 0.9,
        }
        sig = _make_signal(confidence=0.95)
        sig.pop("position_size", None)
        result = service._compute_base_position_size(sig)
        assert result == 3

    def test_dynamic_sizing_low_confidence(self, service):
        service._strategy_settings = {
            "enable_dynamic_sizing": True,
            "base_contracts": 1,
            "high_conf_contracts": 2,
            "max_conf_contracts": 3,
            "high_conf_threshold": 0.8,
            "max_conf_threshold": 0.9,
        }
        sig = _make_signal(confidence=0.5)
        sig.pop("position_size", None)
        result = service._compute_base_position_size(sig)
        assert result == 1

    def test_signal_type_multiplier(self, service):
        service._strategy_settings = {
            "enable_dynamic_sizing": False,
            "base_contracts": 2,
            "signal_type_size_multipliers": {"momentum": 1.5},
        }
        sig = _make_signal(confidence=0.5, type="momentum")
        sig.pop("position_size", None)
        result = service._compute_base_position_size(sig)
        assert result == 3  # 2 * 1.5 = 3

    def test_risk_clamp_min(self, service):
        service._strategy_settings = {"base_contracts": 1}
        service._risk_settings = {"min_position_size": 2, "max_position_size": 5}
        sig = _make_signal()
        sig.pop("position_size", None)
        result = service._compute_base_position_size(sig)
        assert result >= 2

    def test_risk_clamp_max(self, service):
        service._strategy_settings = {
            "enable_dynamic_sizing": True,
            "base_contracts": 10,
            "high_conf_contracts": 10,
            "max_conf_contracts": 10,
        }
        service._risk_settings = {"max_position_size": 3}
        sig = _make_signal(confidence=0.99)
        sig.pop("position_size", None)
        result = service._compute_base_position_size(sig)
        assert result <= 3

    def test_invalid_confidence_defaults_to_zero(self, service):
        service._strategy_settings = {"enable_dynamic_sizing": True, "base_contracts": 1}
        sig = _make_signal(confidence="not_a_number")
        sig.pop("position_size", None)
        result = service._compute_base_position_size(sig)
        assert result >= 1

    def test_none_confidence(self, service):
        sig = _make_signal()
        sig["confidence"] = None
        sig.pop("position_size", None)
        result = service._compute_base_position_size(sig)
        assert result >= 1


# ===========================================================================
# 2. _find_initial_stop_price (lines 1060-1070)
# ===========================================================================

class TestFindInitialStopPrice:
    def test_returns_stop_from_virtual_trade(self, service):
        mock_tracker = MagicMock()
        mock_tracker.get_active_virtual_trades.return_value = [
            {"signal": {"direction": "long", "stop_loss": 17450.0}}
        ]
        service.virtual_trade_manager.position_tracker = mock_tracker
        result = service._find_initial_stop_price("long")
        assert result == 17450.0

    def test_returns_zero_when_no_match(self, service):
        mock_tracker = MagicMock()
        mock_tracker.get_active_virtual_trades.return_value = [
            {"signal": {"direction": "short", "stop_loss": 17550.0}}
        ]
        service.virtual_trade_manager.position_tracker = mock_tracker
        result = service._find_initial_stop_price("long")
        assert result == 0.0

    def test_returns_zero_on_exception(self, service):
        mock_tracker = MagicMock()
        mock_tracker.get_active_virtual_trades.side_effect = RuntimeError("DB error")
        service.virtual_trade_manager.position_tracker = mock_tracker
        result = service._find_initial_stop_price("long")
        assert result == 0.0

    def test_returns_zero_when_empty(self, service):
        mock_tracker = MagicMock()
        mock_tracker.get_active_virtual_trades.return_value = []
        service.virtual_trade_manager.position_tracker = mock_tracker
        result = service._find_initial_stop_price("long")
        assert result == 0.0


# ===========================================================================
# 4. _find_initial_stop_from_broker (lines 1071-1118)
# ===========================================================================

class TestFindInitialStopFromBroker:
    @pytest.mark.asyncio
    async def test_finds_working_stop_order(self, service):
        mock_adapter = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_orders.return_value = [
            {"orderType": "Stop", "action": "Sell", "ordStatus": "Working", "stopPrice": 17450.0}
        ]
        mock_adapter._client = mock_client
        service.execution_adapter = mock_adapter
        result = await service._find_initial_stop_from_broker("long", 17500.0, 10.0)
        assert result == 17450.0

    @pytest.mark.asyncio
    async def test_falls_back_to_atr(self, service):
        mock_adapter = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_orders.return_value = []
        mock_adapter._client = mock_client
        service.execution_adapter = mock_adapter
        result = await service._find_initial_stop_from_broker("long", 17500.0, 10.0)
        assert result == pytest.approx(17480.0)  # 17500 - 2*10

    @pytest.mark.asyncio
    async def test_falls_back_to_atr_short(self, service):
        mock_adapter = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_orders.return_value = []
        mock_adapter._client = mock_client
        service.execution_adapter = mock_adapter
        result = await service._find_initial_stop_from_broker("short", 17500.0, 10.0)
        assert result == pytest.approx(17520.0)  # 17500 + 2*10

    @pytest.mark.asyncio
    async def test_falls_back_to_2pct_long(self, service):
        mock_adapter = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_orders.side_effect = RuntimeError("Connection error")
        mock_adapter._client = mock_client
        service.execution_adapter = mock_adapter
        result = await service._find_initial_stop_from_broker("long", 17500.0, 0)
        assert result == pytest.approx(17500.0 * 0.98)

    @pytest.mark.asyncio
    async def test_falls_back_to_2pct_short(self, service):
        mock_adapter = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_orders.side_effect = RuntimeError("Connection error")
        mock_adapter._client = mock_client
        service.execution_adapter = mock_adapter
        result = await service._find_initial_stop_from_broker("short", 17500.0, 0)
        assert result == pytest.approx(17500.0 * 1.02)


# ===========================================================================
# 5. _get_current_atr (lines 1121-1134)
# ===========================================================================

class TestGetCurrentATR:
    def test_returns_atr_from_df(self, service):
        np.random.seed(42)
        df = _make_df(n=30, base_price=17500.0)
        market_data = {"df": df}
        result = service._get_current_atr(market_data)
        assert result > 0

    def test_returns_zero_when_df_too_short(self, service):
        df = _make_df(n=5)
        result = service._get_current_atr({"df": df})
        assert result == 0.0

    def test_returns_zero_when_df_none(self, service):
        result = service._get_current_atr({"df": None})
        assert result == 0.0

    def test_returns_zero_when_no_df_key(self, service):
        result = service._get_current_atr({})
        assert result == 0.0


# ===========================================================================
# 6. _find_stop_order_id (lines 1136-1148)
# ===========================================================================

class TestFindStopOrderId:
    @pytest.mark.asyncio
    async def test_finds_stop_order_id(self, service):
        mock_adapter = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_orders.return_value = [
            {"orderType": "Stop", "action": "Sell", "ordStatus": "Working", "id": 42}
        ]
        mock_adapter._client = mock_client
        service.execution_adapter = mock_adapter
        result = await service._find_stop_order_id("long")
        assert result == 42

    @pytest.mark.asyncio
    async def test_prefers_normalized_working_orders_from_account_summary(self, service):
        mock_adapter = MagicMock()
        mock_adapter.get_account_summary = AsyncMock(return_value={
            "working_orders": [
                {"id": 84, "action": "Sell", "order_type": "Stop", "stop_price": 17450.0},
            ]
        })
        mock_adapter._client = AsyncMock()
        service.execution_adapter = mock_adapter

        result = await service._find_stop_order_id("long")

        assert result == 84
        mock_adapter._client.get_orders.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self, service):
        mock_adapter = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_orders.return_value = []
        mock_adapter.get_account_summary = AsyncMock(return_value={"working_orders": []})
        mock_adapter._client = mock_client
        service.execution_adapter = mock_adapter
        result = await service._find_stop_order_id("long")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, service):
        mock_adapter = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_orders.side_effect = RuntimeError("Error")
        mock_adapter.get_account_summary = AsyncMock(side_effect=RuntimeError("summary failed"))
        mock_adapter._client = mock_client
        service.execution_adapter = mock_adapter
        result = await service._find_stop_order_id("long")
        assert result is None


# ===========================================================================
# 7. _update_virtual_trade_exits (line 1150-1152)
# ===========================================================================

class TestUpdateVirtualTradeExits:
    def test_delegates_to_virtual_trade_manager(self, service):
        service.virtual_trade_manager.process_exits = MagicMock()
        market_data = {"df": None}
        service._update_virtual_trade_exits(market_data)
        service.virtual_trade_manager.process_exits.assert_called_once_with(market_data)


# ===========================================================================
# 8. _get_status_snapshot (lines 1154-1230)
# ===========================================================================

class TestGetStatusSnapshot:
    def test_returns_required_keys(self, service):
        service.running = True
        service.paused = False
        service.start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        service.signal_count = 5
        service.connection_failures = 0
        service.performance_tracker.get_daily_performance = MagicMock(
            return_value={"total_pnl": 150.0, "wins": 3, "losses": 1}
        )
        result = service._get_status_snapshot()
        assert "agent_running" in result
        assert "daily_pnl" in result
        assert "data_stale" in result
        assert result["agent_running"] is True
        assert result["daily_pnl"] == 150.0
        assert result["wins_today"] == 3

    def test_handles_performance_error(self, service):
        service.running = True
        service.paused = False
        service.start_time = datetime.now(timezone.utc)
        service.performance_tracker.get_daily_performance = MagicMock(
            side_effect=RuntimeError("DB error")
        )
        result = service._get_status_snapshot()
        assert result["daily_pnl"] == 0.0
        assert result["wins_today"] == 0

    def test_uptime_hours_calculated(self, service):
        service.start_time = datetime.now(timezone.utc) - timedelta(hours=2)
        result = service._get_status_snapshot()
        assert result.get("agent_uptime_hours", 0) >= 1.9

    def test_trading_circuit_breaker_status(self, service):
        mock_cb = MagicMock()
        mock_cb.get_status.return_value = {
            "daily_pnl": -50.0,
            "session_pnl": -30.0,
            "would_block_total": 2,
            "mode": "enforce",
        }
        service.trading_circuit_breaker = mock_cb
        result = service._get_status_snapshot()
        assert result["risk_daily_pnl"] == -50.0
        assert result["risk_mode"] == "enforce"


# ===========================================================================
# 10. _generate_pearl_insight (lines 1480-1524)
# ===========================================================================

class TestGeneratePearlInsight:
    def test_futures_closed(self, service):
        result = service._generate_pearl_insight(
            is_running=True, is_session_open=True, is_futures_open=False,
            daily_pnl=0.0, today_trades=[],
        )
        assert "closed" in result.lower()

    def test_session_paused(self, service):
        result = service._generate_pearl_insight(
            is_running=True, is_session_open=False, is_futures_open=True,
            daily_pnl=0.0, today_trades=[],
        )
        assert "paused" in result.lower()

    def test_not_running(self, service):
        result = service._generate_pearl_insight(
            is_running=False, is_session_open=True, is_futures_open=True,
            daily_pnl=0.0, today_trades=[],
        )
        assert "stopped" in result.lower()

    def test_no_trades(self, service):
        result = service._generate_pearl_insight(
            is_running=True, is_session_open=True, is_futures_open=True,
            daily_pnl=0.0, today_trades=[],
        )
        assert "no trades" in result.lower()

    def test_positive_day(self, service):
        trades = [{"is_win": True, "pnl": 50}] * 3
        result = service._generate_pearl_insight(
            is_running=True, is_session_open=True, is_futures_open=True,
            daily_pnl=200.0, today_trades=trades,
        )
        assert "great" in result.lower() or "up" in result.lower()

    def test_negative_day(self, service):
        trades = [{"is_win": False, "pnl": -50}] * 3
        result = service._generate_pearl_insight(
            is_running=True, is_session_open=True, is_futures_open=True,
            daily_pnl=-200.0, today_trades=trades,
        )
        assert "tough" in result.lower() or "down" in result.lower()

    def test_high_winrate(self, service):
        trades = [{"is_win": True}] * 4 + [{"is_win": False}]
        result = service._generate_pearl_insight(
            is_running=True, is_session_open=True, is_futures_open=True,
            daily_pnl=50.0, today_trades=trades,
        )
        assert "win rate" in result.lower() or "sharp" in result.lower()

    def test_low_winrate(self, service):
        trades = [{"is_win": False}] * 4 + [{"is_win": True}]
        result = service._generate_pearl_insight(
            is_running=True, is_session_open=True, is_futures_open=True,
            daily_pnl=-10.0, today_trades=trades,
        )
        assert "choppy" in result.lower() or "wr" in result.lower()

    def test_losing_streak(self, service):
        # 4 losses, 0 wins => wr < 40 and trades_count >= 3, hits "choppy" branch
        trades = [{"is_win": False}] * 4
        result = service._generate_pearl_insight(
            is_running=True, is_session_open=True, is_futures_open=True,
            daily_pnl=-50.0, today_trades=trades,
        )
        assert "choppy" in result.lower() or "wr" in result.lower()

    def test_normal_state(self, service):
        trades = [{"is_win": True}, {"is_win": False}]
        result = service._generate_pearl_insight(
            is_running=True, is_session_open=True, is_futures_open=True,
            daily_pnl=10.0, today_trades=trades,
        )
        assert "normal" in result.lower() or "scanning" in result.lower()


# ===========================================================================
# 11. _build_pearl_review_message (lines 1339-1478)
# ===========================================================================

class TestBuildPearlReviewMessage:
    def test_returns_string_for_running_state(self, service):
        state = {
            "agent_running": True,
            "session_open": True,
            "futures_open": True,
        }
        service.performance_tracker.load_performance_data = MagicMock(return_value=[])
        result = service._build_pearl_review_message(state)
        assert result is not None
        assert "Running" in result

    def test_returns_string_for_stopped_state(self, service):
        state = {
            "agent_running": False,
            "session_open": False,
            "futures_open": False,
        }
        service.performance_tracker.load_performance_data = MagicMock(return_value=[])
        result = service._build_pearl_review_message(state)
        assert result is not None
        assert "Stopped" in result

    def test_includes_trade_count(self, service):
        # service_status.summarize_pearl_review_trades matches today via
        # substring on the ET date. Pin an ET-naive instant so the test
        # is stable around UTC-vs-ET date boundaries.
        now_et = datetime(2026, 3, 25, 15, 0)
        state = {
            "agent_running": True,
            "session_open": True,
            "futures_open": True,
        }
        trades = [
            {"exit_time": now_et.isoformat(), "pnl": 50.0, "is_win": True, "signal_id": "s1"},
            {"exit_time": now_et.isoformat(), "pnl": -20.0, "is_win": False, "signal_id": "s2"},
        ]
        service.performance_tracker.load_performance_data = MagicMock(return_value=trades)
        with patch(
            "pearlalgo.market_agent.service_status._now_et_naive",
            return_value=now_et,
        ):
            result = service._build_pearl_review_message(state)
        assert result is not None
        assert "2 trades" in result

    def test_handles_exception_gracefully(self, service):
        state = {"agent_running": True}
        service.performance_tracker.load_performance_data = MagicMock(
            side_effect=RuntimeError("DB error")
        )
        # Should not raise
        result = service._build_pearl_review_message(state)
        # Might return None or a partial message
        assert result is None or isinstance(result, str)


# ===========================================================================
# 11b. Pure status/review helpers
# ===========================================================================

class TestPureServiceStatusHelpers:
    def test_build_market_agent_status_snapshot(self):
        from pearlalgo.market_agent.service_status import build_market_agent_status_snapshot

        checker = MagicMock()
        checker.check_data_freshness.return_value = {"age_minutes": 1.5, "is_fresh": True}
        perf_tracker = MagicMock()
        perf_tracker.get_daily_performance.return_value = {
            "total_pnl": 125.0,
            "wins": 2,
            "losses": 1,
        }
        circuit_breaker = MagicMock()
        circuit_breaker.get_status.return_value = {
            "daily_pnl": -25.0,
            "session_pnl": -10.0,
            "would_block_total": 1,
            "mode": "enforce",
        }

        with patch(
            "pearlalgo.market_agent.service_status.get_market_hours",
            return_value=MagicMock(is_market_open=MagicMock(return_value=True)),
        ):
            with patch(
                "pearlalgo.market_agent.service_status.check_trading_session",
                return_value=True,
            ):
                result = build_market_agent_status_snapshot(
                    running=True,
                    paused=False,
                    start_time=datetime.now(timezone.utc) - timedelta(hours=1),
                    last_market_data={"latest_bar": {"close": 1}, "df": MagicMock()},
                    data_quality_checker=checker,
                    performance_tracker=perf_tracker,
                    connection_failures=0,
                    max_connection_failures=10,
                    signal_count=4,
                    quiet_period_minutes=7.5,
                    config={},
                    trading_circuit_breaker=circuit_breaker,
                    streak_count=3,
                    streak_type="win",
                )

        assert result["agent_running"] is True
        assert result["daily_pnl"] == 125.0
        assert result["wins_today"] == 2
        assert result["data_stale"] is False
        assert result["risk_mode"] == "enforce"
        assert result["win_streak"] == 3

    def test_build_pearl_review_message_and_summary_helpers(self):
        from pearlalgo.market_agent.service_status import (
            build_pearl_review_message,
            summarize_pearl_review_trades,
        )

        now_et = datetime(2026, 3, 25, 15, 0)
        perf_trades = [
            {"exit_time": "2026-03-25T13:10:00", "pnl": 75.0, "is_win": True, "signal_id": "s1"},
            {"exit_time": "2026-03-25T14:00:00", "pnl": 25.0, "is_win": True, "signal_id": "s1"},
            {"exit_time": "2026-03-25T14:45:00", "pnl": -10.0, "is_win": False, "signal_id": "s2"},
        ]

        summary = summarize_pearl_review_trades(perf_trades, now_et=now_et)
        message = build_pearl_review_message(
            {
                "agent_running": True,
                "session_open": True,
                "futures_open": True,
            },
            perf_trades=perf_trades,
            now_et=now_et,
        )

        assert len(summary.today_trades) == 2
        assert summary.daily_pnl == 15.0
        assert "Last Trade: 15m ago" in summary.time_since_trade
        assert "2 trades" in message
        assert "Running" in message


# ===========================================================================
# 12. _parse_hhmm (lines 2458-2471)
# ===========================================================================

class TestParseHHMM:
    def test_valid_time(self):
        from pearlalgo.market_agent.service import MarketAgentService
        assert MarketAgentService._parse_hhmm("15:55", default=(0, 0)) == (15, 55)

    def test_midnight(self):
        from pearlalgo.market_agent.service import MarketAgentService
        assert MarketAgentService._parse_hhmm("00:00", default=(1, 1)) == (0, 0)

    def test_invalid_returns_default(self):
        from pearlalgo.market_agent.service import MarketAgentService
        assert MarketAgentService._parse_hhmm("invalid", default=(10, 30)) == (10, 30)

    def test_none_returns_default(self):
        from pearlalgo.market_agent.service import MarketAgentService
        assert MarketAgentService._parse_hhmm(None, default=(10, 30)) == (10, 30)

    def test_out_of_range_returns_default(self):
        from pearlalgo.market_agent.service import MarketAgentService
        assert MarketAgentService._parse_hhmm("25:00", default=(10, 30)) == (10, 30)

    def test_single_part_returns_default(self):
        from pearlalgo.market_agent.service import MarketAgentService
        assert MarketAgentService._parse_hhmm("1500", default=(10, 30)) == (10, 30)


# ===========================================================================
# 13. _auto_flat_due (lines 2520-2555)
# ===========================================================================

class TestAutoFlatDue:
    def test_daily_auto_flat(self, service_with_auto_flat):
        svc = service_with_auto_flat
        # 4pm ET on a Wednesday
        et = ZoneInfo("America/New_York")
        local_time = datetime(2026, 3, 11, 16, 0, tzinfo=et)  # Wednesday
        utc_time = local_time.astimezone(timezone.utc)
        result = svc._auto_flat_due(utc_time, market_open=True)
        assert result == "daily_auto_flat"

    def test_daily_auto_flat_before_time(self, service_with_auto_flat):
        svc = service_with_auto_flat
        et = ZoneInfo("America/New_York")
        local_time = datetime(2026, 3, 11, 14, 0, tzinfo=et)  # Before 15:55
        utc_time = local_time.astimezone(timezone.utc)
        result = svc._auto_flat_due(utc_time, market_open=True)
        assert result is None

    def test_friday_auto_flat(self, service_with_auto_flat):
        svc = service_with_auto_flat
        et = ZoneInfo("America/New_York")
        local_time = datetime(2026, 3, 13, 17, 0, tzinfo=et)  # Friday 5pm
        utc_time = local_time.astimezone(timezone.utc)
        # Already triggered daily, reset
        svc._auto_flat_last_dates["daily_auto_flat"] = local_time.date()
        result = svc._auto_flat_due(utc_time, market_open=True)
        assert result == "friday_auto_flat"

    def test_weekend_auto_flat_saturday(self, service_with_auto_flat):
        svc = service_with_auto_flat
        et = ZoneInfo("America/New_York")
        local_time = datetime(2026, 3, 14, 12, 0, tzinfo=et)  # Saturday
        utc_time = local_time.astimezone(timezone.utc)
        result = svc._auto_flat_due(utc_time, market_open=False)
        assert result == "weekend_auto_flat"

    def test_no_flat_when_disabled(self, service):
        # Default service has auto_flat disabled
        now = datetime.now(timezone.utc)
        result = service._auto_flat_due(now, market_open=True)
        assert result is None

    def test_no_duplicate_daily_flat(self, service_with_auto_flat):
        svc = service_with_auto_flat
        et = ZoneInfo("America/New_York")
        local_time = datetime(2026, 3, 11, 16, 0, tzinfo=et)
        utc_time = local_time.astimezone(timezone.utc)
        svc._auto_flat_last_dates["daily_auto_flat"] = local_time.date()
        result = svc._auto_flat_due(utc_time, market_open=True)
        # Daily already done, check if friday or weekend would trigger
        assert result != "daily_auto_flat"


# ===========================================================================
# 14. _resolve_latest_prices (lines 2486-2518)
# ===========================================================================

class TestResolveLatestPrices:
    def test_from_market_data(self, service):
        md = {"latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0, "_data_level": "L1"}}
        result = service._resolve_latest_prices(md)
        assert result["close"] == 17500.0
        assert result["bid"] == 17499.0
        assert result["ask"] == 17501.0
        assert result["source"] == "L1"

    def test_from_cached_data(self, service):
        service.data_fetcher._last_market_data = {
            "latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0}
        }
        result = service._resolve_latest_prices(None)
        assert result["close"] == 17500.0

    def test_no_data_available(self, service):
        service.data_fetcher._last_market_data = None
        result = service._resolve_latest_prices(None)
        assert result["close"] is None
        assert result["bid"] is None

    def test_invalid_prices(self, service):
        md = {"latest_bar": {"close": 0, "bid": -1}}
        result = service._resolve_latest_prices(md)
        assert result["close"] is None
        assert result["bid"] is None


# ===========================================================================
# 15. _get_active_virtual_trades (lines 2473-2484)
# ===========================================================================

class TestGetActiveVirtualTrades:
    def test_returns_entered_signals(self, service):
        service.state_manager.get_recent_signals = MagicMock(return_value=[
            {"status": "entered", "signal_id": "s1"},
            {"status": "exited", "signal_id": "s2"},
            {"status": "entered", "signal_id": "s3"},
        ])
        result = service._get_active_virtual_trades()
        assert len(result) == 2
        assert all(r["status"] == "entered" for r in result)

    def test_returns_empty_on_error(self, service):
        service.state_manager.get_recent_signals = MagicMock(
            side_effect=RuntimeError("IO error")
        )
        result = service._get_active_virtual_trades()
        assert result == []

    def test_returns_empty_when_no_entered(self, service):
        service.state_manager.get_recent_signals = MagicMock(return_value=[
            {"status": "exited", "signal_id": "s1"},
        ])
        result = service._get_active_virtual_trades()
        assert result == []


# ===========================================================================
# 16. _close_all_virtual_trades (lines 2557-2665)
# ===========================================================================

class TestCloseAllVirtualTrades:
    @pytest.mark.asyncio
    async def test_closes_active_trades(self, service):
        service.state_manager.get_recent_signals = MagicMock(return_value=[
            {"status": "entered", "signal_id": "s1", "signal": {"direction": "long"}},
        ])
        service.performance_tracker.track_exit = MagicMock(return_value={"pnl": 50.0})
        service.state_manager.load_state = MagicMock(return_value={})
        service.state_manager.save_state = MagicMock()
        service.state_manager.append_event = MagicMock()
        md = {"latest_bar": {"close": 17500.0}}
        closed, pnl = await service._close_all_virtual_trades(
            market_data=md, reason="test", notify=False,
        )
        assert closed == 1
        assert pnl == 50.0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_active(self, service):
        service.state_manager.get_recent_signals = MagicMock(return_value=[])
        md = {"latest_bar": {"close": 17500.0}}
        closed, pnl = await service._close_all_virtual_trades(
            market_data=md, reason="test", notify=False,
        )
        assert closed == 0
        assert pnl == 0.0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_price(self, service):
        service.state_manager.get_recent_signals = MagicMock(return_value=[
            {"status": "entered", "signal_id": "s1", "signal": {"direction": "long"}},
        ])
        service.data_fetcher._last_market_data = None
        md = {}
        closed, pnl = await service._close_all_virtual_trades(
            market_data=md, reason="test", notify=False,
        )
        assert closed == 0

    @pytest.mark.asyncio
    async def test_uses_bid_for_long_exit(self, service):
        service.state_manager.get_recent_signals = MagicMock(return_value=[
            {"status": "entered", "signal_id": "s1", "signal": {"direction": "long"}},
        ])
        service.performance_tracker.track_exit = MagicMock(return_value={"pnl": 10.0})
        service.state_manager.load_state = MagicMock(return_value={})
        service.state_manager.save_state = MagicMock()
        service.state_manager.append_event = MagicMock()
        md = {"latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0}}
        await service._close_all_virtual_trades(market_data=md, reason="test", notify=False)
        call_args = service.performance_tracker.track_exit.call_args
        assert call_args.kwargs["exit_price"] == 17499.0


# ===========================================================================
# 17. _close_specific_virtual_trades (lines 2667-2744)
# ===========================================================================

class TestCloseSpecificVirtualTrades:
    @pytest.mark.asyncio
    async def test_closes_matching_signal_ids(self, service):
        service.state_manager.get_recent_signals = MagicMock(return_value=[
            {"status": "entered", "signal_id": "s1", "signal": {"direction": "long"}},
            {"status": "entered", "signal_id": "s2", "signal": {"direction": "short"}},
        ])
        service.performance_tracker.track_exit = MagicMock(return_value={"pnl": 25.0})
        service.state_manager.load_state = MagicMock(return_value={})
        service.state_manager.save_state = MagicMock()
        md = {"latest_bar": {"close": 17500.0}}
        closed = await service._close_specific_virtual_trades(
            signal_ids=["s1"], market_data=md, reason="manual",
        )
        assert "s1" in closed
        assert "s2" not in closed

    @pytest.mark.asyncio
    async def test_returns_empty_for_nonexistent_ids(self, service):
        service.state_manager.get_recent_signals = MagicMock(return_value=[
            {"status": "entered", "signal_id": "s1", "signal": {"direction": "long"}},
        ])
        md = {"latest_bar": {"close": 17500.0}}
        closed = await service._close_specific_virtual_trades(
            signal_ids=["nonexistent"], market_data=md, reason="manual",
        )
        assert closed == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_ids(self, service):
        closed = await service._close_specific_virtual_trades(
            signal_ids=[], market_data={}, reason="manual",
        )
        assert closed == []


# ===========================================================================
# 18. _clear_close_all_flag (lines 2746-2765)
# ===========================================================================

class TestClearCloseAllFlag:
    def test_with_orchestrator(self, service):
        service.execution_orchestrator.clear_close_all_flag = MagicMock()
        service._clear_close_all_flag()
        service.execution_orchestrator.clear_close_all_flag.assert_called_once()

    def test_fallback_without_orchestrator(self, service):
        service.execution_orchestrator = None
        service.state_manager.load_state = MagicMock(
            return_value={"close_all_requested": True, "close_all_requested_time": "now"}
        )
        service.state_manager.save_state = MagicMock()
        service._clear_close_all_flag()
        saved = service.state_manager.save_state.call_args[0][0]
        assert "close_all_requested" not in saved


# ===========================================================================
# 19. _get_close_signals_requested / _clear_close_signals_requested
# ===========================================================================

class TestCloseSignalsRequested:
    def test_get_with_orchestrator(self, service):
        service.execution_orchestrator.get_close_signals_requested = MagicMock(return_value=["s1"])
        result = service._get_close_signals_requested()
        assert result == ["s1"]

    def test_get_fallback(self, service):
        service.execution_orchestrator = None
        service.state_manager.load_state = MagicMock(
            return_value={"close_signals_requested": ["s1", "s2"]}
        )
        result = service._get_close_signals_requested()
        assert result == ["s1", "s2"]

    def test_clear_specific_ids(self, service):
        service.execution_orchestrator = None
        service.state_manager.load_state = MagicMock(
            return_value={"close_signals_requested": ["s1", "s2", "s3"]}
        )
        service.state_manager.save_state = MagicMock()
        service._clear_close_signals_requested(["s1", "s3"])
        saved = service.state_manager.save_state.call_args[0][0]
        assert saved["close_signals_requested"] == ["s2"]

    def test_clear_all(self, service):
        service.execution_orchestrator = None
        service.state_manager.load_state = MagicMock(
            return_value={"close_signals_requested": ["s1"], "close_signals_requested_time": "t"}
        )
        service.state_manager.save_state = MagicMock()
        service._clear_close_signals_requested(None)
        saved = service.state_manager.save_state.call_args[0][0]
        assert "close_signals_requested" not in saved
        assert "close_signals_requested_time" not in saved


# ===========================================================================
# 20. _compute_effective_interval (lines 1584-1673)
# ===========================================================================

class TestComputeEffectiveInterval:
    def test_disabled_returns_base(self, service):
        result = service._compute_effective_interval()
        assert result == float(service.config.scan_interval)

    def test_paused_returns_paused_interval(self, service_adaptive):
        svc = service_adaptive
        svc.paused = True
        result = svc._compute_effective_interval()
        assert result == 60.0

    def test_market_closed_returns_closed_interval(self, service_adaptive):
        svc = service_adaptive
        svc.paused = False
        with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = False
            result = svc._compute_effective_interval()
        assert result == 300.0

    def test_session_open_returns_active(self, service_adaptive):
        svc = service_adaptive
        svc.paused = False
        with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True
            with patch("pearlalgo.trading_bots.signal_generator.check_trading_session", return_value=True):
                svc.data_fetcher._last_market_data = {
                    "latest_bar": {"timestamp": datetime.now(timezone.utc).isoformat()},
                    "df": _make_df(n=5),
                }
                result = svc._compute_effective_interval()
        # Should be active (5s) or velocity (1.5s)
        assert result <= 30.0

    def test_session_closed_returns_idle(self, service_adaptive):
        svc = service_adaptive
        svc.paused = False
        svc._velocity_mode_enabled = False
        with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True
            with patch("pearlalgo.trading_bots.signal_generator.check_trading_session", return_value=False):
                svc.data_fetcher._last_market_data = {
                    "latest_bar": {"timestamp": datetime.now(timezone.utc).isoformat()},
                }
                result = svc._compute_effective_interval()
        assert result == 30.0


# ===========================================================================
# 21. _check_velocity_conditions (lines 1675-1715)
# ===========================================================================

class TestCheckVelocityConditions:
    def test_atr_expansion_triggers(self, service_adaptive):
        svc = service_adaptive
        df = _make_df(n=25, include_atr=True)
        # Force ATR expansion
        df.loc[df.index[-1], "atr"] = 20.0
        df.loc[df.index[-6], "atr"] = 5.0  # 4x expansion > 1.20 threshold
        svc.data_fetcher._last_market_data = {"df": df}
        result = svc._check_velocity_conditions()
        assert "atr_expansion" in result

    def test_volume_spike_triggers(self, service_adaptive):
        svc = service_adaptive
        df = _make_df(n=25, include_volume=True)
        df["volume"] = 100  # Low baseline
        df.loc[df.index[-1], "volume"] = 500  # 5x spike > 2.0 threshold
        svc.data_fetcher._last_market_data = {"df": df}
        result = svc._check_velocity_conditions()
        assert "volume_spike" in result

    def test_no_trigger_normal_data(self, service_adaptive):
        svc = service_adaptive
        df = _make_df(n=25, include_atr=True, include_volume=True)
        # Make ATR and volume uniform
        df["atr"] = 5.0
        df["volume"] = 1000
        svc.data_fetcher._last_market_data = {"df": df}
        result = svc._check_velocity_conditions()
        assert result == ""

    def test_too_few_bars(self, service_adaptive):
        svc = service_adaptive
        df = _make_df(n=5)
        svc.data_fetcher._last_market_data = {"df": df}
        result = svc._check_velocity_conditions()
        assert result == ""

    def test_no_data(self, service_adaptive):
        svc = service_adaptive
        svc.data_fetcher._last_market_data = None
        result = svc._check_velocity_conditions()
        assert result == ""


# ===========================================================================
# 22. Additional init and state tests
# ===========================================================================

class TestServiceInitState:
    def test_signal_follower_mode_default_off(self, service):
        assert service._signal_follower_mode is False

    def test_signal_writer_mode_default_off(self, service):
        assert service._signal_writer_mode is False

    def test_state_dirty_default_false(self, service):
        assert service._state_dirty is False

    def test_mark_state_dirty(self, service):
        service._state_dirty = False
        service.mark_state_dirty()
        assert service._state_dirty is True

    def test_strategy_adapter_exists(self, service):
        assert hasattr(service, "strategy")
        assert callable(service.strategy.analyze)

    def test_virtual_trade_manager_exists(self, service):
        assert service.virtual_trade_manager is not None

    def test_scheduled_tasks_exists(self, service):
        assert service.scheduled_tasks is not None

    def test_operator_handler_exists(self, service):
        assert service.operator_handler is not None


# ===========================================================================
# 23. get_status (lines 2222-2388)
# ===========================================================================

class TestGetStatus:
    def test_basic_status_keys(self, service):
        service.running = True
        service.paused = False
        service.start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = service.get_status()
        assert "running" in result
        assert "paused" in result
        assert "cycle_count" in result
        assert "signal_count" in result
        assert "execution" in result
        assert "learning" not in result

    def test_uptime_calculation(self, service):
        service.start_time = datetime.now(timezone.utc) - timedelta(hours=2, minutes=30)
        result = service.get_status()
        assert result["uptime"]["hours"] == 2
        assert result["uptime"]["minutes"] == 30

    def test_no_start_time(self, service):
        service.start_time = None
        result = service.get_status()
        assert result["uptime"] is None

    def test_execution_disabled(self, service):
        service.execution_adapter = None
        result = service.get_status()
        assert result["execution"]["enabled"] is False

    def test_session_counters(self, service):
        service._cycle_count_at_start = 10
        service.cycle_count = 25
        service._signal_count_at_start = 5
        service.signal_count = 8
        result = service.get_status()
        assert result["cycle_count_session"] == 15
        assert result["signal_count_session"] == 3


# ===========================================================================
# 24. _sync_signal_handler_counters (lines 747-764)
# ===========================================================================

class TestSyncSignalHandlerCounters:
    def test_syncs_all_counters(self, service):
        sh = service._signal_handler
        sh.signal_count = 10
        sh.signals_sent = 8
        sh.signals_send_failures = 2
        sh.error_count = 3
        sh.last_signal_generated_at = "2026-01-01T00:00:00Z"
        sh.last_signal_sent_at = "2026-01-01T00:01:00Z"
        sh.last_signal_send_error = None
        sh.last_signal_id_prefix = "test_"

        service._prev_sh_error_count = 0
        service.error_count = 5

        service._sync_signal_handler_counters()

        assert service.signal_count == 10
        assert service.signals_sent == 8
        assert service.signals_send_failures == 2
        assert service.error_count == 8  # 5 + 3
        assert service.last_signal_generated_at == "2026-01-01T00:00:00Z"
        assert service.last_signal_id_prefix == "test_"

    def test_no_error_delta(self, service):
        sh = service._signal_handler
        sh.signal_count = 5
        sh.signals_sent = 3
        sh.signals_send_failures = 0
        sh.error_count = 2
        sh.last_signal_generated_at = None
        sh.last_signal_sent_at = None
        sh.last_signal_send_error = None
        sh.last_signal_id_prefix = None

        service._prev_sh_error_count = 2  # No new errors
        service.error_count = 10

        service._sync_signal_handler_counters()
        assert service.error_count == 10  # Unchanged


# ===========================================================================
# 25. _persist_cycle_diagnostics (lines 2390-2428)
# ===========================================================================

class TestPersistCycleDiagnostics:
    def test_noop_when_sqlite_disabled(self, service):
        service._sqlite_enabled = False
        # Should not raise
        service._persist_cycle_diagnostics(quiet_reason=None, diagnostics_raw=None)

    def test_blocking_write(self, service):
        service._sqlite_enabled = True
        mock_db = MagicMock()
        service._trade_db = mock_db
        service._async_writes_enabled = False
        service._persist_cycle_diagnostics(quiet_reason="no_signal", diagnostics_raw={"key": "val"})
        mock_db.add_cycle_diagnostics.assert_called_once()

    def test_exception_does_not_raise(self, service):
        service._sqlite_enabled = True
        mock_db = MagicMock()
        mock_db.add_cycle_diagnostics.side_effect = RuntimeError("DB locked")
        service._trade_db = mock_db
        service._async_writes_enabled = False
        # Should not raise
        service._persist_cycle_diagnostics(quiet_reason="err", diagnostics_raw=None)


# ===========================================================================
# 26. _os_signal_handler (lines 3277-3285)
# ===========================================================================

class TestOSSignalHandler:
    def test_sigterm_sets_shutdown(self, service):
        service.shutdown_requested = False
        service._os_signal_handler(signal_module.SIGTERM, None)
        assert service.shutdown_requested is True

    def test_sigint_sets_shutdown(self, service):
        service.shutdown_requested = False
        service._os_signal_handler(signal_module.SIGINT, None)
        assert service.shutdown_requested is True


# ===========================================================================
# 27. _heartbeat (lines 2986-3015)
# ===========================================================================

class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_sends_heartbeat_when_due(self, service):
        service.last_heartbeat = None  # Never sent
        service.notification_queue.enqueue_heartbeat = AsyncMock(return_value=True)
        service.data_fetcher.fetch_latest_data = AsyncMock(return_value={
            "latest_bar": {"close": 17500.0}
        })
        await service._check_heartbeat()
        service.notification_queue.enqueue_heartbeat.assert_awaited_once()
        assert service.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_skips_heartbeat_within_interval(self, service):
        service.last_heartbeat = datetime.now(timezone.utc)
        service.notification_queue.enqueue_heartbeat = AsyncMock(return_value=True)
        await service._check_heartbeat()
        service.notification_queue.enqueue_heartbeat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_heartbeat_includes_price(self, service):
        service.last_heartbeat = None
        service.notification_queue.enqueue_heartbeat = AsyncMock(return_value=True)
        service.data_fetcher.fetch_latest_data = AsyncMock(return_value={
            "latest_bar": {"close": 17500.0, "timestamp": datetime.now(timezone.utc).isoformat()}
        })
        await service._check_heartbeat()
        call_args = service.notification_queue.enqueue_heartbeat.call_args
        status = call_args[0][0]
        assert status.get("latest_price") == 17500.0


# ===========================================================================
# 29. _check_data_quality - buffer and recovery paths (lines 3100-3162)
# ===========================================================================

class TestCheckDataQualityBufferAndRecovery:
    @pytest.mark.asyncio
    async def test_buffer_issue_sends_alert(self, service):
        now = datetime.now(timezone.utc)
        # Fresh data but small buffer
        df = pd.DataFrame({
            "open": [17500.0] * 3,
            "high": [17510.0] * 3,
            "low": [17490.0] * 3,
            "close": [17505.0] * 3,
            "volume": [1000] * 3,
        }, index=pd.date_range(now - timedelta(minutes=3), periods=3, freq="1min", tz=timezone.utc))
        market_data = {
            "df": df,
            "latest_bar": {"timestamp": now, "close": 17505.0},
        }
        service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)
        service.last_data_quality_alert = None
        service._last_buffer_severity = None
        service._was_buffer_inadequate = False

        await service._check_data_quality(market_data)

        service.notification_queue.enqueue_data_quality_alert.assert_awaited()
        call_args = service.notification_queue.enqueue_data_quality_alert.call_args
        assert call_args[0][0] == "buffer_issue"

    @pytest.mark.asyncio
    async def test_data_gap_recovery(self, service):
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            "open": [17500.0] * 50,
            "high": [17510.0] * 50,
            "low": [17490.0] * 50,
            "close": [17505.0] * 50,
            "volume": [1000] * 50,
        }, index=pd.date_range(now - timedelta(minutes=50), periods=50, freq="1min", tz=timezone.utc))
        market_data = {
            "df": df,
            "latest_bar": {"timestamp": now, "close": 17505.0},
        }
        service._was_data_gap = True
        service.last_data_quality_alert = now - timedelta(minutes=5)
        service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)

        await service._check_data_quality(market_data)

        service.notification_queue.enqueue_data_quality_alert.assert_awaited()
        call_args = service.notification_queue.enqueue_data_quality_alert.call_args
        assert call_args[0][0] == "recovery"


# ===========================================================================
# 30. _handle_connection_failure (lines 3165-3185)
# ===========================================================================

class TestHandleConnectionFailureDetailed:
    @pytest.mark.asyncio
    async def test_includes_suggestion(self, service):
        service.connection_failures = 5
        service.last_connection_failure_alert = None
        service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)
        await service._handle_connection_failure()
        call_args = service.notification_queue.enqueue_data_quality_alert.call_args
        details = call_args[0][2]
        assert "suggestion" in details


# ===========================================================================
# 31. get_trading_day_date (lines 146-159)
# ===========================================================================

class TestGetTradingDayDate:
    def test_returns_date(self):
        from pearlalgo.market_agent.service import get_trading_day_date
        result = get_trading_day_date()
        assert isinstance(result, date)


# ===========================================================================
# 35. _monitor_open_position - no adapter path (line 848)
# ===========================================================================

class TestMonitorOpenPosition:
    @pytest.mark.asyncio
    async def test_returns_early_no_adapter(self, service):
        service.execution_adapter = None
        # Should return immediately without error
        await service._monitor_open_position({})


# ===========================================================================
# 36. Config warnings (lines 278-288)
# ===========================================================================

class TestConfigWarnings:
    def test_config_warnings_populated(self, mock_data_provider, tmp_path):
        cfg = MINIMAL_SERVICE_CONFIG.copy()
        cfg["signals"] = {"skip_overnight": True, "avoid_lunch_lull": True}
        with patch(
            "pearlalgo.market_agent.service.load_service_config",
            return_value=cfg,
        ):
            from pearlalgo.market_agent.service import MarketAgentService
            svc = MarketAgentService(data_provider=mock_data_provider, state_dir=tmp_path)
        assert len(svc._config_warnings) == 2
        assert any("skip_overnight" in w["key"] for w in svc._config_warnings)

    def test_no_config_warnings_by_default(self, service):
        assert service._config_warnings == []


# ===========================================================================
# 37. Trading circuit breaker init (lines 293-306)
# ===========================================================================

class TestTradingCircuitBreakerInit:
    def test_disabled_by_config(self, service):
        assert service.trading_circuit_breaker is None

    def test_enabled(self, mock_data_provider, tmp_path):
        cfg = MINIMAL_SERVICE_CONFIG.copy()
        cfg["trading_circuit_breaker"] = {
            "enabled": True,
            "max_consecutive_losses": 3,
            "max_session_drawdown": 200,
        }
        with patch(
            "pearlalgo.market_agent.service.load_service_config",
            return_value=cfg,
        ):
            from pearlalgo.market_agent.service import MarketAgentService
            svc = MarketAgentService(data_provider=mock_data_provider, state_dir=tmp_path)
        assert svc.trading_circuit_breaker is not None

"""
Tests for Telegram State Query Utilities.

Tests the TelegramStateQueriesMixin class which provides state reading and
metrics computation for the Telegram bot interface.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
from datetime import datetime, timezone, timedelta
import tempfile
import os


@pytest.fixture
def temp_state_dir():
    """Create a temporary state directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        exports_dir = state_dir / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        yield state_dir


@pytest.fixture
def state_queries_mixin(temp_state_dir):
    """Create a TelegramStateQueriesMixin instance for testing."""
    from pearlalgo.market_agent.telegram_state_queries import TelegramStateQueriesMixin

    class TestHandler(TelegramStateQueriesMixin):
        """Test handler class using the mixin."""

        def __init__(self, state_dir):
            self.state_dir = state_dir
            self.exports_dir = state_dir / "exports"
            self.active_market = "NQ"
            self.service_controller = None

    return TestHandler(temp_state_dir)


def write_state_file(state_dir: Path, state: dict) -> Path:
    """Helper to write a state.json file."""
    state_file = state_dir / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state_file


def write_signals_file(state_dir: Path, signals: list) -> Path:
    """Helper to write a signals.jsonl file."""
    signals_file = state_dir / "signals.jsonl"
    with open(signals_file, 'w', encoding='utf-8') as f:
        for sig in signals:
            f.write(json.dumps(sig) + "\n")
    return signals_file


class TestReadState:
    """Tests for _read_state method."""

    def test_reads_valid_state(self, state_queries_mixin, temp_state_dir):
        """Should read valid state file."""
        state = {"agent_running": True, "daily_pnl": 150.00}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._read_state()

        assert result is not None
        assert result["agent_running"] is True
        assert result["daily_pnl"] == 150.00

    def test_returns_none_for_missing_file(self, state_queries_mixin):
        """Should return None when state file doesn't exist."""
        result = state_queries_mixin._read_state()

        assert result is None

    def test_handles_invalid_json(self, state_queries_mixin, temp_state_dir):
        """Should return None for invalid JSON."""
        state_file = temp_state_dir / "state.json"
        state_file.write_text("not valid json", encoding="utf-8")

        result = state_queries_mixin._read_state()

        assert result is None


class TestReadRecentSignals:
    """Tests for _read_recent_signals method."""

    def test_reads_signals(self, state_queries_mixin, temp_state_dir):
        """Should read signals from file."""
        signals = [
            {"signal_id": "sig1", "signal": {"direction": "long"}},
            {"signal_id": "sig2", "signal": {"direction": "short"}},
        ]
        write_signals_file(temp_state_dir, signals)

        result = state_queries_mixin._read_recent_signals()

        assert len(result) == 2
        assert result[0]["signal_id"] == "sig1"

    def test_respects_limit(self, state_queries_mixin, temp_state_dir):
        """Should respect the limit parameter."""
        signals = [{"signal_id": f"sig{i}"} for i in range(20)]
        write_signals_file(temp_state_dir, signals)

        result = state_queries_mixin._read_recent_signals(limit=5)

        assert len(result) == 5

    def test_returns_empty_for_missing_file(self, state_queries_mixin):
        """Should return empty list when file doesn't exist."""
        result = state_queries_mixin._read_recent_signals()

        assert result == []

    def test_normalizes_nested_signal_fields(self, state_queries_mixin, temp_state_dir):
        """Should normalize fields from nested signal object."""
        signals = [
            {
                "signal_id": "sig1",
                "signal": {
                    "direction": "long",
                    "type": "breakout",
                    "entry_price": 15000.00,
                },
            },
        ]
        write_signals_file(temp_state_dir, signals)

        result = state_queries_mixin._read_recent_signals()

        assert result[0]["direction"] == "long"
        assert result[0]["type"] == "breakout"
        assert result[0]["entry_price"] == 15000.00

    def test_handles_invalid_lines(self, state_queries_mixin, temp_state_dir):
        """Should skip invalid JSON lines."""
        signals_file = temp_state_dir / "signals.jsonl"
        with open(signals_file, 'w', encoding='utf-8') as f:
            f.write('{"signal_id": "valid"}\n')
            f.write('not valid json\n')
            f.write('{"signal_id": "also_valid"}\n')

        result = state_queries_mixin._read_recent_signals()

        assert len(result) == 2


class TestReadLatestMetrics:
    """Tests for _read_latest_metrics method."""

    def test_reads_latest_metrics(self, state_queries_mixin, temp_state_dir):
        """Should read the most recent metrics file."""
        exports_dir = temp_state_dir / "exports"
        exports_dir.mkdir(exist_ok=True)

        metrics = {"total_pnl": 500.00, "win_rate": 0.65}
        metrics_file = exports_dir / "performance_20240101_metrics.json"
        metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

        result = state_queries_mixin._read_latest_metrics()

        assert result is not None
        assert result["total_pnl"] == 500.00

    def test_returns_none_for_missing_exports(self, state_queries_mixin):
        """Should return None when exports directory doesn't exist."""
        state_queries_mixin.exports_dir = Path("/nonexistent")

        result = state_queries_mixin._read_latest_metrics()

        assert result is None

    def test_returns_none_for_no_metrics_files(self, state_queries_mixin, temp_state_dir):
        """Should return None when no metrics files exist."""
        result = state_queries_mixin._read_latest_metrics()

        assert result is None


class TestReadStrategySelection:
    """Tests for _read_strategy_selection method."""

    def test_reads_strategy_selection(self, state_queries_mixin, temp_state_dir):
        """Should read strategy selection file."""
        exports_dir = temp_state_dir / "exports"

        selection = {"selected_strategy": "momentum", "confidence": 0.8}
        selection_file = exports_dir / "strategy_selection_20240101.json"
        selection_file.write_text(json.dumps(selection), encoding="utf-8")

        result = state_queries_mixin._read_strategy_selection()

        assert result is not None
        assert result["selected_strategy"] == "momentum"

    def test_reads_latest_file(self, state_queries_mixin, temp_state_dir):
        """Should read the strategy_selection_latest.json file."""
        exports_dir = temp_state_dir / "exports"

        selection = {"selected_strategy": "latest"}
        selection_file = exports_dir / "strategy_selection_latest.json"
        selection_file.write_text(json.dumps(selection), encoding="utf-8")

        result = state_queries_mixin._read_strategy_selection()

        assert result is not None
        assert result["selected_strategy"] == "latest"


class TestFindSignalByPrefix:
    """Tests for _find_signal_by_prefix method."""

    def test_finds_matching_signal(self, state_queries_mixin, temp_state_dir):
        """Should find signal by ID prefix."""
        signals = [
            {"signal_id": "abc123def", "direction": "long"},
            {"signal_id": "xyz789ghi", "direction": "short"},
        ]
        write_signals_file(temp_state_dir, signals)

        result = state_queries_mixin._find_signal_by_prefix("abc")

        assert result is not None
        assert result["signal_id"] == "abc123def"

    def test_returns_none_for_no_match(self, state_queries_mixin, temp_state_dir):
        """Should return None when no match found."""
        signals = [{"signal_id": "abc123"}]
        write_signals_file(temp_state_dir, signals)

        result = state_queries_mixin._find_signal_by_prefix("xyz")

        assert result is None

    def test_finds_most_recent_match(self, state_queries_mixin, temp_state_dir):
        """Should find the most recent matching signal."""
        signals = [
            {"signal_id": "abc111", "order": 1},
            {"signal_id": "abc222", "order": 2},
        ]
        write_signals_file(temp_state_dir, signals)

        result = state_queries_mixin._find_signal_by_prefix("abc")

        # Should return most recent (last in file)
        assert result["signal_id"] == "abc222"


class TestExtractLatestPrice:
    """Tests for _extract_latest_price method."""

    def test_extracts_direct_price(self, state_queries_mixin):
        """Should extract price from latest_price field."""
        state = {"latest_price": 15000.50}

        result = state_queries_mixin._extract_latest_price(state)

        assert result == 15000.50

    def test_extracts_from_latest_bar(self, state_queries_mixin):
        """Should extract price from latest_bar.close."""
        state = {"latest_bar": {"close": 15001.25}}

        result = state_queries_mixin._extract_latest_price(state)

        assert result == 15001.25

    def test_prefers_direct_price(self, state_queries_mixin):
        """Should prefer latest_price over latest_bar."""
        state = {
            "latest_price": 15000.00,
            "latest_bar": {"close": 15001.00},
        }

        result = state_queries_mixin._extract_latest_price(state)

        assert result == 15000.00

    def test_returns_none_for_missing(self, state_queries_mixin):
        """Should return None when no price available."""
        state = {}

        result = state_queries_mixin._extract_latest_price(state)

        assert result is None


class TestExtractDataAgeMinutes:
    """Tests for _extract_data_age_minutes method."""

    def test_calculates_data_age(self, state_queries_mixin):
        """Should calculate age from latest_bar timestamp."""
        five_mins_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        state = {"latest_bar": {"timestamp": five_mins_ago}}

        result = state_queries_mixin._extract_data_age_minutes(state)

        assert result is not None
        assert 4.9 < result < 5.5  # Allow some tolerance

    def test_returns_none_for_missing_bar(self, state_queries_mixin):
        """Should return None when no latest_bar."""
        state = {}

        result = state_queries_mixin._extract_data_age_minutes(state)

        assert result is None

    def test_returns_none_for_missing_timestamp(self, state_queries_mixin):
        """Should return None when no timestamp in bar."""
        state = {"latest_bar": {"close": 15000.00}}

        result = state_queries_mixin._extract_data_age_minutes(state)

        assert result is None


class TestComputeStateStaleThreshold:
    """Tests for _compute_state_stale_threshold method."""

    def test_returns_configured_threshold(self, state_queries_mixin):
        """Should return threshold from state."""
        state = {"data_stale_threshold_minutes": 15.0}

        result = state_queries_mixin._compute_state_stale_threshold(state)

        assert result == 15.0

    def test_returns_default_for_missing(self, state_queries_mixin):
        """Should return 10.0 as default."""
        state = {}

        result = state_queries_mixin._compute_state_stale_threshold(state)

        assert result == 10.0

    def test_handles_invalid_value(self, state_queries_mixin):
        """Should return default for invalid value."""
        state = {"data_stale_threshold_minutes": "not a number"}

        result = state_queries_mixin._compute_state_stale_threshold(state)

        assert result == 10.0


class TestIsAgentProcessRunning:
    """Tests for _is_agent_process_running method."""

    def test_returns_true_when_running(self, state_queries_mixin):
        """Should return True when agent is running."""
        mock_sc = MagicMock()
        mock_sc.get_agent_status.return_value = {"running": True}
        state_queries_mixin.service_controller = mock_sc

        result = state_queries_mixin._is_agent_process_running()

        assert result is True

    def test_returns_false_when_stopped(self, state_queries_mixin):
        """Should return False when agent is stopped."""
        mock_sc = MagicMock()
        mock_sc.get_agent_status.return_value = {"running": False}
        state_queries_mixin.service_controller = mock_sc

        result = state_queries_mixin._is_agent_process_running()

        assert result is False

    def test_returns_false_without_controller(self, state_queries_mixin):
        """Should return False when no service controller."""
        state_queries_mixin.service_controller = None

        result = state_queries_mixin._is_agent_process_running()

        assert result is False


class TestGetCurrentTimeStr:
    """Tests for _get_current_time_str method."""

    def test_returns_time_string(self, state_queries_mixin):
        """Should return a time string."""
        result = state_queries_mixin._get_current_time_str()

        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_timezone(self, state_queries_mixin):
        """Should include timezone indicator."""
        result = state_queries_mixin._get_current_time_str()

        assert "ET" in result or "UTC" in result


class TestCountOpenPositions:
    """Tests for _count_open_positions method."""

    def test_counts_execution_positions(self, state_queries_mixin, temp_state_dir):
        """Should count execution positions."""
        state = {"execution": {"positions": 3}}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._count_open_positions()

        assert result == 3

    def test_counts_active_trades(self, state_queries_mixin, temp_state_dir):
        """Should count active trades."""
        state = {"active_trades_count": 2}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._count_open_positions()

        assert result == 2

    def test_sums_both_types(self, state_queries_mixin, temp_state_dir):
        """Should sum execution positions and active trades."""
        state = {
            "execution": {"positions": 2},
            "active_trades_count": 3,
        }
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._count_open_positions()

        assert result == 5

    def test_returns_zero_for_empty_state(self, state_queries_mixin):
        """Should return 0 when no positions."""
        result = state_queries_mixin._count_open_positions()

        assert result == 0


class TestGetDailyPerformance:
    """Tests for _get_daily_performance method."""

    def test_returns_performance_metrics(self, state_queries_mixin, temp_state_dir):
        """Should return daily performance metrics."""
        state = {
            "daily_pnl": 250.00,
            "daily_trades": 10,
            "daily_wins": 7,
            "daily_losses": 3,
        }
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._get_daily_performance()

        assert result["daily_pnl"] == 250.00
        assert result["daily_trades"] == 10
        assert result["daily_wins"] == 7
        assert result["daily_losses"] == 3
        assert result["win_rate"] == 70.0

    def test_returns_defaults_for_missing_state(self, state_queries_mixin):
        """Should return default values when no state."""
        result = state_queries_mixin._get_daily_performance()

        assert result["daily_pnl"] == 0.0
        assert result["daily_trades"] == 0
        assert result["win_rate"] == 0.0

    def test_handles_zero_trades(self, state_queries_mixin, temp_state_dir):
        """Should handle zero trades for win rate."""
        state = {"daily_trades": 0}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._get_daily_performance()

        assert result["win_rate"] == 0.0


class TestGetGatewayStatus:
    """Tests for _get_gateway_status method."""

    def test_returns_healthy_status(self, state_queries_mixin):
        """Should return healthy status."""
        mock_sc = MagicMock()
        mock_sc.get_gateway_status.return_value = {
            "process_running": True,
            "port_listening": True,
        }
        state_queries_mixin.service_controller = mock_sc

        result = state_queries_mixin._get_gateway_status()

        assert result["process_running"] is True
        assert result["port_listening"] is True
        assert result["is_healthy"] is True

    def test_returns_unhealthy_status(self, state_queries_mixin):
        """Should return unhealthy when process not running."""
        mock_sc = MagicMock()
        mock_sc.get_gateway_status.return_value = {
            "process_running": False,
            "port_listening": False,
        }
        state_queries_mixin.service_controller = mock_sc

        result = state_queries_mixin._get_gateway_status()

        assert result["is_healthy"] is False

    def test_returns_defaults_without_controller(self, state_queries_mixin):
        """Should return defaults when no service controller."""
        result = state_queries_mixin._get_gateway_status()

        assert result["process_running"] is False
        assert result["port_listening"] is False
        assert result["is_healthy"] is False


class TestGetAgentHealth:
    """Tests for _get_agent_health method."""

    def test_returns_running_status(self, state_queries_mixin, temp_state_dir):
        """Should return running status."""
        mock_sc = MagicMock()
        mock_sc.get_agent_status.return_value = {"running": True}
        state_queries_mixin.service_controller = mock_sc

        state = {"paused": False}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._get_agent_health()

        assert result["running"] is True
        assert result["paused"] is False

    def test_returns_paused_status(self, state_queries_mixin, temp_state_dir):
        """Should return paused status."""
        mock_sc = MagicMock()
        mock_sc.get_agent_status.return_value = {"running": True}
        state_queries_mixin.service_controller = mock_sc

        state = {"paused": True}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._get_agent_health()

        assert result["paused"] is True

    def test_calculates_cycle_age(self, state_queries_mixin, temp_state_dir):
        """Should calculate cycle age."""
        mock_sc = MagicMock()
        mock_sc.get_agent_status.return_value = {"running": True}
        state_queries_mixin.service_controller = mock_sc

        ten_secs_ago = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        state = {"last_successful_cycle": ten_secs_ago}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._get_agent_health()

        assert result["cycle_age_seconds"] is not None
        assert 9 < result["cycle_age_seconds"] < 15


class TestGetConnectionStatus:
    """Tests for _get_connection_status method."""

    def test_returns_connected_status(self, state_queries_mixin, temp_state_dir):
        """Should return connected status."""
        state = {"connection_status": "connected"}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._get_connection_status()

        assert result["status"] == "connected"
        assert result["is_connected"] is True

    def test_returns_disconnected_status(self, state_queries_mixin, temp_state_dir):
        """Should return disconnected status."""
        state = {"connection_status": "disconnected"}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._get_connection_status()

        assert result["status"] == "disconnected"
        assert result["is_connected"] is False

    def test_falls_back_to_data_fresh(self, state_queries_mixin, temp_state_dir):
        """Should fall back to data_fresh when no connection_status."""
        state = {"data_fresh": True}
        write_state_file(temp_state_dir, state)

        result = state_queries_mixin._get_connection_status()

        assert result["is_connected"] is True


class TestLoadPerformanceTrades:
    """Tests for _load_performance_trades method."""

    def test_loads_trades(self, state_queries_mixin, temp_state_dir):
        """Should load trades from performance.json."""
        trades = [
            {"signal_id": "sig1", "pnl": 100},
            {"signal_id": "sig2", "pnl": -50},
        ]
        perf_file = temp_state_dir / "performance.json"
        perf_file.write_text(json.dumps(trades), encoding="utf-8")

        result = state_queries_mixin._load_performance_trades()

        assert len(result) == 2

    def test_deduplicates_by_signal_id(self, state_queries_mixin, temp_state_dir):
        """Should deduplicate trades by signal_id."""
        trades = [
            {"signal_id": "sig1", "pnl": 100, "version": 1},
            {"signal_id": "sig1", "pnl": 100, "version": 2},  # Duplicate
        ]
        perf_file = temp_state_dir / "performance.json"
        perf_file.write_text(json.dumps(trades), encoding="utf-8")

        result = state_queries_mixin._load_performance_trades()

        assert len(result) == 1
        assert result[0]["version"] == 2  # Should keep most recent

    def test_returns_empty_for_missing_file(self, state_queries_mixin):
        """Should return empty list when file doesn't exist."""
        result = state_queries_mixin._load_performance_trades()

        assert result == []


class TestGetTradingDayStart:
    """Tests for _get_trading_day_start method."""

    def test_returns_datetime(self, state_queries_mixin):
        """Should return a datetime object."""
        result = state_queries_mixin._get_trading_day_start()

        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_returns_6pm_et(self, state_queries_mixin):
        """Should return 6pm ET start time."""
        result = state_queries_mixin._get_trading_day_start()

        # Convert to ET for verification
        from zoneinfo import ZoneInfo
        et_tz = ZoneInfo("America/New_York")
        result_et = result.astimezone(et_tz)

        assert result_et.hour == 18
        assert result_et.minute == 0


class TestGetTodayTrades:
    """Tests for _get_today_trades method."""

    def test_filters_to_today(self, state_queries_mixin, temp_state_dir):
        """Should filter trades to today's session."""
        now = datetime.now(timezone.utc)
        today_exit = now.isoformat()
        yesterday_exit = (now - timedelta(days=2)).isoformat()

        trades = [
            {"signal_id": "today", "exit_time": today_exit, "pnl": 100},
            {"signal_id": "yesterday", "exit_time": yesterday_exit, "pnl": 50},
        ]
        perf_file = temp_state_dir / "performance.json"
        perf_file.write_text(json.dumps(trades), encoding="utf-8")

        result = state_queries_mixin._get_today_trades()

        assert len(result) == 1
        assert result[0]["signal_id"] == "today"

    def test_returns_empty_for_no_trades(self, state_queries_mixin):
        """Should return empty list when no trades."""
        result = state_queries_mixin._get_today_trades()

        assert result == []

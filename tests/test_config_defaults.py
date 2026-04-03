"""Tests for config/defaults.py — ensure safety-critical defaults are correct."""

from pearlalgo.config.defaults import (
    # Execution safety
    EXECUTION_ARMED,
    EXECUTION_ENABLED,
    EXECUTION_MODE,
    MAX_POSITIONS,
    # TCB safety
    TCB_ENABLED,
    TCB_MODE,
    TCB_MAX_CONSECUTIVE_LOSSES,
    TCB_MAX_SESSION_DRAWDOWN,
    TCB_MAX_DAILY_DRAWDOWN,
    TCB_MAX_CONCURRENT_POSITIONS,
    # Storage
    STORAGE_SQLITE_ENABLED,
    STORAGE_DUAL_WRITE_FILES,
    # Data
    DATA_BUFFER_SIZE,
    HISTORICAL_HOURS,
    # IBKR
    IBKR_HOST,
    IBKR_PORT,
    # Server
    API_SERVER_PORT,
    CHART_PORT,
)


class TestExecutionSafetyDefaults:
    """Execution defaults must be conservative — never armed by default."""

    def test_execution_not_armed_by_default(self):
        assert EXECUTION_ARMED is False

    def test_execution_not_enabled_by_default(self):
        assert EXECUTION_ENABLED is False

    def test_execution_mode_is_dry_run(self):
        assert EXECUTION_MODE == "dry_run"

    def test_max_positions_is_reasonable(self):
        assert MAX_POSITIONS >= 1
        assert MAX_POSITIONS <= 10


class TestCircuitBreakerDefaults:
    """TCB defaults must enforce safety limits."""

    def test_tcb_enabled_by_default(self):
        assert TCB_ENABLED is True

    def test_tcb_mode_is_enforce(self):
        assert TCB_MODE == "enforce"

    def test_consecutive_loss_limit_is_reasonable(self):
        assert 1 <= TCB_MAX_CONSECUTIVE_LOSSES <= 10

    def test_session_drawdown_limit_is_positive(self):
        assert TCB_MAX_SESSION_DRAWDOWN > 0

    def test_daily_drawdown_limit_is_positive(self):
        assert TCB_MAX_DAILY_DRAWDOWN > 0

    def test_daily_drawdown_gte_session_drawdown(self):
        assert TCB_MAX_DAILY_DRAWDOWN >= TCB_MAX_SESSION_DRAWDOWN

    def test_max_concurrent_positions_is_reasonable(self):
        assert 1 <= TCB_MAX_CONCURRENT_POSITIONS <= 10


class TestStorageDefaults:
    def test_sqlite_enabled_by_default(self):
        assert STORAGE_SQLITE_ENABLED is True

    def test_dual_write_disabled(self):
        assert STORAGE_DUAL_WRITE_FILES is False


class TestNetworkDefaults:
    def test_ibkr_host_is_localhost(self):
        assert IBKR_HOST == "127.0.0.1"

    def test_ibkr_port_is_standard(self):
        assert IBKR_PORT == 4001

    def test_api_server_port_is_reasonable(self):
        assert 1024 < API_SERVER_PORT < 65535

    def test_chart_port_is_reasonable(self):
        assert 1024 < CHART_PORT < 65535


class TestDataDefaults:
    def test_buffer_size_is_positive(self):
        assert DATA_BUFFER_SIZE > 0

    def test_historical_hours_is_positive(self):
        assert HISTORICAL_HOURS > 0

"""
Tests for pearlalgo.config.defaults module.

Verifies that all default constants:
- Are importable and of the expected types
- Have sensible values (positive intervals, risk between 0-1, etc.)
- Stay consistent with config_schema.py Pydantic model defaults
"""

from __future__ import annotations

import pytest

from pearlalgo.config import defaults
from pearlalgo.config.config_schema import FullServiceConfig


class TestDefaultsModuleImport:
    """Verify the defaults module is importable and well-formed."""

    def test_module_is_importable(self):
        assert hasattr(defaults, "IBKR_HOST")
        assert hasattr(defaults, "MAX_RISK_PER_TRADE")

    def test_no_none_constants(self):
        """Public constants (UPPER_CASE) should not be None unless explicitly optional."""
        optional = {"ML_FILTER_MODEL_PATH"}
        for name in dir(defaults):
            if name.startswith("_") or not name.isupper():
                continue
            val = getattr(defaults, name)
            if name not in optional:
                assert val is not None, f"defaults.{name} should not be None"


class TestDefaultTypes:
    """All defaults should have the declared type."""

    def test_string_defaults(self):
        for name in ("IBKR_HOST", "EXECUTION_MODE", "CADENCE_MODE",
                      "CHART_URL", "API_SERVER_HOST", "STORAGE_DB_PATH"):
            assert isinstance(getattr(defaults, name), str), f"{name} should be str"

    def test_int_defaults(self):
        for name in ("IBKR_PORT", "IBKR_CLIENT_ID", "CHART_PORT",
                      "MAX_POSITIONS", "DEFAULT_SCAN_INTERVAL",
                      "DATA_BUFFER_SIZE", "COOLDOWN_SECONDS"):
            assert isinstance(getattr(defaults, name), int), f"{name} should be int"

    def test_float_defaults(self):
        for name in ("MAX_RISK_PER_TRADE", "MAX_DRAWDOWN", "EXPLORE_RATE",
                      "ML_FILTER_MIN_PROBABILITY", "STOP_LOSS_ATR_MULTIPLIER"):
            assert isinstance(getattr(defaults, name), float), f"{name} should be float"

    def test_bool_defaults(self):
        for name in ("EXECUTION_ENABLED", "EXECUTION_ARMED",
                      "LEARNING_ENABLED", "CHALLENGE_ENABLED"):
            assert isinstance(getattr(defaults, name), bool), f"{name} should be bool"

    def test_list_defaults(self):
        assert isinstance(defaults.DEFAULT_SYMBOL_WHITELIST, list)
        assert isinstance(defaults.TCB_ALLOWED_SESSIONS, list)


class TestSensibleValues:
    """Key defaults should have sensible, safe values."""

    def test_scan_interval_positive(self):
        assert defaults.DEFAULT_SCAN_INTERVAL > 0

    def test_risk_per_trade_range(self):
        assert 0 < defaults.MAX_RISK_PER_TRADE <= 1.0

    def test_max_drawdown_range(self):
        assert 0 < defaults.MAX_DRAWDOWN <= 1.0

    def test_execution_defaults_safe(self):
        """Execution should be off by default (safety)."""
        assert defaults.EXECUTION_ENABLED is False
        assert defaults.EXECUTION_ARMED is False
        assert defaults.EXECUTION_MODE == "dry_run"

    def test_challenge_disabled_by_default(self):
        assert defaults.CHALLENGE_ENABLED is False

    def test_intervals_positive(self):
        assert defaults.STATUS_UPDATE_INTERVAL > 0
        assert defaults.HEARTBEAT_INTERVAL > 0
        assert defaults.STATE_SAVE_INTERVAL > 0

    def test_data_buffers_positive(self):
        assert defaults.DATA_BUFFER_SIZE >= 10
        assert defaults.DATA_BUFFER_SIZE_5M >= 10

    def test_ml_filter_disabled_by_default(self):
        assert defaults.ML_FILTER_ENABLED is False

    def test_confidence_thresholds_ordered(self):
        assert defaults.CONFIDENCE_LOW_SIZE_MULTIPLIER < defaults.CONFIDENCE_MEDIUM_SIZE_MULTIPLIER
        assert defaults.CONFIDENCE_MEDIUM_SIZE_MULTIPLIER < defaults.CONFIDENCE_HIGH_SIZE_MULTIPLIER


class TestSchemaConsistency:
    """Pydantic schema defaults must match defaults.py constants."""

    @pytest.fixture()
    def schema(self) -> FullServiceConfig:
        return FullServiceConfig()

    def test_risk_defaults_match(self, schema: FullServiceConfig):
        assert schema.risk.max_risk_per_trade == defaults.MAX_RISK_PER_TRADE
        assert schema.risk.max_drawdown == defaults.MAX_DRAWDOWN
        assert schema.risk.stop_loss_atr_multiplier == defaults.STOP_LOSS_ATR_MULTIPLIER
        assert schema.risk.take_profit_risk_reward == defaults.TAKE_PROFIT_RISK_REWARD

    def test_service_defaults_match(self, schema: FullServiceConfig):
        assert schema.service.status_update_interval == defaults.STATUS_UPDATE_INTERVAL
        assert schema.service.heartbeat_interval == defaults.HEARTBEAT_INTERVAL
        assert schema.service.state_save_interval == defaults.STATE_SAVE_INTERVAL

    def test_data_defaults_match(self, schema: FullServiceConfig):
        assert schema.data.buffer_size == defaults.DATA_BUFFER_SIZE
        assert schema.data.historical_hours == defaults.HISTORICAL_HOURS

    def test_circuit_breaker_defaults_match(self, schema: FullServiceConfig):
        assert schema.circuit_breaker.max_consecutive_errors == defaults.MAX_CONSECUTIVE_ERRORS
        assert schema.circuit_breaker.max_connection_failures == defaults.MAX_CONNECTION_FAILURES

    def test_challenge_defaults_match(self, schema: FullServiceConfig):
        assert schema.challenge.start_balance == defaults.CHALLENGE_START_BALANCE
        assert schema.challenge.profit_target == defaults.CHALLENGE_PROFIT_TARGET
        assert schema.challenge.max_drawdown == defaults.CHALLENGE_MAX_DRAWDOWN

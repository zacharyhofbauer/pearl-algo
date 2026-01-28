"""
Tests for config/config_schema.py

Validates the Pydantic configuration schema including:
- Default values
- Field validation (ranges, types)
- Cross-field validation
- Config file validation
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pearlalgo.config.config_schema import (
    CircuitBreakerConfig,
    DataConfig,
    ExecutionConfig,
    FullServiceConfig,
    LearningConfig,
    RiskConfig,
    ServiceConfig,
    SessionConfig,
    SignalsConfig,
    StrategyConfig,
    TelegramConfig,
    validate_config,
    validate_config_file,
)


class TestDefaultValues:
    """Tests for default configuration values."""

    def test_full_config_defaults(self) -> None:
        """Full config should have sensible defaults."""
        config = FullServiceConfig()

        assert config.symbol == "MNQ"
        assert config.timeframe == "1m"
        assert config.scan_interval == 30

    def test_telegram_config_defaults(self) -> None:
        """Telegram config should default to enabled with no credentials."""
        config = TelegramConfig()

        assert config.enabled is True
        assert config.bot_token is None
        assert config.chat_id is None

    def test_session_config_defaults(self) -> None:
        """Session config should default to prop firm hours."""
        config = SessionConfig()

        assert config.start_time == "18:00"
        assert config.end_time == "16:10"

    def test_risk_config_defaults(self) -> None:
        """Risk config should have conservative defaults."""
        config = RiskConfig()

        assert config.max_risk_per_trade == 0.01
        assert config.max_drawdown == 0.1
        assert config.min_position_size == 5
        assert config.max_position_size == 25

    def test_execution_config_defaults_to_disabled(self) -> None:
        """Execution config should default to disabled for safety."""
        config = ExecutionConfig()

        assert config.enabled is False
        assert config.armed is False
        assert config.mode == "dry_run"

    def test_learning_config_defaults_to_shadow(self) -> None:
        """Learning config should default to shadow mode for safety."""
        config = LearningConfig()

        assert config.enabled is True
        assert config.mode == "shadow"


class TestFieldValidation:
    """Tests for field-level validation."""

    def test_risk_per_trade_range(self) -> None:
        """max_risk_per_trade must be between 0.001 and 0.1."""
        # Valid
        config = RiskConfig(max_risk_per_trade=0.05)
        assert config.max_risk_per_trade == 0.05

        # Too low
        with pytest.raises(ValidationError):
            RiskConfig(max_risk_per_trade=0.0001)

        # Too high
        with pytest.raises(ValidationError):
            RiskConfig(max_risk_per_trade=0.5)

    def test_service_intervals_minimum(self) -> None:
        """Service intervals should have minimum values."""
        # status_update_interval minimum is 60
        with pytest.raises(ValidationError):
            ServiceConfig(status_update_interval=30)

        # heartbeat_interval minimum is 60
        with pytest.raises(ValidationError):
            ServiceConfig(heartbeat_interval=30)

    def test_circuit_breaker_minimums(self) -> None:
        """Circuit breaker thresholds should have minimum of 1."""
        with pytest.raises(ValidationError):
            CircuitBreakerConfig(max_consecutive_errors=0)

    def test_data_buffer_size_minimum(self) -> None:
        """Buffer size should have minimum of 10."""
        with pytest.raises(ValidationError):
            DataConfig(buffer_size=5)

    def test_signals_confidence_range(self) -> None:
        """Confidence must be between 0 and 1."""
        # Valid
        config = SignalsConfig(min_confidence=0.75)
        assert config.min_confidence == 0.75

        # Too high
        with pytest.raises(ValidationError):
            SignalsConfig(min_confidence=1.5)

    def test_execution_mode_literal(self) -> None:
        """Execution mode must be one of: dry_run, paper, live."""
        # Valid modes
        for mode in ["dry_run", "paper", "live"]:
            config = ExecutionConfig(mode=mode)  # type: ignore
            assert config.mode == mode

        # Invalid mode
        with pytest.raises(ValidationError):
            ExecutionConfig(mode="invalid_mode")  # type: ignore

    def test_ibkr_port_accepts_int_and_env_var(self) -> None:
        """ibkr_port should accept int, string int, or env var placeholder."""
        # Integer
        config = ExecutionConfig(ibkr_port=4002)
        assert config.ibkr_port == 4002

        # String integer
        config = ExecutionConfig(ibkr_port="4002")
        assert config.ibkr_port == 4002

        # Env var placeholder (should be preserved)
        config = ExecutionConfig(ibkr_port="${IBKR_PORT}")
        assert config.ibkr_port == "${IBKR_PORT}"


class TestCrossFieldValidation:
    """Tests for cross-field validation."""

    def test_position_size_constraints(self) -> None:
        """min_position_size cannot exceed max_position_size."""
        with pytest.raises(ValidationError, match="cannot exceed"):
            FullServiceConfig(
                risk=RiskConfig(min_position_size=50, max_position_size=25)
            )

    def test_confidence_threshold_ordering(self) -> None:
        """high_conf_threshold must be less than max_conf_threshold."""
        with pytest.raises(ValidationError, match="must be less than"):
            FullServiceConfig(
                strategy=StrategyConfig(
                    high_conf_threshold=0.95,
                    max_conf_threshold=0.90,
                )
            )


class TestValidateConfig:
    """Tests for validate_config function."""

    def test_empty_dict_returns_defaults(self) -> None:
        """Empty dict should return config with all defaults."""
        config = validate_config({})

        assert config.symbol == "MNQ"
        assert config.execution.enabled is False

    def test_partial_dict_merges_with_defaults(self) -> None:
        """Partial dict should merge with defaults."""
        config = validate_config({
            "symbol": "MES",
            "timeframe": "5m",
        })

        assert config.symbol == "MES"
        assert config.timeframe == "5m"
        assert config.scan_interval == 30  # Default

    def test_nested_config_override(self) -> None:
        """Should handle nested config overrides."""
        config = validate_config({
            "risk": {
                "max_risk_per_trade": 0.02,
            },
            "signals": {
                "min_confidence": 0.80,
            },
        })

        assert config.risk.max_risk_per_trade == 0.02
        assert config.signals.min_confidence == 0.80
        # Other defaults preserved
        assert config.risk.max_drawdown == 0.1

    def test_extra_fields_allowed(self) -> None:
        """Extra fields should be allowed for forward compatibility."""
        # Should not raise
        config = validate_config({
            "future_feature": True,
            "new_section": {"key": "value"},
        })
        assert config.symbol == "MNQ"  # Defaults still work


class TestValidateConfigFile:
    """Tests for validate_config_file function."""

    def test_valid_yaml_file(self, tmp_path: Path) -> None:
        """Should validate a valid YAML config file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
symbol: MNQ
timeframe: 1m
scan_interval: 30
risk:
  max_risk_per_trade: 0.015
""")

        config = validate_config_file(config_file)

        assert config.symbol == "MNQ"
        assert config.risk.max_risk_per_trade == 0.015

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            validate_config_file(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        """Should raise ValidationError for invalid config values."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
risk:
  max_risk_per_trade: 0.999
""")

        with pytest.raises(ValidationError):
            validate_config_file(config_file)

    def test_empty_yaml_returns_defaults(self, tmp_path: Path) -> None:
        """Empty YAML file should return defaults."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        config = validate_config_file(config_file)
        assert config.symbol == "MNQ"

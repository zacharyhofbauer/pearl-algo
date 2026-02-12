"""
Tests for the lightweight Pydantic config schema (v2).

Covers:
  - Valid config passes validation
  - Defaults are applied for missing keys
  - Type errors fail fast with clear messages
  - Required fields (symbol) are validated
  - Extra keys are preserved (forward-compatible)
  - Invalid timeframe is rejected
"""

from __future__ import annotations

import pytest

from pearlalgo.config.schema_v2 import validate_config, AgentConfigSchema


class TestValidateConfig:
    """Tests for validate_config()."""

    def test_minimal_config_gets_defaults(self):
        """A config with only required fields should get all defaults."""
        result = validate_config({"symbol": "MNQ"})
        assert result["symbol"] == "MNQ"
        assert result["timeframe"] == "1m"
        assert result["scan_interval"] == 30
        assert result["risk"]["max_risk_per_trade"] == 0.015
        assert result["execution"]["enabled"] is False

    def test_full_config_passes(self):
        """A realistic full config should pass validation."""
        config = {
            "symbol": "MNQ",
            "timeframe": "1m",
            "scan_interval": 30,
            "account": {
                "name": "tradovate_paper",
                "display_name": "Tradovate Paper",
                "badge": "PAPER",
            },
            "risk": {
                "max_risk_per_trade": 0.015,
                "stop_loss_atr_multiplier": 4.0,
            },
            "execution": {
                "enabled": True,
                "adapter": "tradovate",
                "mode": "paper",
            },
            "signals": {
                "min_confidence": 0.55,
            },
        }
        result = validate_config(config)
        assert result["account"]["name"] == "tradovate_paper"
        assert result["execution"]["enabled"] is True
        assert result["execution"]["adapter"] == "tradovate"
        assert result["signals"]["min_confidence"] == 0.55

    def test_symbol_uppercased(self):
        """Symbol should be uppercased."""
        result = validate_config({"symbol": "mnq"})
        assert result["symbol"] == "MNQ"

    def test_empty_symbol_rejected(self):
        """Empty symbol should fail validation."""
        with pytest.raises(Exception, match="symbol"):
            validate_config({"symbol": ""})

    def test_invalid_timeframe_rejected(self):
        """Invalid timeframe should fail validation."""
        with pytest.raises(Exception, match="timeframe"):
            validate_config({"symbol": "MNQ", "timeframe": "2m"})

    def test_negative_scan_interval_rejected(self):
        """Negative scan interval should fail validation."""
        with pytest.raises(Exception, match="scan_interval"):
            validate_config({"symbol": "MNQ", "scan_interval": 0})

    def test_wrong_type_rejected(self):
        """Wrong types should fail validation."""
        with pytest.raises(Exception):
            validate_config({"symbol": "MNQ", "scan_interval": "not_a_number"})

    def test_extra_keys_preserved(self):
        """Unknown top-level keys should pass through (forward-compatible)."""
        result = validate_config({
            "symbol": "MNQ",
            "some_future_feature": {"enabled": True},
            "custom_setting": 42,
        })
        assert result["some_future_feature"] == {"enabled": True}
        assert result["custom_setting"] == 42

    def test_defaults_not_overwrite_provided_values(self):
        """Explicitly provided values should not be replaced by defaults."""
        result = validate_config({
            "symbol": "ES",
            "timeframe": "5m",
            "scan_interval": 60,
            "risk": {"max_risk_per_trade": 0.02},
        })
        assert result["symbol"] == "ES"
        assert result["timeframe"] == "5m"
        assert result["scan_interval"] == 60
        assert result["risk"]["max_risk_per_trade"] == 0.02

    def test_challenge_config_defaults(self):
        """Challenge config should default to disabled."""
        result = validate_config({"symbol": "MNQ"})
        assert result["challenge"]["enabled"] is False

    def test_challenge_config_enabled(self):
        """Challenge config can be enabled via override."""
        result = validate_config({
            "symbol": "MNQ",
            "challenge": {
                "enabled": True,
                "stage": "tv_paper_eval",
                "profit_target": 3000.0,
            },
        })
        assert result["challenge"]["enabled"] is True
        assert result["challenge"]["stage"] == "tv_paper_eval"
        assert result["challenge"]["profit_target"] == 3000.0

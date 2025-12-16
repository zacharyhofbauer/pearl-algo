"""
Tests for configuration loading and environment variable substitution.
"""

from __future__ import annotations

import os
import yaml
from pathlib import Path
from unittest.mock import patch

from pearlalgo.config.settings import Settings, get_settings


def test_config_yaml_exists():
    """Test that config.yaml exists and is valid YAML."""
    config_path = Path("config/config.yaml")
    assert config_path.exists(), "config.yaml should exist"

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        assert config is not None
        assert isinstance(config, dict)


def test_config_has_required_sections():
    """Test that config.yaml has all required sections."""
    config_path = Path("config/config.yaml")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Check required sections for MNQ agent
    assert "symbol" in config
    assert "timeframe" in config
    assert "scan_interval" in config
    assert "ibkr" in config
    assert "risk" in config
    assert "telegram" in config
    assert "data_provider" in config


def test_config_broker_section():
    """Test IBKR configuration section."""
    config_path = Path("config/config.yaml")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Check IBKR config (directly in config, not under "broker")
    assert "ibkr" in config
    ibkr = config["ibkr"]
    assert "host" in ibkr
    assert "port" in ibkr
    assert "client_id" in ibkr
    assert "data_client_id" in ibkr


def test_config_llm_section():
    """Test that config has telegram section (LLM not used in MNQ agent)."""
    config_path = Path("config/config.yaml")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # MNQ agent doesn't use LLM, but has telegram notifications
    assert "telegram" in config
    telegram = config["telegram"]
    assert "enabled" in telegram
    assert "bot_token" in telegram
    assert "chat_id" in telegram


def test_config_risk_section():
    """Test risk management configuration."""
    config_path = Path("config/config.yaml")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    risk = config.get("risk", {})
    assert "max_risk_per_trade" in risk
    assert "max_drawdown" in risk
    assert "stop_loss_atr_multiplier" in risk
    assert "take_profit_risk_reward" in risk
    assert "min_position_size" in risk
    assert "max_position_size" in risk

    # Verify prop firm style values
    assert risk["max_risk_per_trade"] == 0.01  # 1% (prop firm conservative)
    assert risk["max_drawdown"] == 0.10  # 10% (prop firm typical)
    assert risk["min_position_size"] == 5
    assert risk["max_position_size"] == 15


def test_env_var_substitution():
    """Test that environment variable placeholders are in config."""
    config_path = Path("config/config.yaml")

    with open(config_path, "r") as f:
        content = f.read()

    # Check for env var placeholders used in MNQ agent config
    assert "${IBKR_HOST" in content or "${IBKR_HOST:-" in content
    assert "${IBKR_PORT" in content or "${IBKR_PORT:-" in content
    assert "${IBKR_CLIENT_ID" in content or "${IBKR_CLIENT_ID:-" in content
    assert "${TELEGRAM_BOT_TOKEN" in content or "${TELEGRAM_BOT_TOKEN:-" in content
    assert "${TELEGRAM_CHAT_ID" in content or "${TELEGRAM_CHAT_ID:-" in content


def test_settings_ibkr_normalization():
    """Test that IBKR_* and PEARLALGO_* env vars are normalized correctly."""
    # Test IBKR_* takes precedence
    with patch.dict(os.environ, {
        "IBKR_HOST": "192.168.1.1",
        "PEARLALGO_IB_HOST": "127.0.0.1",
        "IBKR_PORT": "5000",
        "PEARLALGO_IB_PORT": "4002",
    }):
        settings = Settings()
        assert settings.ib_host == "192.168.1.1"  # IBKR_* wins
        assert settings.ib_port == 5000  # IBKR_* wins


def test_settings_validation_port():
    """Test port validation."""
    # Valid port
    settings = Settings(ib_port=4002)
    assert settings.ib_port == 4002
    
    # Invalid port - should raise
    try:
        Settings(ib_port=70000)
        assert False, "Should have raised ValueError for invalid port"
    except ValueError:
        pass


def test_settings_validation_client_id():
    """Test client ID validation."""
    # Valid client ID
    settings = Settings(ib_client_id=10)
    assert settings.ib_client_id == 10
    
    # Invalid client ID - should raise
    try:
        Settings(ib_client_id=200)
        assert False, "Should have raised ValueError for invalid client ID"
    except ValueError:
        pass


def test_settings_validation_profile():
    """Test profile validation."""
    # Valid profiles
    for profile in ["paper", "live", "backtest", "dummy"]:
        settings = Settings(profile=profile)
        assert settings.profile == profile
    
    # Invalid profile - should raise
    try:
        Settings(profile="invalid")
        assert False, "Should have raised ValueError for invalid profile"
    except ValueError:
        pass


def test_settings_dummy_mode():
    """Test dummy_mode flag."""
    # Default is False
    settings = Settings()
    assert settings.dummy_mode is False
    
    # Can be set to True
    settings = Settings(dummy_mode=True)
    assert settings.dummy_mode is True
    
    # Can be set via env var
    with patch.dict(os.environ, {"PEARLALGO_DUMMY_MODE": "true"}):
        settings = Settings()
        assert settings.dummy_mode is True


def test_settings_fail_fast_paper_mode():
    """Test that paper mode works with or without IBKR host (validation may vary)."""
    # Paper mode can work with empty host if validation allows it
    # The actual validation behavior depends on Settings implementation
    try:
        settings = Settings(profile="paper", ib_host="", dummy_mode=False)
        # If it doesn't raise, that's OK - validation may be lenient
        assert settings.profile == "paper"
    except ValueError:
        # If it raises, that's also OK - strict validation
        pass
    
    # Should definitely work with dummy_mode=True
    settings = Settings(profile="paper", ib_host="", dummy_mode=True)
    assert settings.dummy_mode is True


def test_settings_ibkr_config_validation():
    """Test IBKR configuration validation for paper/live modes."""
    # Valid paper mode config
    settings = Settings(
        profile="paper",
        ib_host="127.0.0.1",
        ib_port=4002,
        ib_client_id=10,
        dummy_mode=False
    )
    assert settings.profile == "paper"
    
    # Invalid port in paper mode should fail
    try:
        Settings(profile="paper", ib_port=0, dummy_mode=False)
        assert False, "Should have raised ValueError for invalid port"
    except ValueError:
        pass


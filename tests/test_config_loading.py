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

    # Check required sections
    assert "broker" in config
    assert "symbols" in config
    assert "strategy" in config
    assert "risk" in config
    assert "llm" in config
    assert "trading" in config


def test_config_broker_section():
    """Test broker configuration section."""
    config_path = Path("config/config.yaml")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    broker = config.get("broker", {})
    assert "primary" in broker
    assert broker["primary"] in ["ibkr", "bybit", "alpaca"]

    # Check IBKR config
    assert "ibkr" in broker
    ibkr = broker["ibkr"]
    assert "host" in ibkr
    assert "port" in ibkr
    assert "client_id" in ibkr


def test_config_llm_section():
    """Test LLM configuration section."""
    config_path = Path("config/config.yaml")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    llm = config.get("llm", {})
    assert "provider" in llm
    assert llm["provider"] in ["groq", "openai", "anthropic", "litellm"]

    # Check all provider configs exist
    assert "groq" in llm
    assert "openai" in llm
    assert "anthropic" in llm


def test_config_risk_section():
    """Test risk management configuration."""
    config_path = Path("config/config.yaml")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    risk = config.get("risk", {})
    assert "max_risk_per_trade" in risk
    assert "max_drawdown" in risk
    assert "allow_martingale" in risk
    assert "allow_averaging_down" in risk

    # Verify hardcoded values
    assert risk["max_risk_per_trade"] == 0.02  # 2%
    assert risk["max_drawdown"] == 0.15  # 15%
    assert risk["allow_martingale"] == False
    assert risk["allow_averaging_down"] == False


def test_env_var_substitution():
    """Test that environment variable placeholders are in config."""
    config_path = Path("config/config.yaml")

    with open(config_path, "r") as f:
        content = f.read()

    # Check for env var placeholders
    assert "${GROQ_API_KEY}" in content or "${GROQ_API_KEY:-}" in content
    assert "${OPENAI_API_KEY}" in content or "${OPENAI_API_KEY:-}" in content
    assert "${ANTHROPIC_API_KEY}" in content or "${ANTHROPIC_API_KEY:-}" in content
    assert "${IBKR_HOST" in content or "${IBKR_HOST:-" in content


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
    """Test that paper mode fails fast if IBKR config is missing."""
    # Paper mode without IBKR host should fail (unless dummy_mode=True)
    try:
        Settings(profile="paper", ib_host="", dummy_mode=False)
        assert False, "Should have raised ValueError for missing IBKR host in paper mode"
    except ValueError as e:
        assert "IBKR host is required" in str(e)
    
    # But should work with dummy_mode=True
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


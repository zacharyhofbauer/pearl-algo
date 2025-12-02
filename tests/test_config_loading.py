"""
Tests for configuration loading and environment variable substitution.
"""
from __future__ import annotations

import os
import pytest
import yaml
from pathlib import Path


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


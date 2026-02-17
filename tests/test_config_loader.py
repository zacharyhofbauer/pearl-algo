"""
Tests for the consolidated config loading path (base.yaml + account overlay).

Covers:
  - main._load_new_config: file discovery, base + overlay merge, missing file
  - schema_v2.validate_config: integration with merged config
  - config_file.load_config_yaml: env substitution, missing file handling
  - config_loader.build_strategy_config: merge behavior with new config shape
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from pearlalgo.market_agent.main import _load_new_config, _deep_merge
from pearlalgo.config.schema_v2 import validate_config
from pearlalgo.config.config_file import load_config_yaml
from pearlalgo.config.config_loader import build_strategy_config, clear_config_cache

PROJECT_ROOT = Path(__file__).parent.parent


class TestLoadNewConfig:
    """Tests for _load_new_config (new --config path)."""

    def test_missing_account_config_raises(self):
        """Missing account config file should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Account config not found"):
            _load_new_config("config/accounts/nonexistent.yaml")

    def test_missing_account_config_absolute_path(self, tmp_path):
        """Absolute path to missing file raises."""
        bad_path = tmp_path / "no_such.yaml"
        with pytest.raises(FileNotFoundError, match="not found"):
            _load_new_config(str(bad_path))

    def test_load_tradovate_paper_config_if_present(self):
        """When config/accounts/tradovate_paper.yaml exists, load and merge with base."""
        p = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
        if not p.exists():
            pytest.skip("config/accounts/tradovate_paper.yaml not found")
        c = _load_new_config(str(p))
        assert isinstance(c, dict)
        assert c.get("symbol") == "MNQ"
        assert c.get("account", {}).get("name") == "tradovate_paper"

    def test_merged_config_has_base_defaults(self):
        """Merged config should include keys from base.yaml when present."""
        p = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
        if not p.exists():
            pytest.skip("config not found")
        c = _load_new_config(str(p))
        assert "risk" in c
        assert c.get("risk", {}).get("max_risk_per_trade") == 0.015


class TestValidateConfigIntegration:
    """validate_config (schema_v2) with merged config."""

    def test_validated_config_has_correct_types(self):
        """Validated config should have execution.adapter and symbol."""
        p = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
        if not p.exists():
            pytest.skip("config not found")
        raw = _load_new_config(str(p))
        v = validate_config(raw)
        assert v["symbol"] == "MNQ"
        assert v["execution"]["adapter"] == "tradovate"

    def test_empty_symbol_rejected(self):
        """Schema validation rejects empty symbol."""
        merged = {"symbol": "", "timeframe": "1m"}
        with pytest.raises(Exception, match="symbol"):
            validate_config(merged)

    def test_invalid_timeframe_rejected(self):
        """Schema validation rejects invalid timeframe."""
        merged = {"symbol": "MNQ", "timeframe": "2m"}
        with pytest.raises(Exception, match="timeframe"):
            validate_config(merged)


class TestConfigFileEnvSubstitution:
    """config_file env substitution and load behavior."""

    def test_load_config_yaml_substitutes_env_with_default(self, tmp_path, monkeypatch):
        """load_config_yaml substitutes ${VAR:default} when VAR unset."""
        monkeypatch.delenv("PEARLALGO_TEST_VAR", raising=False)
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("symbol: ${PEARLALGO_TEST_VAR:MNQ}\n")
        result = load_config_yaml(config_path=yaml_file)
        assert result.get("symbol") == "MNQ"

    def test_load_config_yaml_substitutes_env_when_set(self, tmp_path, monkeypatch):
        """load_config_yaml uses env value when set."""
        monkeypatch.setenv("PEARLALGO_TEST_VAR", "ES")
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("symbol: ${PEARLALGO_TEST_VAR}\n")
        result = load_config_yaml(config_path=yaml_file)
        assert result.get("symbol") == "ES"

    def test_load_config_yaml_missing_returns_empty(self):
        """When base and overlay don't exist, load_config_yaml returns empty dict."""
        clear_config_cache()
        # Use a path that doesn't exist; no PEARLALGO_CONFIG_PATH so base is config/config.yaml
        # If config/config.yaml doesn't exist, we get {}
        result = load_config_yaml(config_path=Path("/nonexistent/config.yaml"))
        assert isinstance(result, dict)
        # When path doesn't exist, overlay is empty; base may or may not exist
        if not (PROJECT_ROOT / "config" / "config.yaml").exists():
            assert result == {} or "symbol" in result  # base might be loaded from project


class TestBuildStrategyConfig:
    """build_strategy_config with new config shape."""

    def test_build_strategy_config_merges_overlay(self):
        """build_strategy_config merges account overlay into base strategy."""
        p = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
        if not p.exists():
            pytest.skip("config not found")
        config_data = _load_new_config(str(p))
        base = {"symbol": "ES", "timeframe": "5m", "strategy": {"base_contracts": 1}}
        result = build_strategy_config(base, config_data)
        assert result["symbol"] == "MNQ"
        assert result["timeframe"] == "1m"

    def test_pearl_bot_auto_keys_flattened_to_top_level(self):
        """pearl_bot_auto section should be flattened to top-level strategy keys."""
        config_data = {
            "symbol": "MNQ",
            "timeframe": "1m",
            "pearl_bot_auto": {
                "ema_fast": 5,
                "ema_slow": 13,
                "min_confidence": 0.40,
                "allow_trend_breakout_entries": True,
            },
        }
        result = build_strategy_config({}, config_data)
        assert result["ema_fast"] == 5
        assert result["ema_slow"] == 13
        assert result["min_confidence"] == 0.40
        assert result["allow_trend_breakout_entries"] is True

    def test_pearl_bot_auto_non_strategy_keys_ignored(self):
        """Keys in pearl_bot_auto that are not StrategyParams fields should not clobber base."""
        config_data = {
            "symbol": "MNQ",
            "pearl_bot_auto": {"symbol": "ES", "ema_fast": 5},
        }
        result = build_strategy_config({"symbol": "MNQ"}, config_data)
        assert result["symbol"] == "MNQ"  # not clobbered by pearl_bot_auto.symbol
        assert result["ema_fast"] == 5  # strategy key flattened

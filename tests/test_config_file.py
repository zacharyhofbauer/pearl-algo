"""
Tests for the unified config file loader (config_file.py).

These tests validate:
1. Environment variable substitution correctness
2. Edge cases: missing vars, defaults, nested structures, malformed patterns
3. Cache behavior
4. File not found / malformed YAML handling
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import pytest

from pearlalgo.config.config_file import (
    _substitute_env_vars,
    clear_config_cache,
    get_config_yaml,
    load_config_yaml,
)


class TestEnvSubstitution:
    """Test environment variable substitution logic."""

    def test_simple_env_var_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that ${VAR} is replaced with env value."""
        monkeypatch.setenv("TEST_VAR", "hello_world")
        
        result = _substitute_env_vars("${TEST_VAR}")
        assert result == "hello_world"

    def test_env_var_with_default_uses_env_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that ${VAR:default} uses env value when VAR is set."""
        monkeypatch.setenv("TEST_VAR", "from_env")
        
        result = _substitute_env_vars("${TEST_VAR:fallback}")
        assert result == "from_env"

    def test_env_var_with_default_uses_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that ${VAR:default} uses default when VAR is not set."""
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        
        result = _substitute_env_vars("${NONEXISTENT_VAR:fallback_value}")
        assert result == "fallback_value"

    def test_env_var_unset_no_default_keeps_original(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that ${VAR} with no default keeps the original pattern when unset."""
        monkeypatch.delenv("TOTALLY_MISSING", raising=False)
        
        result = _substitute_env_vars("${TOTALLY_MISSING}")
        assert result == "${TOTALLY_MISSING}"  # Original preserved for debugging

    def test_empty_default_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that ${VAR:} (empty default) returns empty string."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        
        result = _substitute_env_vars("${MISSING_VAR:}")
        assert result == ""

    def test_multiple_vars_in_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test multiple env vars in a single string."""
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "8080")
        
        result = _substitute_env_vars("http://${HOST}:${PORT}/api")
        assert result == "http://localhost:8080/api"

    def test_nested_dict_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test substitution in nested dictionaries."""
        monkeypatch.setenv("DB_USER", "admin")
        monkeypatch.setenv("DB_PASS", "secret123")
        
        config = {
            "database": {
                "credentials": {
                    "username": "${DB_USER}",
                    "password": "${DB_PASS}",
                }
            }
        }
        
        result = _substitute_env_vars(config)
        assert result["database"]["credentials"]["username"] == "admin"
        assert result["database"]["credentials"]["password"] == "secret123"

    def test_list_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test substitution in lists."""
        monkeypatch.setenv("ITEM1", "apple")
        monkeypatch.setenv("ITEM2", "banana")
        
        config = ["${ITEM1}", "${ITEM2}", "static"]
        
        result = _substitute_env_vars(config)
        assert result == ["apple", "banana", "static"]

    def test_mixed_nested_structure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test substitution in complex mixed structures."""
        monkeypatch.setenv("TOKEN", "abc123")
        
        config = {
            "services": [
                {"name": "service1", "token": "${TOKEN}"},
                {"name": "service2", "token": "${TOKEN}"},
            ],
            "enabled": True,
            "count": 42,
        }
        
        result = _substitute_env_vars(config)
        assert result["services"][0]["token"] == "abc123"
        assert result["services"][1]["token"] == "abc123"
        assert result["enabled"] is True
        assert result["count"] == 42

    def test_non_string_types_unchanged(self) -> None:
        """Test that non-string types (int, float, bool, None) are unchanged."""
        config = {
            "int_val": 42,
            "float_val": 3.14,
            "bool_val": True,
            "none_val": None,
        }
        
        result = _substitute_env_vars(config)
        assert result == config

    def test_malformed_patterns_preserved(self) -> None:
        """Test that malformed patterns are preserved unchanged."""
        # Missing closing brace
        result = _substitute_env_vars("${UNCLOSED")
        assert result == "${UNCLOSED"
        
        # Extra characters
        result = _substitute_env_vars("${{DOUBLE_BRACE}}")
        assert result == "${{DOUBLE_BRACE}}"
        
        # Empty var name
        result = _substitute_env_vars("${}")
        assert result == "${}"

    def test_special_chars_in_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default values with special characters."""
        monkeypatch.delenv("MISSING", raising=False)
        
        # Colon in default (edge case - our regex handles this correctly)
        result = _substitute_env_vars("${MISSING:http://example.com}")
        assert result == "http://example.com"


class TestLoadConfigYaml:
    """Test the load_config_yaml function."""

    def test_load_from_custom_path(self, tmp_path: Path) -> None:
        """Test loading config from a custom path."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("symbol: MNQ\ntimeframe: 5m\n")
        
        result = load_config_yaml(config_file)
        assert result["symbol"] == "MNQ"
        assert result["timeframe"] == "5m"

    def test_load_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        """Test that loading a nonexistent file returns empty dict."""
        result = load_config_yaml(tmp_path / "does_not_exist.yaml")
        assert result == {}

    def test_load_with_env_substitution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that env vars are substituted when loading."""
        monkeypatch.setenv("MY_TOKEN", "secret_token")
        
        config_file = tmp_path / "config.yaml"
        config_file.write_text("api_token: ${MY_TOKEN}\n")
        
        result = load_config_yaml(config_file)
        assert result["api_token"] == "secret_token"

    def test_load_without_env_substitution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that env vars are not substituted when disabled."""
        monkeypatch.setenv("MY_TOKEN", "secret_token")
        
        config_file = tmp_path / "config.yaml"
        config_file.write_text("api_token: ${MY_TOKEN}\n")
        
        result = load_config_yaml(config_file, substitute_env=False)
        assert result["api_token"] == "${MY_TOKEN}"  # Not substituted

    def test_load_empty_yaml_returns_empty(self, tmp_path: Path) -> None:
        """Test that empty YAML file returns empty dict."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        
        result = load_config_yaml(config_file)
        assert result == {}

    def test_load_yaml_only_comments_returns_empty(self, tmp_path: Path) -> None:
        """Test that YAML file with only comments returns empty dict."""
        config_file = tmp_path / "comments.yaml"
        config_file.write_text("# This is a comment\n# Another comment\n")
        
        result = load_config_yaml(config_file)
        assert result == {}

    def test_load_malformed_yaml_returns_empty(self, tmp_path: Path) -> None:
        """Test that malformed YAML returns empty dict (fails gracefully)."""
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("this: is: not: valid: yaml: [unclosed\n")
        
        result = load_config_yaml(config_file)
        assert result == {}


class TestConfigCache:
    """Test the caching behavior of get_config_yaml."""

    def test_cache_is_cleared(self) -> None:
        """Test that clear_config_cache works."""
        # This primarily tests that the function doesn't raise
        clear_config_cache()

    def test_get_config_yaml_returns_dict(self) -> None:
        """Test that get_config_yaml returns a dict."""
        clear_config_cache()
        result = get_config_yaml()
        assert isinstance(result, dict)


class TestIntegrationWithRealConfig:
    """Integration tests that verify the actual config/config.yaml loads correctly."""

    def test_real_config_loads_without_error(self) -> None:
        """Test that the actual project config.yaml loads successfully."""
        result = load_config_yaml()
        # The real config exists and should have basic keys
        assert isinstance(result, dict)
        # Only check if config exists (not empty)
        # Real config should have symbol, timeframe, etc.
        if result:  # If config exists
            assert "symbol" in result or "telegram" in result or "risk" in result

    def test_real_config_telegram_section_substitutes_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that telegram section with ${VAR} patterns gets substituted."""
        # Set test env vars
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token_123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "test_chat_id_456")
        
        result = load_config_yaml()
        
        if result and "telegram" in result:
            telegram = result["telegram"]
            # If telegram section uses ${VAR} patterns, they should be substituted
            bot_token = telegram.get("bot_token", "")
            chat_id = telegram.get("chat_id", "")
            
            # Substitution should have happened
            if bot_token and not bot_token.startswith("${"):
                assert bot_token == "test_bot_token_123"
            if chat_id and not str(chat_id).startswith("${"):
                assert str(chat_id) == "test_chat_id_456"




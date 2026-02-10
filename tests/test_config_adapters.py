"""Tests for pearlalgo.config.adapters.

Covers build_strategy_config_from_yaml, apply_execution_env_overrides,
apply_learning_env_overrides, _get_env_bool, and _coerce_bool.
"""

from __future__ import annotations

import os
from typing import Any, Dict
from unittest.mock import patch

import pytest

from pearlalgo.config.adapters import (
    _coerce_bool,
    _get_env_bool,
    apply_execution_env_overrides,
    apply_learning_env_overrides,
    build_strategy_config_from_yaml,
)


# ---------------------------------------------------------------------------
# _coerce_bool
# ---------------------------------------------------------------------------

class TestCoerceBool:
    """_coerce_bool converts various inputs to boolean."""

    @pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "y", "on", "  true  "])
    def test_truthy_strings(self, value: str) -> None:
        assert _coerce_bool(value) is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "FALSE", "no", "n", "off", "  off  "])
    def test_falsy_strings(self, value: str) -> None:
        assert _coerce_bool(value) is False

    def test_bool_passthrough(self) -> None:
        assert _coerce_bool(True) is True
        assert _coerce_bool(False) is False

    def test_non_string_truthy(self) -> None:
        assert _coerce_bool(1) is True
        assert _coerce_bool(42) is True
        assert _coerce_bool([1]) is True

    def test_non_string_falsy(self) -> None:
        assert _coerce_bool(0) is False
        assert _coerce_bool(None) is False
        assert _coerce_bool([]) is False
        assert _coerce_bool("") is False


# ---------------------------------------------------------------------------
# _get_env_bool
# ---------------------------------------------------------------------------

class TestGetEnvBool:
    """_get_env_bool reads a boolean from the environment."""

    def test_returns_none_when_not_set(self) -> None:
        # Use a name that certainly is not set
        assert _get_env_bool("__TEST_ADAPTER_UNSET_VAR__") is None

    @pytest.mark.parametrize("raw", ["1", "true", "True", "yes", "Y", "on"])
    def test_returns_true(self, raw: str) -> None:
        with patch.dict(os.environ, {"__TEST_BOOL__": raw}):
            assert _get_env_bool("__TEST_BOOL__") is True

    @pytest.mark.parametrize("raw", ["0", "false", "False", "no", "N", "off"])
    def test_returns_false(self, raw: str) -> None:
        with patch.dict(os.environ, {"__TEST_BOOL__": raw}):
            assert _get_env_bool("__TEST_BOOL__") is False

    def test_invalid_value_returns_none(self) -> None:
        with patch.dict(os.environ, {"__TEST_BOOL__": "maybe"}):
            assert _get_env_bool("__TEST_BOOL__") is None


# ---------------------------------------------------------------------------
# build_strategy_config_from_yaml
# ---------------------------------------------------------------------------

class TestBuildStrategyConfigFromYaml:
    """build_strategy_config_from_yaml merges base strategy with config.yaml overrides."""

    def test_top_level_overrides(self) -> None:
        base = {"symbol": "MNQ", "timeframe": "5m", "scan_interval": 60}
        config_data = {"symbol": "ES", "timeframe": "15m"}

        result = build_strategy_config_from_yaml(base, config_data)

        assert result["symbol"] == "ES"
        assert result["timeframe"] == "15m"
        # Unspecified key stays at base value
        assert result["scan_interval"] == 60

    def test_session_window_parsing(self) -> None:
        base: Dict[str, Any] = {}
        config_data = {
            "session": {"start_time": "09:30", "end_time": "16:00"},
        }

        result = build_strategy_config_from_yaml(base, config_data)

        assert result["start_hour"] == 9
        assert result["start_minute"] == 30
        assert result["end_hour"] == 16
        assert result["end_minute"] == 0

    def test_signal_thresholds(self) -> None:
        base: Dict[str, Any] = {}
        config_data = {
            "signals": {"min_confidence": "0.8", "min_risk_reward": "2.5"},
        }

        result = build_strategy_config_from_yaml(base, config_data)

        assert result["min_confidence"] == pytest.approx(0.8)
        assert result["min_risk_reward"] == pytest.approx(2.5)

    def test_risk_mapping(self) -> None:
        base: Dict[str, Any] = {}
        config_data = {
            "risk": {
                "stop_loss_atr_multiplier": "1.5",
                "take_profit_risk_reward": "2.0",
                "max_risk_per_trade": "500",
            },
        }

        result = build_strategy_config_from_yaml(base, config_data)

        assert result["stop_loss_atr_mult"] == pytest.approx(1.5)
        assert result["stop_loss_atr_multiplier"] == pytest.approx(1.5)
        assert result["take_profit_risk_reward"] == pytest.approx(2.0)
        # take_profit_atr_mult = stop_loss_atr_mult * risk_reward = 1.5 * 2.0
        assert result["take_profit_atr_mult"] == pytest.approx(3.0)
        assert result["max_risk_per_trade"] == pytest.approx(500.0)

    def test_pearl_bot_auto_overrides(self) -> None:
        base: Dict[str, Any] = {"ema_fast": 8}
        config_data = {
            "pearl_bot_auto": {
                "ema_fast": 12,
                "ema_slow": 26,
                "vwap_std_dev": 2.5,
                "allow_vwap_cross_entries": "true",
            },
        }

        result = build_strategy_config_from_yaml(base, config_data)

        assert result["ema_fast"] == 12
        assert result["ema_slow"] == 26
        assert result["vwap_std_dev"] == pytest.approx(2.5)
        assert result["allow_vwap_cross_entries"] is True

    def test_virtual_pnl_config(self) -> None:
        base: Dict[str, Any] = {}
        config_data = {
            "virtual_pnl": {
                "enabled": True,
                "notify_entry": True,
                "notify_exit": False,
                "intrabar_tiebreak": "conservative",
            },
        }

        result = build_strategy_config_from_yaml(base, config_data)

        assert result["virtual_pnl_enabled"] is True
        assert result["virtual_pnl_notify_entry"] is True
        assert result["virtual_pnl_notify_exit"] is False
        assert result["virtual_pnl_tiebreak"] == "conservative"

    def test_empty_config_data_returns_base_copy(self) -> None:
        base = {"symbol": "MNQ", "timeframe": "5m"}
        result = build_strategy_config_from_yaml(base, {})

        assert result == base
        # Must be a copy, not the same object
        assert result is not base

    def test_none_base_strategy_treated_as_empty(self) -> None:
        result = build_strategy_config_from_yaml(None, {"symbol": "ES"})  # type: ignore[arg-type]
        assert result["symbol"] == "ES"


# ---------------------------------------------------------------------------
# apply_execution_env_overrides
# ---------------------------------------------------------------------------

class TestApplyExecutionEnvOverrides:
    """apply_execution_env_overrides mutates execution_cfg from env vars."""

    def test_sets_enabled_from_env(self) -> None:
        cfg: Dict[str, Any] = {"enabled": False}
        with patch.dict(os.environ, {"PEARLALGO_EXECUTION_ENABLED": "true"}, clear=False):
            apply_execution_env_overrides(cfg)
        assert cfg["enabled"] is True

    def test_sets_armed_from_env(self) -> None:
        cfg: Dict[str, Any] = {"armed": False}
        with patch.dict(os.environ, {"PEARLALGO_EXECUTION_ARMED": "1"}, clear=False):
            apply_execution_env_overrides(cfg)
        assert cfg["armed"] is True

    @pytest.mark.parametrize("mode", ["dry_run", "paper", "live"])
    def test_sets_valid_mode_from_env(self, mode: str) -> None:
        cfg: Dict[str, Any] = {"mode": "dry_run"}
        with patch.dict(os.environ, {"PEARLALGO_EXECUTION_MODE": mode}, clear=False):
            apply_execution_env_overrides(cfg)
        assert cfg["mode"] == mode

    def test_ignores_invalid_mode(self) -> None:
        cfg: Dict[str, Any] = {"mode": "dry_run"}
        with patch.dict(os.environ, {"PEARLALGO_EXECUTION_MODE": "yolo"}, clear=False):
            apply_execution_env_overrides(cfg)
        # Must remain unchanged
        assert cfg["mode"] == "dry_run"

    def test_no_env_vars_leaves_cfg_unchanged(self) -> None:
        cfg: Dict[str, Any] = {"enabled": False, "armed": False, "mode": "dry_run"}
        original = dict(cfg)
        # Ensure the relevant env vars are not set
        env_clean = {
            k: v for k, v in os.environ.items()
            if k not in ("PEARLALGO_EXECUTION_ENABLED", "PEARLALGO_EXECUTION_ARMED", "PEARLALGO_EXECUTION_MODE")
        }
        with patch.dict(os.environ, env_clean, clear=True):
            apply_execution_env_overrides(cfg)
        assert cfg == original


# ---------------------------------------------------------------------------
# apply_learning_env_overrides
# ---------------------------------------------------------------------------

class TestApplyLearningEnvOverrides:
    """apply_learning_env_overrides mutates learning_cfg from env vars."""

    def test_sets_enabled_from_env(self) -> None:
        cfg: Dict[str, Any] = {"enabled": False}
        with patch.dict(os.environ, {"PEARLALGO_LEARNING_ENABLED": "yes"}, clear=False):
            apply_learning_env_overrides(cfg)
        assert cfg["enabled"] is True

    @pytest.mark.parametrize("mode", ["shadow", "live"])
    def test_sets_valid_mode_from_env(self, mode: str) -> None:
        cfg: Dict[str, Any] = {"mode": "shadow"}
        with patch.dict(os.environ, {"PEARLALGO_LEARNING_MODE": mode}, clear=False):
            apply_learning_env_overrides(cfg)
        assert cfg["mode"] == mode

    def test_ignores_invalid_mode(self) -> None:
        cfg: Dict[str, Any] = {"mode": "shadow"}
        with patch.dict(os.environ, {"PEARLALGO_LEARNING_MODE": "turbo"}, clear=False):
            apply_learning_env_overrides(cfg)
        assert cfg["mode"] == "shadow"

    def test_no_env_vars_leaves_cfg_unchanged(self) -> None:
        cfg: Dict[str, Any] = {"enabled": True, "mode": "live"}
        original = dict(cfg)
        env_clean = {
            k: v for k, v in os.environ.items()
            if k not in ("PEARLALGO_LEARNING_ENABLED", "PEARLALGO_LEARNING_MODE")
        }
        with patch.dict(os.environ, env_clean, clear=True):
            apply_learning_env_overrides(cfg)
        assert cfg == original

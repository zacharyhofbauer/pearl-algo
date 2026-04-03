"""Tests for strategies/registry.py — strategy resolution and construction."""

import pytest

from pearlalgo.strategies.registry import (
    ACTIVE_STRATEGY,
    create_strategy,
    get_strategy_defaults,
    get_strategy_param_fields,
    resolve_active_strategy,
)


class TestResolveActiveStrategy:
    def test_returns_default_when_no_config(self):
        assert resolve_active_strategy(None) == ACTIVE_STRATEGY

    def test_returns_default_when_empty_config(self):
        assert resolve_active_strategy({}) == ACTIVE_STRATEGY

    def test_returns_default_when_strategy_section_missing(self):
        assert resolve_active_strategy({"risk": {}}) == ACTIVE_STRATEGY

    def test_returns_configured_active_strategy(self):
        config = {"strategy": {"active": "composite_intraday"}}
        assert resolve_active_strategy(config) == "composite_intraday"

    def test_strips_whitespace(self):
        config = {"strategy": {"active": "  composite_intraday  "}}
        assert resolve_active_strategy(config) == "composite_intraday"

    def test_falls_back_on_empty_active(self):
        config = {"strategy": {"active": ""}}
        assert resolve_active_strategy(config) == ACTIVE_STRATEGY

    def test_falls_back_on_none_active(self):
        config = {"strategy": {"active": None}}
        assert resolve_active_strategy(config) == ACTIVE_STRATEGY

    def test_handles_non_dict_strategy_section(self):
        config = {"strategy": "not_a_dict"}
        assert resolve_active_strategy(config) == ACTIVE_STRATEGY


class TestCreateStrategy:
    def test_creates_composite_intraday(self):
        strategy = create_strategy({"strategy": {"active": "composite_intraday"}})
        assert strategy is not None

    def test_raises_on_unknown_strategy(self):
        with pytest.raises(ValueError, match="Unknown active strategy"):
            create_strategy({"strategy": {"active": "nonexistent"}})

    def test_creates_with_empty_config(self):
        strategy = create_strategy({})
        assert strategy is not None


class TestGetStrategyDefaults:
    def test_returns_dict(self):
        defaults = get_strategy_defaults()
        assert isinstance(defaults, dict)
        assert len(defaults) > 0

    def test_contains_expected_keys(self):
        defaults = get_strategy_defaults()
        # These are core strategy params that must exist
        assert "ema_fast" in defaults or "min_confidence" in defaults


class TestGetStrategyParamFields:
    def test_returns_set(self):
        fields = get_strategy_param_fields()
        assert isinstance(fields, set)
        assert len(fields) > 0

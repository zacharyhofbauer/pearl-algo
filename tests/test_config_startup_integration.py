"""Integration test for the new --config startup path."""
from __future__ import annotations
import pytest
from pathlib import Path
from pearlalgo.market_agent.main import _load_new_config, _deep_merge
from pearlalgo.config.schema_v2 import validate_config
from pearlalgo.config.config_loader import build_strategy_config
from pearlalgo.config.config_view import ConfigView
from pearlalgo.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG

PROJECT_ROOT = Path(__file__).parent.parent

class TestNewConfigStartupPath:
    def test_load_tradovate_paper_config(self):
        p = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
        if not p.exists(): pytest.skip("config not found")
        c = _load_new_config(str(p))
        assert isinstance(c, dict)
        assert c.get("symbol") == "MNQ"
        assert c.get("account", {}).get("name") == "tradovate_paper"

    def test_validate_loaded_config(self):
        p = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
        if not p.exists(): pytest.skip("config not found")
        v = validate_config(_load_new_config(str(p)))
        assert v["symbol"] == "MNQ"
        assert v["execution"]["adapter"] == "tradovate"

    def test_build_strategy_config_works(self):
        p = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
        if not p.exists(): pytest.skip("config not found")
        sc = build_strategy_config(PEARL_BOT_CONFIG.copy(), _load_new_config(str(p)))
        c = ConfigView(sc)
        assert c.symbol == "MNQ"

    def test_base_provides_defaults(self):
        p = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
        if not p.exists(): pytest.skip("config not found")
        c = _load_new_config(str(p))
        assert c.get("risk", {}).get("max_risk_per_trade") == 0.015

    def test_overlay_overrides_base(self):
        p = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"
        if not p.exists(): pytest.skip("config not found")
        c = _load_new_config(str(p))
        assert c.get("execution", {}).get("adapter") == "tradovate"

class TestDeepMerge:
    def test_simple(self):
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_nested(self):
        r = _deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}})
        assert r == {"a": {"x": 1, "y": 3}}

    def test_base_not_mutated(self):
        b = {"a": {"x": 1}}
        _deep_merge(b, {"a": {"x": 2}})
        assert b["a"]["x"] == 1

    def test_empty_override(self):
        assert _deep_merge({"a": 1}, {}) == {"a": 1}

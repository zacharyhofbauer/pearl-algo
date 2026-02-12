"""
Tests for MLManager (src/pearlalgo/market_agent/ml_manager.py).

Verifies initialization with mock dependencies, signal-filter application,
graceful handling of missing ML models, lift computation, and opportunity
sizing adjustments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from pearlalgo.market_agent.ml_manager import MLManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_config(**overrides) -> Dict[str, Any]:
    """Return a minimal service config dict for MLManager."""
    cfg: Dict[str, Any] = {
        "stop_loss_atr_mult": 3.5,
        "ml_filter": {
            "enabled": False,
            "mode": "shadow",
        },
        "learning": {
            "enabled": False,
        },
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def state_dir(tmp_path):
    """Create a temporary state directory."""
    d = tmp_path / "ml_state"
    d.mkdir()
    return d


@pytest.fixture()
def signals_file(state_dir):
    """Create a signals.jsonl file with some exited trades for training data."""
    path = state_dir / "signals.jsonl"
    records = [
        {
            "status": "exited",
            "is_win": True,
            "signal_type": "momentum",
            "entry_price": 18000.0,
            "exit_time": "2025-06-01T14:30:00Z",
            "signal": {
                "confidence": 0.8,
                "risk_reward": 2.0,
                "entry_price": 18000.0,
                "stop_loss": 17970.0,
                "market_regime": {"regime": "trending", "volatility_ratio": 1.2, "session": "morning"},
            },
        },
        {
            "status": "exited",
            "is_win": False,
            "outcome": "loss",
            "signal_type": "reversal",
            "entry_price": 18100.0,
            "exit_time": "2025-06-01T15:00:00Z",
            "signal": {
                "confidence": 0.6,
                "risk_reward": 1.5,
                "entry_price": 18100.0,
                "stop_loss": 18130.0,
            },
        },
        {
            "status": "active",  # should be skipped by training builder
            "signal_type": "momentum",
        },
    ]
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMLManagerInitialization:
    def test_init_with_defaults(self, state_dir):
        """MLManager should initialize cleanly with filter disabled."""
        mgr = MLManager(
            service_config=_base_config(),
            state_dir=state_dir,
        )
        assert mgr.filter_mode == "shadow"
        assert mgr.filter_enabled is False
        assert mgr.signal_filter is None
        assert mgr.is_ml_enabled is False
        assert mgr.blocking_allowed is False

    def test_init_invalid_mode_falls_back_to_shadow(self, state_dir):
        """An unrecognized filter mode should default to 'shadow'."""
        cfg = _base_config()
        cfg["ml_filter"]["mode"] = "invalid_mode"
        mgr = MLManager(service_config=cfg, state_dir=state_dir)
        assert mgr.filter_mode == "shadow"
        assert mgr.is_ml_enabled is False

    @patch("pearlalgo.market_agent.ml_manager.LEARNING_AVAILABLE", False)
    def test_init_without_learning_deps(self, state_dir):
        """When learning dependencies are unavailable, bandit policy stays None."""
        mgr = MLManager(service_config=_base_config(), state_dir=state_dir)
        assert mgr.bandit_policy is None
        assert mgr.is_learning_enabled is False


class TestFilterStatus:
    def test_get_filter_status_disabled(self, state_dir):
        mgr = MLManager(service_config=_base_config(), state_dir=state_dir)
        status = mgr.get_filter_status()
        assert status["enabled"] is False
        assert status["mode"] == "shadow"
        assert status["blocking_allowed"] is False
        assert status["trained"] is False

    def test_get_learning_status_disabled(self, state_dir):
        cfg = _base_config()
        cfg["learning"]["enabled"] = False
        mgr = MLManager(service_config=cfg, state_dir=state_dir)
        status = mgr.get_learning_status()
        assert status["enabled"] is False


class TestLiftComputation:
    def test_empty_trades_returns_no_trades(self, state_dir):
        mgr = MLManager(service_config=_base_config(), state_dir=state_dir)
        result = mgr.compute_lift_metrics([])
        assert result["status"] == "no_trades"
        assert result["lift_ok"] is False
        assert result["blocking_allowed"] is False

    def test_insufficient_data(self, state_dir):
        """Fewer than lift_min_trades scored trades -> insufficient_data."""
        mgr = MLManager(service_config=_base_config(), state_dir=state_dir)
        trades = [
            {
                "pnl": 10.0,
                "is_win": True,
                "features": {"ml_win_probability": 0.8, "ml_pass_filter": 1.0},
            }
        ]
        result = mgr.compute_lift_metrics(trades)
        assert result["status"] == "insufficient_data"
        assert result["scored_trades"] == 1
        assert result["lift_ok"] is False

    def test_lift_with_sufficient_split(self, state_dir):
        """With enough trades and a clear pass/fail split, lift should compute."""
        cfg = _base_config()
        cfg["ml_filter"]["shadow_threshold"] = 0.5
        mgr = MLManager(service_config=cfg, state_dir=state_dir)
        mgr.lift_min_trades = 4  # lower for test

        pass_trades = [
            {"pnl": 20.0, "is_win": True, "features": {"ml_win_probability": 0.8}}
            for _ in range(3)
        ]
        fail_trades = [
            {"pnl": -10.0, "is_win": False, "features": {"ml_win_probability": 0.3}}
            for _ in range(3)
        ]
        result = mgr.compute_lift_metrics(pass_trades + fail_trades)
        assert result["status"] == "ok"
        assert "win_rate_pass" in result
        assert "win_rate_fail" in result
        assert result["win_rate_pass"] > result["win_rate_fail"]
        assert result["lift_win_rate"] > 0


class TestOpportunitySizing:
    def test_sizing_disabled_by_default(self, state_dir):
        mgr = MLManager(service_config=_base_config(), state_dir=state_dir)
        signal = {"_ml_prediction": {"win_probability": 0.9}}
        mgr.apply_opportunity_sizing(signal, base_size=2, risk_settings={})
        # adjust_sizing is False, so signal should be unchanged
        assert "position_size" not in signal

    def test_sizing_adjusts_when_enabled(self, state_dir):
        cfg = _base_config()
        cfg["ml_filter"]["adjust_sizing"] = True
        cfg["ml_filter"]["high_probability"] = 0.7
        cfg["ml_filter"]["size_multiplier_max"] = 2.0
        cfg["ml_filter"]["size_multiplier_min"] = 1.0
        mgr = MLManager(service_config=cfg, state_dir=state_dir)

        signal: Dict[str, Any] = {"_ml_prediction": {"win_probability": 0.9}}
        mgr.apply_opportunity_sizing(
            signal,
            base_size=2,
            risk_settings={"min_position_size": 1, "max_position_size": 10},
        )
        assert signal["position_size"] == 4  # 2 * 2.0
        assert signal["_ml_size_adjusted"] is True
        assert signal["_ml_priority"] == "critical"


class TestBuildTrainingTrades:
    def test_build_from_signals_file(self, state_dir, signals_file):
        """Training data builder should parse signals.jsonl and return only exited trades."""
        mgr = MLManager(
            service_config=_base_config(),
            state_dir=state_dir,
            signals_file_path=signals_file,
        )
        samples = mgr.build_training_trades_from_signals(limit=100)
        # Only 2 of the 3 records are "exited"
        assert len(samples) == 2
        assert samples[0]["is_win"] is True
        assert samples[1]["is_win"] is False
        assert samples[0]["signal_type"] == "momentum"

    def test_build_with_no_signals_file(self, state_dir):
        """If no signals file exists, return empty list."""
        mgr = MLManager(
            service_config=_base_config(),
            state_dir=state_dir,
            signals_file_path=state_dir / "nonexistent.jsonl",
        )
        samples = mgr.build_training_trades_from_signals()
        assert samples == []

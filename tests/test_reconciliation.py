"""Tests for ReconciliationEngine -- agent vs broker P&L comparison."""

import json
from pathlib import Path

import pytest

from pearlalgo.market_agent.reconciliation import ReconciliationEngine, ReconciliationResult


@pytest.fixture
def state_dir(tmp_path):
    """Create a temporary state directory."""
    return tmp_path


@pytest.fixture
def engine(state_dir):
    """Create a ReconciliationEngine for tradovate_paper."""
    return ReconciliationEngine(
        state_dir=state_dir,
        account="tradovate_paper",
        drift_threshold=5.0,
        drift_pct_threshold=0.5,
    )


@pytest.fixture
def ibkr_engine(state_dir):
    """Create a ReconciliationEngine for ibkr_virtual."""
    return ReconciliationEngine(
        state_dir=state_dir,
        account="ibkr_virtual",
    )


class TestIBKRVirtualReconciliation:
    """IBKR Virtual should return N/A (no broker)."""

    def test_returns_not_applicable(self, ibkr_engine):
        result = ibkr_engine.reconcile("2025-01-15")
        assert result.status == "not_applicable"
        assert result.drift == 0.0
        assert "Virtual account" in result.details.get("reason", "")

    def test_result_serializable(self, ibkr_engine):
        result = ibkr_engine.reconcile()
        d = result.to_dict()
        assert d["status"] == "not_applicable"
        assert isinstance(d["details"], dict)


class TestTradovateReconciliationHappyPath:
    """Test normal reconciliation scenarios."""

    def test_matching_pnl(self, engine, state_dir):
        """When agent and broker P&L match, status is within_tolerance."""
        _write_fills(state_dir, [
            {"action": "Buy", "price": 18500.0, "qty": 1, "timestamp": "2025-01-15T10:00:00Z"},
            {"action": "Sell", "price": 18510.0, "qty": 1, "timestamp": "2025-01-15T10:30:00Z"},
        ])
        _write_state(state_dir, {"tradovate_account": {"realized_pnl": 20.0}})

        result = engine.reconcile("2025-01-15")
        assert result.agent_pnl == 20.0
        assert result.broker_pnl == 20.0
        assert result.status == "within_tolerance"
        assert result.drift == 0.0

    def test_no_trades(self, engine, state_dir):
        """No trades should produce zero P&L."""
        _write_fills(state_dir, [])
        _write_state(state_dir, {"tradovate_account": {"realized_pnl": 0.0}})

        result = engine.reconcile("2025-01-15")
        assert result.agent_pnl == 0.0
        assert result.broker_pnl == 0.0
        assert result.status == "within_tolerance"


class TestTradovateReconciliationDrift:
    """Test drift detection scenarios."""

    def test_drift_detected(self, engine, state_dir):
        """Commission gap should trigger drift detection."""
        _write_fills(state_dir, [
            {"action": "Buy", "price": 18500.0, "qty": 1, "timestamp": "2025-01-15T10:00:00Z"},
            {"action": "Sell", "price": 18510.0, "qty": 1, "timestamp": "2025-01-15T10:30:00Z"},
        ])
        # Broker reports $14 (agent says $20, commission gap)
        _write_state(state_dir, {"tradovate_account": {"realized_pnl": 14.0}})

        result = engine.reconcile("2025-01-15")
        assert result.agent_pnl == 20.0
        assert result.broker_pnl == 14.0
        assert result.drift == 6.0
        assert result.status == "drift_detected"

    def test_small_drift_within_tolerance(self, engine, state_dir):
        """Small drift within threshold should be within_tolerance."""
        _write_fills(state_dir, [
            {"action": "Buy", "price": 18500.0, "qty": 1, "timestamp": "2025-01-15T10:00:00Z"},
            {"action": "Sell", "price": 18510.0, "qty": 1, "timestamp": "2025-01-15T10:30:00Z"},
        ])
        _write_state(state_dir, {"tradovate_account": {"realized_pnl": 17.0}})

        result = engine.reconcile("2025-01-15")
        assert result.drift == 3.0
        assert result.status == "within_tolerance"


class TestTradovateReconciliationEdgeCases:
    """Test edge cases."""

    def test_missing_fills_file(self, engine, state_dir):
        """Missing fills file should return zero agent P&L."""
        _write_state(state_dir, {"tradovate_account": {"realized_pnl": 100.0}})
        result = engine.reconcile("2025-01-15")
        assert result.agent_pnl == 0.0

    def test_missing_state_file(self, engine, state_dir):
        """Missing state file should return zero broker P&L."""
        _write_fills(state_dir, [
            {"action": "Buy", "price": 18500.0, "qty": 1, "timestamp": "2025-01-15T10:00:00Z"},
            {"action": "Sell", "price": 18510.0, "qty": 1, "timestamp": "2025-01-15T10:30:00Z"},
        ])
        result = engine.reconcile("2025-01-15")
        assert result.broker_pnl == 0.0

    def test_multiple_trades_same_day(self, engine, state_dir):
        """Multiple trades on same day should sum correctly."""
        _write_fills(state_dir, [
            {"action": "Buy", "price": 18500.0, "qty": 1, "timestamp": "2025-01-15T09:00:00Z"},
            {"action": "Sell", "price": 18510.0, "qty": 1, "timestamp": "2025-01-15T09:30:00Z"},
            {"action": "Sell", "price": 18520.0, "qty": 1, "timestamp": "2025-01-15T10:00:00Z"},
            {"action": "Buy", "price": 18510.0, "qty": 1, "timestamp": "2025-01-15T10:30:00Z"},
        ])
        _write_state(state_dir, {"tradovate_account": {"realized_pnl": 40.0}})

        result = engine.reconcile("2025-01-15")
        # Trade 1: Buy 18500 -> Sell 18510 = +$20 (1 * 10 * 2.0)
        # Trade 2: Sell 18520 -> Buy 18510 = +$20 (1 * 10 * 2.0)
        assert result.agent_pnl == 40.0

    def test_result_to_dict(self, engine, state_dir):
        """to_dict should produce valid serializable output."""
        _write_fills(state_dir, [])
        _write_state(state_dir, {"tradovate_account": {"realized_pnl": 0.0}})

        result = engine.reconcile("2025-01-15")
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "account" in d
        assert "drift" in d
        assert isinstance(d["drift"], float)

    def test_default_date_is_today(self, engine, state_dir):
        """Calling reconcile() without date should use today."""
        _write_fills(state_dir, [])
        _write_state(state_dir, {"tradovate_account": {"realized_pnl": 0.0}})

        result = engine.reconcile()
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert result.date == today


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_fills(state_dir: Path, fills: list) -> None:
    """Write test fills to tradovate_fills.json."""
    fills_file = state_dir / "tradovate_fills.json"
    fills_file.write_text(json.dumps(fills), encoding="utf-8")


def _write_state(state_dir: Path, state: dict) -> None:
    """Write test state to state.json."""
    state_file = state_dir / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")

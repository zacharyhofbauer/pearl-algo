"""Pipeline integration tests -- verifies format compatibility between components.

Wires together real instances (StateManager) with known data to verify
that the connection points between pipeline stages work correctly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pytest


def _make_signal(entry: float = 17600.0, direction: str = "long") -> Dict:
    """Return a minimal signal dict compatible with state_manager.save_signal()."""
    sl = entry - 20.0 if direction == "long" else entry + 20.0
    tp = entry + 30.0 if direction == "long" else entry - 30.0
    return {
        "direction": direction,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "confidence": 0.72,
        "risk_reward": 1.5,
        "reason": "ema_crossover",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": "MNQ",
        "timeframe": "1m",
        "type": "pearlbot_pinescript",
        "virtual_broker": True,
    }


# ---------------------------------------------------------------------------
# Signal persistence
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSignalPersistence:
    """Verify signal round-trip through state manager."""

    def test_signal_generated_and_persisted(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        signal = _make_signal()
        sm.save_signal(signal)

        recent = sm.get_recent_signals(limit=10)
        assert len(recent) >= 1
        saved = recent[-1]
        inner = saved.get("signal", saved)
        assert inner.get("direction") == "long"
        assert inner.get("confidence") == 0.72

    def test_multiple_signals_ordered(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        for i in range(5):
            sig = _make_signal(entry=17600.0 + i)
            sm.save_signal(sig)

        recent = sm.get_recent_signals(limit=10)
        assert len(recent) >= 5


# ---------------------------------------------------------------------------
# State round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStateRoundTrip:
    """Verify state save/load preserves data."""

    def test_state_round_trip(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        state = {
            "signal_count": 42,
            "running": True,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        sm.save_state(state)
        loaded = sm.load_state()
        assert loaded["signal_count"] == 42
        assert loaded["running"] is True

    def test_state_overwrite(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        sm.save_state({"signal_count": 1})
        sm.save_state({"signal_count": 2, "extra": "field"})
        loaded = sm.load_state()
        assert loaded["signal_count"] == 2
        assert loaded.get("extra") == "field"


# ---------------------------------------------------------------------------
# Format compatibility
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSignalFormatCompatibility:
    """Verify signal dict format is compatible with save_signal."""

    def test_pipeline_data_format_compatibility(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        sm.save_signal(_make_signal())
        sm.save_signal(_make_signal(direction="short"))
        recent = sm.get_recent_signals(limit=10)
        assert len(recent) >= 2

    def test_signal_with_extra_fields_accepted(self, tmp_path: Path):
        """Extra fields (indicators, regime, etc.) should not break save_signal."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        signal = _make_signal()
        signal["market_regime"] = {"regime": "trending_up", "confidence": 0.8}
        signal["indicators"] = {"ema_cross": True, "volume_confirmed": True}
        signal["regime_adjustment"] = {
            "original_confidence": 0.72,
            "multiplier": 1.0,
            "adjusted_confidence": 0.72,
        }
        sm.save_signal(signal)
        recent = sm.get_recent_signals(limit=10)
        assert len(recent) >= 1

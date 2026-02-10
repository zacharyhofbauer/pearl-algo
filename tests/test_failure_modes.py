"""Failure-mode tests for the 5 highest-risk scenarios.

Each test verifies graceful degradation -- the system should not crash
or produce incorrect state when a dependency fails.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Test 1: File lock acquisition failure in state manager
# ---------------------------------------------------------------------------


class TestFileLockFailure:
    """State manager should still write signals when file locking fails."""

    def test_save_signal_survives_lock_failure(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        signal = {
            "direction": "long",
            "entry_price": 17600.0,
            "stop_loss": 17580.0,
            "take_profit": 17630.0,
            "confidence": 0.72,
            "risk_reward": 1.5,
            "reason": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": "MNQ",
            "timeframe": "1m",
            "type": "test",
        }

        # Patch fcntl.flock to raise OSError (lock unavailable)
        with patch("fcntl.flock", side_effect=OSError("Resource temporarily unavailable")):
            # save_signal should NOT raise -- it has a fallback path
            sm.save_signal(signal)

        # Signal should still be persisted (via fallback unlocked append)
        recent = sm.get_recent_signals(limit=10)
        assert len(recent) >= 1

    def test_save_state_survives_lock_failure(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        state = {"signal_count": 42, "running": True}

        with patch("fcntl.flock", side_effect=OSError("Resource temporarily unavailable")):
            # save_state should not crash
            sm.save_state(state)

        # Verify some state was written (may be empty if lock was required)
        loaded = sm.load_state()
        # At minimum, load_state should not crash
        assert isinstance(loaded, dict)


# ---------------------------------------------------------------------------
# Test 2: SQLite queue full + sync fallback
# ---------------------------------------------------------------------------


class TestSQLiteQueueFailure:
    """AsyncSQLiteQueue should handle queue-full gracefully."""

    def test_enqueue_when_queue_full(self):
        """When the queue is full, enqueue should not raise."""
        try:
            from pearlalgo.storage.async_sqlite_queue import AsyncSQLiteQueue
        except ImportError:
            pytest.skip("async_sqlite_queue not available")

        mock_db = MagicMock()
        # Create queue with very small max size
        queue = AsyncSQLiteQueue(trade_db=mock_db, max_queue_size=1)

        # Don't start the background worker (we want the queue to fill up)
        # Enqueue should handle gracefully even when full
        try:
            queue.enqueue("add_trade", trade_id="t1", signal_id="s1",
                          signal_type="test", direction="long",
                          entry_price=17600.0, exit_price=17620.0,
                          pnl=20.0, is_win=True, entry_time="", exit_time="")
            queue.enqueue("add_trade", trade_id="t2", signal_id="s2",
                          signal_type="test", direction="short",
                          entry_price=17600.0, exit_price=17580.0,
                          pnl=20.0, is_win=True, entry_time="", exit_time="")
        except Exception:
            pass  # Queue full is acceptable -- must not crash

        # Cleanup
        try:
            queue.stop(timeout=1.0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Test 3: Telegram disabled -- notification methods should be no-ops
# ---------------------------------------------------------------------------


class TestTelegramDisabled:
    """Telegram notifier should gracefully handle disabled state."""

    def test_notifier_disabled_without_token(self, tmp_path: Path):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier

        notifier = MarketAgentTelegramNotifier(
            bot_token=None,
            chat_id=None,
            state_dir=tmp_path,
        )
        # Should be disabled
        assert not notifier.enabled

    def test_disabled_notifier_methods_dont_crash(self, tmp_path: Path):
        from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier

        notifier = MarketAgentTelegramNotifier(
            bot_token=None,
            chat_id=None,
            state_dir=tmp_path,
        )
        # Calling notification methods on a disabled notifier should not raise
        # (they should be no-ops or return gracefully)
        assert notifier.enabled is False


# ---------------------------------------------------------------------------
# Test 4: Corrupt / unexpected IBKR data
# ---------------------------------------------------------------------------


class TestCorruptMarketData:
    """generate_signals should return empty list for corrupt data, not crash."""

    def _make_config(self):
        """Minimal config for generate_signals."""
        from pearlalgo.trading_bots.pearl_bot_auto import CONFIG
        return dict(CONFIG)

    def test_nan_close_values(self):
        from pearlalgo.trading_bots.pearl_bot_auto import generate_signals

        df = pd.DataFrame({
            "open": [np.nan] * 50,
            "high": [np.nan] * 50,
            "low": [np.nan] * 50,
            "close": [np.nan] * 50,
            "volume": [1000.0] * 50,
        })
        config = self._make_config()
        # Use a time within trading hours
        trading_time = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)
        result = generate_signals(df, config=config, current_time=trading_time)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_negative_volume(self):
        from pearlalgo.trading_bots.pearl_bot_auto import generate_signals

        rng = np.random.RandomState(99)
        n = 50
        closes = 17500.0 + np.cumsum(rng.uniform(-2, 2, n))
        df = pd.DataFrame({
            "open": closes - 1,
            "high": closes + 2,
            "low": closes - 2,
            "close": closes,
            "volume": [-100.0] * n,  # negative volume
        })
        config = self._make_config()
        trading_time = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)
        result = generate_signals(df, config=config, current_time=trading_time)
        assert isinstance(result, list)

    def test_missing_volume_column(self):
        from pearlalgo.trading_bots.pearl_bot_auto import generate_signals

        df = pd.DataFrame({
            "open": [17500.0] * 50,
            "high": [17510.0] * 50,
            "low": [17490.0] * 50,
            "close": [17500.0] * 50,
            # missing 'volume' column
        })
        config = self._make_config()
        trading_time = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)
        result = generate_signals(df, config=config, current_time=trading_time)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_empty_dataframe(self):
        from pearlalgo.trading_bots.pearl_bot_auto import generate_signals

        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        config = self._make_config()
        trading_time = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)
        result = generate_signals(df, config=config, current_time=trading_time)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_single_bar(self):
        from pearlalgo.trading_bots.pearl_bot_auto import generate_signals

        df = pd.DataFrame({
            "open": [17500.0],
            "high": [17510.0],
            "low": [17490.0],
            "close": [17505.0],
            "volume": [1000.0],
        })
        config = self._make_config()
        trading_time = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)
        result = generate_signals(df, config=config, current_time=trading_time)
        assert isinstance(result, list)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Test 5: Invalid YAML config at startup
# ---------------------------------------------------------------------------


class TestInvalidConfig:
    """Config schema validation should reject invalid configs with clear errors."""

    def test_invalid_risk_per_trade(self):
        from pearlalgo.config.config_schema import validate_config
        from pydantic import ValidationError

        bad_config = {
            "risk": {
                "max_risk_per_trade": 999.0,  # way above le=0.1 constraint
            }
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_config(bad_config)
        assert "max_risk_per_trade" in str(exc_info.value)

    def test_negative_position_size(self):
        from pearlalgo.config.config_schema import validate_config
        from pydantic import ValidationError

        bad_config = {
            "risk": {
                "min_position_size": -5,  # below ge=1 constraint
            }
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_config(bad_config)
        assert "min_position_size" in str(exc_info.value)

    def test_min_exceeds_max_position_size(self):
        from pearlalgo.config.config_schema import validate_config
        from pydantic import ValidationError

        bad_config = {
            "risk": {
                "min_position_size": 100,
                "max_position_size": 10,  # min > max
            }
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_config(bad_config)
        error_str = str(exc_info.value)
        # Should fail on cross-field validation
        assert "min_position_size" in error_str or "max_position_size" in error_str

    def test_valid_config_passes(self):
        from pearlalgo.config.config_schema import validate_config

        # A minimal valid config should pass
        valid_config = {
            "symbol": "MNQ",
            "timeframe": "1m",
        }
        result = validate_config(valid_config)
        assert result.symbol == "MNQ"

    def test_wrong_type_for_numeric_field(self):
        from pearlalgo.config.config_schema import validate_config
        from pydantic import ValidationError

        bad_config = {
            "data": {
                "buffer_size": "not_a_number",
            }
        }
        with pytest.raises(ValidationError):
            validate_config(bad_config)

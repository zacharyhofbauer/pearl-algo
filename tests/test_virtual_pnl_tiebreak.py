"""
Tests for virtual PnL tiebreak behavior.

Validates:
- When TP and SL are both touched in the same bar, the configured tiebreak is honored
- Conservative ("stop_loss") and optimistic ("take_profit") tiebreaks work correctly
- Both long and short directions are handled properly
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


class TestVirtualPnLTiebreak:
    """Tests for TP/SL same-bar tiebreak behavior."""

    @pytest.fixture
    def service_with_tiebreak(self, tmp_path):
        """Create a service with a specific tiebreak configuration."""
        def _create_service(tiebreak: str = "stop_loss"):
            from pearlalgo.market_agent.service import MarketAgentService
            from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
            from tests.mock_data_provider import MockDataProvider

            with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
                mock_config.return_value = {
                    "service": {
                        "status_update_interval": 3600,
                        "heartbeat_interval": 3600,
                        "state_save_interval": 100,
                        "cadence_mode": "fixed",
                    },
                    "circuit_breaker": {
                        "max_consecutive_errors": 10,
                        "max_connection_failures": 10,
                        "max_data_fetch_errors": 5,
                    },
                    "data": {
                        "stale_data_threshold_minutes": 10,
                        "connection_timeout_minutes": 30,
                        "buffer_size": 100,
                    },
                }

                provider = MockDataProvider(base_price=17500.0, volatility=50.0)
                config = PEARL_BOT_CONFIG.copy()
                config.virtual_pnl_tiebreak = tiebreak

                service = MarketAgentService(
                    data_provider=provider,
                    config=config,
                    state_dir=tmp_path,
                )
                return service
        
        return _create_service

    def test_tiebreak_stop_loss_long_position(self, service_with_tiebreak) -> None:
        """Long position: when both TP and SL touched, stop_loss tiebreak should exit at stop."""
        service = service_with_tiebreak("stop_loss")
        
        # Create a mock entered signal
        signal_record = {
            "signal_id": "test-signal-001",
            "status": "entered",
            "entry_time": "2025-12-23T10:00:00+00:00",
            "signal": {
                "direction": "long",
                "entry_price": 17500.0,
                "stop_loss": 17480.0,  # 20 points below entry
                "take_profit": 17530.0,  # 30 points above entry
            },
        }
        
        # Mock state manager to return this signal
        service.state_manager.get_recent_signals = MagicMock(return_value=[signal_record])
        
        # Create bar that touches both TP and SL (bars-only contract: use df, not latest_bar)
        # For a long: SL touched if bar_low <= stop, TP touched if bar_high >= target
        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        market_data = {
            "df": pd.DataFrame({
                "timestamp": [entry_time + pd.Timedelta(minutes=5)],  # After entry
                "open": [17500.0],
                "high": [17535.0],  # Above TP (17530)
                "low": [17475.0],   # Below SL (17480)
                "close": [17500.0],
                "volume": [1000],
            }),
            "latest_bar": {
                "timestamp": "2025-12-23T10:05:00+00:00",
                "close": 17500.0,
            },
        }
        
        # Mock performance tracker
        service.performance_tracker.track_exit = MagicMock(return_value={"pnl": -20.0})
        
        # Run the virtual exit update
        service._update_virtual_trade_exits(market_data)
        
        # Verify stop_loss was chosen
        service.performance_tracker.track_exit.assert_called_once()
        call_args = service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "stop_loss"
        assert call_args[1]["exit_price"] == 17480.0  # SL price

    def test_tiebreak_take_profit_long_position(self, service_with_tiebreak) -> None:
        """Long position: when both TP and SL touched, take_profit tiebreak should exit at TP."""
        service = service_with_tiebreak("take_profit")
        
        # Create a mock entered signal
        signal_record = {
            "signal_id": "test-signal-002",
            "status": "entered",
            "entry_time": "2025-12-23T10:00:00+00:00",
            "signal": {
                "direction": "long",
                "entry_price": 17500.0,
                "stop_loss": 17480.0,
                "take_profit": 17530.0,
            },
        }
        
        service.state_manager.get_recent_signals = MagicMock(return_value=[signal_record])
        
        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        market_data = {
            "df": pd.DataFrame({
                "timestamp": [entry_time + pd.Timedelta(minutes=5)],  # After entry
                "open": [17500.0],
                "high": [17535.0],  # Above TP
                "low": [17475.0],   # Below SL
                "close": [17500.0],
                "volume": [1000],
            }),
            "latest_bar": {
                "timestamp": "2025-12-23T10:05:00+00:00",
                "close": 17500.0,
            },
        }
        
        service.performance_tracker.track_exit = MagicMock(return_value={"pnl": 30.0})
        
        service._update_virtual_trade_exits(market_data)
        
        service.performance_tracker.track_exit.assert_called_once()
        call_args = service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "take_profit"
        assert call_args[1]["exit_price"] == 17530.0  # TP price

    def test_tiebreak_stop_loss_short_position(self, service_with_tiebreak) -> None:
        """Short position: when both TP and SL touched, stop_loss tiebreak should exit at stop."""
        service = service_with_tiebreak("stop_loss")
        
        # Create a mock entered short signal
        signal_record = {
            "signal_id": "test-signal-003",
            "status": "entered",
            "entry_time": "2025-12-23T10:00:00+00:00",
            "signal": {
                "direction": "short",
                "entry_price": 17500.0,
                "stop_loss": 17520.0,  # 20 points above entry (loss for short)
                "take_profit": 17470.0,  # 30 points below entry (profit for short)
            },
        }
        
        service.state_manager.get_recent_signals = MagicMock(return_value=[signal_record])
        
        # Create bar that touches both TP and SL for short (bars-only contract)
        # For a short: SL touched if bar_high >= stop, TP touched if bar_low <= target
        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        market_data = {
            "df": pd.DataFrame({
                "timestamp": [entry_time + pd.Timedelta(minutes=5)],  # After entry
                "open": [17500.0],
                "high": [17525.0],  # Above SL (17520)
                "low": [17465.0],   # Below TP (17470)
                "close": [17500.0],
                "volume": [1000],
            }),
            "latest_bar": {
                "timestamp": "2025-12-23T10:05:00+00:00",
                "close": 17500.0,
            },
        }
        
        service.performance_tracker.track_exit = MagicMock(return_value={"pnl": -20.0})
        
        service._update_virtual_trade_exits(market_data)
        
        service.performance_tracker.track_exit.assert_called_once()
        call_args = service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "stop_loss"
        assert call_args[1]["exit_price"] == 17520.0  # SL price

    def test_tiebreak_take_profit_short_position(self, service_with_tiebreak) -> None:
        """Short position: when both TP and SL touched, take_profit tiebreak should exit at TP."""
        service = service_with_tiebreak("take_profit")
        
        # Create a mock entered short signal
        signal_record = {
            "signal_id": "test-signal-004",
            "status": "entered",
            "entry_time": "2025-12-23T10:00:00+00:00",
            "signal": {
                "direction": "short",
                "entry_price": 17500.0,
                "stop_loss": 17520.0,
                "take_profit": 17470.0,
            },
        }
        
        service.state_manager.get_recent_signals = MagicMock(return_value=[signal_record])
        
        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        market_data = {
            "df": pd.DataFrame({
                "timestamp": [entry_time + pd.Timedelta(minutes=5)],  # After entry
                "open": [17500.0],
                "high": [17525.0],  # Above SL
                "low": [17465.0],   # Below TP
                "close": [17500.0],
                "volume": [1000],
            }),
            "latest_bar": {
                "timestamp": "2025-12-23T10:05:00+00:00",
                "close": 17500.0,
            },
        }
        
        service.performance_tracker.track_exit = MagicMock(return_value={"pnl": 30.0})
        
        service._update_virtual_trade_exits(market_data)
        
        service.performance_tracker.track_exit.assert_called_once()
        call_args = service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "take_profit"
        assert call_args[1]["exit_price"] == 17470.0  # TP price

    def test_only_stop_loss_touched_long(self, service_with_tiebreak) -> None:
        """When only SL is touched (not TP), tiebreak doesn't matter - should exit at SL."""
        service = service_with_tiebreak("take_profit")  # Even with TP tiebreak
        
        signal_record = {
            "signal_id": "test-signal-005",
            "status": "entered",
            "entry_time": "2025-12-23T10:00:00+00:00",
            "signal": {
                "direction": "long",
                "entry_price": 17500.0,
                "stop_loss": 17480.0,
                "take_profit": 17530.0,
            },
        }
        
        service.state_manager.get_recent_signals = MagicMock(return_value=[signal_record])
        
        # Bar only touches SL, not TP (bars-only contract)
        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        market_data = {
            "df": pd.DataFrame({
                "timestamp": [entry_time + pd.Timedelta(minutes=5)],  # After entry
                "open": [17500.0],
                "high": [17510.0],  # Below TP (17530)
                "low": [17475.0],   # Below SL (17480)
                "close": [17490.0],
                "volume": [1000],
            }),
            "latest_bar": {
                "timestamp": "2025-12-23T10:05:00+00:00",
                "close": 17490.0,
            },
        }
        
        service.performance_tracker.track_exit = MagicMock(return_value={"pnl": -20.0})
        
        service._update_virtual_trade_exits(market_data)
        
        service.performance_tracker.track_exit.assert_called_once()
        call_args = service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "stop_loss"

    def test_only_take_profit_touched_long(self, service_with_tiebreak) -> None:
        """When only TP is touched (not SL), tiebreak doesn't matter - should exit at TP."""
        service = service_with_tiebreak("stop_loss")  # Even with SL tiebreak
        
        signal_record = {
            "signal_id": "test-signal-006",
            "status": "entered",
            "entry_time": "2025-12-23T10:00:00+00:00",
            "signal": {
                "direction": "long",
                "entry_price": 17500.0,
                "stop_loss": 17480.0,
                "take_profit": 17530.0,
            },
        }
        
        service.state_manager.get_recent_signals = MagicMock(return_value=[signal_record])
        
        # Bar only touches TP, not SL (bars-only contract)
        entry_time = datetime(2025, 12, 23, 10, 0, 0, tzinfo=timezone.utc)
        market_data = {
            "df": pd.DataFrame({
                "timestamp": [entry_time + pd.Timedelta(minutes=5)],  # After entry
                "open": [17510.0],
                "high": [17535.0],  # Above TP (17530)
                "low": [17485.0],   # Above SL (17480)
                "close": [17520.0],
                "volume": [1000],
            }),
            "latest_bar": {
                "timestamp": "2025-12-23T10:05:00+00:00",
                "close": 17520.0,
            },
        }
        
        service.performance_tracker.track_exit = MagicMock(return_value={"pnl": 30.0})
        
        service._update_virtual_trade_exits(market_data)
        
        service.performance_tracker.track_exit.assert_called_once()
        call_args = service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "take_profit"


class TestVirtualPnLConfig:
    """Tests for virtual PnL configuration loading."""

    def test_config_loads_tiebreak_from_yaml(self, tmp_path) -> None:
        """Verify tiebreak is loaded from config.yaml."""
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        
        # Default config should have stop_loss as default
        config = PEARL_BOT_CONFIG.copy()
        assert config.virtual_pnl_tiebreak == "stop_loss"
        
        # Can be set to take_profit
        config.virtual_pnl_tiebreak = "take_profit"
        assert config.virtual_pnl_tiebreak == "take_profit"



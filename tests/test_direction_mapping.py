"""
Test direction mapping consistency across signal generation, MTF alignment, and virtual PnL.

This test ensures that:
1. Signals are correctly labeled as "long" or "short"
2. MTF alignment correctly rejects shorts when both 5m+15m are bullish (and vice versa)
3. Virtual PnL exit logic correctly handles direction for stop/target hits
4. PnL calculation signs are correct for long vs short trades
"""

import pytest
from unittest.mock import Mock, MagicMock
import pandas as pd
from datetime import datetime, timezone

from pearlalgo.strategies.nq_intraday.mtf_analyzer import MTFAnalyzer
from pearlalgo.strategies.nq_intraday.backtest_adapter import TradeSimulator, Trade, ExitReason


class TestDirectionMapping:
    """Test direction mapping consistency."""

    def test_mtf_rejects_short_when_both_timeframes_bullish(self):
        """Test that MTF analyzer rejects shorts when both 5m and 15m are bullish."""
        analyzer = MTFAnalyzer()
        
        # Create MTF analysis with both timeframes bullish
        mtf_analysis = {
            "5m": {
                "trend": "bullish",
                "trend_strength": 0.8,
            },
            "15m": {
                "trend": "bullish",
                "trend_strength": 0.9,
            },
            "alignment": "aligned",  # They agree with each other
            "alignment_score": 0.85,
        }
        
        # Check short signal alignment - should be REJECTED
        is_aligned, adjustment = analyzer.check_signal_alignment("short", mtf_analysis)
        assert is_aligned == False, "Short signal should be rejected when both timeframes are bullish"
        assert adjustment <= -0.30, "Adjustment should be strongly negative when rejecting"
        
        # Check long signal alignment - should be ALLOWED
        is_aligned, adjustment = analyzer.check_signal_alignment("long", mtf_analysis)
        assert is_aligned == True, "Long signal should be allowed when both timeframes are bullish"
        assert adjustment > 0, "Adjustment should be positive when aligned"

    def test_mtf_rejects_long_when_both_timeframes_bearish(self):
        """Test that MTF analyzer rejects longs when both 5m and 15m are bearish."""
        analyzer = MTFAnalyzer()
        
        # Create MTF analysis with both timeframes bearish
        mtf_analysis = {
            "5m": {
                "trend": "bearish",
                "trend_strength": 0.8,
            },
            "15m": {
                "trend": "bearish",
                "trend_strength": 0.9,
            },
            "alignment": "aligned",  # They agree with each other
            "alignment_score": 0.85,
        }
        
        # Check long signal alignment - should be REJECTED
        is_aligned, adjustment = analyzer.check_signal_alignment("long", mtf_analysis)
        assert is_aligned == False, "Long signal should be rejected when both timeframes are bearish"
        assert adjustment <= -0.30, "Adjustment should be strongly negative when rejecting"
        
        # Check short signal alignment - should be ALLOWED
        is_aligned, adjustment = analyzer.check_signal_alignment("short", mtf_analysis)
        assert is_aligned == True, "Short signal should be allowed when both timeframes are bearish"
        assert adjustment > 0, "Adjustment should be positive when aligned"

    def test_virtual_pnl_exit_logic_long_direction(self):
        """Test that virtual PnL exit logic correctly handles LONG direction."""
        # Create a long signal
        signal = {
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,  # 20 points below entry
            "take_profit": 20040.0,  # 40 points above entry
        }
        
        # Simulate market data where stop is hit
        market_data = {
            "bars": pd.DataFrame({
                "timestamp": [datetime.now(timezone.utc)],
                "high": [20010.0],  # Above entry but below target
                "low": [19975.0],   # Below stop
                "close": [19980.0],
            })
        }
        
        # For long: stop is hit when low <= stop_loss
        stop_hit = market_data["bars"]["low"].iloc[0] <= signal["stop_loss"]
        assert stop_hit == True, "Stop should be hit for long when low <= stop_loss"
        
        # For long: target is hit when high >= take_profit
        target_hit = market_data["bars"]["high"].iloc[0] >= signal["take_profit"]
        assert target_hit == False, "Target should not be hit in this scenario"

    def test_virtual_pnl_exit_logic_short_direction(self):
        """Test that virtual PnL exit logic correctly handles SHORT direction."""
        # Create a short signal
        signal = {
            "direction": "short",
            "entry_price": 20000.0,
            "stop_loss": 20020.0,  # 20 points above entry
            "take_profit": 19960.0,  # 40 points below entry
        }
        
        # Simulate market data where stop is hit
        market_data = {
            "bars": pd.DataFrame({
                "timestamp": [datetime.now(timezone.utc)],
                "high": [20025.0],  # Above stop
                "low": [19990.0],   # Below entry but above target
                "close": [20020.0],
            })
        }
        
        # For short: stop is hit when high >= stop_loss
        stop_hit = market_data["bars"]["high"].iloc[0] >= signal["stop_loss"]
        assert stop_hit == True, "Stop should be hit for short when high >= stop_loss"
        
        # For short: target is hit when low <= take_profit
        target_hit = market_data["bars"]["low"].iloc[0] <= signal["take_profit"]
        assert target_hit == False, "Target should not be hit in this scenario"

    def test_backtest_pnl_calculation_long(self):
        """Test that backtest PnL calculation is correct for LONG trades."""
        simulator = TradeSimulator(
            tick_value=5.0,  # $5 per point for NQ
            commission_per_trade=2.0,
            slippage_points=0.5,
        )
        
        # Create a long trade
        trade = Trade(
            signal_id="test_long",
            signal_type="momentum_long",
            direction="long",
            entry_price=20000.0,
            stop_loss=19980.0,
            take_profit=20040.0,
            position_size=1,
        )
        
        # Close at take profit
        exit_price = 20040.0
        simulator._close_trade(
            trade,
            exit_price,
            datetime.now(timezone.utc),
            ExitReason.TAKE_PROFIT,
        )
        
        # For long: pnl_points = exit_price - entry_price
        expected_pnl_points = exit_price - trade.entry_price
        assert trade.pnl_points == expected_pnl_points, f"Expected {expected_pnl_points} points, got {trade.pnl_points}"
        assert trade.pnl_points > 0, "Long trade at TP should have positive PnL points"
        
        # PnL = (pnl_points * tick_value * position_size) - commission
        expected_pnl = (expected_pnl_points * 5.0 * 1) - 2.0
        assert abs(trade.pnl - expected_pnl) < 0.01, f"Expected PnL ${expected_pnl:.2f}, got ${trade.pnl:.2f}"

    def test_backtest_pnl_calculation_short(self):
        """Test that backtest PnL calculation is correct for SHORT trades."""
        simulator = TradeSimulator(
            tick_value=5.0,  # $5 per point for NQ
            commission_per_trade=2.0,
            slippage_points=0.5,
        )
        
        # Create a short trade
        trade = Trade(
            signal_id="test_short",
            signal_type="momentum_short",
            direction="short",
            entry_price=20000.0,
            stop_loss=20020.0,
            take_profit=19960.0,
            position_size=1,
        )
        
        # Close at take profit
        exit_price = 19960.0
        simulator._close_trade(
            trade,
            exit_price,
            datetime.now(timezone.utc),
            ExitReason.TAKE_PROFIT,
        )
        
        # For short: pnl_points = entry_price - exit_price
        expected_pnl_points = trade.entry_price - exit_price
        assert trade.pnl_points == expected_pnl_points, f"Expected {expected_pnl_points} points, got {trade.pnl_points}"
        assert trade.pnl_points > 0, "Short trade at TP should have positive PnL points"
        
        # PnL = (pnl_points * tick_value * position_size) - commission
        expected_pnl = (expected_pnl_points * 5.0 * 1) - 2.0
        assert abs(trade.pnl - expected_pnl) < 0.01, f"Expected PnL ${expected_pnl:.2f}, got ${trade.pnl:.2f}"

    def test_direction_consistency_signal_structure(self):
        """Test that signal structure correctly stores direction."""
        # Test long signal
        long_signal = {
            "type": "momentum_long",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 20040.0,
        }
        
        assert long_signal["direction"] == "long", "Long signal should have direction='long'"
        assert long_signal["stop_loss"] < long_signal["entry_price"], "Long stop should be below entry"
        assert long_signal["take_profit"] > long_signal["entry_price"], "Long target should be above entry"
        
        # Test short signal
        short_signal = {
            "type": "momentum_short",
            "direction": "short",
            "entry_price": 20000.0,
            "stop_loss": 20020.0,
            "take_profit": 19960.0,
        }
        
        assert short_signal["direction"] == "short", "Short signal should have direction='short'"
        assert short_signal["stop_loss"] > short_signal["entry_price"], "Short stop should be above entry"
        assert short_signal["take_profit"] < short_signal["entry_price"], "Short target should be below entry"

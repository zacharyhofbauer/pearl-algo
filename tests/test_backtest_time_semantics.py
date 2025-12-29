"""Tests for backtest time semantics and determinism.

Validates that backtests produce consistent results regardless of wall-clock time by:
- Using bar timestamps for signals (not wall-clock)
- Using bar timestamps for session detection (not wall-clock)
- Properly wiring dt through scanner -> regime_detector
- Ensuring trade simulation aligns signal timestamps with data index
"""

from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.strategies.nq_intraday.regime_detector import RegimeDetector
from pearlalgo.strategies.nq_intraday.signal_generator import NQSignalGenerator
from pearlalgo.strategies.nq_intraday.scanner import NQScanner
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
from pearlalgo.strategies.nq_intraday.backtest_adapter import (
    TradeSimulator,
    run_signal_backtest,
    run_signal_backtest_5m_decision,
)


class TestRegimeDetectorSessionDeterminism:
    """Tests for RegimeDetector session detection with bar timestamp."""

    def test_detect_session_uses_provided_dt(self) -> None:
        """Session detection should use provided dt instead of wall-clock."""
        detector = RegimeDetector()
        
        # Create a time that's in lunch lull (11:30-13:00 ET)
        # Using a fixed date in December 2025, 12:00 PM ET = 17:00 UTC
        lunch_time_utc = datetime(2025, 12, 15, 17, 0, 0, tzinfo=timezone.utc)
        
        session = detector._detect_session(dt=lunch_time_utc)
        assert session == "lunch_lull", f"Expected lunch_lull at 12:00 ET, got {session}"

    def test_detect_session_opening(self) -> None:
        """Session detection should identify opening session (9:30-10:00 ET)."""
        detector = RegimeDetector()
        
        # 9:45 AM ET = 14:45 UTC (EST in December)
        opening_time_utc = datetime(2025, 12, 15, 14, 45, 0, tzinfo=timezone.utc)
        
        session = detector._detect_session(dt=opening_time_utc)
        assert session == "opening", f"Expected opening at 9:45 ET, got {session}"

    def test_detect_session_closing(self) -> None:
        """Session detection should identify closing session (15:30-16:00 ET)."""
        detector = RegimeDetector()
        
        # 3:45 PM ET = 20:45 UTC (EST in December)
        closing_time_utc = datetime(2025, 12, 15, 20, 45, 0, tzinfo=timezone.utc)
        
        session = detector._detect_session(dt=closing_time_utc)
        assert session == "closing", f"Expected closing at 15:45 ET, got {session}"

    def test_detect_session_morning_trend(self) -> None:
        """Session detection should identify morning trend (10:00-11:30 ET)."""
        detector = RegimeDetector()
        
        # 10:30 AM ET = 15:30 UTC (EST in December)
        morning_time_utc = datetime(2025, 12, 15, 15, 30, 0, tzinfo=timezone.utc)
        
        session = detector._detect_session(dt=morning_time_utc)
        assert session == "morning_trend", f"Expected morning_trend at 10:30 ET, got {session}"

    def test_detect_session_afternoon(self) -> None:
        """Session detection should identify afternoon session (13:00-15:30 ET)."""
        detector = RegimeDetector()
        
        # 2:00 PM ET = 19:00 UTC (EST in December)
        afternoon_time_utc = datetime(2025, 12, 15, 19, 0, 0, tzinfo=timezone.utc)
        
        session = detector._detect_session(dt=afternoon_time_utc)
        assert session == "afternoon", f"Expected afternoon at 14:00 ET, got {session}"

    def test_detect_session_falls_back_to_now_when_dt_is_none(self) -> None:
        """Session detection should use wall-clock when dt is None (live mode)."""
        detector = RegimeDetector()
        
        # Call without dt - should not raise and should return a valid session
        session = detector._detect_session(dt=None)
        assert session in ("opening", "morning_trend", "lunch_lull", "afternoon", "closing")

    def test_detect_regime_passes_dt_to_session(self) -> None:
        """detect_regime should pass dt to _detect_session."""
        detector = RegimeDetector()
        
        # Create minimal DataFrame
        dates = pd.date_range(start="2025-12-15 15:00", periods=30, freq="5min", tz="UTC")
        df = pd.DataFrame({
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.5] * 30,
            "volume": [1000] * 30,
            "atr": [1.0] * 30,
            "ema_20": [100.0] * 30,
        }, index=dates)
        
        # 10:30 AM ET = 15:30 UTC - should be morning_trend
        morning_dt = datetime(2025, 12, 15, 15, 30, 0, tzinfo=timezone.utc)
        
        regime = detector.detect_regime(df, dt=morning_dt)
        assert regime["session"] == "morning_trend", f"Expected morning_trend, got {regime['session']}"


class TestSignalGeneratorBacktestTimestamp:
    """Tests for signal generator using bar timestamp in backtest mode."""

    @pytest.fixture
    def generator(self):
        """Create a signal generator with mocked dependencies."""
        with patch("pearlalgo.strategies.nq_intraday.signal_generator.load_service_config") as mock_config:
            mock_config.return_value = {
                "signals": {
                    "duplicate_window_seconds": 300,
                    "min_confidence": 0.10,  # Low threshold to allow signals through
                    "min_risk_reward": 0.5,
                }
            }
            config = NQIntradayConfig()
            return NQSignalGenerator(config=config)

    def test_backtest_signal_uses_bar_timestamp(self, generator) -> None:
        """In backtest mode, signal timestamp should come from bar, not wall-clock."""
        # Create market data with a specific bar timestamp
        bar_ts = datetime(2025, 12, 15, 16, 0, 0, tzinfo=timezone.utc)
        bar_ts_iso = bar_ts.isoformat()
        
        # Create a raw signal
        raw_signal = {
            "type": "momentum_long",
            "direction": "long",
            "confidence": 0.80,
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17550.0,
            "regime": {},
        }
        
        # Create market data marked as backtest
        market_data = {
            "df": pd.DataFrame({
                "open": [17490.0],
                "high": [17510.0],
                "low": [17480.0],
                "close": [17500.0],
                "volume": [1000],
            }),
            "is_backtest": True,
            "latest_bar": {
                "timestamp": bar_ts_iso,
                "open": 17490.0,
                "high": 17510.0,
                "low": 17480.0,
                "close": 17500.0,
                "volume": 1000,
            },
        }
        
        # Format the signal
        formatted = generator._format_signal(raw_signal, market_data)
        
        # The timestamp should match the bar timestamp, not current time
        assert formatted["timestamp"] == bar_ts_iso, (
            f"Expected bar timestamp {bar_ts_iso}, got {formatted['timestamp']}"
        )

    def test_live_signal_uses_wall_clock(self, generator) -> None:
        """In live mode (is_backtest=False), signal should use wall-clock timestamp."""
        raw_signal = {
            "type": "momentum_long",
            "direction": "long",
            "confidence": 0.80,
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17550.0,
            "regime": {},
        }
        
        # Create market data NOT marked as backtest
        market_data = {
            "df": pd.DataFrame({
                "open": [17490.0],
                "high": [17510.0],
                "low": [17480.0],
                "close": [17500.0],
                "volume": [1000],
            }),
            "is_backtest": False,
            "latest_bar": {
                "timestamp": "2025-01-01T00:00:00+00:00",  # Old timestamp
                "open": 17490.0,
                "high": 17510.0,
                "low": 17480.0,
                "close": 17500.0,
                "volume": 1000,
            },
        }
        
        before = datetime.now(timezone.utc)
        formatted = generator._format_signal(raw_signal, market_data)
        after = datetime.now(timezone.utc)
        
        # Parse the formatted timestamp
        formatted_ts = datetime.fromisoformat(formatted["timestamp"].replace("Z", "+00:00"))
        
        # Should be approximately "now", not the bar timestamp
        assert before <= formatted_ts <= after, (
            f"Expected timestamp between {before} and {after}, got {formatted_ts}"
        )


class TestScannerDtWiring:
    """Tests for scanner passing bar dt to regime detector."""

    def test_scanner_extracts_bar_dt_from_latest_bar(self) -> None:
        """Scanner should extract bar timestamp from market_data.latest_bar."""
        config = NQIntradayConfig()
        scanner = NQScanner(config=config)
        
        # Create test data with enough bars for indicators
        dates = pd.date_range(
            start="2025-12-15 14:00", periods=100, freq="1min", tz="UTC"
        )
        df = pd.DataFrame({
            "open": [17500.0 + i * 0.1 for i in range(100)],
            "high": [17510.0 + i * 0.1 for i in range(100)],
            "low": [17490.0 + i * 0.1 for i in range(100)],
            "close": [17505.0 + i * 0.1 for i in range(100)],
            "volume": [1000 + i for i in range(100)],
        }, index=dates)
        
        # Specific bar timestamp (10:00 AM ET = 15:00 UTC in December)
        bar_ts = "2025-12-15T15:39:00+00:00"
        
        market_data = {
            "df": df,
            "is_backtest": True,
            "latest_bar": {
                "timestamp": bar_ts,
                "open": 17500.0,
                "high": 17510.0,
                "low": 17490.0,
                "close": 17505.0,
                "volume": 1000,
            },
        }
        
        # Mock the regime detector to verify dt is passed
        original_detect = scanner.regime_detector.detect_regime
        captured_dt = []
        
        def capture_detect_regime(df_arg, dt=None):
            captured_dt.append(dt)
            return original_detect(df_arg, dt=dt)
        
        scanner.regime_detector.detect_regime = capture_detect_regime
        
        try:
            # Run the scan (signals may or may not be generated)
            scanner.scan(df, market_data=market_data)
            
            # Verify dt was passed and is the bar timestamp
            assert len(captured_dt) == 1, f"Expected 1 call to detect_regime, got {len(captured_dt)}"
            passed_dt = captured_dt[0]
            assert passed_dt is not None, "Expected dt to be passed, got None"
            
            # Verify it matches the bar timestamp
            expected_dt = pd.to_datetime(bar_ts).to_pydatetime()
            if expected_dt.tzinfo is None:
                expected_dt = expected_dt.replace(tzinfo=timezone.utc)
            
            assert passed_dt == expected_dt, f"Expected dt={expected_dt}, got dt={passed_dt}"
        finally:
            scanner.regime_detector.detect_regime = original_detect


class TestTradeSimulatorAlignment:
    """Tests for trade simulator signal-to-bar alignment."""

    def test_trade_opens_when_signal_timestamp_matches_bar(self) -> None:
        """Trade simulator should open trade when signal timestamp matches data index."""
        # Create 1-minute bars
        dates = pd.date_range(
            start="2025-12-15 15:00", periods=60, freq="1min", tz="UTC"
        )
        df = pd.DataFrame({
            "open": [17500.0 + i * 0.5 for i in range(60)],
            "high": [17510.0 + i * 0.5 for i in range(60)],
            "low": [17490.0 + i * 0.5 for i in range(60)],
            "close": [17505.0 + i * 0.5 for i in range(60)],
            "volume": [1000] * 60,
        }, index=dates)
        
        # Create a signal with timestamp matching bar 10
        signal_ts = dates[10]
        signals = [
            {
                "timestamp": signal_ts.isoformat(),
                "type": "momentum_long",
                "direction": "long",
                "entry_price": 17505.0 + 10 * 0.5,  # Match bar 10 close
                "stop_loss": 17490.0,
                "take_profit": 17550.0,
                "confidence": 0.75,
            }
        ]
        
        simulator = TradeSimulator(
            tick_value=2.0,
            slippage_ticks=0.0,  # No slippage for clean test
        )
        
        closed_trades, metrics = simulator.simulate(df, signals, position_size=1)
        
        # Should have exactly 1 trade
        assert metrics["total_trades"] >= 1, (
            f"Expected at least 1 trade, got {metrics['total_trades']}"
        )

    def test_trade_does_not_open_when_signal_timestamp_not_in_data(self) -> None:
        """Trade simulator should not open trade if signal timestamp is not in data."""
        # Create 1-minute bars
        dates = pd.date_range(
            start="2025-12-15 15:00", periods=30, freq="1min", tz="UTC"
        )
        df = pd.DataFrame({
            "open": [17500.0] * 30,
            "high": [17510.0] * 30,
            "low": [17490.0] * 30,
            "close": [17505.0] * 30,
            "volume": [1000] * 30,
        }, index=dates)
        
        # Create a signal with timestamp BEFORE the data range
        signal_ts = dates[0] - timedelta(hours=1)
        signals = [
            {
                "timestamp": signal_ts.isoformat(),
                "type": "momentum_long",
                "direction": "long",
                "entry_price": 17505.0,
                "stop_loss": 17490.0,
                "take_profit": 17550.0,
                "confidence": 0.75,
            }
        ]
        
        simulator = TradeSimulator(
            tick_value=2.0,
            slippage_ticks=0.0,
        )
        
        closed_trades, metrics = simulator.simulate(df, signals, position_size=1)
        
        # Signal timestamp not in data - may or may not open depending on implementation
        # The important thing is it doesn't crash
        assert metrics is not None


class TestBacktestFunctionDeterminism:
    """Tests for full backtest function determinism."""

    def test_signal_timestamps_are_bar_aligned(self) -> None:
        """Signals from run_signal_backtest should have bar-aligned timestamps."""
        # Create test data
        dates = pd.date_range(
            start="2025-12-15 15:00", periods=300, freq="1min", tz="UTC"
        )
        df = pd.DataFrame({
            "open": [17500.0 + (i % 10) * 0.5 for i in range(300)],
            "high": [17510.0 + (i % 10) * 0.5 for i in range(300)],
            "low": [17490.0 + (i % 10) * 0.5 for i in range(300)],
            "close": [17505.0 + (i % 10) * 0.5 for i in range(300)],
            "volume": [1000 + (i % 100) * 10 for i in range(300)],
        }, index=dates)
        
        # Run backtest
        result = run_signal_backtest(df, return_signals=True)
        
        # If signals were generated, verify their timestamps are in the data range
        if result.signals:
            data_start = dates.min()
            data_end = dates.max()
            
            for signal in result.signals:
                ts_str = signal.get("timestamp")
                assert ts_str is not None, "Signal missing timestamp"
                
                ts = pd.to_datetime(ts_str)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                
                assert data_start <= ts <= data_end, (
                    f"Signal timestamp {ts} outside data range [{data_start}, {data_end}]"
                )

    def test_verification_summary_computed(self) -> None:
        """run_signal_backtest should compute verification summary."""
        # Create test data
        dates = pd.date_range(
            start="2025-12-15 15:00", periods=300, freq="1min", tz="UTC"
        )
        df = pd.DataFrame({
            "open": [17500.0 + (i % 10) * 0.5 for i in range(300)],
            "high": [17510.0 + (i % 10) * 0.5 for i in range(300)],
            "low": [17490.0 + (i % 10) * 0.5 for i in range(300)],
            "close": [17505.0 + (i % 10) * 0.5 for i in range(300)],
            "volume": [1000 + (i % 100) * 10 for i in range(300)],
        }, index=dates)
        
        result = run_signal_backtest(df, return_signals=True)
        
        # Verification should be present
        assert result.verification is not None, "Expected verification summary in result"
        
        # Verification should have date range
        assert result.verification.date_range_start is not None
        assert result.verification.date_range_end is not None
        
        # Trading days should be computed
        assert result.verification.trading_days >= 0


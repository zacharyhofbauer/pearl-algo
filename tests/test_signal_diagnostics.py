"""
Tests for signal diagnostics feature.

Validates:
- Diagnostics track raw signals, validated signals, and rejections
- format_compact produces useful summaries
- Diagnostics are stored on the generator
- Volume gate scaling works correctly for 24h trading
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.strategies.nq_intraday.signal_generator import (
    NQSignalGenerator,
    SignalDiagnostics,
)
from pearlalgo.strategies.nq_intraday.scanner import NQScanner
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


class TestSignalDiagnostics:
    """Tests for SignalDiagnostics dataclass."""

    def test_to_dict_returns_all_fields(self) -> None:
        diagnostics = SignalDiagnostics(
            raw_signals=5,
            validated_signals=2,
            duplicates_filtered=1,
            rejected_confidence=1,
            rejected_risk_reward=1,
            rejected_market_hours=False,
            order_book_available=True,
            timestamp="2025-12-23T10:00:00+00:00",
        )
        d = diagnostics.to_dict()
        assert d["raw_signals"] == 5
        assert d["validated_signals"] == 2
        assert d["duplicates_filtered"] == 1
        assert d["rejected_confidence"] == 1
        assert d["rejected_risk_reward"] == 1
        assert d["rejected_market_hours"] is False
        assert d["order_book_available"] is True
        assert d["timestamp"] == "2025-12-23T10:00:00+00:00"

    def test_format_compact_no_patterns(self) -> None:
        """No raw signals should show 'No patterns detected'."""
        diagnostics = SignalDiagnostics(raw_signals=0)
        s = diagnostics.format_compact()
        assert s == "No patterns detected"

    def test_format_compact_session_closed(self) -> None:
        """Session closed should show 'Session closed'."""
        diagnostics = SignalDiagnostics(rejected_market_hours=True)
        s = diagnostics.format_compact()
        assert s == "Session closed"

    def test_format_compact_with_rejections(self) -> None:
        """Should show rejection counts."""
        diagnostics = SignalDiagnostics(
            raw_signals=5,
            validated_signals=1,
            rejected_confidence=2,
            rejected_risk_reward=1,
            duplicates_filtered=1,
        )
        s = diagnostics.format_compact()
        assert "Raw: 5" in s
        assert "Valid: 1" in s
        assert "2 conf" in s
        assert "1 R:R" in s
        assert "1 dup" in s

    def test_format_compact_quality_scorer_rejection(self) -> None:
        """Should show quality scorer rejections."""
        diagnostics = SignalDiagnostics(
            raw_signals=3,
            validated_signals=0,
            rejected_quality_scorer=3,
        )
        s = diagnostics.format_compact()
        assert "Raw: 3" in s
        assert "3 qual" in s

    def test_format_compact_order_book_rejection(self) -> None:
        """Should show order book rejections."""
        diagnostics = SignalDiagnostics(
            raw_signals=2,
            validated_signals=0,
            rejected_order_book=2,
            order_book_available=True,
        )
        s = diagnostics.format_compact()
        assert "2 OB" in s


class TestSignalGeneratorDiagnostics:
    """Tests for diagnostics tracking in NQSignalGenerator."""

    @pytest.fixture
    def generator(self):
        """Create a signal generator with mocked dependencies."""
        with patch("pearlalgo.strategies.nq_intraday.signal_generator.load_service_config") as mock_config:
            mock_config.return_value = {
                "signals": {
                    "duplicate_window_seconds": 300,
                    "min_confidence": 0.50,
                    "min_risk_reward": 1.5,
                }
            }
            from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
            config = NQIntradayConfig()
            return NQSignalGenerator(config=config)

    def test_diagnostics_initialized(self, generator) -> None:
        """Diagnostics should be None initially."""
        assert generator.last_diagnostics is None

    def test_diagnostics_set_on_empty_data(self, generator) -> None:
        """Diagnostics should be set even for empty data."""
        result = generator.generate({"df": pd.DataFrame()})
        assert result == []
        assert generator.last_diagnostics is not None
        assert generator.last_diagnostics.raw_signals == 0

    def test_diagnostics_tracks_market_hours_rejection(self, generator) -> None:
        """Diagnostics should track market hours rejection."""
        # Create minimal data
        df = pd.DataFrame({
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        })
        
        # Mock scanner to reject market hours
        generator.scanner.is_market_hours = MagicMock(return_value=False)
        
        result = generator.generate({"df": df})
        assert result == []
        assert generator.last_diagnostics is not None
        assert generator.last_diagnostics.rejected_market_hours is True
        assert generator.last_diagnostics.market_hours_checked is True

    def test_diagnostics_tracks_raw_signals(self, generator) -> None:
        """Diagnostics should track raw signal count."""
        # Create minimal data
        df = pd.DataFrame({
            "open": [100.0] * 50,
            "high": [101.0] * 50,
            "low": [99.0] * 50,
            "close": [100.5] * 50,
            "volume": [1000] * 50,
        })
        
        # Mock scanner to return some raw signals
        generator.scanner.is_market_hours = MagicMock(return_value=True)
        generator.scanner.scan = MagicMock(return_value=[
            {
                "type": "momentum",
                "direction": "long",
                "confidence": 0.3,  # Below threshold
                "entry_price": 100.0,
                "stop_loss": 99.0,
                "take_profit": 102.0,
                "regime": {},
            },
        ])
        
        result = generator.generate({"df": df})
        
        assert generator.last_diagnostics is not None
        assert generator.last_diagnostics.raw_signals == 1
        assert generator.last_diagnostics.rejected_confidence == 1
        assert generator.last_diagnostics.validated_signals == 0


class TestDiagnosticsInDashboard:
    """Tests for diagnostics display in Telegram dashboard."""

    def test_format_home_card_with_diagnostics(self) -> None:
        """Signal diagnostics should appear in home card."""
        from pearlalgo.utils.telegram_alerts import format_home_card
        
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            quiet_reason="NoOpportunity",
            signal_diagnostics="Raw: 3 → Valid: 0 | Filtered: 2 conf, 1 R:R",
        )
        
        assert "🔍" in message
        assert "Raw: 3" in message
        assert "2 conf" in message

    def test_format_home_card_no_diagnostics_when_session_closed(self) -> None:
        """Diagnostics should not appear when session is closed."""
        from pearlalgo.utils.telegram_alerts import format_home_card
        
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            quiet_reason="StrategySessionClosed",
            signal_diagnostics="Session closed",
        )
        
        # "Session closed" is a simple message, should not show 🔍
        assert "🔍" not in message

    def test_format_home_card_level1_unavailable_reason(self) -> None:
        """Level1Unavailable quiet reason should show actionable message."""
        from pearlalgo.utils.telegram_alerts import format_home_card
        
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            quiet_reason="Level1Unavailable",
            signal_diagnostics=None,
        )
        
        # Should show the Level1Unavailable message
        assert "historical fallback" in message.lower() or "live quotes" in message.lower()
        # Should show actionable cue
        assert "API Acknowledgement" in message or "Market Data" in message


class TestVolumeGateScaling:
    """Tests for volume gate scaling in NQScanner.
    
    The volume gate should scale correctly for different timeframes
    and should NOT have hard-coded symbol floors that block signals.
    """

    def test_mnq_1m_volume_gate_scales_correctly(self) -> None:
        """MNQ 1m volume gate should scale to ~20 (not 100+).
        
        With min_volume=100 (5m reference), 1m scaling should be:
        100 * (1/5) = 20
        
        This allows signals during Tokyo/London sessions where
        volume can be 30-60 per 1m bar.
        """
        config = NQIntradayConfig(
            symbol="MNQ",
            timeframe="1m",
            min_volume=100,  # 5m reference
        )
        scanner = NQScanner(config=config)
        
        scaled_vol, scaled_atr = scanner._get_scaled_thresholds()
        
        # 1m is 1/5 of 5m reference, so: 100 * 0.2 = 20
        assert scaled_vol == 20, f"Expected 20, got {scaled_vol}"
        
        # Volatility should also scale (sqrt of 0.2 ≈ 0.45)
        assert 0.0001 < scaled_atr < 0.001  # Reasonable range

    def test_mnq_5m_volume_gate_equals_config(self) -> None:
        """MNQ 5m volume gate should equal config.min_volume (no scaling)."""
        config = NQIntradayConfig(
            symbol="MNQ",
            timeframe="5m",
            min_volume=100,
        )
        scanner = NQScanner(config=config)
        
        scaled_vol, _ = scanner._get_scaled_thresholds()
        
        # 5m is reference, so: 100 * 1.0 = 100
        assert scaled_vol == 100, f"Expected 100, got {scaled_vol}"

    def test_mnq_15m_volume_gate_scales_up(self) -> None:
        """MNQ 15m volume gate should scale up to 300."""
        config = NQIntradayConfig(
            symbol="MNQ",
            timeframe="15m",
            min_volume=100,
        )
        scanner = NQScanner(config=config)
        
        scaled_vol, _ = scanner._get_scaled_thresholds()
        
        # 15m is 3x 5m reference, so: 100 * 3.0 = 300
        assert scaled_vol == 300, f"Expected 300, got {scaled_vol}"

    def test_volume_gate_respects_safety_floor(self) -> None:
        """Volume gate should have safety floor of 10 (not 0)."""
        config = NQIntradayConfig(
            symbol="MNQ",
            timeframe="1m",
            min_volume=10,  # Very low base
        )
        scanner = NQScanner(config=config)
        
        scaled_vol, _ = scanner._get_scaled_thresholds()
        
        # 10 * 0.2 = 2, but floor is 10
        assert scaled_vol == 10, f"Expected 10 (floor), got {scaled_vol}"

    def test_nq_volume_gate_no_hardcoded_floor(self) -> None:
        """NQ volume gate should respect config (no hardcoded floor)."""
        config = NQIntradayConfig(
            symbol="NQ",
            timeframe="5m",
            min_volume=50,  # Lower than old hardcoded floor
        )
        scanner = NQScanner(config=config)
        
        scaled_vol, _ = scanner._get_scaled_thresholds()
        
        # Should respect config, not have hardcoded 100 floor
        assert scaled_vol == 50, f"Expected 50, got {scaled_vol}"

    def test_low_volume_config_for_overnight_trading(self) -> None:
        """Config can be set for low-volume overnight sessions."""
        # Tokyo session typical volume: 30-60 per 1m bar
        # Setting min_volume=50 for 5m reference → 10 for 1m
        config = NQIntradayConfig(
            symbol="MNQ",
            timeframe="1m",
            min_volume=50,  # Lower for 24h trading
        )
        scanner = NQScanner(config=config)
        
        scaled_vol, _ = scanner._get_scaled_thresholds()
        
        # 50 * 0.2 = 10
        assert scaled_vol == 10, f"Expected 10, got {scaled_vol}"
        
        # Verify a typical Tokyo bar (volume=45) would pass
        assert 45 > scaled_vol, "Tokyo session bars (vol=45) should pass gate"











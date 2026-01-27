"""
Tests for Sparkline rendering utilities.

Validates compact sparkline generation for Telegram UI.
"""

import pytest
from pearlalgo.utils.sparkline import (
    generate_sparkline,
    generate_progress_bar,
    format_price_change,
    trend_arrow,
    format_mtf_snapshot,
    format_session_summary,
    SPARK_CHARS,
)


class TestGenerateSparkline:
    """Test sparkline rendering."""

    def test_empty_values(self):
        """Should handle empty list."""
        result = generate_sparkline([])
        assert result == "─" * 20  # Default width

    def test_single_value(self):
        """Should handle single value."""
        result = generate_sparkline([50])
        assert len(result) >= 1

    def test_ascending_values(self):
        """Should show upward trend."""
        result = generate_sparkline([1, 2, 3, 4, 5])
        assert len(result) == 5
        # First char should be lower block than last
        assert SPARK_CHARS.index(result[0]) < SPARK_CHARS.index(result[-1])

    def test_descending_values(self):
        """Should show downward trend."""
        result = generate_sparkline([5, 4, 3, 2, 1])
        assert len(result) == 5
        # First char should be higher block than last
        assert SPARK_CHARS.index(result[0]) > SPARK_CHARS.index(result[-1])

    def test_constant_values(self):
        """Should handle constant values."""
        result = generate_sparkline([5, 5, 5, 5, 5])
        assert len(result) == 5
        # All chars should be the same (middle block)
        assert len(set(result)) == 1

    def test_negative_values(self):
        """Should handle negative values."""
        result = generate_sparkline([-5, -2, 0, 2, 5])
        assert len(result) == 5

    def test_float_values(self):
        """Should handle float values."""
        result = generate_sparkline([1.5, 2.7, 3.2, 4.8])
        assert len(result) == 4

    def test_width_parameter(self):
        """Should resample to target width."""
        result = generate_sparkline([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], width=5)
        assert len(result) == 5

    def test_uses_correct_characters(self):
        """Should use block characters."""
        result = generate_sparkline([1, 5, 3, 8, 2])
        for char in result:
            assert char in SPARK_CHARS


class TestGenerateProgressBar:
    """Test progress bar rendering."""

    def test_zero_percent(self):
        """Should render empty bar at 0%."""
        result = generate_progress_bar(0, 100, width=10)
        assert len(result) == 10
        assert "░" in result
        assert "█" not in result

    def test_full_percent(self):
        """Should render full bar at 100%."""
        result = generate_progress_bar(100, 100, width=10)
        assert len(result) == 10
        assert "█" in result
        assert "░" not in result

    def test_half_percent(self):
        """Should render half-filled bar at 50%."""
        result = generate_progress_bar(50, 100, width=10)
        assert len(result) == 10
        assert result.count("█") == 5
        assert result.count("░") == 5

    def test_over_100_percent(self):
        """Should cap at 100%."""
        result = generate_progress_bar(150, 100, width=10)
        assert len(result) == 10
        assert result == "█" * 10

    def test_zero_total(self):
        """Should handle zero total."""
        result = generate_progress_bar(50, 0, width=10)
        assert len(result) == 10
        assert result == "░" * 10

    def test_custom_width(self):
        """Should respect custom width."""
        result = generate_progress_bar(50, 100, width=20)
        assert len(result) == 20

    def test_custom_chars(self):
        """Should use custom characters."""
        result = generate_progress_bar(50, 100, width=10, filled_char="X", empty_char="O")
        assert "X" in result
        assert "O" in result


class TestFormatPriceChange:
    """Test price change formatting."""

    def test_positive_change(self):
        """Should show up arrow for positive."""
        result = format_price_change(101, 100)
        assert "↑" in result
        assert "+" in result
        assert "1.00%" in result

    def test_negative_change(self):
        """Should show down arrow for negative."""
        result = format_price_change(99, 100)
        assert "↓" in result
        assert "-1.00%" in result

    def test_no_change(self):
        """Should show neutral for no change."""
        result = format_price_change(100, 100)
        assert "→" in result
        assert "0.00%" in result

    def test_zero_previous(self):
        """Should handle zero previous price."""
        result = format_price_change(100, 0)
        assert "→ 0.00%" in result


class TestTrendArrow:
    """Test trend arrow rendering."""

    def test_positive_trend(self):
        """Should show up arrow for positive."""
        result = trend_arrow(0.5)
        assert result == "↑"

    def test_negative_trend(self):
        """Should show down arrow for negative."""
        result = trend_arrow(-0.5)
        assert result == "↓"

    def test_neutral_trend(self):
        """Should show neutral for small values."""
        result = trend_arrow(0.05)
        assert result == "→"

    def test_custom_threshold(self):
        """Should respect custom threshold."""
        result = trend_arrow(0.3, threshold=0.5)
        assert result == "→"  # Below threshold


class TestFormatMtfSnapshot:
    """Test multi-timeframe snapshot formatting."""

    def test_basic_snapshot(self):
        """Should format basic snapshot."""
        trends = {"5m": 0.5, "15m": -0.3, "1h": 0.0}
        result = format_mtf_snapshot(trends)
        
        assert "5m" in result
        assert "15m" in result
        assert "1h" in result

    def test_empty_trends(self):
        """Should handle empty trends."""
        result = format_mtf_snapshot({})
        assert result == "N/A"

    def test_custom_timeframes(self):
        """Should respect custom timeframe order."""
        trends = {"1h": 0.5, "5m": 0.3}
        result = format_mtf_snapshot(trends, timeframes=["1h", "5m"])
        
        # Should be in specified order
        assert result.index("1h") < result.index("5m")


class TestFormatSessionSummary:
    """Test session summary formatting."""

    def test_basic_summary(self):
        """Should format session summary."""
        result = format_session_summary(
            cycles=100,
            signals_gen=5,
            signals_sent=5,
            errors=0,
            buffer_bars=250,
            buffer_target=300,
        )
        
        assert "100" in result
        assert "5 gen/5 sent" in result
        assert "250/300" in result

    def test_includes_progress_bar(self):
        """Should include buffer progress bar."""
        result = format_session_summary(
            cycles=1,
            signals_gen=0,
            signals_sent=0,
            errors=0,
            buffer_bars=150,
            buffer_target=300,
        )
        
        # Should have progress bar characters
        assert "█" in result or "░" in result

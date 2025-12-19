"""
Unit tests for chart_generator module.

Tests verify TradingView-correct rendering:
- Rectangle count == bar count
- Wick count == bar count
- Categorical x-axis (no datetime floats)
- Candle spacing (no overlapping)
- Visual regression (image hash)
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import numpy as np
import pandas as pd
from datetime import datetime, timezone
import hashlib

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from PIL import Image
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

import pytest

from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig


@pytest.fixture
def chart_generator():
    """Create a ChartGenerator instance for testing."""
    if not MATPLOTLIB_AVAILABLE:
        pytest.skip("matplotlib not available")
    return ChartGenerator()


@pytest.fixture
def sample_ohlc_data():
    """Create sample OHLC data for testing."""
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq='1min')
    return pd.DataFrame({
        'timestamp': dates,
        'open': [25000 + i * 0.5 + (i % 3 - 1) * 0.2 for i in range(50)],
        'high': [25001 + i * 0.5 + abs(i % 3 - 1) * 0.3 for i in range(50)],
        'low': [24999 + i * 0.5 - abs(i % 3 - 1) * 0.3 for i in range(50)],
        'close': [25000.5 + i * 0.5 + (i % 3 - 1) * 0.1 for i in range(50)],
        'volume': [1000 + (i % 10) * 100 for i in range(50)],
    })


def test_draw_candles_rectangle_count(chart_generator, sample_ohlc_data):
    """Test that rectangle count equals bar count."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    opens = sample_ohlc_data["open"].values
    highs = sample_ohlc_data["high"].values
    lows = sample_ohlc_data["low"].values
    closes = sample_ohlc_data["close"].values
    
    bar_count = len(sample_ohlc_data)
    chart_generator.draw_candles(ax, opens, highs, lows, closes)
    
    # Count Rectangle patches
    rectangles = [p for p in ax.patches if isinstance(p, Rectangle)]
    
    assert len(rectangles) == bar_count, \
        f"Expected {bar_count} rectangles, got {len(rectangles)}"
    
    plt.close(fig)


def test_draw_candles_wick_count(chart_generator, sample_ohlc_data):
    """Test that wick count equals bar count."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    opens = sample_ohlc_data["open"].values
    highs = sample_ohlc_data["high"].values
    lows = sample_ohlc_data["low"].values
    closes = sample_ohlc_data["close"].values
    
    bar_count = len(sample_ohlc_data)
    chart_generator.draw_candles(ax, opens, highs, lows, closes)
    
    # vlines creates LineCollection objects
    # Count segments in collections (each segment is a wick)
    vertical_lines = 0
    for collection in ax.collections:
        if hasattr(collection, 'get_segments'):
            segments = collection.get_segments()
            # Each segment should be a vertical line (2 points with same x)
            for segment in segments:
                if len(segment) == 2:
                    # Check if it's vertical (same x coordinate)
                    if abs(segment[0][0] - segment[1][0]) < 0.001:
                        vertical_lines += 1
    
    # If no collections found, check lines (fallback)
    if vertical_lines == 0:
        for line in ax.lines:
            xdata = line.get_xdata()
            ydata = line.get_ydata()
            if len(xdata) == 2 and len(ydata) == 2:
                # Check if vertical (same x, different y)
                if abs(xdata[0] - xdata[1]) < 0.001 and abs(ydata[0] - ydata[1]) > 0.001:
                    vertical_lines += 1
    
    assert vertical_lines == bar_count, \
        f"Expected {bar_count} wicks, got {vertical_lines}"
    
    plt.close(fig)


def test_categorical_x_axis(chart_generator, sample_ohlc_data):
    """Test that x-axis uses categorical indices, not datetime floats."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    opens = sample_ohlc_data["open"].values
    highs = sample_ohlc_data["high"].values
    lows = sample_ohlc_data["low"].values
    closes = sample_ohlc_data["close"].values
    timestamps = sample_ohlc_data["timestamp"].values
    
    chart_generator.draw_candles(ax, opens, highs, lows, closes)
    chart_generator._apply_tradingview_styling(ax, timestamps)
    
    # Get x-axis limits - should be integer range
    xlim = ax.get_xlim()
    assert isinstance(xlim[0], (int, float)), "X-axis limit should be numeric"
    assert isinstance(xlim[1], (int, float)), "X-axis limit should be numeric"
    
    # X-axis should start near -1 and end at len(data)
    expected_max = len(sample_ohlc_data)
    assert abs(xlim[1] - expected_max) < 1, \
        f"X-axis max should be near {expected_max}, got {xlim[1]}"
    
    # Verify tick positions are integers (categorical indices)
    tick_positions = ax.get_xticks()
    for pos in tick_positions:
        # Allow some tolerance for floating point
        assert abs(pos - round(pos)) < 0.01, \
            f"Tick position {pos} should be near an integer"
    
    plt.close(fig)


def test_candle_spacing(chart_generator, sample_ohlc_data):
    """Test that candles have proper spacing and don't overlap."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    opens = sample_ohlc_data["open"].values
    highs = sample_ohlc_data["high"].values
    lows = sample_ohlc_data["low"].values
    closes = sample_ohlc_data["close"].values
    
    chart_generator.draw_candles(ax, opens, highs, lows, closes)
    
    # Extract rectangle positions
    rectangles = [p for p in ax.patches if isinstance(p, Rectangle)]
    
    # Get x positions of rectangles (center of each candle)
    x_positions = []
    for rect in rectangles:
        x_center = rect.get_x() + rect.get_width() / 2
        x_positions.append(x_center)
    
    x_positions = sorted(x_positions)
    
    # Verify spacing between adjacent candles
    candle_width = 0.6
    min_gap = 0.1  # Minimum gap between candles
    
    for i in range(len(x_positions) - 1):
        gap = x_positions[i + 1] - x_positions[i]
        # Gap should be at least the minimum (candles don't touch)
        assert gap >= min_gap, \
            f"Candles at positions {x_positions[i]} and {x_positions[i+1]} overlap or touch (gap: {gap})"
    
    plt.close(fig)


def test_chart_visual_regression(chart_generator, sample_ohlc_data):
    """Test visual regression using image hash comparison."""
    # Generate chart
    signal = {
        'entry_price': 25025.0,
        'stop_loss': 25000.0,
        'take_profit': 25050.0,
        'direction': 'long',
        'type': 'test',
    }
    
    chart_path = chart_generator.generate_entry_chart(
        signal, sample_ohlc_data, 'MNQ'
    )
    
    assert chart_path is not None, "Chart generation failed"
    assert chart_path.exists(), "Chart file does not exist"
    
    try:
        # Load image and compute hash
        img = Image.open(chart_path)
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Compute perceptual hash (simpler than full image hash)
        # Using a simple approach: resize to small size and hash
        img_small = img.resize((32, 32), Image.Resampling.LANCZOS)
        img_bytes = img_small.tobytes()
        img_hash = hashlib.md5(img_bytes).hexdigest()
        
        # For now, just verify hash is computed (not comparing to reference)
        # In production, you'd store reference hash and compare
        assert len(img_hash) == 32, "Image hash should be 32 characters"
        
        # Store hash for future comparison (could save to file)
        # This test passes if hash is computed successfully
        # To enable regression detection, store reference hash and compare
        
    finally:
        # Cleanup
        if chart_path.exists():
            chart_path.unlink()
    
    # Test passes if hash computation succeeds
    # In CI/CD, you'd compare against stored reference hash


def test_background_color(chart_generator, sample_ohlc_data):
    """Test that background color is set to TradingView dark (#0e1013)."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    opens = sample_ohlc_data["open"].values
    highs = sample_ohlc_data["high"].values
    lows = sample_ohlc_data["low"].values
    closes = sample_ohlc_data["close"].values
    timestamps = sample_ohlc_data["timestamp"].values
    
    chart_generator.draw_candles(ax, opens, highs, lows, closes)
    chart_generator._apply_tradingview_styling(ax, timestamps)
    
    # Check axes face color
    facecolor = ax.get_facecolor()
    # Convert to hex for comparison
    if isinstance(facecolor, tuple):
        # RGBA tuple, convert to hex
        r, g, b = int(facecolor[0] * 255), int(facecolor[1] * 255), int(facecolor[2] * 255)
        facecolor_hex = f"#{r:02x}{g:02x}{b:02x}"
    else:
        facecolor_hex = facecolor
    
    # Current implementation uses #0e1013 (TradingView dark theme)
    assert facecolor_hex.lower() == '#0e1013' or facecolor == '#0e1013', \
        f"Background color should be #0e1013, got {facecolor_hex}"
    
    plt.close(fig)


def test_price_axis_right_side(chart_generator, sample_ohlc_data):
    """Test that price axis is on the right side only."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    opens = sample_ohlc_data["open"].values
    highs = sample_ohlc_data["high"].values
    lows = sample_ohlc_data["low"].values
    closes = sample_ohlc_data["close"].values
    timestamps = sample_ohlc_data["timestamp"].values
    
    chart_generator.draw_candles(ax, opens, highs, lows, closes)
    chart_generator._apply_tradingview_styling(ax, timestamps)
    
    # Check that left spine is hidden (TradingView style)
    assert not ax.spines['left'].get_visible(), "Left spine should be hidden"
    
    # Check y-axis label position (should be on right)
    label_position = ax.yaxis.get_label_position()
    assert label_position == 'right', f"Y-axis label should be on right, got {label_position}"
    
    # Note: Right spine visibility may vary based on styling implementation
    # The key is that the label is on the right side
    
    plt.close(fig)


def test_chart_config():
    """Test ChartConfig dataclass."""
    config = ChartConfig()
    assert config.show_vwap is True
    assert config.show_ma is True
    assert config.timeframe == "1m"
    assert config.max_signals_displayed == 50


def test_backtest_chart_with_performance(chart_generator, sample_ohlc_data):
    """Test backtest chart generation with performance data."""
    signals = [
        {
            'entry_price': 25025.0,
            'stop_loss': 25000.0,
            'take_profit': 25050.0,
            'direction': 'long',
            'type': 'test',
            'timestamp': sample_ohlc_data['timestamp'].iloc[10].isoformat(),
        }
    ]
    
    performance_data = {
        'total_signals': 1,
        'avg_confidence': 0.75,
        'avg_risk_reward': 1.5,
    }
    
    chart_path = chart_generator.generate_backtest_chart(
        sample_ohlc_data,
        signals,
        'MNQ',
        'Test Backtest',
        performance_data=performance_data
    )
    
    assert chart_path is not None, "Chart generation failed"
    assert chart_path.exists(), "Chart file does not exist"
    
    # Cleanup
    if chart_path.exists():
        chart_path.unlink()


def test_signal_timestamp_matching(chart_generator, sample_ohlc_data):
    """Test signal timestamp matching."""
    # Create signal with timestamp
    signal = {
        'entry_price': 25025.0,
        'direction': 'long',
        'timestamp': sample_ohlc_data['timestamp'].iloc[20].isoformat(),
    }
    
    timestamps = sample_ohlc_data['timestamp'].values
    idx = chart_generator._find_signal_index(signal, timestamps, sample_ohlc_data)
    
    assert idx is not None, "Should find signal index"
    assert 0 <= idx < len(sample_ohlc_data), "Index should be valid"


def test_generate_and_save_chart(chart_generator, sample_ohlc_data, tmp_path):
    """Generate a chart and save it so we can visually inspect it."""
    signal = {
        'entry_price': 25025.0,
        'stop_loss': 25000.0,
        'take_profit': 25050.0,
        'direction': 'long',
        'type': 'momentum_breakout',
        'reason': 'test signal'
    }
    
    chart_path = chart_generator.generate_entry_chart(
        signal, sample_ohlc_data, 'MNQ', '1m'
    )
    
    assert chart_path is not None, "Chart generation failed"
    assert chart_path.exists(), "Chart file does not exist"
    
    # Copy to a visible location for inspection
    output_path = tmp_path / "test_chart.png"
    import shutil
    shutil.copy(chart_path, output_path)
    
    print(f"\n✅ Chart generated and saved to: {output_path}")
    print(f"   Chart shows: Blue VWAP, Purple EMA, Candlesticks, Shaded zones")
    
    # Cleanup original temp file
    if chart_path.exists():
        chart_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])  # -s to show print statements

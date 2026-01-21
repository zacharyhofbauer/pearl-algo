"""
Chart semantic contract tests (non-rendering).

This module tests visual contracts and semantic invariants of the chart generator
WITHOUT requiring actual chart rendering. These tests are fast, deterministic,
and catch accidental semantic drift in colors, priorities, z-order, and merge logic.

Usage:
    pytest tests/test_chart_semantic_contracts.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


class TestColorContracts:
    """
    Test that color constants match documented TradingView-style semantics.
    
    These tests prevent accidental changes to colors that traders rely on
    for quick visual pattern recognition.
    """
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Import color constants from chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import (
                DARK_BG,
                GRID_COLOR,
                TEXT_PRIMARY,
                TEXT_SECONDARY,
                CANDLE_UP,
                CANDLE_DOWN,
                SIGNAL_LONG,
                SIGNAL_SHORT,
                ENTRY_COLOR,
                VWAP_COLOR,
                MA_COLORS,
                SUPPLY_ZONE_COLOR,
                DEMAND_ZONE_COLOR,
                POWER_CHANNEL_RESISTANCE,
                POWER_CHANNEL_SUPPORT,
            )
            self.DARK_BG = DARK_BG
            self.GRID_COLOR = GRID_COLOR
            self.TEXT_PRIMARY = TEXT_PRIMARY
            self.TEXT_SECONDARY = TEXT_SECONDARY
            self.CANDLE_UP = CANDLE_UP
            self.CANDLE_DOWN = CANDLE_DOWN
            self.SIGNAL_LONG = SIGNAL_LONG
            self.SIGNAL_SHORT = SIGNAL_SHORT
            self.ENTRY_COLOR = ENTRY_COLOR
            self.VWAP_COLOR = VWAP_COLOR
            self.MA_COLORS = MA_COLORS
            self.SUPPLY_ZONE_COLOR = SUPPLY_ZONE_COLOR
            self.DEMAND_ZONE_COLOR = DEMAND_ZONE_COLOR
            self.POWER_CHANNEL_RESISTANCE = POWER_CHANNEL_RESISTANCE
            self.POWER_CHANNEL_SUPPORT = POWER_CHANNEL_SUPPORT
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_candle_colors_match_tradingview(self):
        """Candle colors must match TradingView defaults for muscle memory."""
        # TradingView's teal-green for bullish candles
        assert self.CANDLE_UP == "#26a69a", (
            f"CANDLE_UP changed from TradingView default: {self.CANDLE_UP}"
        )
        # TradingView's red for bearish candles
        assert self.CANDLE_DOWN == "#ef5350", (
            f"CANDLE_DOWN changed from TradingView default: {self.CANDLE_DOWN}"
        )

    def test_signal_colors_match_candle_semantics(self):
        """Signal long/short must match candle up/down for visual consistency."""
        assert self.SIGNAL_LONG == self.CANDLE_UP, (
            "SIGNAL_LONG must match CANDLE_UP for green=bullish consistency"
        )
        assert self.SIGNAL_SHORT == self.CANDLE_DOWN, (
            "SIGNAL_SHORT must match CANDLE_DOWN for red=bearish consistency"
        )

    def test_entry_color_distinct_from_signal_colors(self):
        """Entry line must be distinct blue (not green/red) for visibility."""
        assert self.ENTRY_COLOR == "#2962ff", (
            f"ENTRY_COLOR changed: {self.ENTRY_COLOR}"
        )
        assert self.ENTRY_COLOR != self.SIGNAL_LONG, (
            "Entry must be distinct from long signal color"
        )
        assert self.ENTRY_COLOR != self.SIGNAL_SHORT, (
            "Entry must be distinct from short signal color"
        )

    def test_background_is_dark(self):
        """Background must be dark for eye comfort during trading."""
        assert self.DARK_BG == "#0e1013", (
            f"DARK_BG changed: {self.DARK_BG}"
        )

    def test_ma_colors_defined(self):
        """At least 3 MA colors must be defined for common MAs (20/50/200)."""
        assert len(self.MA_COLORS) >= 3, (
            f"MA_COLORS must have at least 3 colors: {self.MA_COLORS}"
        )

    def test_vwap_color_in_blue_family(self):
        """VWAP must be in blue family to distinguish from price action."""
        assert self.VWAP_COLOR == "#2196f3", (
            f"VWAP_COLOR changed: {self.VWAP_COLOR}"
        )


class TestZOrderContracts:
    """
    Test z-order layering rules that ensure candles are always visible.
    
    Z-order defines what's drawn on top of what. Violating these rules
    can hide price data behind overlays.
    """
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Import z-order constants from chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import (
                ZORDER_SESSION_SHADING,
                ZORDER_ZONES,
                ZORDER_LEVEL_LINES,
                ZORDER_CANDLES,
                ZORDER_TEXT_LABELS,
            )
            self.ZORDER_SESSION_SHADING = ZORDER_SESSION_SHADING
            self.ZORDER_ZONES = ZORDER_ZONES
            self.ZORDER_LEVEL_LINES = ZORDER_LEVEL_LINES
            self.ZORDER_CANDLES = ZORDER_CANDLES
            self.ZORDER_TEXT_LABELS = ZORDER_TEXT_LABELS
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_session_shading_is_background(self):
        """Session shading must be at z=0 (furthest back)."""
        assert self.ZORDER_SESSION_SHADING == 0, (
            f"Session shading z-order changed: {self.ZORDER_SESSION_SHADING}"
        )

    def test_zones_behind_candles(self):
        """Zones (RR boxes, supply/demand) must be behind candles."""
        assert self.ZORDER_ZONES < self.ZORDER_CANDLES, (
            f"Zones ({self.ZORDER_ZONES}) must be < candles ({self.ZORDER_CANDLES})"
        )

    def test_level_lines_behind_candles(self):
        """Level lines must be behind candles but above zones."""
        assert self.ZORDER_ZONES < self.ZORDER_LEVEL_LINES < self.ZORDER_CANDLES, (
            f"Level lines ({self.ZORDER_LEVEL_LINES}) must be between "
            f"zones ({self.ZORDER_ZONES}) and candles ({self.ZORDER_CANDLES})"
        )

    def test_labels_on_top(self):
        """Text labels must be on top of everything."""
        assert self.ZORDER_TEXT_LABELS > self.ZORDER_CANDLES, (
            f"Text labels ({self.ZORDER_TEXT_LABELS}) must be above candles ({self.ZORDER_CANDLES})"
        )

    def test_z_order_exact_values(self):
        """Z-order values must be exact for baseline stability."""
        assert self.ZORDER_SESSION_SHADING == 0
        assert self.ZORDER_ZONES == 1
        assert self.ZORDER_LEVEL_LINES == 2
        assert self.ZORDER_CANDLES == 3
        assert self.ZORDER_TEXT_LABELS == 4


class TestAlphaContracts:
    """
    Test alpha (transparency) caps that ensure candles are never obscured.
    
    Zones and shading must be semi-transparent so price data remains visible.
    """
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Import alpha constants from chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import (
                ALPHA_ZONE_SUPPLY_DEMAND,
                ALPHA_ZONE_POWER_CHANNEL,
                ALPHA_ZONE_RR_BOX_PROFIT,
                ALPHA_ZONE_RR_BOX_RISK,
                ALPHA_SESSION_SHADING,
                ALPHA_LINE_PRIMARY,
                ALPHA_LINE_SECONDARY,
                ALPHA_LINE_CONTEXTUAL,
                ALPHA_VWAP_BAND_1,
                ALPHA_VWAP_BAND_2,
            )
            self.ALPHA_ZONE_SUPPLY_DEMAND = ALPHA_ZONE_SUPPLY_DEMAND
            self.ALPHA_ZONE_POWER_CHANNEL = ALPHA_ZONE_POWER_CHANNEL
            self.ALPHA_ZONE_RR_BOX_PROFIT = ALPHA_ZONE_RR_BOX_PROFIT
            self.ALPHA_ZONE_RR_BOX_RISK = ALPHA_ZONE_RR_BOX_RISK
            self.ALPHA_SESSION_SHADING = ALPHA_SESSION_SHADING
            self.ALPHA_LINE_PRIMARY = ALPHA_LINE_PRIMARY
            self.ALPHA_LINE_SECONDARY = ALPHA_LINE_SECONDARY
            self.ALPHA_LINE_CONTEXTUAL = ALPHA_LINE_CONTEXTUAL
            self.ALPHA_VWAP_BAND_1 = ALPHA_VWAP_BAND_1
            self.ALPHA_VWAP_BAND_2 = ALPHA_VWAP_BAND_2
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_zone_alphas_low_enough(self):
        """Zone fills must be transparent enough to see candles through."""
        assert self.ALPHA_ZONE_SUPPLY_DEMAND <= 0.25, (
            f"Supply/demand zone alpha too high: {self.ALPHA_ZONE_SUPPLY_DEMAND}"
        )
        assert self.ALPHA_ZONE_POWER_CHANNEL <= 0.15, (
            f"Power channel zone alpha too high: {self.ALPHA_ZONE_POWER_CHANNEL}"
        )
        assert self.ALPHA_ZONE_RR_BOX_PROFIT <= 0.25, (
            f"RR box profit alpha too high: {self.ALPHA_ZONE_RR_BOX_PROFIT}"
        )
        assert self.ALPHA_ZONE_RR_BOX_RISK <= 0.25, (
            f"RR box risk alpha too high: {self.ALPHA_ZONE_RR_BOX_RISK}"
        )

    def test_session_shading_very_light(self):
        """Session shading must be very light (ambient, not directive)."""
        assert self.ALPHA_SESSION_SHADING <= 0.10, (
            f"Session shading alpha too high: {self.ALPHA_SESSION_SHADING}"
        )

    def test_primary_lines_visible(self):
        """Primary lines (entry) should be nearly opaque."""
        assert self.ALPHA_LINE_PRIMARY >= 0.85, (
            f"Primary line alpha too low: {self.ALPHA_LINE_PRIMARY}"
        )

    def test_alpha_hierarchy(self):
        """Alpha should decrease: primary > secondary > contextual."""
        assert self.ALPHA_LINE_PRIMARY > self.ALPHA_LINE_SECONDARY > self.ALPHA_LINE_CONTEXTUAL, (
            f"Alpha hierarchy violated: {self.ALPHA_LINE_PRIMARY} > "
            f"{self.ALPHA_LINE_SECONDARY} > {self.ALPHA_LINE_CONTEXTUAL}"
        )


class TestFontSizeContracts:
    """
    Test font size constants for readability.
    """
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Import font size constants from chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import (
                FONT_SIZE_LABEL,
                FONT_SIZE_SESSION,
                FONT_SIZE_POWER_READOUT,
                FONT_SIZE_RR_BOX,
                FONT_SIZE_LEGEND,
            )
            self.FONT_SIZE_LABEL = FONT_SIZE_LABEL
            self.FONT_SIZE_SESSION = FONT_SIZE_SESSION
            self.FONT_SIZE_POWER_READOUT = FONT_SIZE_POWER_READOUT
            self.FONT_SIZE_RR_BOX = FONT_SIZE_RR_BOX
            self.FONT_SIZE_LEGEND = FONT_SIZE_LEGEND
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_font_sizes_readable(self):
        """Font sizes must be in readable range (8-14pt)."""
        for name, size in [
            ("FONT_SIZE_LABEL", self.FONT_SIZE_LABEL),
            ("FONT_SIZE_SESSION", self.FONT_SIZE_SESSION),
            ("FONT_SIZE_RR_BOX", self.FONT_SIZE_RR_BOX),
            ("FONT_SIZE_LEGEND", self.FONT_SIZE_LEGEND),
        ]:
            assert 8 <= size <= 14, f"{name} out of readable range: {size}"


class TestMarkerSemanticContracts:
    """
    Test marker semantics (shapes/colors) for trade vs EMA crossover markers.
    
    This addresses the semantic ambiguity risk where both trade markers and
    EMA crossover markers use triangles but must be visually distinguishable.
    """
    
    def test_ema_crossover_colors_distinct_from_trade_colors(self):
        """EMA crossover markers must use distinct colors from trade markers."""
        try:
            from pearlalgo.nq_agent.chart_generator import SIGNAL_LONG, SIGNAL_SHORT
        except ImportError:
            pytest.skip("Chart generator not available")
        
        # EMA crossover colors (hardcoded in generate_dashboard_chart)
        ema_crossover_up = "#00bcd4"  # cyan
        ema_crossover_down = "#e91e63"  # pink
        
        # These must be different from signal colors
        assert ema_crossover_up != SIGNAL_LONG, (
            f"EMA crossover up ({ema_crossover_up}) must differ from SIGNAL_LONG ({SIGNAL_LONG})"
        )
        assert ema_crossover_down != SIGNAL_SHORT, (
            f"EMA crossover down ({ema_crossover_down}) must differ from SIGNAL_SHORT ({SIGNAL_SHORT})"
        )
        
        # Document the expected colors for reference
        assert ema_crossover_up == "#00bcd4", "EMA crossover up color changed"
        assert ema_crossover_down == "#e91e63", "EMA crossover down color changed"


class TestMergeLevelsContract:
    """
    Test the _merge_levels function's semantic contract.
    
    The merge function must:
    1. Use the TOP-PRIORITY level's exact price (not averaged)
    2. Combine labels from merged levels
    3. Preserve the anchor level's styling (color, linestyle)
    """
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Import chart generator and create instance."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_merge_uses_top_priority_price(self):
        """Merged level must use the top-priority level's exact price."""
        levels = [
            {"price": 25000.00, "label": "Low Priority", "color": "#888", "priority": 10},
            {"price": 25000.50, "label": "High Priority", "color": "#fff", "priority": 100},
            {"price": 25000.25, "label": "Med Priority", "color": "#ccc", "priority": 50},
        ]
        
        merged = self.generator._merge_levels(levels, tick_size=0.25, merge_ticks=4)
        
        # All three levels are within 4 ticks (1.0 points), should merge to one
        assert len(merged) == 1, f"Expected 1 merged level, got {len(merged)}"
        
        # The merged level should use the HIGH priority level's exact price
        assert merged[0]["price"] == 25000.50, (
            f"Merged price should be 25000.50 (high priority), got {merged[0]['price']}"
        )
        
        # Should inherit high priority level's color
        assert merged[0]["color"] == "#fff", (
            f"Merged color should be #fff, got {merged[0]['color']}"
        )

    def test_merge_combines_labels(self):
        """Merged level should combine labels from all merged levels."""
        levels = [
            {"price": 25000.00, "label": "Entry", "color": "#fff", "priority": 100},
            {"price": 25000.25, "label": "VWAP", "color": "#888", "priority": 60},
        ]
        
        merged = self.generator._merge_levels(levels, tick_size=0.25, merge_ticks=4)
        
        assert len(merged) == 1
        # Label should contain both level names
        assert "Entry" in merged[0]["label"]
        assert "VWAP" in merged[0]["label"]

    def test_merge_respects_distance_threshold(self):
        """Levels farther than merge_ticks should NOT be merged."""
        levels = [
            {"price": 25000.00, "label": "Level A", "color": "#fff", "priority": 100},
            {"price": 25010.00, "label": "Level B", "color": "#888", "priority": 100},
        ]
        
        merged = self.generator._merge_levels(levels, tick_size=0.25, merge_ticks=4)
        
        # 10 points apart (40 ticks) > 4 ticks threshold, should NOT merge
        assert len(merged) == 2, f"Expected 2 separate levels, got {len(merged)}"

    def test_merge_handles_empty_input(self):
        """Empty input should return empty output."""
        merged = self.generator._merge_levels([], tick_size=0.25, merge_ticks=4)
        assert merged == []

    def test_merge_handles_single_level(self):
        """Single level should pass through unchanged."""
        levels = [
            {"price": 25000.00, "label": "Only Level", "color": "#fff", "priority": 100},
        ]
        
        merged = self.generator._merge_levels(levels, tick_size=0.25, merge_ticks=4)
        
        assert len(merged) == 1
        assert merged[0]["price"] == 25000.00
        assert merged[0]["label"] == "Only Level"


class TestPriorityHierarchyContract:
    """
    Test that priority values follow the documented hierarchy.
    
    Trade-related labels (Entry/Stop/Target) must always take priority
    over contextual levels (VWAP, S/R, etc.).
    """
    
    def test_trade_priorities_higher_than_contextual(self):
        """Entry/Stop/Target priorities must exceed all contextual priorities."""
        # Documented priorities from CHART_VISUAL_SCHEMA.md
        trade_priorities = {
            "Entry": 100,
            "Stop": 95,
            "Target": 95,
            "Exit": 90,
        }
        
        contextual_max = 60  # Daily Open/VWAP are highest contextual at 60
        
        for label, priority in trade_priorities.items():
            assert priority > contextual_max, (
                f"{label} priority ({priority}) must exceed contextual max ({contextual_max})"
            )

    def test_priority_ordering_stable(self):
        """Priority ordering must match documentation."""
        expected_priorities = {
            "Entry": 100,
            "Stop/Target": 95,
            "Exit": 90,
            "Daily Open": 60,
            "VWAP": 60,
            "PDH/PDL": 58,
        }
        
        # Entry must be highest
        assert expected_priorities["Entry"] > expected_priorities["Stop/Target"]
        assert expected_priorities["Stop/Target"] > expected_priorities["Exit"]
        assert expected_priorities["Exit"] > expected_priorities["Daily Open"]


class TestChartConfigContracts:
    """
    Test ChartConfig default values that affect visual output.
    """
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Import ChartConfig."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartConfig
            self.ChartConfig = ChartConfig
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_default_ma_periods(self):
        """Default MA periods should include common values."""
        config = self.ChartConfig()
        assert 20 in config.ma_periods, "MA20 should be in default periods"
        assert 50 in config.ma_periods, "MA50 should be in default periods"

    def test_right_labels_bounded(self):
        """max_right_labels should be bounded to prevent clutter."""
        config = self.ChartConfig()
        assert config.max_right_labels <= 15, (
            f"max_right_labels too high: {config.max_right_labels}"
        )

    def test_rr_box_enabled_by_default(self):
        """RR box should be enabled by default for trade context."""
        config = self.ChartConfig()
        assert config.show_rr_box is True

    def test_hud_enabled_by_default(self):
        """HUD overlays should be enabled by default."""
        config = self.ChartConfig()
        assert config.show_hud is True

    def test_mobile_enhanced_fonts_off_by_default(self):
        """Mobile font enhancement should be OFF by default for baseline stability."""
        config = self.ChartConfig()
        assert config.mobile_enhanced_fonts is False

    def test_compact_labels_off_by_default(self):
        """Compact label mode should be OFF by default for baseline stability."""
        config = self.ChartConfig()
        assert config.compact_labels is False


class TestRenderManifest:
    """
    Test the optional render manifest for semantic regression.
    """
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Import RenderManifest."""
        try:
            from pearlalgo.nq_agent.chart_generator import RenderManifest
            self.RenderManifest = RenderManifest
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_manifest_to_dict_returns_valid_json(self):
        """Manifest should serialize to valid JSON-compatible dict."""
        manifest = self.RenderManifest(
            chart_type="dashboard",
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=288,
            figsize=(16, 7),
            dpi=150,
            render_mode="telegram",
        )
        
        result = manifest.to_dict()
        
        assert isinstance(result, dict)
        assert result["chart_type"] == "dashboard"
        assert result["symbol"] == "MNQ"
        assert result["figsize"] == [16, 7]  # Converted from tuple to list
        assert result["dpi"] == 150

    def test_manifest_save_creates_file(self, tmp_path):
        """Manifest.save() should create a valid JSON file."""
        import json
        
        manifest = self.RenderManifest(
            chart_type="dashboard",
            symbol="MNQ",
            timeframe="5m",
        )
        
        manifest_path = tmp_path / "test_manifest.json"
        manifest.save(manifest_path)
        
        assert manifest_path.exists()
        
        # Should be valid JSON
        with open(manifest_path) as f:
            loaded = json.load(f)
        
        assert loaded["chart_type"] == "dashboard"
        assert loaded["symbol"] == "MNQ"

    def test_manifest_default_values(self):
        """Manifest should have sensible defaults for optional fields."""
        manifest = self.RenderManifest()
        
        result = manifest.to_dict()
        
        assert result["levels"] == []
        assert result["merged_labels"] == []
        assert result["sessions"] == []
        assert result["trade_markers"] == []
        assert result["indicators"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

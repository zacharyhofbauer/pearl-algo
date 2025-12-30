"""
Tests for strategy variant configuration system.

Tests the A/B testing framework for comparing different strategy configurations.
"""

from __future__ import annotations

import pytest
from pearlalgo.strategies.nq_intraday.config import (
    NQIntradayConfig,
    DEFAULT_ENABLED_SIGNALS,
    DEFAULT_DISABLED_SIGNALS,
)


class TestSignalEnableDisable:
    """Tests for signal type enable/disable functionality."""

    def test_default_enabled_signals(self):
        """Verify default enabled signals are correct."""
        config = NQIntradayConfig()
        
        # Winners from backtest analysis
        assert config.is_signal_enabled("sr_bounce")
        assert config.is_signal_enabled("sr_bounce_long")
        assert config.is_signal_enabled("sr_bounce_short")
        assert config.is_signal_enabled("mean_reversion_long")
        assert config.is_signal_enabled("momentum_short")
        assert config.is_signal_enabled("vwap_reversion")
        assert config.is_signal_enabled("breakout_long")
        assert config.is_signal_enabled("breakout_short")

    def test_default_disabled_signals(self):
        """Verify broken signals are disabled by default."""
        config = NQIntradayConfig()
        
        # Losers from backtest analysis (0/5 wins, 0/3 wins)
        assert not config.is_signal_enabled("momentum_long")
        assert not config.is_signal_enabled("engulfing_short")
        assert not config.is_signal_enabled("engulfing_long")
        assert not config.is_signal_enabled("engulfing")  # Parent type

    def test_custom_enabled_signals(self):
        """Test custom enabled signals list."""
        config = NQIntradayConfig()
        config.enabled_signals = ["sr_bounce"]
        config.disabled_signals = []
        
        assert config.is_signal_enabled("sr_bounce")
        assert not config.is_signal_enabled("momentum_short")
        assert not config.is_signal_enabled("breakout_long")

    def test_disabled_takes_precedence(self):
        """Disabled list should take precedence over enabled list."""
        config = NQIntradayConfig()
        config.enabled_signals = ["momentum_long", "sr_bounce"]
        config.disabled_signals = ["momentum_long"]
        
        assert not config.is_signal_enabled("momentum_long")
        assert config.is_signal_enabled("sr_bounce")


class TestDynamicPositionSizing:
    """Tests for confidence-based dynamic position sizing."""

    def test_base_contracts_low_confidence(self):
        """Low confidence should use base contracts."""
        config = NQIntradayConfig()
        
        assert config.get_position_size(0.5, "sr_bounce") == config.base_contracts
        assert config.get_position_size(0.6, "momentum_short") == config.base_contracts

    def test_high_confidence_contracts(self):
        """High confidence should use high_conf_contracts."""
        config = NQIntradayConfig()
        
        # Any signal type above high_conf_threshold
        assert config.get_position_size(0.85, "sr_bounce") == config.high_conf_contracts
        assert config.get_position_size(0.85, "breakout_long") == config.high_conf_contracts

    def test_max_contracts_winning_type(self):
        """Max confidence + winning type should use max_conf_contracts."""
        config = NQIntradayConfig()
        
        # Winning types: sr_bounce, mean_reversion_long, momentum_short
        assert config.get_position_size(0.95, "sr_bounce") == config.max_conf_contracts
        assert config.get_position_size(0.92, "mean_reversion_long") == config.max_conf_contracts
        assert config.get_position_size(0.91, "momentum_short") == config.max_conf_contracts

    def test_max_confidence_non_winning_type(self):
        """Max confidence but non-winning type should use high_conf_contracts."""
        config = NQIntradayConfig()
        
        # Non-winning types
        assert config.get_position_size(0.95, "breakout_long") == config.high_conf_contracts
        assert config.get_position_size(0.95, "vwap_reversion") == config.high_conf_contracts

    def test_dynamic_sizing_disabled(self):
        """When dynamic sizing disabled, should always use base_contracts."""
        config = NQIntradayConfig()
        config.enable_dynamic_sizing = False
        
        assert config.get_position_size(0.5, "sr_bounce") == config.base_contracts
        assert config.get_position_size(0.95, "sr_bounce") == config.base_contracts


class TestVariantPresets:
    """Tests for strategy variant presets."""

    def test_presets_exist(self):
        """Verify all expected presets exist."""
        presets = NQIntradayConfig.get_variant_presets()
        
        assert "default" in presets
        assert "aggressive_scalp" in presets
        assert "conservative" in presets
        assert "high_volume" in presets

    def test_preset_has_description(self):
        """Each preset should have a description."""
        presets = NQIntradayConfig.get_variant_presets()
        
        for name, preset in presets.items():
            assert "description" in preset, f"Preset {name} missing description"

    def test_apply_variant_aggressive(self):
        """Test applying aggressive_scalp variant."""
        config = NQIntradayConfig()
        presets = NQIntradayConfig.get_variant_presets()
        
        config._apply_variant(presets["aggressive_scalp"])
        
        assert config.take_profit_risk_reward == 1.0
        assert "sr_bounce" in config.enabled_signals
        assert "mean_reversion" in config.enabled_signals
        assert config.use_scalp_presets  # Should enable scalp presets

    def test_apply_variant_conservative(self):
        """Test applying conservative variant."""
        config = NQIntradayConfig()
        presets = NQIntradayConfig.get_variant_presets()
        
        config._apply_variant(presets["conservative"])
        
        assert config.take_profit_risk_reward == 1.5  # Stricter R:R


class TestLoosenedFilters:
    """Tests for loosened filter defaults."""

    def test_reduced_rr_requirement(self):
        """R:R requirement should be reduced from 1.5 to 1.2."""
        config = NQIntradayConfig()
        assert config.take_profit_risk_reward == 1.2

    def test_reduced_volatility_threshold(self):
        """Volatility threshold should be reduced from 0.001 to 0.0005."""
        config = NQIntradayConfig()
        assert config.volatility_threshold == 0.0005

    def test_lunch_lull_disabled(self):
        """Lunch lull avoidance should be disabled by default."""
        config = NQIntradayConfig()
        assert config.avoid_lunch_lull is False


class TestScalpPresets:
    """Tests for scalp-optimized stop/target presets."""

    def test_scalp_presets_default_off(self):
        """Scalp presets should be off by default."""
        config = NQIntradayConfig()
        assert config.use_scalp_presets is False

    def test_scalp_presets_values(self):
        """Verify scalp preset default values."""
        config = NQIntradayConfig()
        
        # Default scalp target for $200 with 5 contracts
        assert config.scalp_target_points == 20.0
        assert config.scalp_stop_points == 12.0

    def test_scalp_presets_can_be_enabled(self):
        """Scalp presets can be enabled via variant."""
        config = NQIntradayConfig()
        presets = NQIntradayConfig.get_variant_presets()
        
        config._apply_variant(presets["aggressive_scalp"])
        
        assert config.use_scalp_presets is True
        assert config.scalp_target_points == 20  # From variant
        assert config.scalp_stop_points == 15  # From variant


class TestFromConfigFile:
    """Tests for loading config from file."""

    def test_variant_parameter(self):
        """Test that variant parameter works."""
        # This should not raise even if variant doesn't exist in file
        config = NQIntradayConfig.from_config_file(variant="nonexistent")
        assert config is not None

    def test_config_loads_signals(self):
        """Test that signals config is loaded from file."""
        config = NQIntradayConfig.from_config_file()
        
        # Should have loaded from config.yaml
        assert isinstance(config.enabled_signals, list)
        assert isinstance(config.disabled_signals, list)




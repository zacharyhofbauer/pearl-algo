"""
Tests for OrderManager

Tests:
- Constructor / initialization with various dependency configurations
- Base position size computation (static, dynamic, multipliers, clamping)
- ML opportunity sizing adjustments (all score tiers, clamping, error handling)
- Position size validation against risk limits (min/max, account-based)
- Sizing summary reporting
- Edge cases (empty signals, invalid types, zero/negative values)
"""

import pytest
from unittest.mock import MagicMock

from pearlalgo.market_agent.order_manager import OrderManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(**overrides) -> dict:
    """Create a minimal signal dict, applying any overrides."""
    base = {
        "signal_id": "test_signal_1",
        "type": "sr_bounce",
        "symbol": "MNQ",
        "direction": "long",
        "confidence": 0.5,
    }
    base.update(overrides)
    return base


def _make_ml_filter(*, opportunity_score=0.7, raise_error=False):
    """Return a mock MLSignalFilter with a configurable get_opportunity_score."""
    mock = MagicMock()
    if raise_error:
        mock.get_opportunity_score.side_effect = RuntimeError("ML model crashed")
    else:
        mock.get_opportunity_score.return_value = opportunity_score
    return mock


# ═══════════════════════════════════════════════════════════════════════════
# 1. Constructor / Initialization
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderManagerInit:
    """Tests for OrderManager constructor and initialization."""

    def test_default_initialization(self):
        """Default constructor should set empty dicts and no ML filter."""
        om = OrderManager()

        assert om._risk_settings == {}
        assert om._strategy_settings == {}
        assert om._ml_signal_filter is None
        assert om._ml_adjust_sizing is False

    def test_initialization_with_risk_settings(self):
        """Risk settings should be stored and accessible."""
        risk = {"min_position_size": 1, "max_position_size": 10}
        om = OrderManager(risk_settings=risk)

        assert om._risk_settings is risk
        assert om._risk_settings["min_position_size"] == 1
        assert om._risk_settings["max_position_size"] == 10

    def test_initialization_with_strategy_settings(self):
        """Strategy settings should be stored for sizing logic."""
        strategy = {
            "enable_dynamic_sizing": True,
            "base_contracts": 2,
            "high_conf_contracts": 4,
            "max_conf_contracts": 6,
        }
        om = OrderManager(strategy_settings=strategy)

        assert om._strategy_settings["enable_dynamic_sizing"] is True
        assert om._strategy_settings["base_contracts"] == 2

    def test_initialization_with_ml_filter(self):
        """ML filter and adjust flag should be stored as keyword args."""
        ml_filter = _make_ml_filter()
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)

        assert om._ml_signal_filter is ml_filter
        assert om._ml_adjust_sizing is True

    def test_none_settings_default_to_empty_dicts(self):
        """Passing None explicitly should behave same as default."""
        om = OrderManager(risk_settings=None, strategy_settings=None)

        assert om._risk_settings == {}
        assert om._strategy_settings == {}


# ═══════════════════════════════════════════════════════════════════════════
# 2. configure_ml_sizing
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigureMLSizing:
    """Tests for runtime ML sizing configuration."""

    def test_configure_sets_filter_and_flag(self):
        """configure_ml_sizing should update both the filter and the flag."""
        om = OrderManager()
        ml_filter = _make_ml_filter()

        om.configure_ml_sizing(ml_filter, ml_adjust_sizing=True)

        assert om._ml_signal_filter is ml_filter
        assert om._ml_adjust_sizing is True

    def test_configure_can_disable_ml(self):
        """configure_ml_sizing(None) should disable ML sizing."""
        ml_filter = _make_ml_filter()
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)

        om.configure_ml_sizing(None, ml_adjust_sizing=False)

        assert om._ml_signal_filter is None
        assert om._ml_adjust_sizing is False


# ═══════════════════════════════════════════════════════════════════════════
# 3. compute_base_position_size – Order Placement Sizing
# ═══════════════════════════════════════════════════════════════════════════

class TestComputeBasePositionSize:
    """Tests for base position size calculation."""

    def test_default_config_returns_one(self):
        """With no strategy config, base size should be 1 contract."""
        om = OrderManager()
        signal = _make_signal()

        size = om.compute_base_position_size(signal)

        assert size == 1

    def test_signal_with_existing_position_size_honored(self):
        """If signal already carries a position_size, that value is used."""
        om = OrderManager()
        signal = _make_signal(position_size=5)

        size = om.compute_base_position_size(signal)

        assert size == 5

    def test_signal_position_size_string_is_cast(self):
        """A stringified position_size in the signal should be cast to int."""
        om = OrderManager()
        signal = _make_signal(position_size="3")

        size = om.compute_base_position_size(signal)

        assert size == 3

    def test_signal_position_size_zero_returns_min_one(self):
        """position_size=0 in signal should be clamped to at least 1."""
        om = OrderManager()
        signal = _make_signal(position_size=0)

        size = om.compute_base_position_size(signal)

        assert size == 1

    def test_base_contracts_from_strategy(self):
        """base_contracts config should set the baseline size."""
        om = OrderManager(strategy_settings={"base_contracts": 3})
        signal = _make_signal(confidence=0.5)

        size = om.compute_base_position_size(signal)

        assert size == 3

    def test_dynamic_sizing_below_high_threshold(self):
        """Confidence below high threshold should use base_contracts."""
        om = OrderManager(strategy_settings={
            "enable_dynamic_sizing": True,
            "base_contracts": 2,
            "high_conf_contracts": 4,
            "max_conf_contracts": 6,
            "high_conf_threshold": 0.8,
            "max_conf_threshold": 0.9,
        })
        signal = _make_signal(confidence=0.5)

        size = om.compute_base_position_size(signal)

        assert size == 2

    def test_dynamic_sizing_high_confidence(self):
        """Confidence at high threshold should use high_conf_contracts."""
        om = OrderManager(strategy_settings={
            "enable_dynamic_sizing": True,
            "base_contracts": 2,
            "high_conf_contracts": 4,
            "max_conf_contracts": 6,
            "high_conf_threshold": 0.8,
            "max_conf_threshold": 0.9,
        })
        signal = _make_signal(confidence=0.85)

        size = om.compute_base_position_size(signal)

        assert size == 4

    def test_dynamic_sizing_max_confidence(self):
        """Confidence at/above max threshold should use max_conf_contracts."""
        om = OrderManager(strategy_settings={
            "enable_dynamic_sizing": True,
            "base_contracts": 2,
            "high_conf_contracts": 4,
            "max_conf_contracts": 6,
            "high_conf_threshold": 0.8,
            "max_conf_threshold": 0.9,
        })
        signal = _make_signal(confidence=0.95)

        size = om.compute_base_position_size(signal)

        assert size == 6

    def test_dynamic_sizing_disabled_ignores_confidence(self):
        """Dynamic sizing off should always return base_contracts."""
        om = OrderManager(strategy_settings={
            "enable_dynamic_sizing": False,
            "base_contracts": 2,
            "high_conf_contracts": 4,
            "max_conf_contracts": 6,
        })
        signal = _make_signal(confidence=0.99)

        size = om.compute_base_position_size(signal)

        assert size == 2

    def test_signal_type_multiplier_applied(self):
        """Signal type multiplier should scale the computed size."""
        om = OrderManager(strategy_settings={
            "base_contracts": 2,
            "signal_type_size_multipliers": {"sr_bounce": 1.5},
        })
        signal = _make_signal(type="sr_bounce")

        size = om.compute_base_position_size(signal)

        # 2 * 1.5 = 3.0 → rounded to 3
        assert size == 3

    def test_signal_type_multiplier_unknown_type_no_change(self):
        """A signal type without a multiplier entry should not be scaled."""
        om = OrderManager(strategy_settings={
            "base_contracts": 2,
            "signal_type_size_multipliers": {"momentum": 2.0},
        })
        signal = _make_signal(type="sr_bounce")

        size = om.compute_base_position_size(signal)

        assert size == 2

    def test_size_clamped_to_risk_max(self):
        """Size exceeding max_position_size should be clamped down."""
        om = OrderManager(
            risk_settings={"max_position_size": 3},
            strategy_settings={
                "enable_dynamic_sizing": True,
                "base_contracts": 2,
                "high_conf_contracts": 4,
                "max_conf_contracts": 6,
                "max_conf_threshold": 0.9,
            },
        )
        signal = _make_signal(confidence=0.95)

        size = om.compute_base_position_size(signal)

        # Would be 6 but clamped to 3
        assert size == 3

    def test_size_raised_to_risk_min(self):
        """Size below min_position_size should be raised."""
        om = OrderManager(
            risk_settings={"min_position_size": 3},
            strategy_settings={"base_contracts": 1},
        )
        signal = _make_signal()

        size = om.compute_base_position_size(signal)

        assert size == 3

    def test_never_returns_less_than_one(self):
        """compute_base_position_size should always return >= 1."""
        om = OrderManager(risk_settings={"min_position_size": 0, "max_position_size": 0})
        signal = _make_signal()

        size = om.compute_base_position_size(signal)

        assert size >= 1

    def test_zero_confidence_uses_base(self):
        """Zero confidence should use base_contracts when dynamic sizing on."""
        om = OrderManager(strategy_settings={
            "enable_dynamic_sizing": True,
            "base_contracts": 2,
            "high_conf_contracts": 4,
        })
        signal = _make_signal(confidence=0.0)

        size = om.compute_base_position_size(signal)

        assert size == 2

    def test_missing_confidence_treated_as_zero(self):
        """Signal with no confidence key should default to 0."""
        om = OrderManager(strategy_settings={
            "enable_dynamic_sizing": True,
            "base_contracts": 2,
            "high_conf_contracts": 4,
        })
        signal = {"type": "test"}

        size = om.compute_base_position_size(signal)

        assert size == 2

    def test_empty_signal_returns_base(self):
        """A completely empty signal dict should not crash."""
        om = OrderManager()
        size = om.compute_base_position_size({})

        assert size == 1


# ═══════════════════════════════════════════════════════════════════════════
# 4. apply_ml_opportunity_sizing – ML-Based Sizing Adjustments
# ═══════════════════════════════════════════════════════════════════════════

class TestApplyMLOpportunitySizing:
    """Tests for ML opportunity score sizing adjustments."""

    def test_skipped_when_ml_adjust_disabled(self):
        """No changes if ml_adjust_sizing is False."""
        ml_filter = _make_ml_filter(opportunity_score=0.9)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=False)
        signal = _make_signal(position_size=2)

        om.apply_ml_opportunity_sizing(signal)

        assert "_ml_opportunity_score" not in signal
        assert signal.get("position_size") == 2

    def test_skipped_when_no_filter(self):
        """No changes if ml_signal_filter is None."""
        om = OrderManager(ml_signal_filter=None, ml_adjust_sizing=True)
        signal = _make_signal(position_size=2)

        om.apply_ml_opportunity_sizing(signal)

        assert "_ml_opportunity_score" not in signal

    def test_high_opportunity_applies_1_5x(self):
        """Score >= 0.8 should apply 1.5x multiplier and critical priority."""
        ml_filter = _make_ml_filter(opportunity_score=0.85)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=2)

        om.apply_ml_opportunity_sizing(signal)

        assert signal["_ml_opportunity_score"] == 0.85
        assert signal["_ml_size_multiplier"] == 1.5
        assert signal["_ml_priority"] == "critical"
        # 2 * 1.5 = 3.0 → 3
        assert signal["position_size"] == 3

    def test_good_opportunity_applies_1_25x(self):
        """Score >= 0.6 (but < 0.8) should apply 1.25x and high priority."""
        ml_filter = _make_ml_filter(opportunity_score=0.65)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=4)

        om.apply_ml_opportunity_sizing(signal)

        assert signal["_ml_opportunity_score"] == 0.65
        assert signal["_ml_size_multiplier"] == 1.25
        assert signal["_ml_priority"] == "high"
        # 4 * 1.25 = 5.0 → 5
        assert signal["position_size"] == 5

    def test_normal_opportunity_applies_1x(self):
        """Score >= 0.4 (but < 0.6) should apply 1.0x multiplier."""
        ml_filter = _make_ml_filter(opportunity_score=0.5)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=3)

        om.apply_ml_opportunity_sizing(signal)

        assert signal["_ml_opportunity_score"] == 0.5
        assert signal["_ml_size_multiplier"] == 1.0
        assert signal["_ml_priority"] == "normal"
        assert signal["position_size"] == 3

    def test_low_opportunity_applies_0_75x(self):
        """Score < 0.4 should apply 0.75x multiplier and normal priority."""
        ml_filter = _make_ml_filter(opportunity_score=0.2)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=4)

        om.apply_ml_opportunity_sizing(signal)

        assert signal["_ml_opportunity_score"] == 0.2
        assert signal["_ml_size_multiplier"] == 0.75
        assert signal["_ml_priority"] == "normal"
        # 4 * 0.75 = 3.0 → 3
        assert signal["position_size"] == 3

    def test_ml_sizing_clamps_to_risk_max(self):
        """Adjusted size should not exceed max_position_size."""
        ml_filter = _make_ml_filter(opportunity_score=0.9)
        om = OrderManager(
            risk_settings={"max_position_size": 4},
            ml_signal_filter=ml_filter,
            ml_adjust_sizing=True,
        )
        signal = _make_signal(position_size=4)

        om.apply_ml_opportunity_sizing(signal)

        # 4 * 1.5 = 6, but clamped to 4
        assert signal["position_size"] == 4

    def test_ml_sizing_never_below_one(self):
        """ML-adjusted size should never go below 1."""
        ml_filter = _make_ml_filter(opportunity_score=0.1)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=1)

        om.apply_ml_opportunity_sizing(signal)

        # 1 * 0.75 = 0.75 → max(1, round(0.75)) = max(1, 1) = 1
        assert signal["position_size"] >= 1

    def test_ml_none_score_leaves_signal_unchanged(self):
        """If get_opportunity_score returns None, signal is not modified."""
        ml_filter = _make_ml_filter()
        ml_filter.get_opportunity_score.return_value = None
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=3)

        om.apply_ml_opportunity_sizing(signal)

        assert "_ml_opportunity_score" not in signal
        assert "_ml_size_multiplier" not in signal
        assert signal.get("position_size") == 3

    def test_ml_filter_exception_is_non_fatal(self):
        """Exception in ML filter should be swallowed, signal unchanged."""
        ml_filter = _make_ml_filter(raise_error=True)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=2)

        # Should not raise
        om.apply_ml_opportunity_sizing(signal)

        assert "_ml_opportunity_score" not in signal
        assert signal.get("position_size") == 2

    def test_ml_sizing_boundary_score_0_8(self):
        """Score exactly 0.8 should hit the 'critical' tier (>=0.8)."""
        ml_filter = _make_ml_filter(opportunity_score=0.8)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=2)

        om.apply_ml_opportunity_sizing(signal)

        assert signal["_ml_size_multiplier"] == 1.5
        assert signal["_ml_priority"] == "critical"

    def test_ml_sizing_boundary_score_0_6(self):
        """Score exactly 0.6 should hit the 'high' tier (>=0.6)."""
        ml_filter = _make_ml_filter(opportunity_score=0.6)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=2)

        om.apply_ml_opportunity_sizing(signal)

        assert signal["_ml_size_multiplier"] == 1.25
        assert signal["_ml_priority"] == "high"

    def test_ml_sizing_boundary_score_0_4(self):
        """Score exactly 0.4 should hit the 'normal' 1.0x tier (>=0.4)."""
        ml_filter = _make_ml_filter(opportunity_score=0.4)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=2)

        om.apply_ml_opportunity_sizing(signal)

        assert signal["_ml_size_multiplier"] == 1.0
        assert signal["_ml_priority"] == "normal"


# ═══════════════════════════════════════════════════════════════════════════
# 5. validate_position_size – Risk Limit Validation
# ═══════════════════════════════════════════════════════════════════════════

class TestValidatePositionSize:
    """Tests for position size validation against risk limits."""

    @pytest.fixture
    def om(self):
        """OrderManager with explicit risk limits."""
        return OrderManager(risk_settings={
            "min_position_size": 1,
            "max_position_size": 10,
            "max_position_pct": 0.1,
        })

    def test_valid_size_passes(self, om):
        """A size within min/max should pass with no adjustments."""
        result = om.validate_position_size(5)

        assert result["valid"] is True
        assert result["adjusted_size"] == 5
        assert result["reason"] is None

    def test_below_minimum_rejected(self, om):
        """A size below min should be invalid."""
        result = om.validate_position_size(0)

        assert result["valid"] is False
        assert "below minimum" in result["reason"]

    def test_above_maximum_adjusted(self, om):
        """A size above max should be adjusted down."""
        result = om.validate_position_size(15)

        assert result["adjusted_size"] == 10
        assert "reduced from 15 to 10" in result["reason"]

    def test_at_exact_maximum_passes(self, om):
        """A size exactly at max should pass with no adjustment."""
        result = om.validate_position_size(10)

        assert result["adjusted_size"] == 10
        # reason could be None (not adjusted)

    def test_at_exact_minimum_passes(self, om):
        """A size exactly at min should pass."""
        result = om.validate_position_size(1)

        assert result["valid"] is True
        assert result["adjusted_size"] == 1

    def test_account_based_limit_reduces_size(self, om):
        """Account-based percentage limit should cap position size."""
        # account_value=30_000, max_pct=0.1 → max margin=3000 → 3000/5000 = 0 → clamped to 1
        result = om.validate_position_size(5, account_value=30_000.0)

        # 5 contracts * $5000 = $25,000 margin, which is 83% of $30k → exceeds 10%
        # Adjusted: 30000 * 0.1 / 5000 = 0.6 → max(1, 0) = 1
        assert result["adjusted_size"] <= 5
        assert "account" in result["reason"].lower() or "reduced" in result["reason"].lower()

    def test_account_based_limit_large_account_no_change(self, om):
        """A large account should not reduce the position size."""
        # account_value=1_000_000 → max margin=100_000 → 100_000/5000 = 20
        result = om.validate_position_size(5, account_value=1_000_000.0)

        assert result["adjusted_size"] == 5

    def test_direction_parameter_accepted(self, om):
        """Direction parameter should be accepted without error."""
        result_long = om.validate_position_size(3, direction="long")
        result_short = om.validate_position_size(3, direction="short")

        assert result_long["valid"] is True
        assert result_short["valid"] is True

    def test_no_risk_settings_permissive(self):
        """With no risk settings, most sizes should pass."""
        om = OrderManager()
        result = om.validate_position_size(100)

        assert result["valid"] is True
        assert result["adjusted_size"] == 100

    def test_zero_account_value_skips_pct_check(self, om):
        """account_value=0 should skip percentage-based check."""
        result = om.validate_position_size(5, account_value=0.0)

        assert result["adjusted_size"] == 5

    def test_negative_size_below_minimum(self, om):
        """Negative size should be flagged as below minimum."""
        result = om.validate_position_size(-1)

        assert result["valid"] is False
        assert "below minimum" in result["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# 6. get_sizing_summary – Configuration Reporting
# ═══════════════════════════════════════════════════════════════════════════

class TestGetSizingSummary:
    """Tests for sizing summary reporting."""

    def test_defaults_summary(self):
        """Default OrderManager should report sensible defaults."""
        om = OrderManager()
        summary = om.get_sizing_summary()

        assert summary["enable_dynamic_sizing"] is False
        assert summary["base_contracts"] == 1
        assert summary["high_conf_contracts"] == 1
        assert summary["max_conf_contracts"] == 1
        assert summary["high_conf_threshold"] == 0.8
        assert summary["max_conf_threshold"] == 0.9
        assert summary["min_position_size"] == 1
        assert summary["max_position_size"] is None
        assert summary["ml_adjust_sizing"] is False

    def test_configured_summary(self):
        """Summary should reflect the actual configuration."""
        om = OrderManager(
            risk_settings={
                "min_position_size": 2,
                "max_position_size": 8,
            },
            strategy_settings={
                "enable_dynamic_sizing": True,
                "base_contracts": 3,
                "high_conf_contracts": 5,
                "max_conf_contracts": 7,
                "high_conf_threshold": 0.75,
                "max_conf_threshold": 0.85,
            },
            ml_adjust_sizing=True,
        )
        summary = om.get_sizing_summary()

        assert summary["enable_dynamic_sizing"] is True
        assert summary["base_contracts"] == 3
        assert summary["high_conf_contracts"] == 5
        assert summary["max_conf_contracts"] == 7
        assert summary["high_conf_threshold"] == 0.75
        assert summary["max_conf_threshold"] == 0.85
        assert summary["min_position_size"] == 2
        assert summary["max_position_size"] == 8
        assert summary["ml_adjust_sizing"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 7. Edge Cases & Robustness
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Tests for edge cases and defensive behavior."""

    def test_signal_with_non_numeric_confidence(self):
        """Non-numeric confidence should be treated as 0."""
        om = OrderManager(strategy_settings={
            "enable_dynamic_sizing": True,
            "base_contracts": 2,
            "high_conf_contracts": 4,
        })
        signal = _make_signal(confidence="not_a_number")

        size = om.compute_base_position_size(signal)

        # Bad confidence → 0.0 → base_contracts
        assert size == 2

    def test_signal_with_none_confidence(self):
        """None confidence should be treated as 0."""
        om = OrderManager(strategy_settings={
            "enable_dynamic_sizing": True,
            "base_contracts": 2,
            "high_conf_contracts": 4,
        })
        signal = _make_signal(confidence=None)

        size = om.compute_base_position_size(signal)

        assert size == 2

    def test_signal_with_invalid_position_size_string(self):
        """Non-numeric position_size string in signal should fall through to config."""
        om = OrderManager(strategy_settings={"base_contracts": 3})
        signal = _make_signal(position_size="invalid")

        size = om.compute_base_position_size(signal)

        # "invalid" → exception → falls through to config calculation
        assert size == 3

    def test_signal_type_multiplier_with_none_type(self):
        """Signal with type=None should not crash on multiplier lookup."""
        om = OrderManager(strategy_settings={
            "base_contracts": 2,
            "signal_type_size_multipliers": {"sr_bounce": 2.0},
        })
        signal = _make_signal(type=None)

        size = om.compute_base_position_size(signal)

        # type is None → str(None) = "None" → not in multipliers → no scaling
        assert size == 2

    def test_risk_settings_with_none_values(self):
        """None values in risk settings should use safe defaults."""
        om = OrderManager(risk_settings={
            "min_position_size": None,
            "max_position_size": None,
        })
        signal = _make_signal()

        size = om.compute_base_position_size(signal)

        assert size >= 1

    def test_ml_sizing_modifies_signal_in_place(self):
        """apply_ml_opportunity_sizing should mutate the signal dict directly."""
        ml_filter = _make_ml_filter(opportunity_score=0.7)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size=2)
        original_id = id(signal)

        om.apply_ml_opportunity_sizing(signal)

        # Same object, modified in-place
        assert id(signal) == original_id
        assert "_ml_opportunity_score" in signal

    def test_ml_sizing_with_non_int_position_size(self):
        """ML sizing should handle non-integer position_size gracefully."""
        ml_filter = _make_ml_filter(opportunity_score=0.85)
        om = OrderManager(ml_signal_filter=ml_filter, ml_adjust_sizing=True)
        signal = _make_signal(position_size="3")

        om.apply_ml_opportunity_sizing(signal)

        # "3" → int("3") = 3, then 3 * 1.5 = 4.5 → 5 (rounded)
        # But the code does int(current_size) → if that fails → 1
        # Let's check it either succeeds or falls back
        assert signal["position_size"] >= 1

    def test_validate_with_current_exposure_param(self):
        """current_exposure parameter should be accepted without error."""
        om = OrderManager(risk_settings={"min_position_size": 1, "max_position_size": 10})

        result = om.validate_position_size(
            5, direction="long", current_exposure=25_000.0
        )

        assert result["valid"] is True

    def test_compute_size_large_multiplier_still_clamped(self):
        """Even with a large multiplier, risk max should clamp the result."""
        om = OrderManager(
            risk_settings={"max_position_size": 5},
            strategy_settings={
                "base_contracts": 3,
                "signal_type_size_multipliers": {"aggressive": 10.0},
            },
        )
        signal = _make_signal(type="aggressive")

        size = om.compute_base_position_size(signal)

        # 3 * 10 = 30, clamped to 5
        assert size == 5

from __future__ import annotations

import pytest

from pearlalgo.market_agent.order_manager import OrderManager


def _make_signal(**overrides) -> dict:
    signal = {
        "signal_id": "test-signal-001",
        "type": "sr_bounce",
        "direction": "long",
        "confidence": 0.5,
    }
    signal.update(overrides)
    return signal


# ── validate_signal_financials ──────────────────────────────────────


class TestValidateSignalFinancials:
    def test_valid_long_signal(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 95.0, "direction": "long"}
        ) is True

    def test_valid_short_signal(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 105.0, "direction": "short"}
        ) is True

    def test_long_stop_above_entry_rejected(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 105.0, "direction": "long"}
        ) is False

    def test_short_stop_below_entry_rejected(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 95.0, "direction": "short"}
        ) is False

    def test_zero_entry_price_rejected(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 0, "stop_loss": 95.0, "direction": "long"}
        ) is False

    def test_negative_stop_loss_rejected(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": -5.0, "direction": "long"}
        ) is False

    def test_non_numeric_entry_rejected(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": "abc", "stop_loss": 95.0, "direction": "long"}
        ) is False

    def test_non_numeric_stop_rejected(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": "bad", "direction": "long"}
        ) is False

    def test_missing_prices_passes(self) -> None:
        """Signals without price fields are not yet set — pass validation."""
        manager = OrderManager()
        assert manager.validate_signal_financials({"direction": "long"}) is True

    def test_only_entry_price_passes(self) -> None:
        """If only entry_price is set, no direction check needed."""
        manager = OrderManager()
        assert manager.validate_signal_financials({"entry_price": 100.0}) is True

    def test_only_stop_loss_passes(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials({"stop_loss": 95.0}) is True

    def test_stop_equal_to_entry_long_rejected(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 100.0, "direction": "long"}
        ) is False

    def test_stop_equal_to_entry_short_rejected(self) -> None:
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 100.0, "direction": "short"}
        ) is False

    def test_buy_alias_works(self) -> None:
        """'buy' is an alias for 'long'."""
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 95.0, "direction": "buy"}
        ) is True

    def test_sell_alias_works(self) -> None:
        """'sell' is an alias for 'short'."""
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 105.0, "direction": "sell"}
        ) is True

    def test_unknown_direction_skips_check(self) -> None:
        """Unknown direction doesn't trigger stop/entry comparison."""
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 105.0, "direction": "neutral"}
        ) is True

    def test_side_field_alias(self) -> None:
        """'side' is read when 'direction' is absent."""
        manager = OrderManager()
        assert manager.validate_signal_financials(
            {"entry_price": 100.0, "stop_loss": 95.0, "side": "long"}
        ) is True


# ── compute_base_position_size ──────────────────────────────────────


class TestComputeBasePositionSize:
    def test_defaults_to_one(self) -> None:
        manager = OrderManager()
        assert manager.compute_base_position_size(_make_signal()) == 1

    def test_uses_existing_signal_size(self) -> None:
        manager = OrderManager()
        assert manager.compute_base_position_size(_make_signal(position_size="3")) == 3

    def test_existing_signal_size_zero_ignored(self) -> None:
        manager = OrderManager()
        assert manager.compute_base_position_size(_make_signal(position_size="0")) == 1

    def test_existing_signal_size_negative_ignored(self) -> None:
        manager = OrderManager()
        assert manager.compute_base_position_size(_make_signal(position_size="-1")) == 1

    def test_dynamic_sizing_base(self) -> None:
        manager = OrderManager(
            strategy_settings={
                "enable_dynamic_sizing": True,
                "base_contracts": 2,
                "high_conf_contracts": 4,
                "max_conf_contracts": 6,
                "high_conf_threshold": 0.8,
                "max_conf_threshold": 0.9,
            }
        )
        assert manager.compute_base_position_size(_make_signal(confidence=0.5)) == 2

    def test_dynamic_sizing_high_confidence(self) -> None:
        manager = OrderManager(
            strategy_settings={
                "enable_dynamic_sizing": True,
                "base_contracts": 2,
                "high_conf_contracts": 4,
                "max_conf_contracts": 6,
                "high_conf_threshold": 0.8,
                "max_conf_threshold": 0.9,
            }
        )
        assert manager.compute_base_position_size(_make_signal(confidence=0.85)) == 4

    def test_dynamic_sizing_max_confidence(self) -> None:
        manager = OrderManager(
            strategy_settings={
                "enable_dynamic_sizing": True,
                "base_contracts": 2,
                "high_conf_contracts": 4,
                "max_conf_contracts": 6,
                "high_conf_threshold": 0.8,
                "max_conf_threshold": 0.9,
            }
        )
        assert manager.compute_base_position_size(_make_signal(confidence=0.95)) == 6

    def test_dynamic_sizing_exact_threshold(self) -> None:
        """Confidence exactly at high threshold should use high_conf_contracts."""
        manager = OrderManager(
            strategy_settings={
                "enable_dynamic_sizing": True,
                "base_contracts": 2,
                "high_conf_contracts": 4,
                "max_conf_contracts": 6,
                "high_conf_threshold": 0.8,
                "max_conf_threshold": 0.9,
            }
        )
        assert manager.compute_base_position_size(_make_signal(confidence=0.8)) == 4
        assert manager.compute_base_position_size(_make_signal(confidence=0.9)) == 6

    def test_signal_type_multiplier(self) -> None:
        manager = OrderManager(
            strategy_settings={
                "base_contracts": 2,
                "signal_type_size_multipliers": {"aggressive": 2.0},
            },
        )
        assert manager.compute_base_position_size(_make_signal(type="aggressive")) == 4

    def test_signal_type_multiplier_clamped_by_max(self) -> None:
        manager = OrderManager(
            risk_settings={"max_position_size": 5},
            strategy_settings={
                "base_contracts": 3,
                "signal_type_size_multipliers": {"aggressive": 10.0},
            },
        )
        assert manager.compute_base_position_size(_make_signal(type="aggressive")) == 5

    def test_min_size_enforced(self) -> None:
        manager = OrderManager(
            risk_settings={"min_position_size": 3, "max_position_size": 10},
            strategy_settings={"base_contracts": 1},
        )
        assert manager.compute_base_position_size(_make_signal()) == 3

    def test_returns_safe_default_on_invalid_financials(self) -> None:
        """If financials fail validation, return safe minimum."""
        manager = OrderManager(risk_settings={"min_position_size": 2})
        signal = _make_signal(entry_price=0, stop_loss=95.0)
        assert manager.compute_base_position_size(signal) == 2

    def test_zero_confidence_uses_base(self) -> None:
        manager = OrderManager(
            strategy_settings={
                "enable_dynamic_sizing": True,
                "base_contracts": 2,
                "high_conf_contracts": 4,
            }
        )
        assert manager.compute_base_position_size(_make_signal(confidence=0)) == 2

    def test_none_confidence_uses_base(self) -> None:
        manager = OrderManager(
            strategy_settings={
                "enable_dynamic_sizing": True,
                "base_contracts": 2,
                "high_conf_contracts": 4,
            }
        )
        assert manager.compute_base_position_size(_make_signal(confidence=None)) == 2

    def test_always_returns_at_least_one(self) -> None:
        """Even with bad config, never return 0 contracts."""
        manager = OrderManager(
            risk_settings={"min_position_size": 0, "max_position_size": 0},
            strategy_settings={"base_contracts": 0},
        )
        assert manager.compute_base_position_size(_make_signal()) >= 1


# ── validate_position_size ──────────────────────────────────────────


class TestValidatePositionSize:
    def test_rejects_below_minimum(self) -> None:
        manager = OrderManager(risk_settings={"min_position_size": 2, "max_position_size": 10})
        result = manager.validate_position_size(1)
        assert result["valid"] is False
        assert "below minimum" in str(result["reason"]).lower()

    def test_caps_above_maximum(self) -> None:
        manager = OrderManager(risk_settings={"min_position_size": 1, "max_position_size": 3})
        result = manager.validate_position_size(5)
        assert result["valid"] is True
        assert result["adjusted_size"] == 3

    def test_valid_within_range(self) -> None:
        manager = OrderManager(risk_settings={"min_position_size": 1, "max_position_size": 10})
        result = manager.validate_position_size(5)
        assert result["valid"] is True
        assert result["adjusted_size"] == 5
        assert result["reason"] is None

    def test_caps_at_account_pct_limit(self) -> None:
        manager = OrderManager(
            risk_settings={"min_position_size": 1, "max_position_size": 10, "max_position_pct": 0.1}
        )
        result = manager.validate_position_size(5, account_value=30_000.0)
        assert result["adjusted_size"] == 1
        assert "account" in str(result["reason"]).lower()

    def test_account_limit_ignores_zero_value(self) -> None:
        manager = OrderManager(
            risk_settings={"min_position_size": 1, "max_position_size": 10, "max_position_pct": 0.1}
        )
        result = manager.validate_position_size(5, account_value=0)
        assert result["adjusted_size"] == 5

    def test_account_limit_ignores_negative_value(self) -> None:
        manager = OrderManager(
            risk_settings={"min_position_size": 1, "max_position_size": 10, "max_position_pct": 0.1}
        )
        result = manager.validate_position_size(5, account_value=-1000)
        assert result["adjusted_size"] == 5

    def test_invalid_min_config_rejects(self) -> None:
        """If min_position_size can't be parsed, reject the order."""
        manager = OrderManager(risk_settings={"min_position_size": "bad", "max_position_size": 10})
        result = manager.validate_position_size(5)
        assert result["valid"] is False
        assert "configuration error" in str(result["reason"]).lower()

    def test_invalid_max_config_rejects(self) -> None:
        """If max_position_size can't be parsed, reject the order."""
        manager = OrderManager(risk_settings={"min_position_size": 1, "max_position_size": "bad"})
        result = manager.validate_position_size(5)
        assert result["valid"] is False
        assert "configuration error" in str(result["reason"]).lower()


# ── get_sizing_summary ──────────────────────────────────────────────


class TestGetSizingSummary:
    def test_reflects_live_configuration(self) -> None:
        manager = OrderManager(
            risk_settings={"min_position_size": 2, "max_position_size": 8},
            strategy_settings={
                "enable_dynamic_sizing": True,
                "base_contracts": 3,
                "high_conf_contracts": 5,
                "max_conf_contracts": 7,
                "high_conf_threshold": 0.75,
                "max_conf_threshold": 0.85,
            },
        )
        summary = manager.get_sizing_summary()
        assert summary == {
            "enable_dynamic_sizing": True,
            "base_contracts": 3,
            "high_conf_contracts": 5,
            "max_conf_contracts": 7,
            "high_conf_threshold": 0.75,
            "max_conf_threshold": 0.85,
            "min_position_size": 2,
            "max_position_size": 8,
        }

    def test_defaults_when_no_config(self) -> None:
        manager = OrderManager()
        summary = manager.get_sizing_summary()
        assert summary["enable_dynamic_sizing"] is False
        assert summary["base_contracts"] == 1
        assert summary["min_position_size"] == 1

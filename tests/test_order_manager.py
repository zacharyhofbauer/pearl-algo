from __future__ import annotations

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


def test_compute_base_position_size_defaults_to_one() -> None:
    manager = OrderManager()

    assert manager.compute_base_position_size(_make_signal()) == 1


def test_compute_base_position_size_uses_existing_signal_size() -> None:
    manager = OrderManager()

    assert manager.compute_base_position_size(_make_signal(position_size="3")) == 3


def test_compute_base_position_size_applies_dynamic_sizing() -> None:
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
    assert manager.compute_base_position_size(_make_signal(confidence=0.95)) == 6


def test_compute_base_position_size_applies_signal_multiplier_and_risk_clamp() -> None:
    manager = OrderManager(
        risk_settings={"max_position_size": 5},
        strategy_settings={
            "base_contracts": 3,
            "signal_type_size_multipliers": {"aggressive": 10.0},
        },
    )

    assert manager.compute_base_position_size(_make_signal(type="aggressive")) == 5


def test_validate_position_size_rejects_below_minimum() -> None:
    manager = OrderManager(risk_settings={"min_position_size": 2, "max_position_size": 10})

    result = manager.validate_position_size(1)

    assert result["valid"] is False
    assert "below minimum" in str(result["reason"]).lower()


def test_validate_position_size_caps_at_account_pct_limit() -> None:
    manager = OrderManager(
        risk_settings={"min_position_size": 1, "max_position_size": 10, "max_position_pct": 0.1}
    )

    result = manager.validate_position_size(5, account_value=30_000.0)

    assert result["adjusted_size"] == 1
    assert "account" in str(result["reason"]).lower()


def test_get_sizing_summary_reflects_live_configuration() -> None:
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

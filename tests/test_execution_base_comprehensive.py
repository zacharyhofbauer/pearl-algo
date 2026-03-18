"""
Comprehensive tests for execution/base.py.

Covers:
- ExecutionConfig: from_dict, to_dict, validation, defaults
- Position: properties, to_dict
- ExecutionDecision: to_dict
- ExecutionResult: to_dict
- ExecutionAdapter (base class): check_preconditions all guard paths,
  arm/disarm, daily counters, order increment, cooldown, status
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.execution.base import (
    ExecutionAdapter,
    ExecutionConfig,
    ExecutionDecision,
    ExecutionMode,
    ExecutionResult,
    OrderStatus,
    Position,
)


# ═══════════════════════════════════════════════════════════════════════════
# ExecutionMode
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionMode:
    def test_dry_run_value(self):
        assert ExecutionMode.DRY_RUN.value == "dry_run"

    def test_paper_value(self):
        assert ExecutionMode.PAPER.value == "paper"

    def test_live_value(self):
        assert ExecutionMode.LIVE.value == "live"


# ═══════════════════════════════════════════════════════════════════════════
# OrderStatus
# ═══════════════════════════════════════════════════════════════════════════


class TestOrderStatus:
    def test_all_statuses_exist(self):
        expected = {"PENDING", "PLACED", "FILLED", "PARTIALLY_FILLED",
                    "CANCELLED", "REJECTED", "EXPIRED", "ERROR"}
        actual = {s.name for s in OrderStatus}
        assert actual == expected


# ═══════════════════════════════════════════════════════════════════════════
# ExecutionConfig
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionConfigDefaults:
    def test_defaults_safe(self):
        cfg = ExecutionConfig()
        assert cfg.enabled is False
        assert cfg.armed is False
        assert cfg.mode == ExecutionMode.DRY_RUN

    def test_max_position_size_per_order_default(self):
        cfg = ExecutionConfig()
        assert cfg.max_position_size_per_order == 1

    def test_symbol_whitelist_default(self):
        cfg = ExecutionConfig()
        assert "MNQ" in cfg.symbol_whitelist


class TestExecutionConfigFromDict:
    def test_from_dict_full(self):
        cfg = ExecutionConfig.from_dict({
            "enabled": True,
            "armed": True,
            "mode": "paper",
            "max_positions": 3,
            "max_orders_per_day": 50,
            "max_daily_loss": 1000.0,
            "cooldown_seconds": 30,
            "max_position_size_per_order": 2,
            "symbol_whitelist": ["MNQ", "ES"],
            "allow_reversal_on_opposite_signal": True,
            "enforce_protection_guard": True,
        })
        assert cfg.enabled is True
        assert cfg.armed is True
        assert cfg.mode == ExecutionMode.PAPER
        assert cfg.max_positions == 3
        assert cfg.max_orders_per_day == 50
        assert cfg.max_daily_loss == 1000.0
        assert cfg.cooldown_seconds == 30
        assert cfg.max_position_size_per_order == 2
        assert cfg.symbol_whitelist == ["MNQ", "ES"]
        assert cfg.allow_reversal_on_opposite_signal is True
        assert cfg.enforce_protection_guard is True

    def test_from_dict_defaults(self):
        cfg = ExecutionConfig.from_dict({})
        assert cfg.enabled is False
        assert cfg.mode == ExecutionMode.DRY_RUN

    def test_from_dict_invalid_mode_defaults_to_dry_run(self):
        cfg = ExecutionConfig.from_dict({"mode": "unknown"})
        assert cfg.mode == ExecutionMode.DRY_RUN

    def test_from_dict_negative_max_positions_corrected(self):
        cfg = ExecutionConfig.from_dict({"max_positions": -1})
        assert cfg.max_positions > 0

    def test_from_dict_negative_max_orders_corrected(self):
        cfg = ExecutionConfig.from_dict({"max_orders_per_day": -5})
        assert cfg.max_orders_per_day > 0

    def test_from_dict_negative_max_daily_loss_corrected(self):
        cfg = ExecutionConfig.from_dict({"max_daily_loss": -100})
        assert cfg.max_daily_loss > 0

    def test_from_dict_negative_cooldown_corrected(self):
        cfg = ExecutionConfig.from_dict({"cooldown_seconds": -10})
        assert cfg.cooldown_seconds >= 0

    def test_from_dict_live_mode(self):
        cfg = ExecutionConfig.from_dict({"mode": "live"})
        assert cfg.mode == ExecutionMode.LIVE


class TestExecutionConfigToDict:
    def test_to_dict_roundtrip(self):
        cfg = ExecutionConfig(
            enabled=True, armed=True, mode=ExecutionMode.PAPER,
            max_positions=3, max_orders_per_day=50,
        )
        d = cfg.to_dict()
        assert d["enabled"] is True
        assert d["armed"] is True
        assert d["mode"] == "paper"
        assert d["max_positions"] == 3
        assert d["max_orders_per_day"] == 50

    def test_to_dict_contains_all_fields(self):
        cfg = ExecutionConfig()
        d = cfg.to_dict()
        expected_keys = {
            "enabled", "armed", "mode", "max_positions",
            "max_orders_per_day", "max_daily_loss", "cooldown_seconds",
            "symbol_whitelist", "allow_reversal_on_opposite_signal",
            "enforce_protection_guard", "ibkr_trading_client_id",
            "ibkr_host", "ibkr_port",
        }
        assert expected_keys.issubset(set(d.keys()))


# ═══════════════════════════════════════════════════════════════════════════
# Position
# ═══════════════════════════════════════════════════════════════════════════


class TestPosition:
    def test_long_direction(self):
        pos = Position(symbol="MNQ", quantity=2, avg_price=18000.0)
        assert pos.direction == "long"

    def test_short_direction(self):
        pos = Position(symbol="MNQ", quantity=-1, avg_price=18000.0)
        assert pos.direction == "short"

    def test_abs_quantity(self):
        pos = Position(symbol="MNQ", quantity=-3, avg_price=18000.0)
        assert pos.abs_quantity == 3

    def test_to_dict(self):
        now = datetime.now(timezone.utc)
        pos = Position(
            symbol="MNQ", quantity=1, avg_price=18000.0,
            unrealized_pnl=50.0, realized_pnl=100.0,
            signal_id="sig1", entry_time=now,
        )
        d = pos.to_dict()
        assert d["symbol"] == "MNQ"
        assert d["quantity"] == 1
        assert d["direction"] == "long"
        assert d["avg_price"] == 18000.0
        assert d["unrealized_pnl"] == 50.0
        assert d["realized_pnl"] == 100.0
        assert d["signal_id"] == "sig1"
        assert d["entry_time"] == now.isoformat()

    def test_to_dict_no_entry_time(self):
        pos = Position(symbol="MNQ", quantity=1, avg_price=18000.0)
        d = pos.to_dict()
        assert d["entry_time"] is None


# ═══════════════════════════════════════════════════════════════════════════
# ExecutionDecision
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionDecision:
    def test_to_dict(self):
        dec = ExecutionDecision(
            execute=True, reason="preconditions_passed", signal_id="sig1",
            size_multiplier=1.5, adjusted_size=2,
            policy_score=0.8, policy_recommendation="trade",
        )
        d = dec.to_dict()
        assert d["execute"] is True
        assert d["reason"] == "preconditions_passed"
        assert d["size_multiplier"] == 1.5
        assert d["adjusted_size"] == 2

    def test_defaults(self):
        dec = ExecutionDecision(execute=False, reason="test", signal_id="s")
        assert dec.size_multiplier == 1.0
        assert dec.adjusted_size is None
        assert dec.policy_score is None


# ═══════════════════════════════════════════════════════════════════════════
# ExecutionResult
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionResult:
    def test_to_dict(self):
        now = datetime.now(timezone.utc)
        res = ExecutionResult(
            success=True, status=OrderStatus.FILLED, signal_id="sig1",
            order_id="42", fill_price=18000.0, fill_quantity=1,
            fill_time=now,
        )
        d = res.to_dict()
        assert d["success"] is True
        assert d["status"] == "filled"
        assert d["order_id"] == "42"
        assert d["fill_price"] == 18000.0

    def test_error_result_to_dict(self):
        res = ExecutionResult(
            success=False, status=OrderStatus.ERROR, signal_id="sig2",
            error_message="test error", error_code=429,
        )
        d = res.to_dict()
        assert d["success"] is False
        assert d["error_message"] == "test error"
        assert d["error_code"] == 429

    def test_timestamp_auto_set(self):
        res = ExecutionResult(success=True, status=OrderStatus.PLACED, signal_id="s")
        assert res.timestamp is not None
        assert res.timestamp.tzinfo == timezone.utc


# ═══════════════════════════════════════════════════════════════════════════
# ExecutionAdapter (base class via concrete stub)
# ═══════════════════════════════════════════════════════════════════════════


class StubAdapter(ExecutionAdapter):
    """Minimal concrete adapter for testing base class methods."""

    async def place_bracket(self, signal):
        return ExecutionResult(success=True, status=OrderStatus.PLACED, signal_id="s")

    async def cancel_order(self, order_id):
        return ExecutionResult(success=True, status=OrderStatus.CANCELLED, signal_id="c")

    async def cancel_all(self):
        return []

    async def flatten_all_positions(self):
        return []

    async def get_positions(self):
        return []

    async def connect(self):
        return True

    async def disconnect(self):
        pass

    def is_connected(self):
        return True


def _make_stub(**config_kw) -> StubAdapter:
    cfg = ExecutionConfig(
        enabled=True, armed=True, mode=ExecutionMode.PAPER,
        symbol_whitelist=["MNQ"],
        **config_kw,
    )
    return StubAdapter(cfg)


def _valid_signal(**overrides) -> dict:
    sig = {
        "signal_id": "test_sig",
        "symbol": "MNQ",
        "direction": "long",
        "entry_price": 18000.0,
        "stop_loss": 17990.0,
        "take_profit": 18020.0,
        "position_size": 1,
        "type": "momentum",
    }
    sig.update(overrides)
    return sig


class TestCheckPreconditionsEnabled:
    def test_disabled_execution_blocked(self):
        adapter = StubAdapter(ExecutionConfig(enabled=False, armed=True))
        dec = adapter.check_preconditions(_valid_signal())
        assert dec.execute is False
        assert "execution_disabled" in dec.reason

    def test_enabled_execution_passes(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal())
        assert dec.execute is True


class TestCheckPreconditionsArmed:
    def test_not_armed_blocked(self):
        adapter = StubAdapter(ExecutionConfig(enabled=True, armed=False))
        dec = adapter.check_preconditions(_valid_signal())
        assert dec.execute is False
        assert "not_armed" in dec.reason


class TestCheckPreconditionsSymbolWhitelist:
    def test_symbol_not_in_whitelist_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(symbol="ES"))
        assert dec.execute is False
        assert "symbol_not_whitelisted" in dec.reason

    def test_empty_whitelist_allows_all(self):
        cfg = ExecutionConfig(enabled=True, armed=True, symbol_whitelist=[])
        adapter = StubAdapter(cfg)
        dec = adapter.check_preconditions(_valid_signal(symbol="ES"))
        assert dec.execute is True


class TestCheckPreconditionsMaxPositions:
    def test_max_positions_reached_blocked(self):
        adapter = _make_stub(max_positions=1)
        adapter._positions["MNQ"] = Position(symbol="MNQ", quantity=1, avg_price=18000.0)
        dec = adapter.check_preconditions(_valid_signal())
        assert dec.execute is False
        assert "max_positions_reached" in dec.reason


class TestCheckPreconditionsDailyOrderLimit:
    def test_daily_order_limit_reached_blocked(self):
        adapter = _make_stub(max_orders_per_day=2)
        adapter._orders_today = 2
        dec = adapter.check_preconditions(_valid_signal())
        assert dec.execute is False
        assert "max_daily_orders_reached" in dec.reason

    def test_under_daily_limit_passes(self):
        adapter = _make_stub(max_orders_per_day=20)
        adapter._orders_today = 5
        dec = adapter.check_preconditions(_valid_signal())
        assert dec.execute is True


class TestCheckPreconditionsDailyLoss:
    def test_daily_loss_limit_disarms_and_blocks(self):
        adapter = _make_stub(max_daily_loss=500.0)
        adapter._daily_pnl = -500.0
        assert adapter._armed is True
        dec = adapter.check_preconditions(_valid_signal())
        assert dec.execute is False
        assert "daily_loss_limit_hit" in dec.reason
        assert adapter._armed is False  # auto-disarmed

    def test_daily_loss_under_limit_passes(self):
        adapter = _make_stub(max_daily_loss=500.0)
        adapter._daily_pnl = -100.0
        dec = adapter.check_preconditions(_valid_signal())
        assert dec.execute is True


class TestCheckPreconditionsCooldown:
    def test_cooldown_active_blocked(self):
        adapter = _make_stub(cooldown_seconds=60)
        adapter._last_order_time["momentum"] = datetime.now(timezone.utc) - timedelta(seconds=10)
        dec = adapter.check_preconditions(_valid_signal(type="momentum"))
        assert dec.execute is False
        assert "cooldown_active" in dec.reason

    def test_cooldown_expired_passes(self):
        adapter = _make_stub(cooldown_seconds=60)
        adapter._last_order_time["momentum"] = datetime.now(timezone.utc) - timedelta(seconds=120)
        dec = adapter.check_preconditions(_valid_signal(type="momentum"))
        assert dec.execute is True

    def test_no_previous_order_passes(self):
        adapter = _make_stub(cooldown_seconds=60)
        dec = adapter.check_preconditions(_valid_signal(type="momentum"))
        assert dec.execute is True


class TestCheckPreconditionsDirection:
    def test_invalid_direction_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(direction="sideways"))
        assert dec.execute is False
        assert "invalid_direction" in dec.reason

    def test_empty_direction_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(direction=""))
        assert dec.execute is False

    def test_long_direction_accepted(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(direction="long"))
        assert dec.execute is True

    def test_short_direction_accepted(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(
            direction="short",
            entry_price=18000.0,
            stop_loss=18020.0,
            take_profit=17980.0,
        ))
        assert dec.execute is True


class TestCheckPreconditionsPrices:
    def test_non_numeric_prices_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(entry_price="bad"))
        assert dec.execute is False
        assert "invalid_prices" in dec.reason

    def test_zero_entry_price_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(entry_price=0))
        assert dec.execute is False
        assert "non_positive" in dec.reason

    def test_zero_stop_loss_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(stop_loss=0))
        assert dec.execute is False

    def test_negative_take_profit_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(take_profit=-1))
        assert dec.execute is False


class TestCheckPreconditionsBracketGeometry:
    def test_long_sl_above_entry_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(
            direction="long",
            entry_price=18000.0,
            stop_loss=18010.0,
            take_profit=18020.0,
        ))
        assert dec.execute is False
        assert "invalid_bracket_geometry" in dec.reason

    def test_long_tp_below_entry_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(
            direction="long",
            entry_price=18000.0,
            stop_loss=17990.0,
            take_profit=17995.0,
        ))
        assert dec.execute is False

    def test_short_sl_below_entry_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(
            direction="short",
            entry_price=18000.0,
            stop_loss=17990.0,
            take_profit=17980.0,
        ))
        assert dec.execute is False
        assert "invalid_bracket_geometry" in dec.reason

    def test_short_tp_above_entry_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(
            direction="short",
            entry_price=18000.0,
            stop_loss=18020.0,
            take_profit=18010.0,
        ))
        assert dec.execute is False

    def test_valid_long_geometry_passes(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(
            direction="long",
            entry_price=18000.0,
            stop_loss=17990.0,
            take_profit=18020.0,
        ))
        assert dec.execute is True

    def test_valid_short_geometry_passes(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(
            direction="short",
            entry_price=18000.0,
            stop_loss=18020.0,
            take_profit=17980.0,
        ))
        assert dec.execute is True


class TestCheckPreconditionsPositionSize:
    def test_non_integer_position_size_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(position_size="abc"))
        assert dec.execute is False
        assert "invalid_position_size" in dec.reason

    def test_zero_position_size_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(position_size=0))
        assert dec.execute is False
        assert "non_positive" in dec.reason

    def test_negative_position_size_blocked(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(position_size=-1))
        assert dec.execute is False

    def test_valid_position_size_passes(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal(position_size=1))
        assert dec.execute is True


class TestCheckPreconditionsAllPass:
    def test_all_checks_pass(self):
        adapter = _make_stub()
        dec = adapter.check_preconditions(_valid_signal())
        assert dec.execute is True
        assert dec.reason == "preconditions_passed"


# ═══════════════════════════════════════════════════════════════════════════
# Arm / Disarm
# ═══════════════════════════════════════════════════════════════════════════


class TestArmDisarm:
    def test_arm_success(self):
        adapter = _make_stub()
        adapter._armed = False
        assert adapter.arm() is True
        assert adapter.armed is True

    def test_arm_fails_when_disabled(self):
        cfg = ExecutionConfig(enabled=False, armed=False)
        adapter = StubAdapter(cfg)
        assert adapter.arm() is False
        assert adapter.armed is False

    def test_disarm(self):
        adapter = _make_stub()
        assert adapter.armed is True
        adapter.disarm()
        assert adapter.armed is False


# ═══════════════════════════════════════════════════════════════════════════
# Daily Counters
# ═══════════════════════════════════════════════════════════════════════════


class TestDailyCounters:
    def test_reset_daily_counters(self):
        adapter = _make_stub()
        adapter._orders_today = 10
        adapter._daily_pnl = -200.0
        adapter._last_order_time["momentum"] = datetime.now(timezone.utc)

        adapter.reset_daily_counters()

        assert adapter._orders_today == 0
        assert adapter._daily_pnl == 0.0
        assert len(adapter._last_order_time) == 0

    def test_update_daily_pnl(self):
        adapter = _make_stub()
        adapter.update_daily_pnl(50.0)
        adapter.update_daily_pnl(-30.0)
        assert adapter._daily_pnl == 20.0

    def test_increment_order_count(self):
        adapter = _make_stub()
        adapter.increment_order_count("momentum")
        adapter.increment_order_count("mean_reversion")
        assert adapter._orders_today == 2
        assert "momentum" in adapter._last_order_time
        assert "mean_reversion" in adapter._last_order_time

    def test_counter_lock_exists(self):
        adapter = _make_stub()
        assert hasattr(adapter._counter_lock, "acquire")
        assert hasattr(adapter._counter_lock, "release")


# ═══════════════════════════════════════════════════════════════════════════
# Base get_status
# ═══════════════════════════════════════════════════════════════════════════


class TestBaseGetStatus:
    def test_status_returns_dict(self):
        adapter = _make_stub()
        status = adapter.get_status()
        assert isinstance(status, dict)
        assert status["enabled"] is True
        assert status["armed"] is True
        assert status["mode"] == "paper"
        assert status["connected"] is True
        assert status["orders_today"] == 0
        assert status["daily_pnl"] == 0.0
        assert status["positions"] == 0

    def test_status_with_positions(self):
        adapter = _make_stub()
        adapter._positions["MNQ"] = Position(symbol="MNQ", quantity=1, avg_price=18000.0)
        status = adapter.get_status()
        assert status["positions"] == 1

    def test_status_with_flat_position_not_counted(self):
        adapter = _make_stub()
        adapter._positions["MNQ"] = Position(symbol="MNQ", quantity=0, avg_price=18000.0)
        status = adapter.get_status()
        assert status["positions"] == 0

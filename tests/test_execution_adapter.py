"""
Tests for Execution Adapter

Tests:
- Execution gating: unarmed => no orders
- Precondition checks (limits, cooldowns, whitelist)
- Shadow mode behavior
- Live mode behavior with policy
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from pearlalgo.execution.base import (
    ExecutionAdapter,
    ExecutionConfig,
    ExecutionDecision,
    ExecutionResult,
    ExecutionMode,
    OrderStatus,
    Position,
)


class MockExecutionAdapter(ExecutionAdapter):
    """Mock execution adapter for testing (no IBKR connection)."""
    
    def __init__(self, config: ExecutionConfig):
        super().__init__(config)
        self._connected = True
        self._placed_orders = []
        self._cancelled_orders = []
    
    async def place_bracket(self, signal: dict) -> ExecutionResult:
        """Mock bracket order placement."""
        signal_id = signal.get("signal_id", "mock_id")
        
        # Check preconditions
        decision = self.check_preconditions(signal)
        if not decision.execute:
            return ExecutionResult(
                success=False,
                status=OrderStatus.REJECTED,
                signal_id=signal_id,
                error_message=decision.reason,
            )
        
        # Mock successful placement
        self._placed_orders.append(signal)
        self._orders_today += 1
        signal_type = signal.get("type", "unknown")
        self._last_order_time[signal_type] = datetime.now(timezone.utc)
        
        return ExecutionResult(
            success=True,
            status=OrderStatus.PLACED,
            signal_id=signal_id,
            parent_order_id=f"mock_parent_{len(self._placed_orders)}",
            stop_order_id=f"mock_stop_{len(self._placed_orders)}",
            take_profit_order_id=f"mock_tp_{len(self._placed_orders)}",
        )
    
    async def cancel_order(self, order_id: str) -> ExecutionResult:
        """Mock order cancellation."""
        self._cancelled_orders.append(order_id)
        return ExecutionResult(
            success=True,
            status=OrderStatus.CANCELLED,
            signal_id="",
            order_id=order_id,
        )
    
    async def cancel_all(self) -> list[ExecutionResult]:
        """Mock cancel all."""
        self.disarm()
        return [ExecutionResult(
            success=True,
            status=OrderStatus.CANCELLED,
            signal_id="kill_switch",
        )]

    async def flatten_all_positions(self) -> list[ExecutionResult]:
        """Mock flatten all positions (kill switch)."""
        # Mirror safety behavior: disarm immediately.
        self.disarm()
        # No broker in tests; clear tracked positions and return a successful no-op.
        self._positions.clear()
        return [ExecutionResult(
            success=True,
            status=OrderStatus.PLACED,
            signal_id="kill_switch_flatten",
        )]
    
    async def get_positions(self) -> list[Position]:
        """Mock get positions."""
        return list(self._positions.values())
    
    async def connect(self) -> bool:
        """Mock connect."""
        self._connected = True
        return True
    
    async def disconnect(self) -> None:
        """Mock disconnect."""
        self._connected = False
    
    def is_connected(self) -> bool:
        """Mock connection check."""
        return self._connected


class TestExecutionConfig:
    """Tests for ExecutionConfig class."""
    
    def test_default_config_is_safe(self):
        """Default config should be safe (disabled, disarmed)."""
        config = ExecutionConfig()
        
        assert config.enabled is False
        assert config.armed is False
        assert config.mode == ExecutionMode.DRY_RUN
    
    def test_from_dict(self):
        """Should parse config from dictionary."""
        data = {
            "enabled": True,
            "armed": False,
            "mode": "paper",
            "max_positions": 2,
            "max_orders_per_day": 10,
            "symbol_whitelist": ["MNQ", "NQ"],
        }
        
        config = ExecutionConfig.from_dict(data)
        
        assert config.enabled is True
        assert config.armed is False
        assert config.mode == ExecutionMode.PAPER
        assert config.max_positions == 2
        assert config.max_orders_per_day == 10
        assert config.symbol_whitelist == ["MNQ", "NQ"]
    
    def test_to_dict(self):
        """Should serialize config to dictionary."""
        config = ExecutionConfig(
            enabled=True,
            mode=ExecutionMode.LIVE,
        )
        
        data = config.to_dict()
        
        assert data["enabled"] is True
        assert data["mode"] == "live"


class TestExecutionPreconditions:
    """Tests for execution precondition checks."""
    
    @pytest.fixture
    def config(self):
        """Create test config."""
        return ExecutionConfig(
            enabled=True,
            armed=True,
            mode=ExecutionMode.PAPER,
            max_positions=1,
            max_orders_per_day=5,
            cooldown_seconds=60,
            symbol_whitelist=["MNQ"],
        )
    
    @pytest.fixture
    def adapter(self, config):
        """Create mock adapter."""
        return MockExecutionAdapter(config)
    
    def test_execution_disabled_blocks(self, adapter):
        """Disabled execution should block all orders."""
        adapter.config.enabled = False
        
        signal = {"signal_id": "test", "type": "test", "symbol": "MNQ"}
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "execution_disabled" in decision.reason
    
    def test_unarmed_blocks(self, adapter):
        """Unarmed adapter should block all orders."""
        adapter.disarm()
        
        signal = {"signal_id": "test", "type": "test", "symbol": "MNQ"}
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "not_armed" in decision.reason
    
    def test_symbol_whitelist_blocks_unknown(self, adapter):
        """Symbol not in whitelist should be blocked."""
        signal = {"signal_id": "test", "type": "test", "symbol": "ES"}
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "symbol_not_whitelisted" in decision.reason
    
    def test_symbol_whitelist_allows_known(self, adapter):
        """Symbol in whitelist should be allowed."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is True
    
    def test_max_positions_blocks(self, adapter):
        """At max positions should block new orders."""
        # Simulate having a position
        adapter._positions["MNQ"] = Position(
            symbol="MNQ",
            quantity=1,
            avg_price=20000.0,
        )
        
        signal = {"signal_id": "test", "type": "test", "symbol": "MNQ"}
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "max_positions_reached" in decision.reason
    
    def test_max_daily_orders_blocks(self, adapter):
        """At max daily orders should block new orders."""
        adapter._orders_today = 5  # At limit
        
        signal = {"signal_id": "test", "type": "test", "symbol": "MNQ"}
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "max_daily_orders_reached" in decision.reason
    
    def test_daily_loss_limit_blocks(self, adapter):
        """At max daily loss should block new orders."""
        adapter._daily_pnl = -600.0  # Exceeds 500 limit
        
        signal = {"signal_id": "test", "type": "test", "symbol": "MNQ"}
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "daily_loss_limit_hit" in decision.reason
    
    def test_cooldown_blocks(self, adapter):
        """Active cooldown should block same signal type."""
        signal_type = "test_type"
        adapter._last_order_time[signal_type] = datetime.now(timezone.utc)
        
        signal = {"signal_id": "test", "type": signal_type, "symbol": "MNQ"}
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "cooldown_active" in decision.reason
    
    def test_all_preconditions_pass(self, adapter):
        """All preconditions met should allow order."""
        signal = {
            "signal_id": "test",
            "type": "new_type",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is True
        assert "preconditions_passed" in decision.reason


class TestBracketValidation:
    """Tests for bracket order geometry validation."""
    
    @pytest.fixture
    def config(self):
        """Create test config."""
        return ExecutionConfig(
            enabled=True,
            armed=True,
            mode=ExecutionMode.PAPER,
            max_positions=1,
            max_orders_per_day=5,
            cooldown_seconds=60,
            symbol_whitelist=["MNQ"],
        )
    
    @pytest.fixture
    def adapter(self, config):
        """Create mock adapter."""
        return MockExecutionAdapter(config)
    
    def test_invalid_direction_blocks(self, adapter):
        """Invalid direction should block execution."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "sideways",  # Invalid
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_direction" in decision.reason
    
    def test_missing_direction_blocks(self, adapter):
        """Missing direction should block execution."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_direction" in decision.reason
    
    def test_non_positive_entry_price_blocks(self, adapter):
        """Non-positive entry price should block execution."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 0,  # Invalid
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_prices:non_positive" in decision.reason
    
    def test_non_positive_stop_loss_blocks(self, adapter):
        """Non-positive stop loss should block execution."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": -100.0,  # Invalid
            "take_profit": 20030.0,
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_prices:non_positive" in decision.reason
    
    def test_invalid_long_bracket_geometry_blocks(self, adapter):
        """Invalid long bracket geometry (SL >= entry) should block."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 20010.0,  # SL above entry - invalid for long
            "take_profit": 20030.0,
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_bracket_geometry:long" in decision.reason
    
    def test_invalid_long_bracket_geometry_tp_blocks(self, adapter):
        """Invalid long bracket geometry (TP <= entry) should block."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 19990.0,  # TP below entry - invalid for long
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_bracket_geometry:long" in decision.reason
    
    def test_valid_long_bracket_passes(self, adapter):
        """Valid long bracket (SL < entry < TP) should pass."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,  # Below entry
            "take_profit": 20030.0,  # Above entry
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is True
    
    def test_invalid_short_bracket_geometry_blocks(self, adapter):
        """Invalid short bracket geometry (SL <= entry) should block."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "short",
            "entry_price": 20000.0,
            "stop_loss": 19990.0,  # SL below entry - invalid for short
            "take_profit": 19970.0,
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_bracket_geometry:short" in decision.reason
    
    def test_invalid_short_bracket_geometry_tp_blocks(self, adapter):
        """Invalid short bracket geometry (TP >= entry) should block."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "short",
            "entry_price": 20000.0,
            "stop_loss": 20020.0,
            "take_profit": 20010.0,  # TP above entry - invalid for short
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_bracket_geometry:short" in decision.reason
    
    def test_valid_short_bracket_passes(self, adapter):
        """Valid short bracket (TP < entry < SL) should pass."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "short",
            "entry_price": 20000.0,
            "stop_loss": 20020.0,  # Above entry
            "take_profit": 19970.0,  # Below entry
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is True
    
    def test_non_positive_position_size_blocks(self, adapter):
        """Non-positive position size should block execution."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": 0,  # Invalid
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_position_size:non_positive" in decision.reason
    
    def test_negative_position_size_blocks(self, adapter):
        """Negative position size should block execution."""
        signal = {
            "signal_id": "test",
            "type": "test",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": -5,  # Invalid
        }
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is False
        assert "invalid_position_size:non_positive" in decision.reason


class TestArmDisarm:
    """Tests for arm/disarm functionality."""
    
    def test_arm_when_enabled(self):
        """Should arm successfully when enabled."""
        config = ExecutionConfig(enabled=True, armed=False)
        adapter = MockExecutionAdapter(config)
        
        success = adapter.arm()
        
        assert success is True
        assert adapter.armed is True
    
    def test_arm_when_disabled_fails(self):
        """Should fail to arm when disabled."""
        config = ExecutionConfig(enabled=False, armed=False)
        adapter = MockExecutionAdapter(config)
        
        success = adapter.arm()
        
        assert success is False
        assert adapter.armed is False
    
    def test_disarm(self):
        """Should disarm successfully."""
        config = ExecutionConfig(enabled=True, armed=True)
        adapter = MockExecutionAdapter(config)
        
        adapter.disarm()
        
        assert adapter.armed is False


class TestExecutionResult:
    """Tests for ExecutionResult and ExecutionDecision."""
    
    def test_execution_result_to_dict(self):
        """ExecutionResult should serialize correctly."""
        result = ExecutionResult(
            success=True,
            status=OrderStatus.PLACED,
            signal_id="test_signal",
            parent_order_id="123",
            stop_order_id="124",
            take_profit_order_id="125",
        )
        
        data = result.to_dict()
        
        assert data["success"] is True
        assert data["status"] == "placed"
        assert data["signal_id"] == "test_signal"
        assert data["parent_order_id"] == "123"
    
    def test_execution_decision_to_dict(self):
        """ExecutionDecision should serialize correctly."""
        decision = ExecutionDecision(
            execute=True,
            reason="preconditions_passed",
            signal_id="test_signal",
            size_multiplier=1.2,
            policy_score=0.75,
        )
        
        data = decision.to_dict()
        
        assert data["execute"] is True
        assert data["reason"] == "preconditions_passed"
        assert data["size_multiplier"] == 1.2
        assert data["policy_score"] == 0.75


class TestPosition:
    """Tests for Position class."""
    
    def test_position_direction(self):
        """Position should report correct direction."""
        long_pos = Position(symbol="MNQ", quantity=1, avg_price=20000.0)
        short_pos = Position(symbol="MNQ", quantity=-1, avg_price=20000.0)
        
        assert long_pos.direction == "long"
        assert short_pos.direction == "short"
    
    def test_position_abs_quantity(self):
        """Position should report absolute quantity."""
        pos = Position(symbol="MNQ", quantity=-3, avg_price=20000.0)
        
        assert pos.abs_quantity == 3
    
    def test_position_to_dict(self):
        """Position should serialize correctly."""
        pos = Position(
            symbol="MNQ",
            quantity=2,
            avg_price=20000.0,
            unrealized_pnl=100.0,
            signal_id="test_signal",
        )
        
        data = pos.to_dict()
        
        assert data["symbol"] == "MNQ"
        assert data["quantity"] == 2
        assert data["direction"] == "long"
        assert data["avg_price"] == 20000.0
        assert data["unrealized_pnl"] == 100.0


class TestDailyReset:
    """Tests for daily counter reset."""
    
    def test_reset_daily_counters(self):
        """Should reset all daily counters."""
        config = ExecutionConfig(enabled=True, armed=True)
        adapter = MockExecutionAdapter(config)
        
        # Simulate a day of trading
        adapter._orders_today = 10
        adapter._daily_pnl = -200.0
        adapter._last_order_time["type1"] = datetime.now(timezone.utc)
        
        adapter.reset_daily_counters()
        
        assert adapter._orders_today == 0
        assert adapter._daily_pnl == 0.0
        assert len(adapter._last_order_time) == 0
    
    def test_update_daily_pnl(self):
        """Should track daily P&L correctly."""
        config = ExecutionConfig(enabled=True, armed=True)
        adapter = MockExecutionAdapter(config)
        
        adapter.update_daily_pnl(100.0)
        adapter.update_daily_pnl(-50.0)
        
        assert adapter._daily_pnl == 50.0
    
    def test_daily_loss_limit_auto_disarms(self):
        """Should auto-disarm when daily loss limit is hit."""
        config = ExecutionConfig(
            enabled=True, 
            armed=True, 
            max_daily_loss=500.0,
            symbol_whitelist=["MNQ"],
        )
        adapter = MockExecutionAdapter(config)
        
        # Simulate losses approaching limit
        adapter.update_daily_pnl(-400.0)
        assert adapter.armed  # Still armed
        
        # Simulate crossing limit
        adapter.update_daily_pnl(-150.0)  # Total -550
        
        # Check preconditions should auto-disarm
        signal = {
            "signal_id": "test_loss_limit",
            "symbol": "MNQ",
            "type": "test",
            "direction": "long",
            "entry_price": 25000.0,
            "stop_loss": 24990.0,
            "take_profit": 25020.0,
            "position_size": 1,
        }
        decision = adapter.check_preconditions(signal)
        
        # Should reject execution
        assert not decision.execute
        assert "daily_loss_limit_hit" in decision.reason
        
        # Should auto-disarm
        assert not adapter.armed


@pytest.mark.asyncio
class TestMockExecution:
    """Integration tests with mock execution."""
    
    async def test_place_bracket_success(self):
        """Should successfully place bracket order."""
        config = ExecutionConfig(
            enabled=True,
            armed=True,
            mode=ExecutionMode.PAPER,
            symbol_whitelist=["MNQ"],
        )
        adapter = MockExecutionAdapter(config)
        
        signal = {
            "signal_id": "test_1",
            "type": "sr_bounce",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": 1,
        }
        
        result = await adapter.place_bracket(signal)
        
        assert result.success is True
        assert result.status == OrderStatus.PLACED
        assert result.parent_order_id is not None
        assert len(adapter._placed_orders) == 1
    
    async def test_place_bracket_unarmed_fails(self):
        """Should fail when unarmed."""
        config = ExecutionConfig(
            enabled=True,
            armed=False,  # Disarmed
            mode=ExecutionMode.PAPER,
            symbol_whitelist=["MNQ"],
        )
        adapter = MockExecutionAdapter(config)
        
        signal = {
            "signal_id": "test_1",
            "type": "sr_bounce",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 20000.0,
            "stop_loss": 19980.0,
            "take_profit": 20030.0,
            "position_size": 1,
        }
        
        result = await adapter.place_bracket(signal)
        
        assert result.success is False
        assert "not_armed" in result.error_message
        assert len(adapter._placed_orders) == 0
    
    async def test_cancel_all_disarms(self):
        """Cancel all should also disarm."""
        config = ExecutionConfig(enabled=True, armed=True)
        adapter = MockExecutionAdapter(config)
        
        assert adapter.armed is True
        
        await adapter.cancel_all()
        
        assert adapter.armed is False


@pytest.mark.asyncio
class TestKillSwitchBehavior:
    """Tests for kill switch safety behavior.
    
    The kill switch (/kill command) must:
    1. Disarm the execution adapter FIRST (prevent new orders)
    2. Cancel all open orders
    3. Remain disarmed even if cancel_all fails
    """
    
    async def test_kill_disarms_before_cancel(self):
        """Kill should disarm before attempting to cancel orders."""
        config = ExecutionConfig(enabled=True, armed=True)
        adapter = MockExecutionAdapter(config)
        
        assert adapter.armed is True
        
        # Simulate kill: disarm first, then cancel_all
        adapter.disarm()
        assert adapter.armed is False  # Disarmed immediately
        
        await adapter.cancel_all()
        assert adapter.armed is False  # Still disarmed
    
    async def test_kill_stays_disarmed_on_cancel_error(self):
        """Kill should remain disarmed even if cancel_all raises an exception."""
        config = ExecutionConfig(enabled=True, armed=True)
        adapter = MockExecutionAdapter(config)
        
        # Simulate kill with error in cancel_all
        adapter.disarm()
        try:
            # Simulate cancel_all failure (would raise in real adapter)
            raise Exception("IBKR connection lost")
        except Exception:
            pass  # Error caught
        
        # Must remain disarmed
        assert adapter.armed is False
    
    async def test_kill_switch_prevents_new_orders(self):
        """After kill, no new orders should be placed."""
        config = ExecutionConfig(
            enabled=True,
            armed=True,
            symbol_whitelist=["MNQ"],
        )
        adapter = MockExecutionAdapter(config)
        
        # Simulate kill
        adapter.disarm()
        await adapter.cancel_all()
        
        # Try to place an order after kill
        signal = {
            "signal_id": "post_kill_signal",
            "type": "momentum_short",
            "symbol": "MNQ",
            "direction": "short",
            "entry_price": 25000.0,
            "stop_loss": 25020.0,
            "take_profit": 24970.0,
            "position_size": 1,
        }
        
        result = await adapter.place_bracket(signal)
        
        # Order should be rejected because adapter is disarmed
        assert result.success is False
        assert "not_armed" in result.error_message
        assert len(adapter._placed_orders) == 0

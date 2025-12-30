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
        signal = {"signal_id": "test", "type": "test", "symbol": "MNQ"}
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
        signal = {"signal_id": "test", "type": "new_type", "symbol": "MNQ"}
        decision = adapter.check_preconditions(signal)
        
        assert decision.execute is True
        assert "preconditions_passed" in decision.reason


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


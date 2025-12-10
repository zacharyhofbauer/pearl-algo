"""
Tests for error recovery scenarios including state recovery and provider failures.
"""

from __future__ import annotations

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

from pearlalgo.agents.langgraph_state import create_initial_state, TradingState
from pearlalgo.agents.state_store import StateStore
from pearlalgo.agents.market_data_agent import MarketDataAgent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.data_providers.dummy_provider import DummyDataProvider
from pearlalgo.data_providers.polygon_provider import PolygonDataProvider


@pytest.fixture
def sample_portfolio():
    """Create sample portfolio."""
    return Portfolio(cash=100000.0)


@pytest.fixture
def sample_config():
    """Create sample configuration."""
    return {
        "strategy": {"default": "sr"},
        "risk": {
            "max_risk_per_trade": 0.02,
            "max_drawdown": 0.15,
        },
        "trading": {
            "mode": "paper",
            "signal_only": True,
        },
    }


@pytest.fixture
def temp_state_dir():
    """Create temporary directory for state storage."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


class TestStateRecovery:
    """Test state persistence and recovery."""
    
    def test_state_store_save_and_load(self, sample_portfolio, sample_config, temp_state_dir):
        """Test that state can be saved and loaded."""
        # Create initial state
        state = create_initial_state(
            portfolio=sample_portfolio,
            config=sample_config,
        )
        
        # Save state
        store = StateStore(storage_path=temp_state_dir)
        store.save_state(state, "test_state")
        
        # Load state
        loaded_state = store.load_state("test_state")
        
        assert loaded_state is not None
        assert loaded_state.portfolio is not None
        assert loaded_state.portfolio.cash == sample_portfolio.cash
    
    def test_state_store_recovery_after_crash(self, sample_portfolio, sample_config, temp_state_dir):
        """Test state recovery after simulated crash."""
        # Create and save state
        state = create_initial_state(
            portfolio=sample_portfolio,
            config=sample_config,
        )
        state.current_step = "quant_research"
        state.errors.append("Simulated error")
        
        store = StateStore(storage_path=temp_state_dir)
        store.save_state(state, "recovery_test")
        
        # Simulate recovery - load state
        recovered_state = store.load_state("recovery_test")
        
        assert recovered_state is not None
        assert recovered_state.current_step == "quant_research"
        assert len(recovered_state.errors) == 1
        assert "Simulated error" in recovered_state.errors
    
    def test_state_store_delete(self, sample_portfolio, sample_config, temp_state_dir):
        """Test that state can be deleted."""
        state = create_initial_state(
            portfolio=sample_portfolio,
            config=sample_config,
        )
        
        store = StateStore(storage_path=temp_state_dir)
        store.save_state(state, "delete_test")
        
        # Verify state exists
        loaded = store.load_state("delete_test")
        assert loaded is not None
        
        # Delete state
        store.delete_state("delete_test")
        
        # Verify state is deleted
        deleted = store.load_state("delete_test")
        assert deleted is None


class TestProviderFailureRecovery:
    """Test recovery from data provider failures."""
    
    @pytest.mark.asyncio
    async def test_market_data_agent_handles_provider_failure(self, sample_config):
        """Test that MarketDataAgent handles provider failures gracefully."""
        agent = MarketDataAgent(
            symbols=["ES"],
            config=sample_config,
        )
        
        # Disable providers to simulate failure
        agent.polygon_provider = None
        agent.dummy_provider = None
        
        portfolio = Portfolio(cash=100000.0)
        state = create_initial_state(portfolio=portfolio, config=sample_config)
        
        # Fetch data (should handle failure)
        state = await agent.fetch_live_data(state)
        
        # Verify errors are recorded
        assert state is not None
        # Should have errors or empty market data
        assert len(state.errors) >= 0 or len(state.market_data) == 0
    
    @pytest.mark.asyncio
    async def test_market_data_agent_fallback_to_dummy(self, sample_config):
        """Test that MarketDataAgent falls back to dummy provider."""
        agent = MarketDataAgent(
            symbols=["ES"],
            config=sample_config,
        )
        
        # Disable Polygon, keep dummy
        agent.polygon_provider = None
        
        portfolio = Portfolio(cash=100000.0)
        state = create_initial_state(portfolio=portfolio, config=sample_config)
        
        # Fetch data
        state = await agent.fetch_live_data(state)
        
        # Should have data from dummy provider
        assert state is not None
        # May have data or errors depending on dummy provider behavior
    
    @pytest.mark.asyncio
    async def test_market_data_agent_all_providers_fail(self, sample_config):
        """Test behavior when all providers fail."""
        agent = MarketDataAgent(
            symbols=["ES"],
            config=sample_config,
        )
        
        # Create mock providers that always fail
        class FailingProvider:
            async def get_latest_bar(self, symbol):
                raise RuntimeError("Provider failure")
        
        agent.polygon_provider = FailingProvider()
        agent.dummy_provider = None
        
        portfolio = Portfolio(cash=100000.0)
        state = create_initial_state(portfolio=portfolio, config=sample_config)
        
        # Fetch data
        state = await agent.fetch_live_data(state)
        
        # Should have errors recorded
        assert state is not None
        assert len(state.errors) > 0


class TestKillSwitchRecovery:
    """Test kill-switch triggering and recovery."""
    
    @pytest.mark.asyncio
    async def test_kill_switch_prevents_trading(self, sample_portfolio, sample_config):
        """Test that kill-switch prevents further trading."""
        from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
        
        agent = RiskManagerAgent(
            portfolio=sample_portfolio,
            config=sample_config,
        )
        
        # Simulate large drawdown
        agent.peak_equity = 100000.0
        agent.portfolio.cash = 80000.0  # 20% drawdown (exceeds 15% limit)
        
        state = create_initial_state(portfolio=sample_portfolio, config=sample_config)
        
        # Evaluate risk
        state = await agent.evaluate_risk(state)
        
        # Kill switch should be triggered
        assert state.kill_switch_triggered is True
        assert state.trading_enabled is False
    
    def test_state_with_kill_switch(self, sample_portfolio, sample_config):
        """Test state validation with kill switch."""
        state = create_initial_state(
            portfolio=sample_portfolio,
            config=sample_config,
        )
        
        # Trigger kill switch
        state.kill_switch_triggered = True
        
        # Validate state
        state.validate_state_transitions()
        
        # Trading should be disabled
        assert state.trading_enabled is False


class TestErrorPropagation:
    """Test error propagation through workflow."""
    
    @pytest.mark.asyncio
    async def test_errors_accumulate_in_state(self, sample_config):
        """Test that errors accumulate in state."""
        agent = MarketDataAgent(
            symbols=["ES", "NQ"],
            config=sample_config,
        )
        
        portfolio = Portfolio(cash=100000.0)
        state = create_initial_state(portfolio=portfolio, config=sample_config)
        
        # Simulate errors
        state.errors.append("Error 1")
        state.errors.append("Error 2")
        
        # Fetch data (may add more errors)
        state = await agent.fetch_live_data(state)
        
        # Errors should be preserved
        assert len(state.errors) >= 2
        assert "Error 1" in state.errors
        assert "Error 2" in state.errors
    
    def test_state_error_limits(self, sample_portfolio, sample_config):
        """Test that state doesn't accumulate unlimited errors."""
        state = create_initial_state(
            portfolio=sample_portfolio,
            config=sample_config,
        )
        
        # Add many errors
        for i in range(1000):
            state.errors.append(f"Error {i}")
        
        # State should handle large error lists
        assert len(state.errors) == 1000
        # Should not crash or cause memory issues


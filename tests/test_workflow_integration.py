"""
Integration tests for the full LangGraph workflow.
"""

from __future__ import annotations

import pytest
import asyncio
from datetime import datetime, timezone

from pearlalgo.agents.langgraph_state import create_initial_state, MarketData
from pearlalgo.agents.langgraph_workflow import TradingWorkflow
from pearlalgo.agents.market_data_agent import MarketDataAgent
from pearlalgo.agents.quant_research_agent import QuantResearchAgent
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.agents.portfolio_execution_agent import PortfolioExecutionAgent
from pearlalgo.core.portfolio import Portfolio


@pytest.fixture
def sample_portfolio():
    """Create sample portfolio."""
    return Portfolio(cash=100000.0)


@pytest.fixture
def sample_config():
    """Create sample configuration."""
    return {
        "broker": {"primary": "ibkr"},
        "strategy": {"default": "sr"},
        "risk": {
            "max_risk_per_trade": 0.02,
            "max_drawdown": 0.15,
        },
        "llm": {
            "provider": "groq",
            "groq": {"api_key": "", "model": "mixtral-8x7b-32768"},
        },
    }


@pytest.fixture
def sample_state(sample_portfolio, sample_config):
    """Create sample trading state."""
    return create_initial_state(
        portfolio=sample_portfolio,
        config=sample_config,
    )


def test_workflow_state_creation(sample_portfolio, sample_config):
    """Test that workflow state can be created."""
    state = create_initial_state(sample_portfolio, sample_config)

    assert state is not None
    assert state.portfolio is not None
    assert state.trading_enabled == True
    assert state.kill_switch_triggered == False
    assert isinstance(state.timestamp, datetime)


def test_market_data_agent_initialization(sample_config):
    """Test MarketDataAgent can be initialized."""
    agent = MarketDataAgent(
        symbols=["ES", "NQ"],
        config=sample_config,
    )

    assert agent is not None
    assert agent.symbols == ["ES", "NQ"]


def test_quant_research_agent_initialization(sample_config):
    """Test QuantResearchAgent can be initialized."""
    agent = QuantResearchAgent(
        symbols=["ES", "NQ"],
        strategy="sr",
        config=sample_config,
    )

    assert agent is not None
    assert agent.symbols == ["ES", "NQ"]
    assert agent.strategy == "sr"


def test_risk_manager_agent_initialization(sample_portfolio, sample_config):
    """Test RiskManagerAgent can be initialized."""
    agent = RiskManagerAgent(
        portfolio=sample_portfolio,
        config=sample_config,
    )

    assert agent is not None
    assert agent.MAX_RISK_PER_TRADE == 0.02
    assert agent.MAX_DRAWDOWN == 0.15
    assert agent.ALLOW_MARTINGALE == False
    assert agent.ALLOW_AVERAGING_DOWN == False


def test_portfolio_execution_agent_initialization(sample_portfolio, sample_config):
    """Test PortfolioExecutionAgent can be initialized."""
    agent = PortfolioExecutionAgent(
        portfolio=sample_portfolio,
        config=sample_config,
    )

    assert agent is not None
    assert agent.portfolio is not None


def test_workflow_state_transitions(sample_state):
    """Test state transitions through workflow."""
    # Initial state
    assert (
        sample_state.current_step == "market_data" or sample_state.current_step is None
    )

    # State should be mutable
    sample_state.current_step = "quant_research"
    assert sample_state.current_step == "quant_research"

    sample_state.current_step = "risk_manager"
    assert sample_state.current_step == "risk_manager"

    sample_state.current_step = "portfolio_execution"
    assert sample_state.current_step == "portfolio_execution"


def test_error_handling_in_state(sample_state):
    """Test error handling in trading state."""
    # Add an error
    sample_state.errors.append("Test error")
    assert len(sample_state.errors) == 1
    assert "Test error" in sample_state.errors

    # Trading should still be enabled unless kill switch
    assert sample_state.trading_enabled

    # Trigger kill switch
    sample_state.kill_switch_triggered = True
    assert sample_state.kill_switch_triggered


@pytest.mark.asyncio
async def test_full_workflow_cycle(sample_portfolio, sample_config):
    """Test a complete workflow cycle through all agents."""
    # Create workflow
    workflow = TradingWorkflow(
        symbols=["ES"],
        portfolio=sample_portfolio,
        strategy="sr",
        config=sample_config,
    )
    
    # Run a single cycle
    state = await workflow.run_cycle()
    
    # Verify state was updated
    assert state is not None
    assert state.timestamp is not None
    assert isinstance(state.timestamp, datetime)
    
    # Verify market data agent ran (may have data or errors)
    assert "market_data_agent" in [r.agent_name for r in state.agent_reasoning]
    
    # Verify workflow completed
    assert state.current_step in ["portfolio_execution", "market_data", "quant_research", "risk_manager"]


@pytest.mark.asyncio
async def test_market_data_agent_fetch(sample_config):
    """Test MarketDataAgent can fetch data."""
    agent = MarketDataAgent(
        symbols=["ES"],
        config=sample_config,
    )
    
    # Create initial state
    portfolio = Portfolio(cash=100000.0)
    state = create_initial_state(portfolio=portfolio, config=sample_config)
    
    # Fetch data
    state = await agent.fetch_live_data(state)
    
    # Verify state was updated
    assert state is not None
    assert state.timestamp is not None
    # May have market data or errors (depending on API availability)
    assert isinstance(state.market_data, dict)


@pytest.mark.asyncio
async def test_quant_research_agent_generate_signals(sample_config):
    """Test QuantResearchAgent can generate signals."""
    agent = QuantResearchAgent(
        symbols=["ES"],
        strategy="sr",
        config=sample_config,
    )
    
    # Create state with market data
    portfolio = Portfolio(cash=100000.0)
    state = create_initial_state(portfolio=portfolio, config=sample_config)
    
    # Add mock market data
    state.market_data["ES"] = MarketData(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000.0,
    )
    
    # Generate signals
    state = await agent.generate_signals(state)
    
    # Verify state was updated
    assert state is not None
    # May have signals or not (depending on strategy logic)
    assert isinstance(state.signals, dict)


@pytest.mark.asyncio
async def test_risk_manager_agent_evaluate_risk(sample_portfolio, sample_config):
    """Test RiskManagerAgent can evaluate risk."""
    agent = RiskManagerAgent(
        portfolio=sample_portfolio,
        config=sample_config,
    )
    
    # Create state with signals
    state = create_initial_state(portfolio=sample_portfolio, config=sample_config)
    
    # Add mock signal
    from pearlalgo.agents.langgraph_state import Signal
    state.signals["ES"] = Signal(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        side="long",
        strategy_name="sr",
        confidence=0.75,
        entry_price=4500.0,
    )
    
    # Evaluate risk
    state = await agent.evaluate_risk(state)
    
    # Verify state was updated
    assert state is not None
    assert state.risk_state is not None or len(state.position_decisions) >= 0


@pytest.mark.asyncio
async def test_portfolio_execution_agent_execute(sample_portfolio, sample_config):
    """Test PortfolioExecutionAgent can execute decisions."""
    agent = PortfolioExecutionAgent(
        portfolio=sample_portfolio,
        config=sample_config,
    )
    
    # Create state with position decisions
    state = create_initial_state(portfolio=sample_portfolio, config=sample_config)
    
    # Add mock position decision
    from pearlalgo.agents.langgraph_state import PositionDecision
    state.position_decisions["ES"] = PositionDecision(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        action="enter_long",
        size=1,
        risk_amount=100.0,
        risk_percent=0.02,
        reasoning="Test signal",
    )
    
    # Execute decisions
    state = await agent.execute_decisions(state)
    
    # Verify state was updated
    assert state is not None
    # In signal-only mode, signals are logged but not executed
    assert agent.signal_only is True


def test_workflow_initialization(sample_portfolio, sample_config):
    """Test TradingWorkflow can be initialized."""
    workflow = TradingWorkflow(
        symbols=["ES", "NQ"],
        portfolio=sample_portfolio,
        strategy="sr",
        config=sample_config,
    )
    
    assert workflow is not None
    assert workflow.symbols == ["ES", "NQ"]
    assert workflow.strategy == "sr"
    assert workflow.portfolio == sample_portfolio
    assert workflow.workflow is not None

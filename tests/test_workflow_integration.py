"""
Integration tests for the full LangGraph workflow.
"""

from __future__ import annotations

import pytest
from datetime import datetime

from pearlalgo.agents.langgraph_state import create_initial_state
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
        broker="ibkr",
        config=sample_config,
    )

    assert agent is not None
    assert agent.symbols == ["ES", "NQ"]
    assert agent.broker == "ibkr"


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
        broker_name="ibkr",
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

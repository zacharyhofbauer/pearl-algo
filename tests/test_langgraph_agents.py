"""
Comprehensive tests for LangGraph agents and workflow.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from pearlalgo.agents.langgraph_state import (
    MarketData,
    Signal,
    create_initial_state,
)
from pearlalgo.agents.market_data_agent import MarketDataAgent
from pearlalgo.agents.quant_research_agent import QuantResearchAgent
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.agents.portfolio_execution_agent import PortfolioExecutionAgent
from pearlalgo.core.portfolio import Portfolio


@pytest.fixture
def sample_portfolio():
    """Create a sample portfolio for testing."""
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
    }


@pytest.fixture
def sample_state(sample_portfolio, sample_config):
    """Create sample trading state."""
    return create_initial_state(
        portfolio=sample_portfolio,
        config=sample_config,
    )


def test_market_data_agent(sample_config):
    """Test Market Data Agent initialization."""
    agent = MarketDataAgent(
        symbols=["ES", "NQ"],
        broker="ibkr",
        config=sample_config,
    )
    assert agent.symbols == ["ES", "NQ"]
    assert agent.broker == "ibkr"


def test_quant_research_agent(sample_config):
    """Test Quant Research Agent initialization."""
    agent = QuantResearchAgent(
        symbols=["ES", "NQ"],
        strategy="sr",
        config=sample_config,
    )
    assert agent.symbols == ["ES", "NQ"]
    assert agent.strategy == "sr"


def test_risk_manager_agent(sample_portfolio, sample_config):
    """Test Risk Manager Agent initialization."""
    agent = RiskManagerAgent(
        portfolio=sample_portfolio,
        config=sample_config,
    )
    assert agent.portfolio == sample_portfolio
    assert agent.MAX_RISK_PER_TRADE == 0.02
    assert agent.MAX_DRAWDOWN == 0.15


def test_portfolio_execution_agent(sample_portfolio, sample_config):
    """Test Portfolio/Execution Agent initialization."""
    agent = PortfolioExecutionAgent(
        portfolio=sample_portfolio,
        broker_name="ibkr",
        config=sample_config,
    )
    assert agent.portfolio == sample_portfolio
    assert agent.broker_name == "ibkr"


def test_trading_state_creation(sample_portfolio, sample_config):
    """Test TradingState creation."""
    state = create_initial_state(
        portfolio=sample_portfolio,
        config=sample_config,
    )
    assert state.portfolio == sample_portfolio
    assert state.trading_enabled is True
    assert state.kill_switch_triggered is False


def test_market_data_model():
    """Test MarketData Pydantic model."""
    data = MarketData(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000.0,
    )
    assert data.symbol == "ES"
    assert data.close == 4505.0


def test_signal_model():
    """Test Signal Pydantic model."""
    signal = Signal(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        side="long",
        strategy_name="sr",
        confidence=0.75,
    )
    assert signal.symbol == "ES"
    assert signal.side == "long"
    assert signal.confidence == 0.75


def test_risk_manager_hardcoded_rules(sample_portfolio, sample_config):
    """Test that risk rules are hardcoded correctly."""
    agent = RiskManagerAgent(
        portfolio=sample_portfolio,
        config=sample_config,
    )
    # Verify hardcoded rules
    assert agent.MAX_RISK_PER_TRADE == 0.02
    assert agent.MAX_DRAWDOWN == 0.15
    assert agent.ALLOW_MARTINGALE is False
    assert agent.ALLOW_AVERAGING_DOWN is False

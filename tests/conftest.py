"""
Pytest configuration and shared fixtures.

This file ensures all tests use actual production code dynamically
without duplicating files or code.

Key principles:
1. Tests import actual code from src/pearlalgo/ (no duplication)
2. Python path is configured so imports work automatically
3. Shared fixtures are available to all tests
4. Package must be installed in development mode: pip install -e .
"""

import sys
from pathlib import Path

# Ensure project root is in path so tests can import actual production code
project_root = Path(__file__).parent.parent
src_path = project_root / "src"

# Add src to path so tests can import actual production code
# This is done here as a fallback, but pytest.ini also configures pythonpath
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Ensure tests can import from tests package (for MockDataProvider, etc.)
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Pytest configuration
import pytest
import numpy as np
import pandas as pd

# Auto-discover tests in tests/ directory
pytest_plugins = []


# ---------------------------------------------------------------------------
# Path Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def project_root_path():
    """Return the project root directory."""
    return project_root


@pytest.fixture(scope="session")
def src_path_fixture():
    """Return the src directory path."""
    return src_path


# ---------------------------------------------------------------------------
# State Directory Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_state_dir(tmp_path):
    """Create a temporary state directory with required subdirectories."""
    state_dir = tmp_path / "agent_state"
    state_dir.mkdir()
    return state_dir


# ---------------------------------------------------------------------------
# Mock Data Provider Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_data_provider():
    """Return a MockDataProvider configured for deterministic testing.

    Uses fixed seed, no simulated failures, for reliable test results.
    """
    from tests.mock_data_provider import MockDataProvider

    return MockDataProvider(
        base_price=17500.0,
        volatility=25.0,
        trend=0.0,
        simulate_delayed_data=False,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )


# ---------------------------------------------------------------------------
# Sample OHLCV DataFrame Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_ohlcv_df():
    """Create a realistic 100-bar OHLCV DataFrame for testing.

    Deterministic (seed=42) so tests are reproducible.
    """
    np.random.seed(42)
    n = 100

    close = 17500.0 + np.cumsum(np.random.randn(n) * 10.0)
    high = close + np.abs(np.random.randn(n) * 5.0)
    low = close - np.abs(np.random.randn(n) * 5.0)
    open_ = close + np.random.randn(n) * 3.0
    volume = np.abs(np.random.randn(n) * 10000 + 50000).astype(int)

    dates = pd.date_range("2024-01-02 09:30:00", periods=n, freq="5min")

    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )


# ---------------------------------------------------------------------------
# Configured Service Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def configured_service(tmp_state_dir, mock_data_provider):
    """Return a fully-configured MarketAgentService for testing.

    Uses tmp_state_dir to avoid polluting real state, and mock_data_provider
    to avoid needing a live IBKR connection.
    """
    from pearlalgo.market_agent.service import MarketAgentService

    return MarketAgentService(
        data_provider=mock_data_provider,
        state_dir=tmp_state_dir,
    )

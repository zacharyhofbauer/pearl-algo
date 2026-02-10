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


# ---------------------------------------------------------------------------
# Signal Factory Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def signal_factory():
    """Factory for creating signal dicts with sensible defaults."""
    def _make_signal(
        *,
        signal_type="momentum_ema_cross",
        direction="long",
        entry_price=17500.0,
        stop_loss=17480.0,
        take_profit=17540.0,
        confidence=0.75,
        symbol="MNQ",
        timestamp=None,
        signal_id=None,
        **overrides,
    ):
        from datetime import datetime, timezone
        sig = {
            "type": signal_type,
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "confidence": confidence,
            "symbol": symbol,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        }
        if signal_id:
            sig["signal_id"] = signal_id
        sig.update(overrides)
        return sig
    return _make_signal


# ---------------------------------------------------------------------------
# Market Hours Parametrized Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(params=["pre_market", "regular", "after_hours", "weekend"])
def market_hours_params(request):
    """Parametrized fixture for market hours scenarios."""
    # Return a dict with the market phase name and a representative datetime
    from datetime import datetime, timezone, timedelta
    # Use a known Monday for pre/regular/after, Saturday for weekend
    base_monday = datetime(2025, 6, 2, tzinfo=timezone.utc)  # a known Monday
    scenarios = {
        "pre_market": {"phase": "pre_market", "dt": base_monday.replace(hour=8, minute=0)},
        "regular": {"phase": "regular", "dt": base_monday.replace(hour=15, minute=0)},
        "after_hours": {"phase": "after_hours", "dt": base_monday.replace(hour=22, minute=0)},
        "weekend": {"phase": "weekend", "dt": (base_monday + timedelta(days=5)).replace(hour=12)},
    }
    return scenarios[request.param]


# ---------------------------------------------------------------------------
# Stale OHLCV DataFrame Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def stale_ohlcv_df():
    """OHLCV DataFrame with timestamps from 2 hours ago (stale data)."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(hours=2)
    rows = []
    for i in range(20):
        ts = stale_time + timedelta(minutes=i)
        rows.append({
            "timestamp": ts,
            "Open": 17500.0 + i,
            "High": 17505.0 + i,
            "Low": 17495.0 + i,
            "Close": 17502.0 + i,
            "Volume": 100 + i * 10,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Corrupt State Directory Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def corrupt_state_dir(tmp_path):
    """Temp directory with corrupt state files for recovery testing."""
    state_dir = tmp_path / "corrupt_state"
    state_dir.mkdir()

    # Corrupt signals.jsonl (malformed JSON lines)
    signals_file = state_dir / "signals.jsonl"
    signals_file.write_text(
        '{"signal_id": "good_1", "timestamp": "2025-01-01T00:00:00Z", "status": "generated", "signal": {"type": "test", "direction": "long", "entry_price": 17500.0}}\n'
        'THIS IS NOT JSON\n'
        '{"truncated": true\n'
        '{"signal_id": "good_2", "timestamp": "2025-01-01T01:00:00Z", "status": "generated", "signal": {"type": "test", "direction": "short", "entry_price": 17600.0}}\n'
    )

    # Corrupt state.json
    state_file = state_dir / "state.json"
    state_file.write_text('{"partial": true')

    # Empty events file
    events_file = state_dir / "events.jsonl"
    events_file.write_text("")

    return state_dir

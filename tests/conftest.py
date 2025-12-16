import warnings
import pytest
from pathlib import Path

# Suppress noisy deprecation warning from eventkit about missing event loop during tests.
warnings.filterwarnings(
    "ignore", message="There is no current event loop", category=DeprecationWarning
)


@pytest.fixture(scope="session")
def real_data_provider():
    """
    Create a real IBKR data provider for testing with actual market data.
    
    Session-scoped to reuse the same connection across all tests (faster).
    Uses actual IBKR Gateway connection - tests will use REAL market data.
    The provider's executor already has faster retry settings (2s delay, 3 attempts).
    """
    from pearlalgo.data_providers.ibkr.ibkr_provider import IBKRProvider
    from pearlalgo.config.settings import get_settings
    import socket
    import time
    
    settings = get_settings()
    
    # Check if IBKR Gateway is available
    port_available = False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        result = sock.connect_ex((settings.ib_host, settings.ib_port))
        sock.close()
        port_available = (result == 0)
    except Exception:
        port_available = False
    
    if not port_available:
        pytest.skip(f"IBKR Gateway not available at {settings.ib_host}:{settings.ib_port}. Start it with: ./scripts/start_ibgateway_ibc.sh")
    
    # Create provider (executor has faster retry settings: 2s delay, 3 attempts)
    provider = IBKRProvider(settings=settings)
    
    # Give executor a moment to start (connection happens in background)
    time.sleep(1.0)
    
    yield provider
    
    # Cleanup
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(asyncio.wait_for(provider.close(), timeout=10.0))
        loop.close()
    except Exception:
        pass


@pytest.fixture
def past_signals():
    """
    Load past real signals from state files for testing.
    
    Returns list of real signal dictionaries from signals.jsonl if available.
    """
    signals_file = Path("data/nq_agent_state/signals.jsonl")
    signals = []
    
    if signals_file.exists():
        import json
        try:
            with open(signals_file, "r") as f:
                for line in f:
                    try:
                        signal = json.loads(line.strip())
                        signals.append(signal)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
    
    # Return last 10 signals if available
    return signals[-10:] if signals else []

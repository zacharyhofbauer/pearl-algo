import warnings
import pytest
from pathlib import Path

# Suppress noisy deprecation warning from eventkit about missing event loop during tests.
warnings.filterwarnings(
    "ignore", message="There is no current event loop", category=DeprecationWarning
)


@pytest.fixture
def real_data_provider():
    """
    Create a real IBKR data provider for testing with actual market data.
    
    Falls back gracefully if IBKR Gateway is not available.
    """
    try:
        from pearlalgo.data_providers.ibkr.ibkr_provider import IBKRProvider
        from pearlalgo.config.settings import get_settings
        
        settings = get_settings()
        provider = IBKRProvider(settings=settings)
        
        # Try to validate connection (non-blocking check)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, connection will be validated during first use
                pass
            else:
                # Quick connection check
                asyncio.run(provider.validate_connection())
        except Exception:
            # Connection not available, but provider is still valid
            pass
        
        yield provider
        
        # Cleanup
        try:
            asyncio.run(provider.close())
        except Exception:
            pass
            
    except Exception as e:
        pytest.skip(f"Real data provider not available: {e}")


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

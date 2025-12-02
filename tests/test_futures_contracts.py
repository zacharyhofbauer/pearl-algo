from __future__ import annotations

import sys
from pathlib import Path


# Ensure scripts package is importable when running tests from repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pearlalgo.futures.contracts import fut_contract  # noqa: E402
# Legacy import removed - use LangGraph system instead
# from scripts.live_paper_loop import fetch_data  # noqa: E402


def test_build_contract_fields():
    contract = fut_contract("ES", expiry="202412", local_symbol="ESZ4")
    assert contract.exchange == "GLOBEX"
    assert contract.lastTradeDateOrContractMonth == "202412"
    assert contract.localSymbol == "ESZ4"
    assert contract.tradingClass == "ES"


def test_fetch_data_accepts_trading_class():
    """Test fetch_data function - skipped as function is legacy/deprecated."""
    # Legacy function removed - LangGraph system uses data providers directly
    # This test is kept for reference but marked as skip
    import pytest

    pytest.skip("fetch_data is legacy function, use data providers directly")

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Ensure scripts package is importable when running tests from repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pearlalgo.brokers.contracts import build_contract  # noqa: E402
from scripts.live_paper_loop import fetch_data  # noqa: E402


def test_build_contract_fields():
    contract = build_contract(
        "ES",
        sec_type="FUT",
        expiry="202412",
        local_symbol="ESZ4",
        trading_class="ES",
    )
    assert contract.exchange == "GLOBEX"
    assert contract.lastTradeDateOrContractMonth == "202412"
    assert contract.localSymbol == "ESZ4"
    assert getattr(contract, "tradingClass") == "ES"


def test_fetch_data_accepts_trading_class():
    captured = {}

    class StubProvider:
        def fetch_historical(self, symbol, **kwargs):
            captured["symbol"] = symbol
            captured.update(kwargs)
            return pd.DataFrame({"Close": [100.0]}, index=pd.date_range("2024-01-01", periods=1, freq="T"))

    provider = StubProvider()
    df = fetch_data(
        provider,
        symbol="ES",
        sec_type="FUT",
        source="ibkr",
        expiry="202412",
        local_symbol="ESZ4",
        trading_class="ES",
    )

    assert not df.empty
    assert captured["symbol"] == "ES"
    assert captured["expiry"] == "202412"
    assert captured["local_symbol"] == "ESZ4"
    assert captured["trading_class"] == "ES"

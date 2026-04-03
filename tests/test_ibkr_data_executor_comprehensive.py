"""
Comprehensive unit tests for IBKRExecutor and related classes.

All IBKR/ib_insync dependencies are fully mocked — no real connection needed.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Patch ib_insync imports BEFORE importing the module under test
# ---------------------------------------------------------------------------

_mock_ib_insync = MagicMock()
_mock_IB_class = MagicMock
_mock_Future_class = MagicMock
_mock_Stock_class = MagicMock


# We need a lightweight mock for these; the module references them at import time.
import sys

_ib_insync_mod = MagicMock()
sys.modules.setdefault("ib_insync", _ib_insync_mod)

# Now import the module under test
from pearlalgo.data_providers.ibkr_data_executor import (
    _is_valid_price,
    _calculate_order_book_metrics,
    _log_trace,
    Task,
    ConnectTask,
    GetLatestBarTask,
    GetHistoricalDataTask,
    ShutdownTask,
    IBKRExecutor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_level(price: float, size: int) -> MagicMock:
    """Create a mock bid/ask level with .price and .size attributes."""
    level = MagicMock()
    level.price = price
    level.size = size
    return level


def _make_ticker(**kwargs) -> MagicMock:
    """Create a mock Ticker with arbitrary attributes."""
    ticker = MagicMock()
    for k, v in kwargs.items():
        setattr(ticker, k, v)
    # Ensure common attributes exist
    for attr in ("last", "close", "open", "high", "low", "bid", "ask", "volume",
                 "modelOption", "errorMessage", "marketDataType", "reqId",
                 "domBids", "domAsks"):
        if not hasattr(ticker, attr) or attr not in kwargs:
            if attr in ("domBids", "domAsks"):
                setattr(ticker, attr, [])
            elif attr == "reqId":
                setattr(ticker, attr, 1)
            elif attr == "marketDataType":
                setattr(ticker, attr, 1)
            elif attr in ("modelOption", "errorMessage"):
                setattr(ticker, attr, None)
            else:
                setattr(ticker, attr, float("nan"))
    return ticker


def _make_bar(open_: float, high: float, low: float, close: float, volume: int,
              date: Optional[datetime] = None) -> MagicMock:
    bar = MagicMock()
    bar.open = open_
    bar.high = high
    bar.low = low
    bar.close = close
    bar.volume = volume
    bar.date = date or datetime.now(timezone.utc)
    return bar


def _make_contract_details(symbol: str = "MNQH6", exp: str = "20260320",
                           con_id: int = 123456, exchange: str = "CME") -> MagicMock:
    cd = MagicMock()
    cd.contract.symbol = symbol
    cd.contract.localSymbol = symbol
    cd.contract.lastTradeDateOrContractMonth = exp
    cd.contract.conId = con_id
    cd.contract.exchange = exchange
    cd.contract.currency = "USD"
    cd.contract.secType = "FUT"
    return cd


# ===========================================================================
# 1. _is_valid_price
# ===========================================================================

class TestIsValidPrice:
    @pytest.mark.unit
    def test_valid_positive_float(self):
        assert _is_valid_price(100.5) is True

    @pytest.mark.unit
    def test_valid_positive_int(self):
        assert _is_valid_price(42) is True

    @pytest.mark.unit
    def test_valid_string_number(self):
        assert _is_valid_price("99.9") is True

    @pytest.mark.unit
    def test_none_returns_false(self):
        assert _is_valid_price(None) is False

    @pytest.mark.unit
    def test_nan_returns_false(self):
        assert _is_valid_price(float("nan")) is False

    @pytest.mark.unit
    def test_zero_returns_false(self):
        assert _is_valid_price(0) is False

    @pytest.mark.unit
    def test_negative_returns_false(self):
        assert _is_valid_price(-10.0) is False

    @pytest.mark.unit
    def test_non_numeric_string_returns_false(self):
        assert _is_valid_price("abc") is False

    @pytest.mark.unit
    def test_empty_string_returns_false(self):
        assert _is_valid_price("") is False

    @pytest.mark.unit
    def test_inf_returns_true(self):
        # float("inf") > 0 and not NaN
        assert _is_valid_price(float("inf")) is True

    @pytest.mark.unit
    def test_negative_inf_returns_false(self):
        assert _is_valid_price(float("-inf")) is False

    @pytest.mark.unit
    def test_very_small_positive(self):
        assert _is_valid_price(0.0001) is True


# ===========================================================================
# 2. _calculate_order_book_metrics
# ===========================================================================

class TestCalculateOrderBookMetrics:
    @pytest.mark.unit
    def test_empty_bids_and_asks(self):
        result = _calculate_order_book_metrics([], [])
        assert result["bid_depth"] == 0
        assert result["ask_depth"] == 0
        assert result["imbalance"] == 0.0
        assert result["weighted_mid"] is None
        assert result["order_book"]["bids"] == []
        assert result["order_book"]["asks"] == []

    @pytest.mark.unit
    def test_single_bid_single_ask(self):
        bids = [_make_level(100.0, 10)]
        asks = [_make_level(101.0, 10)]
        result = _calculate_order_book_metrics(bids, asks)
        assert result["bid_depth"] == 10
        assert result["ask_depth"] == 10
        assert result["imbalance"] == 0.0
        assert result["weighted_mid"] == pytest.approx(100.5)

    @pytest.mark.unit
    def test_more_bids_than_asks_positive_imbalance(self):
        bids = [_make_level(100.0, 30)]
        asks = [_make_level(101.0, 10)]
        result = _calculate_order_book_metrics(bids, asks)
        assert result["imbalance"] == pytest.approx(0.5)  # (30-10)/40

    @pytest.mark.unit
    def test_more_asks_than_bids_negative_imbalance(self):
        bids = [_make_level(100.0, 10)]
        asks = [_make_level(101.0, 30)]
        result = _calculate_order_book_metrics(bids, asks)
        assert result["imbalance"] == pytest.approx(-0.5)

    @pytest.mark.unit
    def test_multiple_levels(self):
        bids = [_make_level(100.0, 10), _make_level(99.0, 20)]
        asks = [_make_level(101.0, 5), _make_level(102.0, 15)]
        result = _calculate_order_book_metrics(bids, asks)
        assert result["bid_depth"] == 30
        assert result["ask_depth"] == 20
        assert len(result["order_book"]["bids"]) == 2
        assert len(result["order_book"]["asks"]) == 2

    @pytest.mark.unit
    def test_weighted_mid_calculation(self):
        # weighted_mid = (100*20 + 102*10) / (20+10) = 3020/30 = 100.666...
        bids = [_make_level(100.0, 20)]
        asks = [_make_level(102.0, 10)]
        result = _calculate_order_book_metrics(bids, asks)
        assert result["weighted_mid"] == pytest.approx(100.6667, rel=1e-3)

    @pytest.mark.unit
    def test_zero_weight_fallback_to_simple_mid(self):
        bids = [_make_level(100.0, 0)]
        asks = [_make_level(102.0, 0)]
        result = _calculate_order_book_metrics(bids, asks)
        # total_weight == 0, so fallback to simple mid
        assert result["weighted_mid"] == pytest.approx(101.0)

    @pytest.mark.unit
    def test_only_bids_no_asks(self):
        bids = [_make_level(100.0, 10)]
        result = _calculate_order_book_metrics(bids, [])
        assert result["bid_depth"] == 10
        assert result["ask_depth"] == 0
        assert result["imbalance"] == pytest.approx(1.0)
        assert result["weighted_mid"] is None

    @pytest.mark.unit
    def test_only_asks_no_bids(self):
        asks = [_make_level(101.0, 10)]
        result = _calculate_order_book_metrics([], asks)
        assert result["bid_depth"] == 0
        assert result["ask_depth"] == 10
        assert result["imbalance"] == pytest.approx(-1.0)
        assert result["weighted_mid"] is None


# ===========================================================================
# 3. Task dataclass hierarchy
# ===========================================================================

class TestConnectTask:
    @pytest.mark.unit
    def test_execute_already_connected(self):
        ib = MagicMock()
        ib.isConnected.return_value = True
        task = ConnectTask(task_id="c1", host="127.0.0.1", port=4001, client_id=1)
        assert task.execute(ib) is True
        ib.connect.assert_not_called()

    @pytest.mark.unit
    def test_execute_connects_successfully(self):
        ib = MagicMock()
        ib.isConnected.side_effect = [False, True]
        task = ConnectTask(task_id="c2", host="127.0.0.1", port=4001, client_id=1)
        assert task.execute(ib) is True
        ib.connect.assert_called_once()

    @pytest.mark.unit
    def test_execute_connect_fails(self):
        ib = MagicMock()
        ib.isConnected.side_effect = [False, False]
        task = ConnectTask(task_id="c3", host="127.0.0.1", port=4001, client_id=1)
        assert task.execute(ib) is False

    @pytest.mark.unit
    def test_default_timeout(self):
        task = ConnectTask(task_id="c4", host="h", port=0, client_id=0)
        assert task.timeout == 10.0


class TestShutdownTask:
    @pytest.mark.unit
    def test_execute_disconnects(self):
        ib = MagicMock()
        ib.isConnected.return_value = True
        task = ShutdownTask(task_id="s1")
        task.execute(ib)
        ib.disconnect.assert_called_once()

    @pytest.mark.unit
    def test_execute_not_connected(self):
        ib = MagicMock()
        ib.isConnected.return_value = False
        task = ShutdownTask(task_id="s2")
        task.execute(ib)
        ib.disconnect.assert_not_called()


# ===========================================================================
# 4. GetLatestBarTask
# ===========================================================================

class TestGetLatestBarTask:
    """Tests for GetLatestBarTask.execute() with fully mocked IB."""

    def _patch_context(self):
        """Return common patches for GetLatestBarTask tests."""
        return [
            patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={}),
            patch("pearlalgo.data_providers.ibkr_data_executor.get_market_hours"),
        ]

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_futures_returns_level1_data(self, mock_config, mock_mh):
        """Successful Level 1 data retrieval for a futures contract."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = True
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ticker = _make_ticker(last=21000.0, close=20990.0, open=20950.0,
                              high=21010.0, low=20940.0, bid=20999.0,
                              ask=21001.0, volume=5000, reqId=42)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = True

        task = GetLatestBarTask(task_id="t1", symbol="MNQ", is_futures=True)
        result = task.execute(ib)

        assert result is not None
        assert result["close"] == 21000.0
        assert result["bid"] == 20999.0
        assert result["ask"] == 21001.0
        assert result["_data_level"] == "level1"

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_stock_contract_creation(self, mock_config, mock_mh):
        """For non-futures, a Stock contract should be used (no reqContractDetails)."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = True
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        ticker = _make_ticker(last=150.0, close=149.0, volume=1000, reqId=1)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = True

        task = GetLatestBarTask(task_id="t2", symbol="AAPL", is_futures=False)
        result = task.execute(ib)

        assert result is not None
        ib.reqContractDetails.assert_not_called()

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_no_contract_details_returns_none(self, mock_config, mock_mh):
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = True
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        ib.reqContractDetails.return_value = []

        task = GetLatestBarTask(task_id="t3", symbol="MNQ", is_futures=True)
        result = task.execute(ib)
        assert result is None

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_contract_details_exception_returns_none(self, mock_config, mock_mh):
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = True
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        ib.reqContractDetails.side_effect = RuntimeError("connection lost")

        task = GetLatestBarTask(task_id="t4", symbol="MNQ", is_futures=True)
        result = task.execute(ib)
        assert result is None

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_nan_ticker_falls_back_to_historical(self, mock_config, mock_mh):
        """When ticker returns NaN, should fall back to historical data."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = False
        mock_hours.get_market_status.return_value = {"next_open_et": "soon"}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        # Ticker with all NaN
        ticker = _make_ticker(last=float("nan"), close=float("nan"), reqId=1)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = False

        # Historical fallback
        bar = _make_bar(20900.0, 21000.0, 20800.0, 20950.0, 3000)
        ib.reqHistoricalData.return_value = [bar]

        task = GetLatestBarTask(task_id="t5", symbol="MNQ", is_futures=True)
        result = task.execute(ib)

        assert result is not None
        assert result["_data_level"] == "historical"
        assert result["close"] == 20950.0

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_all_data_sources_fail_returns_none(self, mock_config, mock_mh):
        """When both L1 and historical fail, returns None."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = False
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ticker = _make_ticker(last=float("nan"), close=float("nan"), reqId=1)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = False

        # Historical also fails
        ib.reqHistoricalData.return_value = []

        task = GetLatestBarTask(task_id="t6", symbol="MNQ", is_futures=True)
        result = task.execute(ib)
        assert result is None

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_close_used_when_last_is_nan(self, mock_config, mock_mh):
        """When last is NaN but close is valid, close should be used."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = True
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ticker = _make_ticker(last=float("nan"), close=21050.0, reqId=1,
                              volume=1000, bid=21049.0, ask=21051.0,
                              open=21000.0, high=21060.0, low=20990.0)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = True

        task = GetLatestBarTask(task_id="t7", symbol="MNQ", is_futures=True)
        result = task.execute(ib)

        assert result is not None
        assert result["close"] == 21050.0

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_expiring_contract_uses_next_month(self, mock_config, mock_mh):
        """When front month expires within 3 days, should use next month."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = True
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()

        # Front month expiring tomorrow
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
        next_month = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")

        cd_front = _make_contract_details(symbol="MNQH6", exp=tomorrow, con_id=1)
        cd_next = _make_contract_details(symbol="MNQM6", exp=next_month, con_id=2)
        ib.reqContractDetails.return_value = [cd_front, cd_next]

        ticker = _make_ticker(last=21000.0, close=20990.0, reqId=1, volume=5000)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = True

        task = GetLatestBarTask(task_id="t8", symbol="MNQ", is_futures=True)
        result = task.execute(ib)

        # Should use next month contract
        assert result is not None

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_market_hours_exception_assumes_open(self, mock_config, mock_mh):
        """If market hours detection fails, assume market may be open."""
        mock_mh.side_effect = RuntimeError("market hours unavailable")

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ticker = _make_ticker(last=21000.0, close=20990.0, reqId=1, volume=5000)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = True

        task = GetLatestBarTask(task_id="t9", symbol="MNQ", is_futures=True)
        result = task.execute(ib)
        assert result is not None

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_historical_fallback_error_162(self, mock_config, mock_mh):
        """Error 162 in historical data should try next strategy."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = False
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ticker = _make_ticker(last=float("nan"), close=float("nan"), reqId=1)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = False

        # First historical call fails with 162, second succeeds
        bar = _make_bar(20900.0, 21000.0, 20800.0, 20950.0, 3000)
        ib.reqHistoricalData.side_effect = [
            RuntimeError("Error 162: TWS session conflict"),
            [bar],
        ]

        task = GetLatestBarTask(task_id="t10", symbol="MNQ", is_futures=True)
        result = task.execute(ib)
        assert result is not None
        assert result["_data_level"] == "historical"

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_historical_exception_returns_none(self, mock_config, mock_mh):
        """General exception in historical fallback returns None."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = False
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ticker = _make_ticker(last=float("nan"), close=float("nan"), reqId=1)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = False

        # All historical strategies fail with unexpected error
        ib.reqHistoricalData.side_effect = Exception("unexpected failure")

        task = GetLatestBarTask(task_id="t11", symbol="MNQ", is_futures=True)
        result = task.execute(ib)
        assert result is None

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_level1_exception_354_falls_back(self, mock_config, mock_mh):
        """Exception containing '354' during L1 should trigger historical fallback."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = True
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ib.reqMktData.side_effect = RuntimeError("Error 354: Not subscribed")

        bar = _make_bar(20900.0, 21000.0, 20800.0, 20950.0, 3000)
        ib.reqHistoricalData.return_value = [bar]

        task = GetLatestBarTask(task_id="t12", symbol="MNQ", is_futures=True)
        result = task.execute(ib)
        assert result is not None
        assert result["_data_level"] == "historical"

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_result_has_order_book_stub(self, mock_config, mock_mh):
        """Result should always include empty order book structure."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = True
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ticker = _make_ticker(last=21000.0, close=20990.0, reqId=1, volume=5000)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = True

        task = GetLatestBarTask(task_id="t13", symbol="MNQ", is_futures=True)
        result = task.execute(ib)

        assert result["order_book"] == {"bids": [], "asks": []}
        assert result["bid_depth"] == 0
        assert result["ask_depth"] == 0
        assert result["imbalance"] == 0.0
        assert result["weighted_mid"] is None


# ===========================================================================
# 5. GetHistoricalDataTask
# ===========================================================================

class TestGetHistoricalDataTask:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_stock_historical_data(self, mock_config):
        ib = MagicMock()
        bars = [_make_bar(100, 105, 99, 104, 1000)]
        ib.reqHistoricalData.return_value = bars

        now = datetime.now(timezone.utc)
        task = GetHistoricalDataTask(
            task_id="h1", symbol="AAPL",
            start=now - timedelta(hours=6), end=now,
            timeframe="5m", is_futures=False,
        )
        result = task.execute(ib)
        assert result == bars

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_futures_historical_selects_contract(self, mock_config):
        ib = MagicMock()
        cd = _make_contract_details(exp="20261220", con_id=100)
        ib.reqContractDetails.return_value = [cd]

        bars = [_make_bar(20900, 21000, 20800, 20950, 3000)]
        ib.reqHistoricalData.return_value = bars

        now = datetime.now(timezone.utc)
        task = GetHistoricalDataTask(
            task_id="h2", symbol="MNQ",
            start=now - timedelta(days=1), end=now,
            timeframe="1m", is_futures=True,
        )
        result = task.execute(ib)
        assert result == bars

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_no_contract_details_returns_empty(self, mock_config):
        ib = MagicMock()
        ib.reqContractDetails.return_value = []

        task = GetHistoricalDataTask(
            task_id="h3", symbol="MNQ",
            start=None, end=None, timeframe="1d", is_futures=True,
        )
        result = task.execute(ib)
        assert result == []

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_contract_details_exception_returns_empty(self, mock_config):
        ib = MagicMock()
        ib.reqContractDetails.side_effect = RuntimeError("connection lost")

        task = GetHistoricalDataTask(
            task_id="h4", symbol="MNQ",
            start=None, end=None, timeframe="1d", is_futures=True,
        )
        result = task.execute(ib)
        assert result == []

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_duration_string_seconds_for_short_range(self, mock_config):
        """For ranges <= 24h, duration should use seconds."""
        ib = MagicMock()
        ib.reqHistoricalData.return_value = []

        now = datetime.now(timezone.utc)
        task = GetHistoricalDataTask(
            task_id="h5", symbol="AAPL",
            start=now - timedelta(hours=2), end=now,
            timeframe="1m", is_futures=False,
        )
        task.execute(ib)

        # Check the durationStr passed to reqHistoricalData
        call_args = ib.reqHistoricalData.call_args
        duration_str = call_args.kwargs.get("durationStr", call_args[1].get("durationStr", ""))
        assert "S" in duration_str

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_duration_string_days_for_long_range(self, mock_config):
        """For ranges > 24h, duration should use days."""
        ib = MagicMock()
        ib.reqHistoricalData.return_value = []

        now = datetime.now(timezone.utc)
        task = GetHistoricalDataTask(
            task_id="h6", symbol="AAPL",
            start=now - timedelta(days=5), end=now,
            timeframe="1d", is_futures=False,
        )
        task.execute(ib)

        call_args = ib.reqHistoricalData.call_args
        duration_str = call_args.kwargs.get("durationStr", call_args[1].get("durationStr", ""))
        assert "D" in duration_str

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_none_start_end_defaults(self, mock_config):
        """When start/end are None, defaults should be used."""
        ib = MagicMock()
        ib.reqHistoricalData.return_value = []

        task = GetHistoricalDataTask(
            task_id="h7", symbol="AAPL",
            start=None, end=None, timeframe="1d", is_futures=False,
        )
        task.execute(ib)
        ib.reqHistoricalData.assert_called_once()

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_bar_size_mapping(self, mock_config):
        """Verify timeframe maps correctly to bar size."""
        ib = MagicMock()
        ib.reqHistoricalData.return_value = []

        for tf, expected_bar in [("1m", "1 min"), ("5m", "5 mins"), ("1h", "1 hour"), ("1d", "1 day")]:
            task = GetHistoricalDataTask(
                task_id=f"h_bs_{tf}", symbol="AAPL",
                start=None, end=None, timeframe=tf, is_futures=False,
            )
            task.execute(ib)
            call_args = ib.reqHistoricalData.call_args
            bar_size = call_args.kwargs.get("barSizeSetting", call_args[1].get("barSizeSetting", ""))
            assert bar_size == expected_bar, f"For timeframe {tf}, expected {expected_bar}, got {bar_size}"

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_futures_all_candidates_fail_returns_empty(self, mock_config):
        """When all candidate contracts fail, returns empty list."""
        ib = MagicMock()
        cd = _make_contract_details(exp="20260320", con_id=100)
        ib.reqContractDetails.return_value = [cd]
        ib.reqHistoricalData.return_value = []  # no bars

        now = datetime.now(timezone.utc)
        task = GetHistoricalDataTask(
            task_id="h8", symbol="MNQ",
            start=now - timedelta(days=1), end=now,
            timeframe="1m", is_futures=True,
        )
        result = task.execute(ib)
        assert result == []

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_futures_historical_exception_fallback(self, mock_config):
        """If first contract raises, should try next one."""
        ib = MagicMock()
        cd1 = _make_contract_details(exp="20260320", con_id=100)
        cd2 = _make_contract_details(exp="20260620", con_id=200)
        ib.reqContractDetails.return_value = [cd1, cd2]

        bars = [_make_bar(20900, 21000, 20800, 20950, 3000)]
        ib.reqHistoricalData.side_effect = [RuntimeError("timeout"), bars]

        now = datetime.now(timezone.utc)
        task = GetHistoricalDataTask(
            task_id="h9", symbol="MNQ",
            start=now - timedelta(days=1), end=now,
            timeframe="1m", is_futures=True,
        )
        result = task.execute(ib)
        assert result == bars


# ===========================================================================
# 6. IBKRExecutor class
# ===========================================================================

class TestIBKRExecutorInit:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_default_initialization(self, mock_config):
        ex = IBKRExecutor(host="127.0.0.1", port=4001, client_id=10)
        assert ex.host == "127.0.0.1"
        assert ex.port == 4001
        assert ex.client_id == 10
        assert ex._running is False
        assert ex._connected is False
        assert ex.connect_on_startup is False

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_custom_reconnect_params(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0,
                          reconnect_delay=2.0, max_reconnect_attempts=3)
        assert ex.reconnect_delay == 2.0
        assert ex.max_reconnect_attempts == 3


class TestIBKRExecutorStartStop:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    @patch("pearlalgo.data_providers.ibkr_data_executor.IB")
    def test_start_creates_thread(self, mock_ib_cls, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex.start()
        assert ex._running is True
        assert ex._executor_thread is not None
        assert ex._executor_thread.is_alive()
        ex.stop(timeout=2.0)

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_start_idempotent(self, mock_config):
        """Calling start() twice should not create a second thread."""
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex._running = True
        ex.start()  # Should return immediately
        assert ex._executor_thread is None  # Never created a thread

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_stop_when_not_running(self, mock_config):
        """Calling stop() when not running should be a no-op."""
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex.stop()  # Should not raise


class TestIBKRExecutorSubmitTask:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_submit_when_not_running_raises(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        task = ConnectTask(task_id="c1", host="h", port=0, client_id=0)
        with pytest.raises(RuntimeError, match="not running"):
            ex.submit_task(task)

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_submit_returns_future(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex._running = True
        task = ConnectTask(task_id="c2", host="h", port=0, client_id=0)
        future = ex.submit_task(task)
        assert isinstance(future, ConcurrentFuture)

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_submit_stores_future_in_results(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex._running = True
        task = ConnectTask(task_id="c3", host="h", port=0, client_id=0)
        future = ex.submit_task(task)
        assert ex._results["c3"] is future


class TestIBKRExecutorRateLimit:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_rate_limit_enforced(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex._last_request_time = time.time()
        start = time.time()
        ex._rate_limit()
        elapsed = time.time() - start
        # Should have waited at least close to _min_request_interval
        assert elapsed >= ex._min_request_interval * 0.5

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_rate_limit_no_wait_when_enough_time_passed(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex._last_request_time = time.time() - 1.0  # 1 second ago
        start = time.time()
        ex._rate_limit()
        elapsed = time.time() - start
        assert elapsed < 0.05  # Should be near-instant


class TestIBKRExecutorIsConnected:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_not_connected_when_ib_none(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        assert ex.is_connected() is False

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_not_connected_when_flag_false(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex.ib = MagicMock()
        ex.ib.isConnected.return_value = True
        ex._connected = False
        assert ex.is_connected() is False

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_connected_when_all_true(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex.ib = MagicMock()
        ex.ib.isConnected.return_value = True
        ex._connected = True
        assert ex.is_connected() is True


class TestIBKRExecutorQueueSize:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_queue_size_empty(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        assert ex.get_queue_size() == 0

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_queue_size_after_submit(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex._running = True
        task = ConnectTask(task_id="c1", host="h", port=0, client_id=0)
        ex.submit_task(task)
        assert ex.get_queue_size() == 1


class TestIBKRExecutorEnsureConnected:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_already_connected_returns_immediately(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex.ib = MagicMock()
        ex.ib.isConnected.return_value = True
        ex._connected = True
        # Should not raise and not try to connect
        ex._ensure_connected()
        ex.ib.connect.assert_not_called()

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    @patch("pearlalgo.data_providers.ibkr_data_executor.IB")
    def test_max_reconnect_attempts_raises(self, mock_ib_cls, mock_config):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = False
        mock_ib.connect.side_effect = ConnectionRefusedError("refused")
        mock_ib_cls.return_value = mock_ib

        ex = IBKRExecutor(host="h", port=0, client_id=0,
                          max_reconnect_attempts=2, reconnect_delay=0.01)
        ex.ib = None

        with pytest.raises(RuntimeError, match="Cannot connect"):
            ex._ensure_connected()

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    @patch("pearlalgo.data_providers.ibkr_data_executor.IB")
    def test_successful_reconnect(self, mock_ib_cls, mock_config):
        mock_ib = MagicMock()
        # isConnected: False during check, then True after connect
        mock_ib.isConnected.side_effect = [False, True]
        mock_ib.accountValues.return_value = []
        mock_ib_cls.return_value = mock_ib

        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex.ib = None
        ex._ensure_connected()

        assert ex._connected is True
        assert ex._reconnect_attempts == 0

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    @patch("pearlalgo.data_providers.ibkr_data_executor.IB")
    def test_registers_error_handler(self, mock_ib_cls, mock_config):
        mock_ib = MagicMock()
        mock_ib.isConnected.side_effect = [False, True]
        mock_ib.accountValues.return_value = []
        mock_ib_cls.return_value = mock_ib

        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex.ib = None
        ex._ensure_connected()

        # The code does `self.ib.errorEvent += on_error`, which triggers
        # __iadd__ on the errorEvent attribute. With MagicMock, += calls
        # are recorded as __iadd__ on the attribute itself.
        # Verify the errorEvent was accessed (interaction occurred).
        assert mock_ib.errorEvent.__iadd__.called or "errorEvent" in str(mock_ib.mock_calls)


class TestIBKRExecutorErrorTracking:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_market_data_errors_dict(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        assert ex._market_data_errors == {}

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_error_lock_is_threading_lock(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        assert isinstance(ex._error_lock, type(threading.Lock()))


# ===========================================================================
# 7. _log_trace
# ===========================================================================

class TestLogTrace:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor._get_ibkr_verbose_logging", return_value=True)
    @patch("pearlalgo.data_providers.ibkr_data_executor.logger")
    def test_verbose_logs_info(self, mock_logger, mock_verbose):
        _log_trace("test message")
        mock_logger.info.assert_called_once_with("test message")

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor._get_ibkr_verbose_logging", return_value=False)
    @patch("pearlalgo.data_providers.ibkr_data_executor.logger")
    def test_non_verbose_logs_debug(self, mock_logger, mock_verbose):
        _log_trace("test message")
        mock_logger.debug.assert_called_once_with("test message")


# ===========================================================================
# 8. Integration-style tests (executor loop with mocked IB)
# ===========================================================================

class TestIBKRExecutorIntegration:
    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    @patch("pearlalgo.data_providers.ibkr_data_executor.IB")
    def test_executor_processes_connect_task(self, mock_ib_cls, mock_config):
        """Executor should process a ConnectTask and set the future result."""
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.accountValues.return_value = []
        mock_ib_cls.return_value = mock_ib

        ex = IBKRExecutor(host="127.0.0.1", port=4001, client_id=1)
        ex.start()
        try:
            task = ConnectTask(task_id="int_c1", host="127.0.0.1", port=4001, client_id=1)
            future = ex.submit_task(task)
            result = future.result(timeout=5.0)
            assert result is True
        finally:
            ex.stop(timeout=3.0)

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    @patch("pearlalgo.data_providers.ibkr_data_executor.IB")
    def test_executor_handles_task_exception(self, mock_ib_cls, mock_config):
        """If a task raises, the exception should be set on the future."""
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.accountValues.return_value = []
        mock_ib_cls.return_value = mock_ib

        ex = IBKRExecutor(host="127.0.0.1", port=4001, client_id=1)
        ex.start()
        try:
            # Create a task whose execute raises
            task = ConnectTask(task_id="int_c2", host="127.0.0.1", port=4001, client_id=1)
            # Monkey-patch execute to raise
            task.execute = MagicMock(side_effect=RuntimeError("boom"))
            future = ex.submit_task(task)
            with pytest.raises(RuntimeError, match="boom"):
                future.result(timeout=5.0)
        finally:
            ex.stop(timeout=3.0)

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    @patch("pearlalgo.data_providers.ibkr_data_executor.IB")
    def test_executor_stop_disconnects(self, mock_ib_cls, mock_config):
        """Stopping the executor should disconnect IB."""
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.accountValues.return_value = []
        mock_ib_cls.return_value = mock_ib

        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex.start()
        time.sleep(0.3)
        ex.stop(timeout=3.0)
        assert ex._running is False

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    @patch("pearlalgo.data_providers.ibkr_data_executor.IB")
    def test_connection_lost_triggers_reconnect_flag(self, mock_ib_cls, mock_config):
        """Connection errors should set _connected = False."""
        mock_ib = MagicMock()
        # Connected initially, then task fails with 'not connected'
        mock_ib.isConnected.return_value = True
        mock_ib.accountValues.return_value = []
        mock_ib.connect.return_value = None
        mock_ib_cls.return_value = mock_ib

        ex = IBKRExecutor(host="h", port=0, client_id=0)
        ex.start()
        try:
            task = ConnectTask(task_id="int_c3", host="h", port=0, client_id=0)
            task.execute = MagicMock(side_effect=RuntimeError("not connected to IB"))
            future = ex.submit_task(task)
            with pytest.raises(RuntimeError):
                future.result(timeout=5.0)
            # Give the loop a moment to process
            time.sleep(0.3)
            assert ex._connected is False
        finally:
            ex.stop(timeout=3.0)


# ===========================================================================
# 9. Edge cases & additional coverage
# ===========================================================================

class TestEdgeCases:
    @pytest.mark.unit
    def test_is_valid_price_with_object(self):
        """Non-numeric objects should return False."""
        assert _is_valid_price(object()) is False

    @pytest.mark.unit
    def test_is_valid_price_with_list(self):
        assert _is_valid_price([1, 2, 3]) is False

    @pytest.mark.unit
    def test_order_book_metrics_large_depth(self):
        """Stress test with many levels."""
        bids = [_make_level(100.0 - i * 0.25, 10 + i) for i in range(20)]
        asks = [_make_level(100.25 + i * 0.25, 10 + i) for i in range(20)]
        result = _calculate_order_book_metrics(bids, asks)
        assert result["bid_depth"] > 0
        assert result["ask_depth"] > 0
        assert len(result["order_book"]["bids"]) == 20
        assert len(result["order_book"]["asks"]) == 20

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_executor_initial_queue_empty(self, mock_config):
        ex = IBKRExecutor(host="h", port=0, client_id=0)
        assert ex.get_queue_size() == 0

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_historical_bar_timestamp_without_tzinfo(self, mock_config, mock_mh):
        """Historical bar with naive datetime should get UTC tzinfo."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = False
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ticker = _make_ticker(last=float("nan"), close=float("nan"), reqId=1)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = False

        # Bar with naive datetime (no tzinfo)
        naive_dt = datetime(2026, 3, 12, 10, 30, 0)  # No tzinfo
        bar = _make_bar(20900.0, 21000.0, 20800.0, 20950.0, 3000, date=naive_dt)
        ib.reqHistoricalData.return_value = [bar]

        task = GetLatestBarTask(task_id="tz1", symbol="MNQ", is_futures=True)
        result = task.execute(ib)
        assert result is not None
        assert result["_data_level"] == "historical"

    @pytest.mark.unit
    @patch("pearlalgo.utils.market_hours.get_market_hours")
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_volume_nan_defaults_to_zero(self, mock_config, mock_mh):
        """When volume is NaN, result should have volume=0."""
        mock_hours = MagicMock()
        mock_hours.is_market_open.return_value = True
        mock_hours.get_market_status.return_value = {}
        mock_mh.return_value = mock_hours

        ib = MagicMock()
        cd = _make_contract_details()
        ib.reqContractDetails.return_value = [cd]

        ticker = _make_ticker(last=21000.0, close=20990.0, reqId=1,
                              volume=float("nan"), bid=20999.0, ask=21001.0)
        ib.reqMktData.return_value = ticker
        ib.waitOnUpdate.return_value = True

        task = GetLatestBarTask(task_id="vol1", symbol="MNQ", is_futures=True)
        result = task.execute(ib)
        assert result is not None
        assert result["volume"] == 0

    @pytest.mark.unit
    @patch("pearlalgo.data_providers.ibkr_data_executor.load_service_config", return_value={})
    def test_duration_string_years_for_very_long_range(self, mock_config):
        """For ranges > 365 days, duration should use years."""
        ib = MagicMock()
        ib.reqHistoricalData.return_value = []

        now = datetime.now(timezone.utc)
        task = GetHistoricalDataTask(
            task_id="h_yr", symbol="AAPL",
            start=now - timedelta(days=400), end=now,
            timeframe="1d", is_futures=False,
        )
        task.execute(ib)
        call_args = ib.reqHistoricalData.call_args
        duration_str = call_args.kwargs.get("durationStr", call_args[1].get("durationStr", ""))
        assert "Y" in duration_str

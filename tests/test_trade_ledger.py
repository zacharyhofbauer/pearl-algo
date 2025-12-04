"""
Tests for trade ledger (immutable SQLite ledger).
"""

import pytest
import sqlite3
from datetime import datetime
from pathlib import Path
import tempfile

from pearlalgo.persistence.trade_ledger import TradeLedger
from pearlalgo.core.events import FillEvent, OrderEvent


class TestTradeLedger:
    """Test trade ledger functionality."""

    @pytest.fixture
    def ledger(self):
        """Create a temporary trade ledger for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_ledger.db"
            ledger = TradeLedger(db_path=str(db_path))
            yield ledger

    def test_record_fill(self, ledger):
        """Test recording a fill."""
        fill = FillEvent(
            timestamp=datetime.now(),
            symbol="QQQ",
            side="BUY",
            quantity=1.0,
            price=400.0,
            commission=1.0,
        )

        ledger.record_fill(fill, order_id="TEST_001")

        fills = ledger.get_fills(symbol="QQQ")
        assert len(fills) == 1
        assert fills[0]["symbol"] == "QQQ"
        assert fills[0]["quantity"] == 1.0

    def test_record_order(self, ledger):
        """Test recording an order."""
        order = OrderEvent(
            timestamp=datetime.now(),
            symbol="QQQ",
            side="BUY",
            quantity=1.0,
            order_type="LMT",
            limit_price=400.0,
        )

        ledger.record_order(order, order_id="TEST_001", status="Pending")

        orders = ledger.get_orders(symbol="QQQ")
        assert len(orders) == 1
        assert orders[0]["symbol"] == "QQQ"
        assert orders[0]["status"] == "Pending"

    def test_update_order_status(self, ledger):
        """Test updating order status."""
        order = OrderEvent(
            timestamp=datetime.now(),
            symbol="QQQ",
            side="BUY",
            quantity=1.0,
        )

        ledger.record_order(order, order_id="TEST_001", status="Pending")
        ledger.update_order_status("TEST_001", "Filled")

        orders = ledger.get_orders(status="Filled")
        assert len(orders) == 1
        assert orders[0]["status"] == "Filled"

    def test_get_fills_with_filters(self, ledger):
        """Test querying fills with filters."""
        now = datetime.now()

        # Create multiple fills
        for i in range(3):
            fill = FillEvent(
                timestamp=now,
                symbol="QQQ" if i < 2 else "SPY",
                side="BUY",
                quantity=1.0,
                price=400.0 + i,
            )
            ledger.record_fill(fill, order_id=f"TEST_{i:03d}")

        # Filter by symbol
        qqq_fills = ledger.get_fills(symbol="QQQ")
        assert len(qqq_fills) == 2

        # Filter by date
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        recent_fills = ledger.get_fills(since=since)
        assert len(recent_fills) == 3

    def test_get_daily_pnl(self, ledger):
        """Test daily PnL calculation."""
        now = datetime.now()

        # Buy fill
        buy_fill = FillEvent(
            timestamp=now,
            symbol="QQQ",
            side="BUY",
            quantity=1.0,
            price=400.0,
            commission=1.0,
        )
        ledger.record_fill(buy_fill, order_id="BUY_001")

        # Sell fill
        sell_fill = FillEvent(
            timestamp=now,
            symbol="QQQ",
            side="SELL",
            quantity=1.0,
            price=410.0,
            commission=1.0,
        )
        ledger.record_fill(sell_fill, order_id="SELL_001")

        daily_pnl = ledger.get_daily_pnl(date=now)

        # PnL = (sell - buy) - commissions = (410 - 400) - 2 = 8
        assert daily_pnl["realized_pnl"] == pytest.approx(8.0, abs=0.01)
        assert daily_pnl["num_fills"] == 2





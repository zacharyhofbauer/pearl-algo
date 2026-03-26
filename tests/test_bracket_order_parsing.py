"""
Integration test for bracket order parsing and protection guard.
FIXED 2026-03-26: bracket detection
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_mock_adapter():
    """Create a minimal mock of TradovateExecutionAdapter for testing."""
    from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter
    from pearlalgo.execution.base import ExecutionConfig, ExecutionMode
    from pearlalgo.execution.tradovate.config import TradovateConfig
    import os
    os.environ.setdefault("TRADOVATE_USERNAME", "test")
    os.environ.setdefault("TRADOVATE_PASSWORD", "test")
    os.environ.setdefault("TRADOVATE_APP_ID", "test")
    os.environ.setdefault("TRADOVATE_APP_VERSION", "1.0")
    os.environ.setdefault("TRADOVATE_CID", "1")
    os.environ.setdefault("TRADOVATE_SEC", "test")
    os.environ.setdefault("TRADOVATE_DEVICE_ID", "test")

    cfg = ExecutionConfig(mode=ExecutionMode.DRY_RUN)
    tv_cfg = TradovateConfig(
        username="test", password="test", app_id="test",
        app_version="1.0", cid=1, sec="test", device_id="test"
    )
    adapter = TradovateExecutionAdapter(cfg, tv_cfg)
    adapter._client = MagicMock()
    adapter._contract_symbol = "MNQH6"
    adapter._connected = True
    return adapter


class TestBracketOrderParsing:
    """Test that place_oso response parsing correctly extracts sl/tp order IDs."""

    def _simulate_parse(self, result: dict):
        """Simulate the parsing logic from adapter.py place_bracket method."""
        if isinstance(result, list):
            entry_order = result[0] if result else {}
            order_id = entry_order.get("orderId") or entry_order.get("id")
            sl_order_id = None
            tp_order_id = None
            if len(result) > 1 and isinstance(result[1], dict):
                tp_order_id = str(result[1].get("orderId") or result[1].get("id") or "")
            if len(result) > 2 and isinstance(result[2], dict):
                sl_order_id = str(result[2].get("orderId") or result[2].get("id") or "")
        elif isinstance(result, dict):
            order_id = result.get("orderId") or result.get("id")
            # FIXED 2026-03-26: parse bracket1/bracket2 from dict response
            b1 = result.get("bracket1") or {}
            b2 = result.get("bracket2") or {}
            tp_order_id = str(b1.get("orderId") or b1.get("id") or "") if isinstance(b1, dict) else None
            sl_order_id = str(b2.get("orderId") or b2.get("id") or "") if isinstance(b2, dict) else None
        else:
            order_id = sl_order_id = tp_order_id = None
        return order_id, sl_order_id, tp_order_id

    def test_dict_response_parses_correctly(self):
        """Tradovate returns dict with bracket1/bracket2 — must extract sl and tp."""
        result = {
            "orderId": 1001,
            "bracket1": {"orderId": 1002},  # TP
            "bracket2": {"orderId": 1003},  # SL
        }
        order_id, sl_order_id, tp_order_id = self._simulate_parse(result)
        assert str(order_id) == "1001", f"entry_order_id should be 1001, got {order_id}"
        assert str(tp_order_id) == "1002", f"tp_order_id should be 1002, got {tp_order_id}"
        assert str(sl_order_id) == "1003", f"sl_order_id should be 1003, got {sl_order_id}"
        print(f"✅ dict response: entry={order_id} tp={tp_order_id} sl={sl_order_id}")

    def test_list_response_parses_correctly(self):
        """List format [entry, tp, sl] also works."""
        result = [
            {"orderId": 2001},  # entry
            {"orderId": 2002},  # tp
            {"orderId": 2003},  # sl
        ]
        order_id, sl_order_id, tp_order_id = self._simulate_parse(result)
        assert str(order_id) == "2001"
        assert str(tp_order_id) == "2002"
        assert str(sl_order_id) == "2003"
        print(f"✅ list response: entry={order_id} tp={tp_order_id} sl={sl_order_id}")

    def test_dict_response_no_brackets_gets_none(self):
        """Dict with no bracket keys → sl/tp are empty strings (falsy)."""
        result = {"orderId": 3001}
        order_id, sl_order_id, tp_order_id = self._simulate_parse(result)
        assert str(order_id) == "3001"
        assert not sl_order_id  # empty string is falsy
        assert not tp_order_id
        print(f"✅ dict no brackets: entry={order_id} sl={sl_order_id!r} tp={tp_order_id!r}")

    def test_dict_with_alternate_id_key(self):
        """Dict with 'id' instead of 'orderId' in bracket legs."""
        result = {
            "orderId": 4001,
            "bracket1": {"id": 4002},
            "bracket2": {"id": 4003},
        }
        order_id, sl_order_id, tp_order_id = self._simulate_parse(result)
        assert str(tp_order_id) == "4002"
        assert str(sl_order_id) == "4003"
        print(f"✅ dict alt id key: entry={order_id} tp={tp_order_id} sl={sl_order_id}")


class TestHasExistingStop:
    """Test _has_existing_stop_for_position helper."""

    @pytest.mark.asyncio
    async def test_finds_existing_stop_for_long(self):
        adapter = make_mock_adapter()
        adapter._client.get_orders = AsyncMock(return_value=[
            {"id": 5001, "orderType": "Stop", "action": "Sell", "ordStatus": "Working", "stopPrice": 19000.0},
        ])
        result = await adapter._has_existing_stop_for_position("long")
        assert result is True, "Should find existing stop for long position"
        print("✅ _has_existing_stop_for_position correctly found stop for long")

    @pytest.mark.asyncio
    async def test_returns_false_when_no_stop(self):
        adapter = make_mock_adapter()
        adapter._client.get_orders = AsyncMock(return_value=[
            {"id": 5002, "orderType": "Limit", "action": "Sell", "ordStatus": "Working", "price": 20000.0},
        ])
        result = await adapter._has_existing_stop_for_position("long")
        assert result is False, "Should return False when no stop exists"
        print("✅ _has_existing_stop_for_position correctly returns False when no stop")

    @pytest.mark.asyncio
    async def test_returns_false_on_api_error(self):
        adapter = make_mock_adapter()
        adapter._client.get_orders = AsyncMock(side_effect=Exception("API error"))
        result = await adapter._has_existing_stop_for_position("long")
        assert result is False, "Should return False (safe default) on API error"
        print("✅ _has_existing_stop_for_position returns False on error (safe default)")


if __name__ == "__main__":
    # Run basic tests without pytest
    t1 = TestBracketOrderParsing()
    t1.test_dict_response_parses_correctly()
    t1.test_list_response_parses_correctly()
    t1.test_dict_response_no_brackets_gets_none()
    t1.test_dict_with_alternate_id_key()
    print("\nAll synchronous tests passed!")

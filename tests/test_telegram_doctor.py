"""Tests for Telegram /doctor rollup."""

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from pearlalgo.learning.trade_database import TradeDatabase


class MockChat:
    def __init__(self, chat_id: int):
        self.id = chat_id


class MockUser:
    def __init__(self, user_id: int = 1):
        self.id = user_id
        self.username = "test"


class MockMessage:
    def __init__(self, chat_id: int):
        self.chat = MockChat(chat_id)
        self.text = ""

    async def reply_text(self, text: str, **kwargs):
        return None


class MockUpdate:
    def __init__(self, chat_id: int):
        self.effective_chat = MockChat(chat_id)
        self.effective_user = MockUser()
        self.message = MockMessage(chat_id)
        self.callback_query = None


class MockBot:
    async def send_chat_action(self, **kwargs):
        return None

    async def send_message(self, **kwargs):
        return None


class MockContext:
    def __init__(self):
        self.bot = MockBot()
        self.user_data = {}


@pytest.mark.asyncio
async def test_doctor_uses_sqlite_when_trade_db_present():
    from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "trades.db"
        db = TradeDatabase(db_path)

        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=24)).isoformat()

        # Insert sample signal event (generated)
        sig_payload = {
            "signal_id": "sig_1",
            "timestamp": now.isoformat(),
            "status": "generated",
            "signal": {
                "type": "mean_reversion_long",
                "direction": "long",
                "entry_price": 25000.0,
                "stop_loss": 24990.0,
                "take_profit": 25015.0,
                "confidence": 0.8,
                "position_size": 3,
            },
        }
        db.add_signal_event("sig_1", "generated", now.isoformat(), sig_payload)

        # Insert cycle diagnostics
        db.add_cycle_diagnostics(
            timestamp=now.isoformat(),
            cycle_count=1,
            quiet_reason="NoOpportunity",
            diagnostics={
                "raw_signals": 2,
                "validated_signals": 0,
                "rejected_confidence": 1,
                "rejected_risk_reward": 1,
            },
        )

        # Insert exited trade
        db.add_trade(
            trade_id="sig_1",
            signal_id="sig_1",
            signal_type="mean_reversion_long",
            direction="long",
            entry_price=25000.0,
            exit_price=25005.0,
            pnl=30.0,
            is_win=True,
            entry_time=now.isoformat(),
            exit_time=now.isoformat(),
            stop_loss=24990.0,
            take_profit=25015.0,
            exit_reason="take_profit",
            hold_duration_minutes=5.0,
            regime="ranging",
            context_key="ranging",
            volatility_percentile=0.5,
            volume_percentile=0.5,
            features={"rsi": 40.0},
        )

        # Build handler instance without full init
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.chat_id = "123"
        handler.state_dir = Path(tmpdir)  # not used by doctor when _trade_db present
        handler._trade_db = db

        sent = []

        async def mock_send(upd, ctx, msg, **kwargs):
            sent.append(msg)

        update = MockUpdate(chat_id=123)
        context = MockContext()

        with patch.object(handler, "_check_authorized", return_value=True):
            with patch.object(handler, "_send_message_or_edit", side_effect=mock_send):
                with patch.object(handler, "_get_back_to_menu_button", return_value=None):
                    await TelegramCommandHandler._handle_doctor(handler, update, context)

        assert len(sent) == 1
        message = sent[0]
        assert "Doctor" in message
        assert "generated" in message
        assert "Trades" in message
        assert len(message) < 4096



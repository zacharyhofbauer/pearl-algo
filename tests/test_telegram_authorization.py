from __future__ import annotations

import types

import pytest

from pearlalgo.nq_agent.telegram_command_handler import TelegramCommandHandler


class _AsyncCallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.answered = False
        self.edited_text: str | None = None

    async def answer(self) -> None:
        self.answered = True

    async def edit_message_text(self, text: str, **_kwargs) -> None:
        self.edited_text = text


@pytest.mark.asyncio
async def test_check_authorized_blocks_wrong_chat_id() -> None:
    handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
    handler.chat_id = "123"

    update = types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(id=999),
        effective_user=types.SimpleNamespace(username="attacker"),
    )

    assert await TelegramCommandHandler._check_authorized(handler, update) is False


@pytest.mark.asyncio
async def test_callback_handler_blocks_unauthorized_chat_id() -> None:
    handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
    handler.chat_id = "123"

    query = _AsyncCallbackQuery(data="status")
    update = types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(id=999),
        effective_user=types.SimpleNamespace(username="attacker"),
        callback_query=query,
    )

    # Context is unused on the unauthorized path (after query.answer()).
    context = types.SimpleNamespace()

    await TelegramCommandHandler._handle_callback(handler, update, context)

    assert query.answered is True
    assert query.edited_text == "❌ Unauthorized access"






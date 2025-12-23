from __future__ import annotations

from pearlalgo.utils.telegram_alerts import TELEGRAM_TEXT_LIMIT, _truncate_telegram_text


def test_truncate_telegram_text_noop_when_under_limit() -> None:
    msg = "hello"
    assert _truncate_telegram_text(msg) == msg


def test_truncate_telegram_text_truncates_and_marks() -> None:
    msg = "x" * (TELEGRAM_TEXT_LIMIT + 100)
    truncated = _truncate_telegram_text(msg)

    assert len(truncated) <= TELEGRAM_TEXT_LIMIT
    assert truncated.endswith("…(truncated)")


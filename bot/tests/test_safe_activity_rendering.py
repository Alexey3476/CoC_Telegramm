"""Telegram names are untrusted markup, so rankings must be render-safe."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.constants import ParseMode
from telegram.error import BadRequest

from app.bot import format_top_players, send_or_edit_message


def test_player_names_escape_html_metacharacters():
    sample = {"mostActive": [
        {"name": "A_<Ace>&", "townHallLevel": 18, "donations": 100, "warAttacks": 2},
        {"name": "⭐King*_", "townHallLevel": 17, "donations": 10, "warAttacks": 1}
    ], "leastActive": [{"name": "CoC_#2", "donations": 0, "warAttacks": 0}]}
    result = format_top_players(sample)
    assert "A_&lt;Ace&gt;&amp;" in result
    assert "CoC_#2" in result
    assert "<Ace>" not in result
    assert "не время последнего входа" in result


def test_ranking_bounds_telegram_message_length():
    large = {"mostActive": [{"name": "Name_<>&" * 80} for _ in range(50)],
             "leastActive": [{"name": "Name_<>&" * 80} for _ in range(50)]}
    assert len(format_top_players(large)) <= 4000


def test_callback_retries_with_plain_text_after_parse_entities_bad_request():
    edit = AsyncMock(side_effect=[BadRequest("Can't parse entities: can't find end of the entity"),
                                  "sent"])
    update = SimpleNamespace(message=None, callback_query=SimpleNamespace(edit_message_text=edit))
    result = asyncio.run(send_or_edit_message(update, "Invalid *markdown_", parse_mode=ParseMode.MARKDOWN))
    assert result == "sent"
    assert edit.await_count == 2
    assert edit.await_args.kwargs["parse_mode"] is None


def test_other_telegram_bad_request_is_not_hidden():
    edit = AsyncMock(side_effect=BadRequest("Chat not found"))
    update = SimpleNamespace(message=None, callback_query=SimpleNamespace(edit_message_text=edit))
    with pytest.raises(BadRequest):
        asyncio.run(send_or_edit_message(update, "Text", parse_mode=ParseMode.HTML))
    assert edit.await_count == 1


def test_non_callback_uses_same_fallback():
    reply = AsyncMock(side_effect=[BadRequest("Can't parse entities"), "ok"])
    update = SimpleNamespace(message=SimpleNamespace(reply_text=reply), callback_query=None)
    assert asyncio.run(send_or_edit_message(update, "Hello <test>", parse_mode=ParseMode.HTML)) == "ok"
    assert reply.await_count == 2

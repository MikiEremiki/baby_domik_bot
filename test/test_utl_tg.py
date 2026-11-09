"""Tests for src/utilities/utl_tg.py — safe Telegram message editing helpers."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest

from utilities.utl_tg import is_not_modified, safe_edit_text, safe_edit_markup, safe_edit_caption


# ─── is_not_modified ──────────────────────────────────────────────────────────

class TestIsNotModified:
    def test_returns_true_for_not_modified(self):
        err = BadRequest("Message is not modified")
        assert is_not_modified(err) is True

    def test_returns_true_for_variant(self):
        err = BadRequest("Message is not modified. Aborted.")
        assert is_not_modified(err) is True

    def test_returns_false_for_other_bad_request(self):
        err = BadRequest("Message to edit not found")
        assert is_not_modified(err) is False

    def test_returns_false_for_empty_message(self):
        err = BadRequest("")
        assert is_not_modified(err) is False


# ─── safe_edit_text ───────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_safe_edit_text_success():
    query = AsyncMock()
    await safe_edit_text(query, text="new text")
    query.edit_message_text.assert_awaited_once_with(text="new text", reply_markup=None)


@pytest.mark.anyio
async def test_safe_edit_text_ignores_not_modified():
    query = AsyncMock()
    query.edit_message_text.side_effect = BadRequest("Message is not modified")
    await safe_edit_text(query, text="same text")


@pytest.mark.anyio
async def test_safe_edit_text_ignores_not_modified_with_logger():
    query = AsyncMock()
    query.edit_message_text.side_effect = BadRequest("Message is not modified")
    logger = MagicMock()
    await safe_edit_text(query, text="same text", logger=logger)
    logger.info.assert_called_once()


@pytest.mark.anyio
async def test_safe_edit_text_reraises_other_bad_request():
    query = AsyncMock()
    query.edit_message_text.side_effect = BadRequest("Message to edit not found")
    with pytest.raises(BadRequest, match="Message to edit not found"):
        await safe_edit_text(query, text="new text")


@pytest.mark.anyio
async def test_safe_edit_text_passes_extra_kwargs():
    query = AsyncMock()
    await safe_edit_text(query, text="hi", parse_mode="HTML")
    call_kwargs = query.edit_message_text.call_args
    assert call_kwargs.kwargs["parse_mode"] == "HTML"


# ─── safe_edit_markup ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_safe_edit_markup_success():
    query = AsyncMock()
    await safe_edit_markup(query, reply_markup=MagicMock())
    query.edit_message_reply_markup.assert_awaited_once()


@pytest.mark.anyio
async def test_safe_edit_markup_ignores_not_modified():
    query = AsyncMock()
    query.edit_message_reply_markup.side_effect = BadRequest("Message is not modified")
    await safe_edit_markup(query, reply_markup=None)


@pytest.mark.anyio
async def test_safe_edit_markup_reraises_other_bad_request():
    query = AsyncMock()
    query.edit_message_reply_markup.side_effect = BadRequest("Message to edit not found")
    with pytest.raises(BadRequest):
        await safe_edit_markup(query, reply_markup=None)


# ─── safe_edit_caption ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_safe_edit_caption_success():
    query = AsyncMock()
    await safe_edit_caption(query, caption="new caption")
    query.edit_message_caption.assert_awaited_once_with(
        caption="new caption", reply_markup=None
    )


@pytest.mark.anyio
async def test_safe_edit_caption_ignores_not_modified():
    query = AsyncMock()
    query.edit_message_caption.side_effect = BadRequest("Message is not modified")
    await safe_edit_caption(query, caption="same caption")


@pytest.mark.anyio
async def test_safe_edit_caption_reraises_other_bad_request():
    query = AsyncMock()
    query.edit_message_caption.side_effect = BadRequest("Message to edit not found")
    with pytest.raises(BadRequest):
        await safe_edit_caption(query, caption="new caption")

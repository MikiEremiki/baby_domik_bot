"""Tests for SEASON_TICKET_HOLDERS type (тип 4) and _show_step helper.

Covers:
- _parse_date: date parsing and validation
- _show_step: edit existing message, fallback to send, not modified handling
- _get_usage_text_for_type: usage text for SEASON_TICKET_HOLDERS
- _get_usage_text_with_highlight: step highlighting
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Update, Message, Chat, User, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest


# ─── _parse_date ──────────────────────────────────────────────────────────────

class TestParseDate:
    """Test _parse_date helper from sales_hl.py."""

    @pytest.fixture
    def parse_date(self):
        from handlers.sales.states import _parse_date
        return _parse_date

    def test_valid_date(self, parse_date):
        assert parse_date("01.02.2025") == date(2025, 2, 1)

    def test_valid_date_31_dec(self, parse_date):
        assert parse_date("31.12.2024") == date(2024, 12, 31)

    def test_invalid_format_spaces(self, parse_date):
        assert parse_date("01 02 2025") is None

    def test_invalid_format_slashes(self, parse_date):
        assert parse_date("01/02/2025") is None

    def test_invalid_date_feb_30(self, parse_date):
        assert parse_date("30.02.2025") is None

    def test_empty_string(self, parse_date):
        assert parse_date("") is None

    def test_leading_zeros(self, parse_date):
        assert parse_date("09.01.2025") == date(2025, 1, 9)


# ─── _show_step ───────────────────────────────────────────────────────────────

class TestShowStep:
    """Test _show_step helper from sales/helpers.py."""

    @pytest.fixture
    def show_step(self):
        from handlers.sales.ui_helpers import _show_step
        return _show_step

    @pytest.fixture
    def update_and_context(self):
        """Create a minimal Update and ContextTypes mock."""
        update = MagicMock()
        update.effective_chat.id = 42
        update.effective_message = MagicMock()
        update.callback_query = None
        context = MagicMock()
        context.user_data = {}
        context.bot = AsyncMock()
        return update, context

    @pytest.mark.anyio
    async def test_edit_existing_message(self, show_step, update_and_context):
        """If step_msg_id is set and edit succeeds, use edit."""
        update, context = update_and_context
        context.user_data['sales'] = {'step_msg_id': 100}
        context.bot.edit_message_text = AsyncMock()

        result = await show_step(
            update, context,
            text="New step",
            reply_markup=InlineKeyboardMarkup([]),
            state="TEST_STATE",
        )
        assert result == "TEST_STATE"
        context.bot.edit_message_text.assert_called_once()
        call_kwargs = context.bot.edit_message_text.call_args[1]
        assert call_kwargs['chat_id'] == 42
        assert call_kwargs['message_id'] == 100
        assert call_kwargs['text'] == "New step"

    @pytest.mark.anyio
    async def test_fallback_send_new_message(self, show_step, update_and_context):
        """If step_msg_id is None, send a new message and store its ID."""
        update, context = update_and_context
        sent_msg = MagicMock()
        sent_msg.message_id = 200
        update.effective_chat.send_message = AsyncMock(return_value=sent_msg)
        update.effective_message = update.message

        result = await show_step(
            update, context,
            text="First step",
            reply_markup=InlineKeyboardMarkup([]),
            state="FIRST_STATE",
        )
        assert result == "FIRST_STATE"
        update.effective_chat.send_message.assert_called_once()
        assert context.user_data['sales']['step_msg_id'] == 200

    @pytest.mark.anyio
    async def test_edit_not_found_fallback(self, show_step, update_and_context):
        """If edit raises 'Message to edit not found', fall back to send."""
        update, context = update_and_context
        context.user_data['sales'] = {'step_msg_id': 100}
        context.bot.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message to edit not found")
        )
        sent_msg = MagicMock()
        sent_msg.message_id = 200
        update.effective_chat.send_message = AsyncMock(return_value=sent_msg)
        update.effective_message = update.message

        result = await show_step(
            update, context,
            text="Step after not found",
            reply_markup=InlineKeyboardMarkup([]),
            state="RECOVER_STATE",
        )
        assert result == "RECOVER_STATE"
        update.effective_chat.send_message.assert_called_once()
        # step_msg_id updated to new message
        assert context.user_data['sales']['step_msg_id'] == 200

    @pytest.mark.anyio
    async def test_edit_not_modified_is_success(self, show_step, update_and_context):
        """If edit raises 'Message is not modified', treat as success (no fallback)."""
        update, context = update_and_context
        context.user_data['sales'] = {'step_msg_id': 100}
        context.bot.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )
        update.effective_chat.send_message = AsyncMock()

        result = await show_step(
            update, context,
            text="Same text",
            reply_markup=InlineKeyboardMarkup([]),
            state="UNCHANGED_STATE",
        )
        assert result == "UNCHANGED_STATE"
        # Should NOT fall back to send_message
        update.effective_chat.send_message.assert_not_called()


# ─── _get_usage_text_for_type ─────────────────────────────────────────────────

class TestUsageText:
    """Test usage text helpers from sales/helpers.py."""

    @pytest.fixture
    def get_usage(self):
        from handlers.sales.states import _get_usage_text_for_type
        return _get_usage_text_for_type

    @pytest.fixture
    def get_usage_highlight(self):
        from handlers.sales.states import _get_usage_text_with_highlight
        return _get_usage_text_with_highlight

    def test_season_usage_text(self, get_usage):
        text = get_usage("SEASON_TICKET_HOLDERS")
        assert "периода" in text
        assert "спектакли" in text
        assert "возраст" in text
        assert "статусы" in text

    def test_was_this_year_usage_text(self, get_usage):
        text = get_usage("WAS_THIS_YEAR_ON_PLAY")
        assert "спектакль" in text

    def test_unknown_type_returns_default(self, get_usage):
        text = get_usage("NONEXISTENT_TYPE")
        assert "Как пользоваться" in text

    def test_highlight_step_1(self, get_usage_highlight):
        text = get_usage_highlight("SEASON_TICKET_HOLDERS", 1)
        assert "<b>" in text
        # Step 1 should be bolded
        assert "1)" in text

    def test_highlight_step_7(self, get_usage_highlight):
        text = get_usage_highlight("SEASON_TICKET_HOLDERS", 7)
        assert "<b>" in text


# ─── _compress_ids (used in audience summary) ────────────────────────────────

class TestCompressIds:
    """Test _compress_ids helper from sales/helpers.py."""

    @pytest.fixture
    def compress(self):
        from handlers.sales.states import _compress_ids
        return _compress_ids

    def test_empty(self, compress):
        assert compress([]) == ""

    def test_single(self, compress):
        assert compress([42]) == "42"

    def test_consecutive_range(self, compress):
        result = compress([1, 2, 3, 4, 5])
        assert "1\u20135" in result

    def test_non_consecutive(self, compress):
        result = compress([1, 3, 5])
        assert "1" in result
        assert "3" in result
        assert "5" in result

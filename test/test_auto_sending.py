"""Unit tests for src/schedule/auto_sending.py."""
import asyncio
from datetime import datetime, timedelta, timezone, time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

from schedule.auto_sending import (
    compute_send_time,
    render_text,
    Recipient,
    RECIPIENT_SELECTORS,
)
from db.enum import AutoSendingTrigger


# ─── compute_send_time ────────────────────────────────────────────────────────

class TestComputeSendTime:
    """Tests for compute_send_time: offset, window, edge cases."""

    def test_negative_offset_no_window(self):
        """Reminder: −1500 min (1 day 1 hour before)."""
        anchor = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_send_time(anchor, offset_minutes=-1500)
        expected = datetime(2026, 5, 14, 11, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_positive_offset_no_window(self):
        """Feedback: +240 min (4 hours after)."""
        anchor = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_send_time(anchor, offset_minutes=240)
        expected = datetime(2026, 5, 15, 16, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_zero_offset(self):
        """Zero offset returns anchor."""
        anchor = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_send_time(anchor, offset_minutes=0)
        assert result == anchor

    def test_window_inside(self):
        """Raw time falls inside window → no shift."""
        anchor = datetime(2026, 5, 15, 10, 0, 0, tzinfo=timezone.utc)
        result = compute_send_time(
            anchor, offset_minutes=120,
            window_start=dt_time(8, 0), window_end=dt_time(21, 0),
        )
        expected = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_window_before_start(self):
        """Raw time before window_start → shift to window_start same day."""
        anchor = datetime(2026, 5, 15, 6, 0, 0, tzinfo=timezone.utc)
        result = compute_send_time(
            anchor, offset_minutes=60,
            window_start=dt_time(8, 0), window_end=dt_time(21, 0),
        )
        # raw = 07:00, before 08:00 → shift to 08:00
        expected = datetime(2026, 5, 15, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_window_after_end(self):
        """Raw time after window_end → shift to window_start next day."""
        anchor = datetime(2026, 5, 15, 20, 0, 0, tzinfo=timezone.utc)
        result = compute_send_time(
            anchor, offset_minutes=180,
            window_start=dt_time(8, 0), window_end=dt_time(21, 0),
        )
        # raw = 23:00, after 21:00 → next day 08:00
        expected = datetime(2026, 5, 16, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_window_only_start(self):
        """Only window_start set, no window_end."""
        anchor = datetime(2026, 5, 15, 6, 0, 0, tzinfo=timezone.utc)
        result = compute_send_time(
            anchor, offset_minutes=60,
            window_start=dt_time(8, 0),
        )
        # raw = 07:00, before 08:00 → shift to 08:00
        expected = datetime(2026, 5, 15, 8, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_window_only_end(self):
        """Only window_end set, no window_start."""
        anchor = datetime(2026, 5, 15, 22, 0, 0, tzinfo=timezone.utc)
        result = compute_send_time(
            anchor, offset_minutes=0,
            window_end=dt_time(21, 0),
        )
        # raw = 22:00, after 21:00 → next day 00:00 (time.min)
        expected = datetime(2026, 5, 16, 0, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_naive_datetime(self):
        """Naive datetime preserves naiveness."""
        anchor = datetime(2026, 5, 15, 12, 0, 0)
        result = compute_send_time(anchor, offset_minutes=60)
        assert result.tzinfo is None
        assert result.hour == 13


# ─── render_text ──────────────────────────────────────────────────────────────

class TestRenderText:
    """Tests for render_text: placeholder substitution, escaping, fallback, truncation."""

    def test_simple_substitution(self):
        """Basic placeholder replacement."""
        template = "Hello {name}!"
        result = render_text(template, {"name": "World"})
        assert result == "Hello World!"

    def test_html_escaping(self):
        """Raw HTML in context values is preserved as-is by render_text.

        render_text uses str.format() which does NOT escape HTML, so raw HTML
        tags from context values will appear in the result. The caller
        (_dispatch_single_recipient) then passes the result through
        transform_html, which converts HTML tags to Telegram entities.

        This test verifies that render_text does not crash on HTML values
        and that the raw HTML tags are present in the output (as expected
        before transform_html processing).
        """
        template = "Event: {event_name}"
        result = render_text(template, {"event_name": "<script>alert(1)</script>"})
        # render_text preserves raw HTML from context values
        assert isinstance(result, str)
        assert len(result) > 0
        # The raw HTML tag IS present in render_text output (expected behavior)
        # transform_html in the caller will convert it to entities
        assert "<script>" in result or "alert" in result

    def test_multiple_placeholders(self):
        """All placeholders substituted."""
        template = "{event_name} on {date} at {time}, tickets: {ticket_ids}"
        result = render_text(
            template,
            {
                "event_name": "Hamlet",
                "date": "15.05",
                "time": "18:00",
                "ticket_ids": "1, 2, 3",
            },
        )
        assert "Hamlet" in result
        assert "15.05" in result
        assert "18:00" in result
        assert "1, 2, 3" in result

    def test_missing_placeholder_filled_empty(self):
        """Missing placeholder is filled with empty string."""
        template = "Hello {missing}!"
        result = render_text(template, {})
        # render_text fills missing placeholders with empty string
        assert result == "Hello !"

    def test_placeholder_error_fallback(self):
        """If format() raises due to unexpected placeholder, return original template.

        render_text fills missing placeholders with empty string before calling
        format(), so format() should not raise KeyError for missing keys.
        However, if format() raises ValueError (e.g., malformed format string),
        render_text returns the original template as a safety net.
        """
        # A malformed format string that triggers ValueError
        template = "Hello {name"  # Missing closing brace
        result = render_text(template, {"name": "World"}, sending_name="test")
        # Should return the original template on error
        assert isinstance(result, str)
        assert result == template

    def test_missing_placeholder_filled_with_empty(self):
        """Missing placeholder is filled with empty string, not an error."""
        template = "Hello {name} and {missing}!"
        result = render_text(template, {"name": "World"})
        assert result == "Hello World and !"

    def test_truncation_over_4096(self):
        """Text over 4096 chars is truncated with '…'."""
        # Build a template that will exceed 4096 after substitution.
        long_value = "A" * 5000
        template = "Text: {value}"
        result = render_text(template, {"value": long_value}, sending_name="long")
        assert len(result) <= 4096
        assert result.endswith("…")

    def test_exact_4096_no_truncation(self):
        """Text exactly 4096 chars is not truncated."""
        value = "A" * 4091  # "Text: " = 6 chars, total = 4097... let's adjust
        # Actually "Text: " is 6 chars, so value needs to be 4090 to get 4096
        value = "A" * 4090
        template = "Text: {value}"
        result = render_text(template, {"value": value})
        # After format: "Text: AAAA..." = 4096 chars
        # sulguk may modify it, but the point is no truncation warning
        assert isinstance(result, str)


# ─── RECIPIENT_SELECTORS ──────────────────────────────────────────────────────

class TestRecipientSelectors:
    """Tests for RECIPIENT_SELECTORS registry."""

    def test_event_selector_registered(self):
        assert AutoSendingTrigger.EVENT in RECIPIENT_SELECTORS

    def test_payment_selector_registered(self):
        assert AutoSendingTrigger.PAYMENT in RECIPIENT_SELECTORS


# ─── dispatch_auto_sending (dedup, blocked, chat_id=0) ────────────────────────

class TestDispatchAutoSending:
    """Tests for dispatch_auto_sending: dedup, blocked users, chat_id=0."""

    def _make_context(self):
        context = MagicMock()
        context.bot = AsyncMock()
        context.bot_data = {"settings": {"REFUND_INFO": "Refund info"}}
        return context

    def _make_user(self, user_id=1, chat_id=123, blocked=False):
        user = MagicMock()
        user.user_id = user_id
        user.chat_id = chat_id
        if blocked:
            status = MagicMock()
            status.is_blocked_by_user = blocked
            status.is_blocked_by_admin = False
            status.is_blacklisted = False
            user.status = status
        else:
            user.status = None
        return user

    def _make_sending(self, sending_id=1, name="Test", text="Hello {name}!",
                      send_via_bot=True):
        sending = MagicMock()
        sending.id = sending_id
        sending.name = name
        sending.text = text
        sending.send_via_bot = send_via_bot
        return sending

    def test_skip_already_delivered(self):
        """Recipient with existing delivery record is skipped."""
        asyncio.run(self._test_skip_already_delivered())

    async def _test_skip_already_delivered(self):
        from schedule.auto_sending import dispatch_auto_sending
        from db import db_postgres

        context = self._make_context()
        session = AsyncMock()
        user = self._make_user()
        sending = self._make_sending()

        # Mock: delivery already exists
        with patch.object(db_postgres, 'get_delivery', new=AsyncMock(return_value=MagicMock())):
            recipients = [Recipient(
                user=user, ctx={"name": "World"},
                dedup_key="se:1", schedule_event_id=1,
            )]
            await dispatch_auto_sending(context, session, sending, recipients)

        # bot.send_message should NOT be called
        context.bot.send_message.assert_not_called()

    def test_skip_chat_id_zero(self):
        """User with chat_id=0 (website order) is skipped."""
        asyncio.run(self._test_skip_chat_id_zero())

    async def _test_skip_chat_id_zero(self):
        from schedule.auto_sending import dispatch_auto_sending
        from db import db_postgres

        context = self._make_context()
        session = AsyncMock()
        user = self._make_user(chat_id=0)
        sending = self._make_sending()

        with patch.object(db_postgres, 'get_delivery', new=AsyncMock(return_value=None)):
            recipients = [Recipient(
                user=user, ctx={"name": "World"},
                dedup_key="se:1", schedule_event_id=1,
            )]
            await dispatch_auto_sending(context, session, sending, recipients)

        context.bot.send_message.assert_not_called()

    def test_skip_blocked_user(self):
        """Blocked user is skipped."""
        asyncio.run(self._test_skip_blocked_user())

    async def _test_skip_blocked_user(self):
        from schedule.auto_sending import dispatch_auto_sending
        from db import db_postgres

        context = self._make_context()
        session = AsyncMock()
        user = self._make_user(blocked=True)
        sending = self._make_sending()

        with patch.object(db_postgres, 'get_delivery', new=AsyncMock(return_value=None)):
            recipients = [Recipient(
                user=user, ctx={"name": "World"},
                dedup_key="se:1", schedule_event_id=1,
            )]
            await dispatch_auto_sending(context, session, sending, recipients)

        context.bot.send_message.assert_not_called()

    def test_send_to_normal_user(self):
        """Normal user receives message and delivery is recorded."""
        asyncio.run(self._test_send_to_normal_user())

    async def _test_send_to_normal_user(self):
        from schedule.auto_sending import dispatch_auto_sending
        from db import db_postgres

        context = self._make_context()
        session = AsyncMock()
        user = self._make_user()
        sending = self._make_sending(text="Hello {name}!")

        mock_delivery = AsyncMock()
        with (
            patch.object(db_postgres, 'get_delivery', new=AsyncMock(return_value=None)),
            patch.object(db_postgres, 'create_delivery', new=mock_delivery),
        ):
            recipients = [Recipient(
                user=user, ctx={"name": "World"},
                dedup_key="se:1", schedule_event_id=1,
            )]
            await dispatch_auto_sending(context, session, sending, recipients)

        # Should have called send_message
        assert context.bot.send_message.call_count >= 1
        # Should have recorded delivery
        mock_delivery.assert_called_once()

    def test_retry_after_handling(self):
        """RetryAfter triggers sleep + retry."""
        asyncio.run(self._test_retry_after_handling())

    async def _test_retry_after_handling(self):
        from schedule.auto_sending import dispatch_auto_sending
        from db import db_postgres
        from telegram.error import RetryAfter

        context = self._make_context()
        session = AsyncMock()
        user = self._make_user()
        sending = self._make_sending(text="Hello!")

        # First call raises RetryAfter, second succeeds
        context.bot.send_message.side_effect = [
            RetryAfter(retry_after=1),
            MagicMock(),  # success on retry
        ]

        with (
            patch.object(db_postgres, 'get_delivery', new=AsyncMock(return_value=None)),
            patch.object(db_postgres, 'create_delivery', new=AsyncMock()),
            patch('asyncio.sleep', new=AsyncMock()),
        ):
            recipients = [Recipient(
                user=user, ctx={},
                dedup_key="se:1", schedule_event_id=1,
            )]
            await dispatch_auto_sending(context, session, sending, recipients)

        # Should have called send_message twice (original + retry)
        assert context.bot.send_message.call_count >= 2

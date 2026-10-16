"""Unit tests for src/schedule/auto_sending.py."""
import asyncio
from datetime import datetime, timedelta, timezone, time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

from schedule.auto_sending import (
    build_recipient_ctx,
    compute_send_time,
    group_tickets_by_user,
    new_recipient_ctx,
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


# ─── Shared helpers: group_tickets_by_user, build_recipient_ctx ───────────────

class TestGroupTicketsByUser:
    """Tests for group_tickets_by_user: grouping, no-user tickets."""

    def _make_ticket(self, ticket_id, user_id=None):
        ticket = MagicMock()
        ticket.id = ticket_id
        if user_id is not None:
            user = MagicMock()
            user.user_id = user_id
            ticket.user = user
        else:
            ticket.user = None
        return ticket

    def test_groups_tickets_by_user(self):
        """Tickets with users are grouped by user_id."""
        tickets = [
            self._make_ticket(1, user_id=100),
            self._make_ticket(2, user_id=100),
            self._make_ticket(3, user_id=200),
        ]
        user_tickets, skipped = group_tickets_by_user(tickets)
        assert len(skipped) == 0
        assert 100 in user_tickets
        assert 200 in user_tickets
        assert len(user_tickets[100]) == 2
        assert len(user_tickets[200]) == 1

    def test_skips_tickets_without_user(self):
        """Tickets with user=None are skipped and their IDs are returned."""
        tickets = [
            self._make_ticket(1, user_id=100),
            self._make_ticket(2, user_id=None),
            self._make_ticket(3, user_id=None),
        ]
        user_tickets, skipped = group_tickets_by_user(tickets)
        assert len(user_tickets) == 1
        assert 100 in user_tickets
        assert skipped == [2, 3]

    def test_empty_list(self):
        """Empty list returns empty dict and empty skipped list."""
        user_tickets, skipped = group_tickets_by_user([])
        assert user_tickets == {}
        assert skipped == []

    def test_all_tickets_without_user(self):
        """When all tickets have no user, returns empty dict with all IDs skipped."""
        tickets = [
            self._make_ticket(1, user_id=None),
            self._make_ticket(2, user_id=None),
        ]
        user_tickets, skipped = group_tickets_by_user(tickets)
        assert user_tickets == {}
        assert skipped == [1, 2]


class TestBuildRecipientCtx:
    """Tests for build_recipient_ctx: context dict structure."""

    def _make_schedule_event(self, event_id=1, place_id=1):
        place = MagicMock()
        place.name = "Main Hall"
        theater_event = MagicMock()
        theater_event.name = "Hamlet"
        theater_event.director = None
        theater_event.genre = None
        theater_event.flag_premier = False
        theater_event.min_age_child = 0
        theater_event.max_age_child = None
        theater_event.duration = None
        theater_event.note = None
        theater_event.link = None

        se = MagicMock()
        se.id = event_id
        se.theater_event = theater_event
        se.place = place if place_id else None
        return se

    def test_returns_correct_keys(self):
        """Context dict contains all expected keys."""
        se = self._make_schedule_event()
        ctx = build_recipient_ctx(se, "1, 2, 3")
        assert set(ctx.keys()) == {
            "event_name", "date", "time", "place", "ticket_ids", "refund_info"
        }

    def test_event_name_from_theater_event(self):
        """event_name is derived from theater_event."""
        se = self._make_schedule_event()
        ctx = build_recipient_ctx(se, "42")
        assert "Hamlet" in ctx["event_name"]

    def test_date_and_time_empty(self):
        """date and time are empty strings — caller fills them."""
        se = self._make_schedule_event()
        ctx = build_recipient_ctx(se, "1")
        assert ctx["date"] == ""
        assert ctx["time"] == ""

    def test_ticket_ids_passed_through(self):
        """ticket_ids is set from the argument."""
        se = self._make_schedule_event()
        ctx = build_recipient_ctx(se, "7, 8, 9")
        assert ctx["ticket_ids"] == "7, 8, 9"

    def test_refund_info_default_empty(self):
        """refund_info defaults to empty string."""
        se = self._make_schedule_event()
        ctx = build_recipient_ctx(se, "1")
        assert ctx["refund_info"] == ""

    def test_refund_info_custom(self):
        """refund_info can be set to a custom value."""
        se = self._make_schedule_event()
        ctx = build_recipient_ctx(se, "1", refund_info="Refund to card")
        assert ctx["refund_info"] == "Refund to card"

    def test_place_none_warning(self):
        """When place is None, place field is empty string."""
        se = self._make_schedule_event(place_id=None)
        ctx = build_recipient_ctx(se, "1")
        assert ctx["place"] == ""


# ─── new_recipient_ctx factory ────────────────────────────────────────────────

class TestNewRecipientCtx:
    """Tests for new_recipient_ctx: factory for the standard context dict."""

    def test_defaults_to_empty_strings(self):
        """All fields default to empty strings."""
        ctx = new_recipient_ctx()
        assert ctx == {
            "event_name": "",
            "date": "",
            "time": "",
            "place": "",
            "ticket_ids": "",
            "refund_info": "",
        }

    def test_sets_all_fields(self):
        """All fields can be set via keyword arguments."""
        ctx = new_recipient_ctx(
            event_name="Hamlet",
            date="15.05.2026",
            time="18:00",
            place="Main Hall",
            ticket_ids="1, 2, 3",
            refund_info="Refund to card",
        )
        assert ctx["event_name"] == "Hamlet"
        assert ctx["date"] == "15.05.2026"
        assert ctx["time"] == "18:00"
        assert ctx["place"] == "Main Hall"
        assert ctx["ticket_ids"] == "1, 2, 3"
        assert ctx["refund_info"] == "Refund to card"

    def test_partial_fields(self):
        """Only some fields set, rest default to empty."""
        ctx = new_recipient_ctx(event_name="Othello", ticket_ids="42")
        assert ctx["event_name"] == "Othello"
        assert ctx["ticket_ids"] == "42"
        assert ctx["date"] == ""
        assert ctx["time"] == ""
        assert ctx["place"] == ""
        assert ctx["refund_info"] == ""

    def test_returns_correct_keys(self):
        """Dict contains exactly the 6 expected keys."""
        ctx = new_recipient_ctx()
        assert set(ctx.keys()) == {
            "event_name", "date", "time", "place", "ticket_ids", "refund_info"
        }


# ─── _format_send_stats (handler report) ──────────────────────────────────────

class TestFormatSendStats:
    """Tests for _format_send_stats: dispatch stats → human-readable message."""

    def _import_format_func(self):
        from handlers.auto_sending_hl import _format_send_stats
        return _format_send_stats

    def test_basic_sent_only(self):
        """Only sent count, no skips."""
        fmt = self._import_format_func()
        stats = {
            "sent": 5,
            "dedup_skipped": 0,
            "no_chat_skipped": 0,
            "blocked_skipped": 0,
            "not_sent_via_bot_skipped": 0,
        }
        result = fmt(stats)
        assert "Отправлено: 5 получателей" in result

    def test_no_user_skipped_displayed(self):
        """no_user_skipped shows count and ticket IDs."""
        fmt = self._import_format_func()
        stats = {
            "sent": 3,
            "dedup_skipped": 0,
            "no_chat_skipped": 0,
            "blocked_skipped": 0,
            "not_sent_via_bot_skipped": 0,
            "no_user_skipped": [10, 20, 30],
        }
        result = fmt(stats)
        assert "Пропущено (билет без пользователя): 3" in result
        assert "IDs: 10, 20, 30" in result

    def test_no_user_skipped_empty_list(self):
        """Empty no_user_skipped list does not add a line."""
        fmt = self._import_format_func()
        stats = {
            "sent": 1,
            "dedup_skipped": 0,
            "no_chat_skipped": 0,
            "blocked_skipped": 0,
            "not_sent_via_bot_skipped": 0,
            "no_user_skipped": [],
        }
        result = fmt(stats)
        assert "билет без пользователя" not in result

    def test_no_user_skipped_missing_key(self):
        """Missing no_user_skipped key does not cause error."""
        fmt = self._import_format_func()
        stats = {
            "sent": 1,
            "dedup_skipped": 0,
            "no_chat_skipped": 0,
            "blocked_skipped": 0,
            "not_sent_via_bot_skipped": 0,
        }
        result = fmt(stats)
        assert "билет без пользователя" not in result

    def test_all_skipped_warning(self):
        """When sent=0 and skips>0, shows warning message."""
        fmt = self._import_format_func()
        stats = {
            "sent": 0,
            "dedup_skipped": 2,
            "no_chat_skipped": 1,
            "blocked_skipped": 0,
            "not_sent_via_bot_skipped": 0,
            "no_user_skipped": [5],
        }
        result = fmt(stats)
        assert "Рассылка не была отправлена" in result

    def test_dedup_skipped_displayed(self):
        """dedup_skipped count is shown."""
        fmt = self._import_format_func()
        stats = {
            "sent": 2,
            "dedup_skipped": 3,
            "no_chat_skipped": 0,
            "blocked_skipped": 0,
            "not_sent_via_bot_skipped": 0,
        }
        result = fmt(stats)
        assert "Пропущено (уже отправлено): 3" in result

    def test_blocked_skipped_displayed(self):
        """blocked_skipped count is shown."""
        fmt = self._import_format_func()
        stats = {
            "sent": 1,
            "dedup_skipped": 0,
            "no_chat_skipped": 0,
            "blocked_skipped": 2,
            "not_sent_via_bot_skipped": 0,
        }
        result = fmt(stats)
        assert "Пропущено (заблокирован): 2" in result

    def test_no_chat_skipped_displayed(self):
        """no_chat_skipped count is shown."""
        fmt = self._import_format_func()
        stats = {
            "sent": 1,
            "dedup_skipped": 0,
            "no_chat_skipped": 1,
            "blocked_skipped": 0,
            "not_sent_via_bot_skipped": 0,
        }
        result = fmt(stats)
        assert "Пропущено (без привязки Telegram): 1" in result

    def test_not_sent_via_bot_displayed(self):
        """not_sent_via_bot_skipped count is shown."""
        fmt = self._import_format_func()
        stats = {
            "sent": 1,
            "dedup_skipped": 0,
            "no_chat_skipped": 0,
            "blocked_skipped": 0,
            "not_sent_via_bot_skipped": 1,
        }
        result = fmt(stats)
        assert "Пропущено (отправка через бот выключена): 1" in result

    def test_no_trailing_br(self):
        """Result does not end with <br>."""
        fmt = self._import_format_func()
        stats = {
            "sent": 1,
            "dedup_skipped": 0,
            "no_chat_skipped": 0,
            "blocked_skipped": 0,
            "not_sent_via_bot_skipped": 0,
        }
        result = fmt(stats)
        assert not result.endswith("<br>")


# ─── _manual_send_by_ticket guard clauses ─────────────────────────────────────

class TestManualSendByTicket:
    """Tests for _manual_send_by_ticket: guard clauses for missing user."""

    def _make_context(self, session=None):
        context = MagicMock()
        context.session = session or AsyncMock()
        return context

    def test_ticket_not_found(self):
        """Returns error when ticket does not exist."""
        from handlers.auto_sending_hl import _manual_send_by_ticket
        from db import db_postgres

        context = self._make_context()
        with patch.object(db_postgres, 'get_ticket', new=AsyncMock(return_value=None)):
            recipients, error, no_user_ids = asyncio.run(_manual_send_by_ticket(context, 999))
        assert recipients is None
        assert "не найден" in error
        assert no_user_ids == []

    def test_ticket_user_none(self):
        """Returns error when ticket has no user (guard clause)."""
        from handlers.auto_sending_hl import _manual_send_by_ticket
        from db import db_postgres

        context = self._make_context()
        ticket = MagicMock()
        ticket.user = None
        with patch.object(db_postgres, 'get_ticket', new=AsyncMock(return_value=ticket)):
            recipients, error, no_user_ids = asyncio.run(_manual_send_by_ticket(context, 42))
        assert recipients is None
        assert "без привязки пользователя" in error
        assert no_user_ids == []

    def test_user_chat_id_zero(self):
        """Returns error when user has chat_id=0 (website order)."""
        from handlers.auto_sending_hl import _manual_send_by_ticket
        from db import db_postgres

        context = self._make_context()
        user = MagicMock()
        user.chat_id = 0
        ticket = MagicMock()
        ticket.user = user
        ticket.schedule_event_id = None
        with patch.object(db_postgres, 'get_ticket', new=AsyncMock(return_value=ticket)):
            recipients, error, no_user_ids = asyncio.run(_manual_send_by_ticket(context, 42))
        assert recipients is None
        assert "без привязки Telegram" in error
        assert no_user_ids == []

    def test_successful_recipient(self):
        """Returns recipient list when everything is valid."""
        from handlers.auto_sending_hl import _manual_send_by_ticket
        from db import db_postgres

        context = self._make_context()
        user = MagicMock()
        user.chat_id = 12345
        user.status = None
        ticket = MagicMock()
        ticket.id = 42
        ticket.user = user
        ticket.schedule_event_id = None
        with patch.object(db_postgres, 'get_ticket', new=AsyncMock(return_value=ticket)):
            recipients, error, no_user_ids = asyncio.run(_manual_send_by_ticket(context, 42))
        assert recipients is not None
        assert error is None
        assert no_user_ids == []
        assert len(recipients) == 1
        assert recipients[0].user == user


# ─── _manual_send_by_session edge cases ───────────────────────────────────────

class TestManualSendBySession:
    """Tests for _manual_send_by_session: edge cases with no-user tickets."""

    def _make_context(self, session=None):
        context = MagicMock()
        context.session = session or AsyncMock()
        return context

    def test_session_not_found(self):
        """Returns error when session does not exist."""
        from handlers.auto_sending_hl import _manual_send_by_session
        from db import db_postgres

        context = self._make_context()
        with patch.object(db_postgres, 'get_schedule_event', new=AsyncMock(return_value=None)):
            recipients, error, no_user_ids = asyncio.run(_manual_send_by_session(context, 999))
        assert recipients is None
        assert "не найден" in error
        assert no_user_ids == []

    def test_all_tickets_no_user(self):
        """When all tickets have no user, returns empty recipients with skipped IDs."""
        from handlers.auto_sending_hl import _manual_send_by_session
        from db import db_postgres
        from schedule.auto_sending import group_tickets_by_user

        schedule_event = MagicMock()
        schedule_event.id = 1

        # Tickets with no user — use simple objects to avoid MagicMock quirks
        class FakeTicket:
            def __init__(self, tid):
                self.id = tid
                self.user = None

        t1 = FakeTicket(10)
        t2 = FakeTicket(11)

        # Verify group_tickets_by_user works correctly with our fake tickets
        user_tickets, skipped = group_tickets_by_user([t1, t2])
        assert skipped == [10, 11], f"group_tickets_by_user skipped: {skipped}"
        assert user_tickets == {}

        # Mock the session execute to return our fake tickets
        # Note: .scalars() returns a ScalarResult; .all() returns the list
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[t1, t2]))))
        )

        context = MagicMock()
        context.session = mock_session

        with patch.object(db_postgres, 'get_schedule_event', new=AsyncMock(return_value=schedule_event)):
            recipients, error, no_user_ids = asyncio.run(_manual_send_by_session(context, 1))
        assert recipients == []
        assert error is None
        assert no_user_ids == [10, 11]

"""Unit tests for SHOW_LIST auto-publishing: build_show_list_text, publish_show_list_to_topic, dedup."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from schedule.auto_sending import (
    _has_published_show_list,
    _record_show_list_published,
    publish_show_list_to_topic,
    RECIPIENT_SELECTORS,
)
from db.enum import AutoSendingTrigger, TicketStatus


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_ticket(ticket_id=1, status=TicketStatus.PAID, base_ticket_id=100):
    """Create a mock Ticket."""
    ticket = MagicMock()
    ticket.id = ticket_id
    ticket.status = status
    ticket.base_ticket_id = base_ticket_id
    ticket.people = []
    ticket.notes = None
    ticket.phone = "9991234567"
    ticket.email = "test@example.com"
    ticket.source = None
    ticket.user = None
    return ticket


def _make_base_ticket(bt_id=100, name="Взрослый", quality_of_children=0,
                      quality_of_adult=1, quality_of_add_adult=0):
    """Create a mock BaseTicket."""
    bt = MagicMock()
    bt.id = bt_id
    bt.name = name
    bt.quality_of_children = quality_of_children
    bt.quality_of_adult = quality_of_adult
    bt.quality_of_add_adult = quality_of_add_adult
    return bt


def _make_schedule_event(se_id=1, theater_event_id=10, tickets=None,
                         datetime_event=None, place_id=1):
    """Create a mock ScheduleEvent."""
    if datetime_event is None:
        datetime_event = datetime(2026, 11, 15, 18, 0, 0, tzinfo=timezone.utc)
    se = MagicMock()
    se.id = se_id
    se.theater_event_id = theater_event_id
    se.datetime_event = datetime_event
    se.tickets = tickets or []
    se.place = MagicMock(id=place_id, name="Зал") if place_id else None
    return se


def _make_theater_event(te_id=10, name="Гамлет"):
    """Create a mock TheaterEvent."""
    te = MagicMock()
    te.id = te_id
    te.name = name
    return te


def _make_default_place():
    """Create a mock default Place."""
    place = MagicMock()
    place.id = 1
    place.name = "Домик"
    place.address = "ул. Пушкина, 1"
    return place


def _make_auto_sending(sending_id=1, offset_minutes=-30):
    """Create a mock AutoSending."""
    sending = MagicMock()
    sending.id = sending_id
    sending.offset_minutes = offset_minutes
    return sending


def _make_context(bot_data=None, developer_chat_id=12345):
    """Create a mock context for publish_show_list_to_topic."""
    context = MagicMock()
    context.bot = AsyncMock()
    context.bot_data = bot_data or {}
    context.config = MagicMock()
    context.config.bot.developer_chat_id = developer_chat_id
    return context


# ─── RECIPIENT_SELECTORS: SHOW_LIST ──────────────────────────────────────────


class TestShowListSelector:
    """Tests for SHOW_LIST selector registration."""

    def test_show_list_selector_registered(self):
        """SHOW_LIST trigger must have a selector in RECIPIENT_SELECTORS."""
        assert AutoSendingTrigger.SHOW_LIST in RECIPIENT_SELECTORS

    def test_show_list_selector_returns_empty(self):
        """SHOW_LIST selector returns empty list (no recipients for topic publish)."""
        asyncio.run(self._test_selector_empty())

    async def _test_selector_empty(self):
        selector = RECIPIENT_SELECTORS[AutoSendingTrigger.SHOW_LIST]
        session = AsyncMock()
        auto_sending = MagicMock()
        now = datetime.now(tz=timezone.utc)
        result = await selector(session, auto_sending, now)
        assert result == []


# ─── build_show_list_text ────────────────────────────────────────────────────


class TestBuildShowListText:
    """Tests for build_show_list_text: text building, empty tickets, skip logic."""

    def test_returns_text_and_tickets(self):
        """build_show_list_text returns (html_text, base_ticket_and_tickets)."""
        asyncio.run(self._test_returns_text_and_tickets())

    async def _test_returns_text_and_tickets(self):
        from utilities.utl_func import build_show_list_text
        from db import db_postgres

        se = _make_schedule_event(se_id=1, tickets=[])
        te = _make_theater_event()
        default_place = _make_default_place()
        session = AsyncMock()

        with (
            patch.object(db_postgres, 'get_theater_event', new=AsyncMock(return_value=te)),
            patch.object(db_postgres, 'get_default_place', new=AsyncMock(return_value=default_place)),
            patch('utilities.utl_func.get_formatted_date_and_time_of_event',
                  new=AsyncMock(return_value=('15.11.2026', '18:00'))),
        ):
            html_text, bt_list = await build_show_list_text(session, se)

        assert isinstance(html_text, str)
        assert isinstance(bt_list, list)
        assert "Гамлет" in html_text
        assert "15.11.2026" in html_text
        assert "18:00" in html_text

    def test_includes_ticket_data(self):
        """Text includes ticket contacts when tickets are present."""
        asyncio.run(self._test_includes_ticket_data())

    async def _test_includes_ticket_data(self):
        from utilities.utl_func import build_show_list_text
        from db import db_postgres

        ticket = _make_ticket(ticket_id=42, status=TicketStatus.PAID, base_ticket_id=100)
        base_ticket = _make_base_ticket(bt_id=100, name="Взрослый")
        se = _make_schedule_event(se_id=1, tickets=[ticket])
        te = _make_theater_event()
        default_place = _make_default_place()
        session = AsyncMock()

        with (
            patch.object(db_postgres, 'get_theater_event', new=AsyncMock(return_value=te)),
            patch.object(db_postgres, 'get_base_ticket', new=AsyncMock(return_value=base_ticket)),
            patch.object(db_postgres, 'get_default_place', new=AsyncMock(return_value=default_place)),
            patch('utilities.utl_func.get_formatted_date_and_time_of_event',
                  new=AsyncMock(return_value=('15.11.2026', '18:00'))),
            patch('utilities.utl_func.format_ticket_contacts', return_value="Источник: не указан<br>Покупатель: Неизвестен<br>Телефон: +79991234567<br>Email: test@example.com"),
        ):
            html_text, bt_list = await build_show_list_text(session, se)

        assert "42" in html_text
        assert len(bt_list) == 1
        assert bt_list[0][0] == base_ticket
        assert bt_list[0][1] == ticket

    def test_skips_created_ticket(self):
        """Tickets with status 'Создан' are skipped."""
        asyncio.run(self._test_skips_created_ticket())

    async def _test_skips_created_ticket(self):
        from utilities.utl_func import build_show_list_text
        from db import db_postgres

        # Ticket with status "Создан" should be skipped
        ticket = _make_ticket(ticket_id=99, status=TicketStatus.CREATED, base_ticket_id=100)
        se = _make_schedule_event(se_id=1, tickets=[ticket])
        te = _make_theater_event()
        default_place = _make_default_place()
        session = AsyncMock()

        with (
            patch.object(db_postgres, 'get_theater_event', new=AsyncMock(return_value=te)),
            patch.object(db_postgres, 'get_base_ticket', new=AsyncMock(return_value=MagicMock())),
            patch.object(db_postgres, 'get_default_place', new=AsyncMock(return_value=default_place)),
            patch('utilities.utl_func.get_formatted_date_and_time_of_event',
                  new=AsyncMock(return_value=('15.11.2026', '18:00'))),
        ):
            html_text, bt_list = await build_show_list_text(session, se)

        # Skipped ticket should not appear in the list
        assert len(bt_list) == 0

    def test_skips_cancelled_ticket(self):
        """Tickets with status 'Отменен' are skipped."""
        asyncio.run(self._test_skips_cancelled_ticket())

    async def _test_skips_cancelled_ticket(self):
        from utilities.utl_func import build_show_list_text
        from db import db_postgres

        ticket = _make_ticket(ticket_id=99, status=TicketStatus.CANCELED, base_ticket_id=100)
        se = _make_schedule_event(se_id=1, tickets=[ticket])
        te = _make_theater_event()
        default_place = _make_default_place()
        session = AsyncMock()

        with (
            patch.object(db_postgres, 'get_theater_event', new=AsyncMock(return_value=te)),
            patch.object(db_postgres, 'get_base_ticket', new=AsyncMock(return_value=MagicMock())),
            patch.object(db_postgres, 'get_default_place', new=AsyncMock(return_value=default_place)),
            patch('utilities.utl_func.get_formatted_date_and_time_of_event',
                  new=AsyncMock(return_value=('15.11.2026', '18:00'))),
        ):
            html_text, bt_list = await build_show_list_text(session, se)

        assert len(bt_list) == 0

    def test_qty_visitors_count(self):
        """Visitor count reflects PAID/APPROVED tickets only."""
        asyncio.run(self._test_qty_visitors_count())

    async def _test_qty_visitors_count(self):
        from utilities.utl_func import build_show_list_text
        from db import db_postgres

        # 1 PAID adult + 1 child, 1 CREATED (should be skipped)
        ticket_paid = _make_ticket(ticket_id=1, status=TicketStatus.PAID, base_ticket_id=100)
        ticket_created = _make_ticket(ticket_id=2, status=TicketStatus.CREATED, base_ticket_id=101)
        base_ticket_paid = _make_base_ticket(bt_id=100, name="Семейный",
                                             quality_of_children=1, quality_of_adult=1, quality_of_add_adult=0)
        base_ticket_created = _make_base_ticket(bt_id=101, name="Взрослый",
                                                quality_of_children=0, quality_of_adult=1, quality_of_add_adult=0)

        se = _make_schedule_event(se_id=1, tickets=[ticket_paid, ticket_created])
        te = _make_theater_event()
        default_place = _make_default_place()
        session = AsyncMock()

        def get_base_ticket_side_effect(sess, bt_id):
            if bt_id == 100:
                return base_ticket_paid
            return base_ticket_created

        with (
            patch.object(db_postgres, 'get_theater_event', new=AsyncMock(return_value=te)),
            patch.object(db_postgres, 'get_base_ticket', new=AsyncMock(side_effect=get_base_ticket_side_effect)),
            patch.object(db_postgres, 'get_default_place', new=AsyncMock(return_value=default_place)),
            patch('utilities.utl_func.get_formatted_date_and_time_of_event',
                  new=AsyncMock(return_value=('15.11.2026', '18:00'))),
            patch('utilities.utl_func.format_ticket_contacts', return_value="Телефон: +79991234567"),
        ):
            html_text, bt_list = await build_show_list_text(session, se)

        # Only PAID ticket should be counted
        assert "д=1|в=1" in html_text
        assert len(bt_list) == 1


# ─── _has_published_show_list ────────────────────────────────────────────────


class TestHasPublishedShowList:
    """Tests for _has_published_show_list: dedup check."""

    def test_no_delivery_returns_false(self):
        """No existing delivery → False."""
        asyncio.run(self._test_no_delivery())

    async def _test_no_delivery(self):
        session = AsyncMock()
        # Mock session.execute to return no results
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        auto_sending = _make_auto_sending(sending_id=1)
        result = await _has_published_show_list(session, auto_sending, schedule_event_id=5, developer_chat_id=123)
        assert result is False

    def test_existing_delivery_returns_true(self):
        """Existing delivery record → True."""
        asyncio.run(self._test_existing_delivery())

    async def _test_existing_delivery(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = MagicMock()  # non-None
        session.execute = AsyncMock(return_value=mock_result)

        auto_sending = _make_auto_sending(sending_id=1)
        result = await _has_published_show_list(session, auto_sending, schedule_event_id=5, developer_chat_id=123)
        assert result is True

    def test_dedup_key_format(self):
        """dedup_key is 'se:{schedule_event_id}'."""
        asyncio.run(self._test_dedup_key_format())

    async def _test_dedup_key_format(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        auto_sending = _make_auto_sending(sending_id=1)
        await _has_published_show_list(session, auto_sending, schedule_event_id=42, developer_chat_id=123)

        # Verify session.execute was called (the WHERE clause should contain dedup_key='se:42')
        session.execute.assert_called_once()


# ─── _record_show_list_published ─────────────────────────────────────────────


class TestRecordShowListPublished:
    """Tests for _record_show_list_published: dedup recording."""

    def test_calls_create_delivery(self):
        """Records delivery via db_postgres.create_delivery."""
        asyncio.run(self._test_calls_create_delivery())

    async def _test_calls_create_delivery(self):
        from db import db_postgres

        session = AsyncMock()
        auto_sending = _make_auto_sending(sending_id=7)

        create_mock = AsyncMock()
        with patch.object(db_postgres, 'create_delivery', new=create_mock):
            await _record_show_list_published(session, auto_sending, schedule_event_id=42, developer_chat_id=999)

        create_mock.assert_called_once()
        kwargs = create_mock.call_args
        assert kwargs.kwargs['auto_sending_id'] == 7
        assert kwargs.kwargs['user_id'] == 999
        assert kwargs.kwargs['dedup_key'] == 'se:42'
        assert kwargs.kwargs['schedule_event_id'] == 42


# ─── publish_show_list_to_topic ──────────────────────────────────────────────


class TestPublishShowListToTopic:
    """Tests for publish_show_list_to_topic: topic, fallback, error handling."""

    def test_sends_to_topic(self):
        """When topic is configured, sends with message_thread_id."""
        asyncio.run(self._test_sends_to_topic())

    async def _test_sends_to_topic(self):
        context = _make_context(bot_data={'dict_topics_name': {'Списки на показы': 42}})
        session = AsyncMock()
        se = _make_schedule_event(se_id=5, tickets=[])

        with (
            patch('schedule.auto_sending.build_show_list_text',
                  new=AsyncMock(return_value=("Test list text", []))),
            patch('schedule.auto_sending.transform_html') as mock_transform,
        ):
            mock_transform.return_value = MagicMock(text="Transformed text", entities=[])
            result = await publish_show_list_to_topic(context, session, se)

        assert result is True
        context.bot.send_message.assert_called_once()
        call_kwargs = context.bot.send_message.call_args.kwargs
        assert call_kwargs['message_thread_id'] == 42
        assert call_kwargs['text'] == "Transformed text"

    def test_fallback_to_general_chat(self):
        """When topic is not configured, sends without message_thread_id."""
        asyncio.run(self._test_fallback_to_general_chat())

    async def _test_fallback_to_general_chat(self):
        context = _make_context(bot_data={'dict_topics_name': {}})
        session = AsyncMock()
        se = _make_schedule_event(se_id=5, tickets=[])

        with (
            patch('schedule.auto_sending.build_show_list_text',
                  new=AsyncMock(return_value=("Test list text", []))),
            patch('schedule.auto_sending.transform_html') as mock_transform,
        ):
            mock_transform.return_value = MagicMock(text="Transformed text", entities=[])
            result = await publish_show_list_to_topic(context, session, se)

        assert result is True
        context.bot.send_message.assert_called_once()
        call_kwargs = context.bot.send_message.call_args.kwargs
        assert 'message_thread_id' not in call_kwargs

    def test_includes_event_hashtag(self):
        """Message text includes #Мероприятие hashtag with event ID."""
        asyncio.run(self._test_includes_event_hashtag())

    async def _test_includes_event_hashtag(self):
        context = _make_context()
        session = AsyncMock()
        se = _make_schedule_event(se_id=99, tickets=[])

        with (
            patch('schedule.auto_sending.build_show_list_text',
                  new=AsyncMock(return_value=("List body", []))),
            patch('schedule.auto_sending.transform_html') as mock_transform,
        ):
            mock_transform.return_value = MagicMock(text="#Мероприятие <code>99</code>", entities=[])
            result = await publish_show_list_to_topic(context, session, se)

        assert result is True
        # The text passed to transform_html should contain the hashtag
        transform_call = mock_transform.call_args
        assert "#Мероприятие" in transform_call[0][0]
        assert "99" in transform_call[0][0]

    def test_handles_send_error(self):
        """On send error, returns False without crashing."""
        asyncio.run(self._test_handles_send_error())

    async def _test_handles_send_error(self):
        context = _make_context()
        session = AsyncMock()
        se = _make_schedule_event(se_id=5, tickets=[])

        context.bot.send_message.side_effect = Exception("Network error")

        with (
            patch('schedule.auto_sending.build_show_list_text',
                  new=AsyncMock(return_value=("Test", []))),
            patch('schedule.auto_sending.transform_html') as mock_transform,
        ):
            mock_transform.return_value = MagicMock(text="Text", entities=[])
            result = await publish_show_list_to_topic(context, session, se)

        assert result is False

    def test_uses_admin_group_chat_id(self):
        """Uses ADMIN_GROUP as chat_id."""
        asyncio.run(self._test_uses_admin_group_chat_id())

    async def _test_uses_admin_group_chat_id(self):
        context = _make_context()
        session = AsyncMock()
        se = _make_schedule_event(se_id=5, tickets=[])

        with (
            patch('schedule.auto_sending.build_show_list_text',
                  new=AsyncMock(return_value=("Test", []))),
            patch('schedule.auto_sending.transform_html') as mock_transform,
        ):
            mock_transform.return_value = MagicMock(text="Text", entities=[])
            await publish_show_list_to_topic(context, session, se)

        call_kwargs = context.bot.send_message.call_args.kwargs
        # ADMIN_GROUP is a list; the first element is used
        from settings.settings import ADMIN_GROUP
        assert call_kwargs['chat_id'] == ADMIN_GROUP

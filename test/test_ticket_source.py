"""Tests for TicketSource — source of initial ticket purchase.

Covers:
- create_ticket with source=TicketSource.WEBSITE (website flow)
- create_ticket with source=TicketSource.BOT (bot flow)
- create_ticket with source=None defaults to BOT
- create_booking_ticket sets source=WEBSITE
- create_transferred_ticket inherits source from original
- utl_ticket.create_tickets passes source=BOT
"""
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio

from db.enum import TicketSource
from db.models import Ticket


def test_ticket_source_enum_values():
    """TicketSource enum has WEBSITE and BOT values."""
    assert TicketSource.WEBSITE.value == 'website'
    assert TicketSource.BOT.value == 'bot'


def test_create_ticket_with_source_website(monkeypatch):
    """db_postgres.create_ticket passes source=TicketSource.WEBSITE to Ticket constructor."""
    import asyncio
    from db import db_postgres

    async def _run():
        captured = {}
        fake_session = AsyncMock()
        fake_session.add = AsyncMock()
        fake_session.commit = AsyncMock()

        def fake_ticket(**kwargs):
            captured.update(kwargs)
            obj = MagicMock(spec=Ticket)
            obj.id = 1
            return obj

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)
        await db_postgres.create_ticket(
            fake_session,
            base_ticket_id=1,
            price=1000,
            schedule_event_id=1,
            source=TicketSource.WEBSITE,
        )
        return captured

    captured = asyncio.new_event_loop().run_until_complete(_run())
    assert captured.get('source') == TicketSource.WEBSITE


def test_create_ticket_with_source_bot(monkeypatch):
    """db_postgres.create_ticket passes source=TicketSource.BOT to Ticket constructor."""
    import asyncio
    from db import db_postgres

    async def _run():
        captured = {}
        fake_session = AsyncMock()
        fake_session.add = AsyncMock()
        fake_session.commit = AsyncMock()

        def fake_ticket(**kwargs):
            captured.update(kwargs)
            obj = MagicMock(spec=Ticket)
            obj.id = 1
            return obj

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)
        await db_postgres.create_ticket(
            fake_session,
            base_ticket_id=1,
            price=1000,
            schedule_event_id=1,
            source=TicketSource.BOT,
        )
        return captured

    captured = asyncio.new_event_loop().run_until_complete(_run())
    assert captured.get('source') == TicketSource.BOT


def test_create_ticket_without_source_defaults_bot(monkeypatch):
    """db_postgres.create_ticket without source defaults to TicketSource.BOT."""
    import asyncio
    from db import db_postgres

    async def _run():
        captured = {}
        fake_session = AsyncMock()
        fake_session.add = AsyncMock()
        fake_session.commit = AsyncMock()

        def fake_ticket(**kwargs):
            captured.update(kwargs)
            obj = MagicMock(spec=Ticket)
            obj.id = 1
            return obj

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)
        await db_postgres.create_ticket(
            fake_session,
            base_ticket_id=1,
            price=1000,
            schedule_event_id=1,
        )
        return captured

    captured = asyncio.new_event_loop().run_until_complete(_run())
    assert captured.get('source') == TicketSource.BOT


def test_utl_ticket_create_tickets_passes_bot_source(monkeypatch):
    """utl_ticket.create_tickets passes source=TicketSource.BOT to create_ticket."""
    import asyncio

    async def _run():
        fake_ticket = MagicMock(spec=Ticket)
        fake_ticket.id = 1
        captured_sources = []

        async def fake_create_ticket(session, **kwargs):
            captured_sources.append(kwargs.get('source'))
            return fake_ticket

        async def fake_get_base_ticket(session, bid):
            bt = MagicMock()
            bt.base_ticket_id = bid
            return bt

        monkeypatch.setattr('db.db_postgres.create_ticket', fake_create_ticket)
        monkeypatch.setattr('db.db_postgres.get_base_ticket', fake_get_base_ticket)

        from utilities import utl_ticket

        context = MagicMock()
        context.session = MagicMock()
        context.user_data = {
            'reserve_user_data': {
                'choose_schedule_event_ids': [1],
                'chose_price': 1000,
                'applied_promo_id': None,
                'chose_base_ticket_id': 1,
            }
        }

        await utl_ticket.create_tickets(context, 'CREATED')
        return captured_sources

    sources = asyncio.new_event_loop().run_until_complete(_run())
    assert TicketSource.BOT in sources


def test_create_booking_ticket_sets_source_website(monkeypatch):
    """db_postgres.create_booking_ticket creates Ticket with source=TicketSource.WEBSITE."""
    import asyncio
    from db import db_postgres

    async def _run():
        captured_ticket_kwargs = {}
        added_objects = []

        fake_session = AsyncMock()

        def fake_add(obj):
            added_objects.append(obj)

        fake_session.add = fake_add
        fake_session.flush = AsyncMock()

        def fake_ticket(**kwargs):
            captured_ticket_kwargs.update(kwargs)
            obj = MagicMock(spec=Ticket)
            obj.id = 1
            return obj

        def fake_person(**kwargs):
            obj = MagicMock()
            obj.id = 10
            return obj

        def fake_adult(**kwargs):
            obj = MagicMock()
            obj.id = 20
            return obj

        def fake_child(**kwargs):
            obj = MagicMock()
            obj.id = 30
            return obj

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)
        monkeypatch.setattr(db_postgres, 'Person', fake_person)
        monkeypatch.setattr(db_postgres, 'Adult', fake_adult)
        monkeypatch.setattr(db_postgres, 'Child', fake_child)

        ticket = await db_postgres.create_booking_ticket(
            fake_session,
            base_ticket_id=1,
            schedule_event_id=1,
            price=1000,
            adult_name='Иван Иванов',
            phone='1234567890',
            email='test@example.com',
        )
        return captured_ticket_kwargs, added_objects

    result = asyncio.new_event_loop().run_until_complete(_run())
    captured_kwargs, added_objects = result
    assert captured_kwargs.get('source') == TicketSource.WEBSITE


def test_create_transferred_ticket_inherits_source(monkeypatch):
    """db_postgres.create_transferred_ticket inherits source from original ticket."""
    import asyncio
    from db import db_postgres

    async def _run():
        captured_ticket_kwargs = {}

        fake_session = AsyncMock()
        fake_session.add = MagicMock()
        fake_session.flush = AsyncMock()

        def fake_ticket(**kwargs):
            captured_ticket_kwargs.update(kwargs)
            obj = MagicMock(spec=Ticket)
            obj.id = 2
            return obj

        original = MagicMock(spec=Ticket)
        original.promo_id = 5
        original.notes = 'Test notes'
        original.source = TicketSource.WEBSITE

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)

        ticket = await db_postgres.create_transferred_ticket(
            fake_session,
            original_ticket=original,
            base_ticket_id=1,
            price=1000,
            schedule_event_id=2,
        )
        return captured_ticket_kwargs

    captured = asyncio.new_event_loop().run_until_complete(_run())
    assert captured.get('source') == TicketSource.WEBSITE
    assert captured.get('promo_id') == 5
    assert captured.get('notes') == 'Test notes'

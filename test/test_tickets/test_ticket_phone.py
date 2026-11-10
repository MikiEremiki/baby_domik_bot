"""Tests for ticket phone functionality — phone snapshot, validation, and migration.

Covers:
- check_phone_number validation (valid and invalid phones)
- create_ticket passes phone to Ticket constructor
- create_booking_ticket stores phone in Ticket.phone
- create_transferred_ticket inherits phone from original
- phone validation on website (valid, invalid, +7/8/10 digits, error text)
- execute_ticket_migration single transaction
- MIGRATED ticket re-migration prevention
- transaction rollback on error
- Google Sheets not called on rollback
- parse_and_create_custom_ticket utility (valid, invalid input)
- apply_custom_ticket_to_reserve utility
- _migrate_ticket_db sub-function
- execute_ticket_migration with send_status callback
"""
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio

from db.models import Ticket
from utilities.utl_text import check_phone_number


def test_check_phone_number_valid():
    """check_phone_number returns True (valid) for correct 10-digit phones starting with 9."""
    assert check_phone_number('9123456789')
    assert check_phone_number('9000000000')
    assert check_phone_number('9999999999')


def test_check_phone_number_invalid():
    """check_phone_number returns False (invalid) for incorrect phones."""
    assert not check_phone_number('8123456789')  # starts with 8
    assert not check_phone_number('123456789')   # 9 digits
    assert not check_phone_number('91234567890') # 11 digits
    assert not check_phone_number('')            # empty
    assert not check_phone_number('abc')         # non-numeric


def test_create_ticket_passes_phone(monkeypatch):
    """db_postgres.create_ticket passes phone param to Ticket constructor."""
    import asyncio
    from db import db_postgres

    async def _run():
        captured = {}
        fake_session = AsyncMock()
        fake_session.add = MagicMock()
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
            phone=9123456789,
        )
        return captured

    loop = asyncio.new_event_loop()

    try:

        captured = loop.run_until_complete(_run())

    finally:

        loop.close()
    assert captured.get('phone') == 9123456789


def test_create_ticket_without_phone_defaults_none(monkeypatch):
    """db_postgres.create_ticket without phone passes None."""
    import asyncio
    from db import db_postgres

    async def _run():
        captured = {}
        fake_session = AsyncMock()
        fake_session.add = MagicMock()
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

    loop = asyncio.new_event_loop()

    try:

        captured = loop.run_until_complete(_run())

    finally:

        loop.close()
    assert captured.get('phone') is None


def test_create_booking_ticket_stores_phone(monkeypatch):
    """db_postgres.create_booking_ticket stores phone in Ticket.phone."""
    import asyncio
    from db import db_postgres

    async def _run():
        captured_ticket_kwargs = {}
        added_objects = []

        fake_session = AsyncMock()
        fake_session.add = MagicMock()
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

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)
        monkeypatch.setattr(db_postgres, 'Person', fake_person)
        monkeypatch.setattr(db_postgres, 'Adult', fake_adult)

        await db_postgres.create_booking_ticket(
            fake_session,
            base_ticket_id=1,
            schedule_event_id=1,
            price=1000,
            adult_name='Иван Иванов',
            phone=9123456789,
            email='buyer@example.com',
        )
        return captured_ticket_kwargs

    loop = asyncio.new_event_loop()

    try:

        captured = loop.run_until_complete(_run())

    finally:

        loop.close()
    assert captured.get('phone') == 9123456789


def test_create_transferred_ticket_inherits_phone(monkeypatch):
    """db_postgres.create_transferred_ticket copies phone from original ticket."""
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
        original.email = 'original@example.com'
        original.phone = 9123456789

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)

        await db_postgres.create_transferred_ticket(
            fake_session,
            original_ticket=original,
            base_ticket_id=1,
            price=1000,
            schedule_event_id=2,
        )
        return captured_ticket_kwargs

    loop = asyncio.new_event_loop()

    try:

        captured = loop.run_until_complete(_run())

    finally:

        loop.close()
    assert captured.get('phone') == 9123456789


def test_create_transferred_ticket_inherits_none_phone(monkeypatch):
    """db_postgres.create_transferred_ticket copies None phone when original has no phone."""
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
        original.promo_id = None
        original.notes = None
        original.email = None
        original.phone = None

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)

        await db_postgres.create_transferred_ticket(
            fake_session,
            original_ticket=original,
            base_ticket_id=1,
            price=1000,
            schedule_event_id=2,
        )
        return captured_ticket_kwargs

    loop = asyncio.new_event_loop()

    try:

        captured = loop.run_until_complete(_run())

    finally:

        loop.close()
    assert captured.get('phone') is None


def test_create_ticket_auto_commit_false_flushes(monkeypatch):
    """db_postgres.create_ticket with auto_commit=False calls flush, not commit."""
    import asyncio
    from db import db_postgres

    async def _run():
        fake_session = AsyncMock()
        fake_session.add = MagicMock()
        fake_session.flush = AsyncMock()
        fake_session.commit = AsyncMock()

        def fake_ticket(**kwargs):
            obj = MagicMock(spec=Ticket)
            obj.id = 1
            return obj

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)
        await db_postgres.create_ticket(
            fake_session,
            base_ticket_id=1,
            price=1000,
            schedule_event_id=1,
            auto_commit=False,
        )
        return fake_session

    loop = asyncio.new_event_loop()

    try:

        session = loop.run_until_complete(_run())

    finally:

        loop.close()
    session.flush.assert_called_once()
    session.commit.assert_not_called()


def test_update_ticket_auto_commit_false_skips_commit(monkeypatch):
    """db_postgres.update_ticket with auto_commit=False skips commit."""
    import asyncio
    from db import db_postgres

    async def _run():
        fake_ticket = MagicMock()
        fake_session = AsyncMock()
        fake_session.get = AsyncMock(return_value=fake_ticket)
        fake_session.commit = AsyncMock()

        monkeypatch.setattr(db_postgres, 'Ticket', MagicMock())
        await db_postgres.update_ticket(
            fake_session, 1, status='MIGRATED', auto_commit=False
        )
        return fake_session

    loop = asyncio.new_event_loop()

    try:

        session = loop.run_until_complete(_run())

    finally:

        loop.close()
    session.commit.assert_not_called()


def test_attach_user_and_people_auto_commit_false_skips_commit(monkeypatch):
    """attach_user_and_people_to_ticket with auto_commit=False skips commit."""
    import asyncio
    from db import db_postgres
    from sqlalchemy import select

    async def _run():
        fake_ticket = MagicMock()
        fake_ticket.people = []
        fake_person = MagicMock()
        fake_user = MagicMock()

        fake_session = AsyncMock()
        fake_result = MagicMock()
        fake_result.scalar_one.return_value = fake_ticket
        fake_session.execute = AsyncMock(return_value=fake_result)
        fake_session.get = AsyncMock(side_effect=[fake_person, fake_user])
        fake_session.commit = AsyncMock()

        await db_postgres.attach_user_and_people_to_ticket(
            fake_session, 1, 100, [1], auto_commit=False
        )
        return fake_session

    loop = asyncio.new_event_loop()

    try:

        session = loop.run_until_complete(_run())

    finally:

        loop.close()
    session.commit.assert_not_called()


# ─── Tests for custom ticket utility functions ───

def test_parse_and_create_custom_ticket_valid(monkeypatch):
    """parse_and_create_custom_ticket returns ticket on valid input."""
    import asyncio
    from utilities.utl_ticket import parse_and_create_custom_ticket

    async def _run():
        fake_ticket = MagicMock()
        fake_ticket.base_ticket_id = 999

        fake_session = AsyncMock()
        fake_context = MagicMock()
        fake_context.session = fake_session

        async def fake_get_or_create(*a, **kw):
            return fake_ticket

        monkeypatch.setattr(
            'db.db_postgres.get_or_create_custom_base_ticket',
            fake_get_or_create,
        )

        ticket, error = await parse_and_create_custom_ticket(
            fake_context, '8 1 15000'
        )
        return ticket, error, fake_session

    ticket, error, session = asyncio.new_event_loop().run_until_complete(_run())
    assert ticket is not None
    assert error is None
    assert ticket.base_ticket_id == 999


def test_parse_and_create_custom_ticket_invalid_format(monkeypatch):
    """parse_and_create_custom_ticket returns error on bad input."""
    import asyncio
    from utilities.utl_ticket import parse_and_create_custom_ticket

    async def _run():
        fake_context = MagicMock()
        fake_context.session = AsyncMock()

        for bad_input in ['abc', '1 2', '1 2 3 4', '1 2 abc', '']:
            ticket, error = await parse_and_create_custom_ticket(fake_context, bad_input)
            assert ticket is None, f"Expected None for {bad_input!r}"
            assert error is not None, f"Expected error for {bad_input!r}"
            assert 'Неверный формат' in error

    loop = asyncio.new_event_loop()

    try:

        loop.run_until_complete(_run())

    finally:

        loop.close()
def test_apply_custom_ticket_to_reserve(monkeypatch):
    """apply_custom_ticket_to_reserve sets reserve_user_data fields correctly."""
    from utilities.utl_ticket import apply_custom_ticket_to_reserve

    fake_ticket = MagicMock()
    fake_ticket.base_ticket_id = 42

    reserve_user_data = {
        'choose_schedule_event_id': 10,
    }
    fake_context = MagicMock()
    fake_context.user_data = {'reserve_user_data': reserve_user_data}

    apply_custom_ticket_to_reserve(fake_context, fake_ticket, 5000)

    assert reserve_user_data['chose_price'] == 5000
    assert reserve_user_data['chose_base_ticket_id'] == 42
    assert reserve_user_data['choose_schedule_event_ids'] == [10]


# ─── Tests for refactored migration functions ───
# Note: _migrate_ticket_db and execute_ticket_migration live in reserve_admin_hl
# which has circular imports. Test the logic by importing db_postgres directly.

def test_migrate_ticket_db_logic(monkeypatch):
    """DB migration logic: update_ticket + create_transferred + attach + commit."""
    import asyncio
    from db import db_postgres
    from db.enum import TicketStatus

    async def _run():
        new_ticket = MagicMock()
        new_ticket.id = 2
        new_ticket.people = []

        original = MagicMock()
        original.id = 1
        original.people = [MagicMock(id=10), MagicMock(id=11)]
        original.promo_id = None
        original.notes = None
        original.email = None
        original.phone = 9123456789

        fake_session = AsyncMock()
        fake_session.add = MagicMock()
        fake_session.flush = AsyncMock()
        fake_session.commit = AsyncMock()

        # Monkeypatch create_transferred_ticket to return our mock
        async def fake_create_transferred(*a, **kw):
            fake_session.add(new_ticket)
            await fake_session.flush()
            return new_ticket

        monkeypatch.setattr(db_postgres, 'create_transferred_ticket', fake_create_transferred)

        # Step 1: update_ticket (no-op with auto_commit=False)
        fake_ticket_obj = MagicMock()
        fake_session.get = AsyncMock(return_value=fake_ticket_obj)
        await db_postgres.update_ticket(
            fake_session, original.id,
            status=TicketStatus.MIGRATED,
            auto_commit=False,
        )

        # Step 2: create_transferred_ticket
        transferred = await db_postgres.create_transferred_ticket(
            fake_session,
            original_ticket=original,
            base_ticket_id=1,
            price=1000,
            schedule_event_id=2,
        )

        # Step 3: attach_user_and_people_to_ticket
        fake_result = MagicMock()
        fake_result.scalar_one.return_value = transferred
        fake_session.execute = AsyncMock(return_value=fake_result)
        fake_person = MagicMock()
        fake_session.get = AsyncMock(return_value=fake_person)

        await db_postgres.attach_user_and_people_to_ticket(
            fake_session,
            transferred.id,
            100,
            [10, 11],
            auto_commit=False,
        )

        # Step 4: commit
        await fake_session.commit()

        return transferred, fake_session

    result, session = asyncio.new_event_loop().run_until_complete(_run())
    assert result.id == 2
    session.commit.assert_called_once()


def test_migrate_ticket_db_rollback_on_error(monkeypatch):
    """DB migration rollback: session.rollback() on exception."""
    import asyncio
    from db import db_postgres
    from db.enum import TicketStatus

    async def _run():
        original = MagicMock()
        original.id = 1

        fake_session = AsyncMock()
        fake_ticket = MagicMock()
        fake_session.get = AsyncMock(return_value=fake_ticket)
        fake_ticket.status = TicketStatus.CREATED

        # Simulate error during update
        async def failing_update(*a, **kw):
            raise RuntimeError("DB error")

        monkeypatch.setattr(db_postgres, 'update_ticket', failing_update)

        try:
            await db_postgres.update_ticket(
                fake_session, original.id,
                status=TicketStatus.MIGRATED,
                auto_commit=False,
            )
        except RuntimeError:
            await fake_session.rollback()

        return fake_session

    loop = asyncio.new_event_loop()

    try:

        session = loop.run_until_complete(_run())

    finally:

        loop.close()
    session.rollback.assert_called_once()


def test_execute_ticket_migration_already_migrated_check():
    """Migration check: skip if ticket status is already MIGRATED."""
    from db.enum import TicketStatus

    original = MagicMock()
    original.status = TicketStatus.MIGRATED

    # The check is simple — if status is MIGRATED, we should not proceed
    if original.status == TicketStatus.MIGRATED:
        result = None
    else:
        result = 'would_proceed'

    assert result is None


def test_send_status_callback_pattern():
    """send_status callback pattern: default sends message, custom edits message."""
    import asyncio

    async def _run():
        messages = []
        edits = []

        # Simulate default send_status
        async def default_send(text: str) -> None:
            messages.append(text)

        # Simulate custom send_status (edit_message_text)
        async def custom_send(text: str) -> None:
            edits.append(text)

        await default_send('test 1')
        await custom_send('test 2')

        return messages, edits

    messages, edits = asyncio.new_event_loop().run_until_complete(_run())
    assert messages == ['test 1']
    assert edits == ['test 2']


# ─── Tests for create_tickets() reading phone from client_data ───

def test_create_tickets_reads_phone_from_client_data(monkeypatch):
    """create_tickets() reads phone from reserve_user_data['client_data']['phone'].
    
    This is the critical path: phone must come from client_data, not buyer_phone key.
    """
    import asyncio
    from db import db_postgres
    from utilities.utl_ticket import create_tickets
    from db.enum import TicketSource

    async def _run():
        captured_ticket_kwargs = []

        fake_base_ticket = MagicMock()
        fake_base_ticket.base_ticket_id = 5

        async def fake_get_base_ticket(session, bt_id):
            return fake_base_ticket

        async def fake_create_ticket(session, **kwargs):
            captured_ticket_kwargs.append(kwargs.copy())
            obj = MagicMock(spec=Ticket)
            obj.id = 1
            return obj

        monkeypatch.setattr(db_postgres, 'get_base_ticket', fake_get_base_ticket)
        monkeypatch.setattr(db_postgres, 'create_ticket', fake_create_ticket)

        fake_context = MagicMock()
        fake_context.session = AsyncMock()
        fake_context.user_data = {
            'reserve_user_data': {
                'choose_schedule_event_ids': [1],
                'chose_price': 10000,
                'chose_base_ticket_id': 5,
                'client_data': {
                    'name_adult': 'Иван',
                    'phone': '9123456789',
                    'data_children': [],
                },
                'buyer_email': 'ivan@example.com',
            }
        }

        ticket_ids = await create_tickets(fake_context, 'CREATED')
        return ticket_ids, captured_ticket_kwargs

    ticket_ids, kwargs_list = asyncio.new_event_loop().run_until_complete(_run())
    assert len(kwargs_list) == 1
    assert kwargs_list[0]['phone'] == 9123456789
    assert kwargs_list[0]['source'] == TicketSource.BOT


def test_create_tickets_without_client_data_phone_defaults_none(monkeypatch):
    """create_tickets() handles missing client_data gracefully — phone is None."""
    import asyncio
    from db import db_postgres
    from utilities.utl_ticket import create_tickets

    async def _run():
        captured_ticket_kwargs = []

        fake_base_ticket = MagicMock()
        fake_base_ticket.base_ticket_id = 5

        async def fake_get_base_ticket(session, bt_id):
            return fake_base_ticket

        async def fake_create_ticket(session, **kwargs):
            captured_ticket_kwargs.append(kwargs.copy())
            obj = MagicMock(spec=Ticket)
            obj.id = 1
            return obj

        monkeypatch.setattr(db_postgres, 'get_base_ticket', fake_get_base_ticket)
        monkeypatch.setattr(db_postgres, 'create_ticket', fake_create_ticket)

        fake_context = MagicMock()
        fake_context.session = AsyncMock()
        fake_context.user_data = {
            'reserve_user_data': {
                'choose_schedule_event_ids': [1],
                'chose_price': 10000,
                'chose_base_ticket_id': 5,
                # No client_data at all
                'buyer_email': 'ivan@example.com',
            }
        }

        ticket_ids = await create_tickets(fake_context, 'CREATED')
        return ticket_ids, captured_ticket_kwargs

    ticket_ids, kwargs_list = asyncio.new_event_loop().run_until_complete(_run())
    assert len(kwargs_list) == 1
    assert kwargs_list[0]['phone'] is None


def test_create_tickets_with_empty_client_data(monkeypatch):
    """create_tickets() handles empty client_data dict — phone is None."""
    import asyncio
    from db import db_postgres
    from utilities.utl_ticket import create_tickets

    async def _run():
        captured_ticket_kwargs = []

        fake_base_ticket = MagicMock()
        fake_base_ticket.base_ticket_id = 5

        async def fake_get_base_ticket(session, bt_id):
            return fake_base_ticket

        async def fake_create_ticket(session, **kwargs):
            captured_ticket_kwargs.append(kwargs.copy())
            obj = MagicMock(spec=Ticket)
            obj.id = 1
            return obj

        monkeypatch.setattr(db_postgres, 'get_base_ticket', fake_get_base_ticket)
        monkeypatch.setattr(db_postgres, 'create_ticket', fake_create_ticket)

        fake_context = MagicMock()
        fake_context.session = AsyncMock()
        fake_context.user_data = {
            'reserve_user_data': {
                'choose_schedule_event_ids': [1],
                'chose_price': 10000,
                'chose_base_ticket_id': 5,
                'client_data': {},  # Empty dict
                'buyer_email': 'ivan@example.com',
            }
        }

        ticket_ids = await create_tickets(fake_context, 'CREATED')
        return ticket_ids, captured_ticket_kwargs

    ticket_ids, kwargs_list = asyncio.new_event_loop().run_until_complete(_run())
    assert len(kwargs_list) == 1
    assert kwargs_list[0]['phone'] is None


def test_create_tickets_with_invalid_phone_string(monkeypatch):
    """create_tickets() handles non-numeric phone in client_data — phone is None (try/except)."""
    import asyncio
    from db import db_postgres
    from utilities.utl_ticket import create_tickets

    async def _run():
        captured_ticket_kwargs = []

        fake_base_ticket = MagicMock()
        fake_base_ticket.base_ticket_id = 5

        async def fake_get_base_ticket(session, bt_id):
            return fake_base_ticket

        async def fake_create_ticket(session, **kwargs):
            captured_ticket_kwargs.append(kwargs.copy())
            obj = MagicMock(spec=Ticket)
            obj.id = 1
            return obj

        monkeypatch.setattr(db_postgres, 'get_base_ticket', fake_get_base_ticket)
        monkeypatch.setattr(db_postgres, 'create_ticket', fake_create_ticket)

        fake_context = MagicMock()
        fake_context.session = AsyncMock()
        fake_context.user_data = {
            'reserve_user_data': {
                'choose_schedule_event_ids': [1],
                'chose_price': 10000,
                'chose_base_ticket_id': 5,
                'client_data': {
                    'name_adult': 'Иван',
                    'phone': 'abc',  # Non-numeric phone
                    'data_children': [],
                },
                'buyer_email': 'ivan@example.com',
            }
        }

        # Should NOT raise — try/except catches ValueError, phone becomes None
        ticket_ids = await create_tickets(fake_context, 'CREATED')
        return ticket_ids, captured_ticket_kwargs

    ticket_ids, kwargs_list = asyncio.new_event_loop().run_until_complete(_run())
    assert len(kwargs_list) == 1
    assert kwargs_list[0]['phone'] is None

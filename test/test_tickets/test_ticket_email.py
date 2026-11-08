"""Tests for ticket email functionality — buyer email storage, validation, and inheritance.

Covers:
- check_email validation (valid and invalid emails)
- create_email_confirm_btn includes email in callback_data
- create_ticket passes email to Ticket constructor
- create_booking_ticket normalizes email (strip + lower)
- create_transferred_ticket inherits email from original
- confirm_go_pay email guard logic (returns EMAIL without email)
- handle_email_input validation flow
- handle_email_confirm_callback email extraction from callback_data
"""
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio

from db.models import Ticket
from utilities.utl_text import check_email


def test_check_email_valid():
    """check_email returns a truthy match for valid email addresses."""
    assert check_email('user@example.com')
    assert check_email('test.user@domain.org')
    assert check_email('a@b.co')
    assert check_email('user+tag@gmail.com')


def test_check_email_invalid():
    """check_email returns a falsy value (None) for invalid email addresses."""
    assert not check_email('not-an-email')
    assert not check_email('user@')
    assert not check_email('@domain.com')
    assert not check_email('user domain.com')
    assert not check_email('')


def test_check_email_case_insensitive():
    """check_email accepts uppercase emails by converting to lower."""
    assert check_email('User@Example.COM')


def test_create_email_confirm_btn_includes_email_in_callback(monkeypatch):
    """create_email_confirm_btn puts email in callback_data as 'email_confirm|{email}'."""
    import asyncio
    from utilities import utl_kbd

    async def _run():
        result_btn, result_text = await utl_kbd.create_email_confirm_btn(
            'Введите email:', 'test@example.com'
        )
        return result_btn, result_text

    btn, text = asyncio.new_event_loop().run_until_complete(_run())
    assert btn is not None
    button = btn[0]
    assert button.callback_data == 'email_confirm|test@example.com'
    assert 'test@example.com' in text


def test_create_email_confirm_btn_no_email_returns_none():
    """create_email_confirm_btn returns None button when email is None."""
    import asyncio
    from utilities import utl_kbd

    async def _run():
        return await utl_kbd.create_email_confirm_btn('Введите email:', None)

    btn, text = asyncio.new_event_loop().run_until_complete(_run())
    assert btn is None
    assert 'Последний введенный email' not in text


def test_create_ticket_passes_email(monkeypatch):
    """db_postgres.create_ticket passes email param to Ticket constructor."""
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
            email='buyer@example.com',
        )
        return captured

    captured = asyncio.new_event_loop().run_until_complete(_run())
    assert captured.get('email') == 'buyer@example.com'


def test_create_ticket_without_email_defaults_none(monkeypatch):
    """db_postgres.create_ticket without email passes None."""
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
    assert captured.get('email') is None


def test_create_booking_ticket_normalizes_email(monkeypatch):
    """db_postgres.create_booking_ticket normalizes email with strip+lower."""
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
            email='  TEST@EXAMPLE.COM  ',
        )
        return captured_ticket_kwargs

    captured = asyncio.new_event_loop().run_until_complete(_run())
    assert captured.get('email') == 'test@example.com'


def test_create_booking_ticket_notes_contains_email(monkeypatch):
    """db_postgres.create_booking_ticket stores email in notes."""
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
            phone='1234567890',
            email='buyer@example.com',
        )
        return captured_ticket_kwargs

    captured = asyncio.new_event_loop().run_until_complete(_run())
    assert 'buyer@example.com' in captured.get('notes', '')


def test_create_transferred_ticket_inherits_email(monkeypatch):
    """db_postgres.create_transferred_ticket copies email from original ticket."""
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
    assert captured.get('email') == 'original@example.com'


def test_create_transferred_ticket_inherits_none_email(monkeypatch):
    """db_postgres.create_transferred_ticket copies None email when original has no email."""
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

        monkeypatch.setattr(db_postgres, 'Ticket', fake_ticket)

        await db_postgres.create_transferred_ticket(
            fake_session,
            original_ticket=original,
            base_ticket_id=1,
            price=1000,
            schedule_event_id=2,
        )
        return captured_ticket_kwargs

    captured = asyncio.new_event_loop().run_until_complete(_run())
    assert captured.get('email') is None


def test_handle_email_input_valid_email_returns_forma():
    """handle_email_input with valid email returns 'FORMA' state."""
    import asyncio
    from conv_hl import reserve_common_hl

    async def _run():
        # Mock the proceed_to_forma_step to return 'FORMA'
        with patch.object(reserve_common_hl, 'proceed_to_forma_step', new_callable=AsyncMock) as mock_forma:
            mock_forma.return_value = 'FORMA'

            update = MagicMock()
            update.effective_message.text = '  Buyer@Example.COM  '
            update.effective_chat.send_message = AsyncMock(return_value=MagicMock(message_id=42))

            context = MagicMock()
            context.bot.edit_message_reply_markup = AsyncMock()
            context.user_data = {
                'reserve_user_data': {'message_id': 10},
                'postfix_for_cancel': 'RESERVE',
            }

            result = await reserve_common_hl.handle_email_input(update, context)
            return result, context.user_data['reserve_user_data'].get('buyer_email')

    result, email = asyncio.new_event_loop().run_until_complete(_run())
    assert result == 'FORMA'
    assert email == 'buyer@example.com'


def test_handle_email_input_invalid_email_returns_email():
    """handle_email_input with invalid email returns 'EMAIL' state (re-prompt)."""
    import asyncio
    from conv_hl import reserve_common_hl

    async def _run():
        with patch.object(reserve_common_hl, 'proceed_to_forma_step', new_callable=AsyncMock) as mock_forma:
            update = MagicMock()
            update.effective_message.text = 'not-an-email'
            update.effective_chat.send_message = AsyncMock(return_value=MagicMock(message_id=43))

            context = MagicMock()
            context.bot.edit_message_reply_markup = AsyncMock()
            context.user_data = {
                'reserve_user_data': {'message_id': 10},
                'postfix_for_cancel': 'RESERVE',
            }

            result = await reserve_common_hl.handle_email_input(update, context)
            return result

    result = asyncio.new_event_loop().run_until_complete(_run())
    assert result == 'EMAIL'


def test_handle_email_confirm_callback_extracts_email():
    """handle_email_confirm_callback extracts email from callback_data and proceeds to FORMA."""
    import asyncio
    from conv_hl import reserve_common_hl

    async def _run():
        with patch.object(reserve_common_hl, 'proceed_to_forma_step', new_callable=AsyncMock) as mock_forma:
            mock_forma.return_value = 'FORMA'

            query = MagicMock()
            query.data = 'email_confirm|test@example.com'
            query.answer = AsyncMock()
            query.edit_message_text = AsyncMock(return_value=MagicMock(message_id=44))
            update = MagicMock()
            update.callback_query = query

            context = MagicMock()
            context.user_data = {
                'reserve_user_data': {'message_id': 10},
                'postfix_for_cancel': 'RESERVE',
            }

            result = await reserve_common_hl.handle_email_confirm_callback(update, context)
            return result, context.user_data['reserve_user_data'].get('buyer_email')

    result, email = asyncio.new_event_loop().run_until_complete(_run())
    assert result == 'FORMA'
    assert email == 'test@example.com'


def test_handle_email_confirm_callback_no_email_falls_back():
    """handle_email_confirm_callback without email in callback_data falls back to manual input."""
    import asyncio
    from conv_hl import reserve_common_hl

    async def _run():
        query = MagicMock()
        query.data = 'email_confirm'
        query.edit_message_text = AsyncMock(return_value=MagicMock(message_id=44))
        update = MagicMock()
        update.callback_query = query

        context = MagicMock()
        context.user_data = {
            'reserve_user_data': {'message_id': 10},
            'postfix_for_cancel': 'RESERVE',
        }

        result = await reserve_common_hl.handle_email_confirm_callback(update, context)
        return result

    result = asyncio.new_event_loop().run_until_complete(_run())
    assert result == 'EMAIL'


def test_handle_email_confirm_callback_invalid_email_falls_back():
    """handle_email_confirm_callback with invalid email falls back to manual input."""
    import asyncio
    from conv_hl import reserve_common_hl

    async def _run():
        query = MagicMock()
        query.data = 'email_confirm|not-an-email'
        query.edit_message_text = AsyncMock(return_value=MagicMock(message_id=45))
        update = MagicMock()
        update.callback_query = query

        context = MagicMock()
        context.user_data = {
            'reserve_user_data': {'message_id': 10},
            'postfix_for_cancel': 'RESERVE',
        }

        result = await reserve_common_hl.handle_email_confirm_callback(update, context)
        return result

    result = asyncio.new_event_loop().run_until_complete(_run())
    assert result == 'EMAIL'


def test_confirm_go_pay_without_email_returns_email_state():
    """confirm_go_pay returns EMAIL state when buyer_email is missing."""
    import asyncio
    from handlers.reserve import payment

    async def _run():
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.callback_query = query

        context = MagicMock()
        context.user_data = {
            'reserve_user_data': {},
            'postfix_for_cancel': 'RESERVE',
        }
        # Mock db_postgres.get_email to return None
        with patch('handlers.reserve.payment.db_postgres.get_email', new_callable=AsyncMock) as mock_get_email:
            mock_get_email.return_value = None
            result = await payment.confirm_go_pay(update, context)
            return result

    result = asyncio.new_event_loop().run_until_complete(_run())
    assert result == 'EMAIL'


def test_confirm_go_pay_with_email_proceeds():
    """confirm_go_pay proceeds when buyer_email is present in reserve_user_data."""
    import asyncio
    from handlers.reserve import payment

    async def _run():
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        update = MagicMock()
        update.callback_query = query

        context = MagicMock()
        context.user_data = {
            'reserve_user_data': {
                'buyer_email': 'buyer@example.com',
            },
            'postfix_for_cancel': 'RESERVE',
        }
        # Mock create_and_send_payment to return a state
        with patch.object(payment, 'create_and_send_payment', new_callable=AsyncMock) as mock_pay:
            mock_pay.return_value = 'PAID'
            # Mock check_entered_command to return False (skip bot reservation checks)
            with patch('handlers.reserve.payment.check_entered_command', return_value=False):
                result = await payment.confirm_go_pay(update, context)
                return result

    result = asyncio.new_event_loop().run_until_complete(_run())
    assert result == 'PAID'


def test_confirm_go_pay_fallback_to_user_profile_email():
    """confirm_go_pay falls back to user profile email when buyer_email not in reserve_user_data."""
    import asyncio
    from handlers.reserve import payment

    async def _run():
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123

        context = MagicMock()
        context.user_data = {
            'reserve_user_data': {},
            'postfix_for_cancel': 'RESERVE',
        }

        with patch('handlers.reserve.payment.db_postgres.get_email', new_callable=AsyncMock) as mock_get_email:
            mock_get_email.return_value = 'profile@example.com'
            with patch.object(payment, 'create_and_send_payment', new_callable=AsyncMock) as mock_pay:
                mock_pay.return_value = 'PAID'
                with patch('handlers.reserve.payment.check_entered_command', return_value=False):
                    result = await payment.confirm_go_pay(update, context)
                    # Verify get_email was called with the user's id
                    mock_get_email.assert_called_once()
                    return result

    result = asyncio.new_event_loop().run_until_complete(_run())
    assert result == 'PAID'


def test_create_email_keyboard_with_email():
    """create_email_keyboard includes email_confirm button when email is present."""
    import asyncio
    from conv_hl import reserve_common_hl

    async def _run():
        keyboard = await reserve_common_hl.create_email_keyboard(
            email='admin@example.com',
            postfix_for_cancel='RESERVE',
            postfix_for_back='TICKET',
        )
        return keyboard

    keyboard = asyncio.new_event_loop().run_until_complete(_run())
    # Should have 2 rows: email_confirm + back_and_cancel
    assert len(keyboard.inline_keyboard) == 2
    # First row should contain the email_confirm button
    first_row = keyboard.inline_keyboard[0]
    email_btn = first_row[0]
    assert email_btn.callback_data == 'email_confirm|admin@example.com'


def test_create_email_keyboard_without_email():
    """create_email_keyboard has only back_and_cancel when email is None."""
    import asyncio
    from conv_hl import reserve_common_hl

    async def _run():
        keyboard = await reserve_common_hl.create_email_keyboard(
            email=None,
            postfix_for_cancel='RESERVE',
            postfix_for_back='TICKET',
        )
        return keyboard

    keyboard = asyncio.new_event_loop().run_until_complete(_run())
    # Should have 1 row: back_and_cancel only
    assert len(keyboard.inline_keyboard) == 1


def test_email_normalization_strip_and_lower():
    """Email input is normalized with strip and lower in handle_email_input."""
    import asyncio
    from conv_hl import reserve_common_hl

    async def _run():
        with patch.object(reserve_common_hl, 'proceed_to_forma_step', new_callable=AsyncMock) as mock_forma:
            mock_forma.return_value = 'FORMA'

            update = MagicMock()
            update.effective_message.text = '  USER@EXAMPLE.COM  '
            update.effective_chat.send_message = AsyncMock(return_value=MagicMock(message_id=42))

            context = MagicMock()
            context.bot.edit_message_reply_markup = AsyncMock()
            context.user_data = {
                'reserve_user_data': {'message_id': 10},
                'postfix_for_cancel': 'RESERVE',
            }

            await reserve_common_hl.handle_email_input(update, context)
            return context.user_data['reserve_user_data'].get('buyer_email')

    email = asyncio.new_event_loop().run_until_complete(_run())
    assert email == 'user@example.com'

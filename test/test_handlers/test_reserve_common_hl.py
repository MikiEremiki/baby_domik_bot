"""Tests for src/handlers/reserve_common_hl.py functions."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.reserve_common_hl import (
    _extract_email_from_callback,
    handle_email_input,
    handle_email_confirm_callback,
    send_email_step,
    proceed_to_forma_step,
    create_email_keyboard,
)


# ─── _extract_email_from_callback ──────────────────────────────────────────────


class TestExtractEmailFromCallback:
    """Tests for the pure function _extract_email_from_callback."""

    def test_valid_email_with_prefix(self):
        """email_confirm|user@example.com returns the email."""
        result = _extract_email_from_callback('email_confirm|user@example.com')
        assert result == 'user@example.com'

    def test_valid_email_without_prefix(self):
        """Standalone valid email is returned directly."""
        result = _extract_email_from_callback('user@example.com')
        assert result == 'user@example.com'

    def test_invalid_email_with_prefix(self):
        """email_confirm|not-an-email returns None."""
        result = _extract_email_from_callback('email_confirm|not-an-email')
        assert result is None

    def test_empty_email_with_prefix(self):
        """email_confirm| returns None."""
        result = _extract_email_from_callback('email_confirm|')
        assert result is None

    def test_empty_string(self):
        """Empty string returns None."""
        result = _extract_email_from_callback('')
        assert result is None

    def test_random_string(self):
        """Random non-email string returns None."""
        result = _extract_email_from_callback('random_callback_data')
        assert result is None

    def test_email_with_subdomain(self):
        """Email with subdomain is valid."""
        result = _extract_email_from_callback('email_confirm|user@mail.example.co.uk')
        assert result == 'user@mail.example.co.uk'

    def test_email_with_plus_sign(self):
        """Email with plus addressing is valid."""
        result = _extract_email_from_callback('email_confirm|user+tag@example.org')
        assert result == 'user+tag@example.org'


# ─── handle_email_input ────────────────────────────────────────────────────────


class TestHandleEmailInput:

    def _make_update(self, text: str):
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = text
        update.effective_chat.id = 12345
        update.effective_chat.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        return update

    def _make_context(self):
        context = MagicMock()
        context.bot.edit_message_reply_markup = AsyncMock()
        context.user_data = {
            'postfix_for_cancel': 'CANCEL',
            'reserve_user_data': {
                'message_id': 100,
                'client_data': {},
            },
        }
        return context

    def test_none_effective_message_returns_email(self):
        """If effective_message is None, return 'EMAIL' without error."""
        update = MagicMock()
        update.effective_message = None
        context = self._make_context()
        result = asyncio.run(handle_email_input(update, context))
        assert result == 'EMAIL'

    def test_valid_email_proceeds_to_forma(self, monkeypatch):
        """Valid email saves buyer_email and proceeds to FORMA."""
        update = self._make_update('  Test@Example.COM  ')
        context = self._make_context()

        mock_proceed = AsyncMock(return_value='FORMA')
        monkeypatch.setattr(
            'handlers.reserve_common_hl.proceed_to_forma_step', mock_proceed
        )

        result = asyncio.run(handle_email_input(update, context))
        assert result == 'FORMA'
        assert context.user_data['reserve_user_data']['buyer_email'] == 'test@example.com'
        mock_proceed.assert_awaited_once()

    def test_invalid_email_reprompts(self):
        """Invalid email sends re-prompt and returns 'EMAIL'."""
        update = self._make_update('not-an-email')
        context = self._make_context()

        result = asyncio.run(handle_email_input(update, context))
        assert result == 'EMAIL'
        update.effective_chat.send_message.assert_awaited()
        sent_text = update.effective_chat.send_message.call_args[1]['text']
        assert 'Пожалуйста проверьте' in sent_text

    def test_edit_message_reply_markup_exception_is_suppressed(self):
        """Exception from edit_message_reply_markup is silently caught."""
        update = self._make_update('valid@email.com')
        context = self._make_context()
        context.bot.edit_message_reply_markup = AsyncMock(side_effect=Exception('network error'))

        with patch('handlers.reserve_common_hl.proceed_to_forma_step', AsyncMock(return_value='FORMA')):
            result = asyncio.run(handle_email_input(update, context))
            assert result == 'FORMA'


# ─── handle_email_confirm_callback ─────────────────────────────────────────────


class TestHandleEmailConfirmCallback:

    def _make_update(self, callback_data: str):
        query = MagicMock()
        query.data = callback_data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(return_value=MagicMock(message_id=999))
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 555
        update.effective_chat.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        return update

    def _make_context(self):
        context = MagicMock()
        context.user_data = {
            'postfix_for_cancel': 'CANCEL',
            'reserve_user_data': {
                'message_id': 100,
                'client_data': {},
            },
        }
        return context

    def test_none_callback_query_returns_email(self):
        """If callback_query is None, return 'EMAIL' without error."""
        update = MagicMock()
        update.callback_query = None
        context = self._make_context()
        result = asyncio.run(handle_email_confirm_callback(update, context))
        assert result == 'EMAIL'

    def test_valid_email_in_callback_proceeds_to_forma(self, monkeypatch):
        """Valid email extracted from callback proceeds to FORMA."""
        # intent_id|email_confirm|user@example.com
        update = self._make_update('abc123|email_confirm|user@example.com')
        context = self._make_context()

        mock_proceed = AsyncMock(return_value='FORMA')
        monkeypatch.setattr(
            'handlers.reserve_common_hl.proceed_to_forma_step', mock_proceed
        )

        result = asyncio.run(handle_email_confirm_callback(update, context))
        assert result == 'FORMA'
        assert context.user_data['reserve_user_data']['buyer_email'] == 'user@example.com'
        mock_proceed.assert_awaited_once()

    def test_invalid_callback_falls_to_manual_input(self):
        """Invalid email in callback falls through to manual input prompt."""
        update = self._make_update('abc123|email_confirm|not-an-email')
        context = self._make_context()

        result = asyncio.run(handle_email_confirm_callback(update, context))
        assert result == 'EMAIL'
        update.callback_query.edit_message_text.assert_awaited()

    def test_empty_callback_after_intent_removal(self):
        """Empty callback_data after intent removal falls to manual input."""
        update = self._make_update('abc123|')
        context = self._make_context()

        result = asyncio.run(handle_email_confirm_callback(update, context))
        assert result == 'EMAIL'

    def test_answer_exception_is_suppressed(self):
        """Exception from query.answer() is silently caught."""
        update = self._make_update('abc123|email_confirm|user@example.com')
        update.callback_query.answer = AsyncMock(side_effect=Exception('already answered'))
        context = self._make_context()

        with patch('handlers.reserve_common_hl.proceed_to_forma_step', AsyncMock(return_value='FORMA')):
            result = asyncio.run(handle_email_confirm_callback(update, context))
            assert result == 'FORMA'


# ─── send_email_step ───────────────────────────────────────────────────────────


class TestSendEmailStep:

    def _make_update(self):
        update = MagicMock()
        update.effective_user.id = 555
        update.effective_chat.send_message = AsyncMock(return_value=MagicMock(message_id=888))
        update.callback_query = None
        return update

    def _make_context(self, admin_email: str | None = 'admin@test.com'):
        context = MagicMock()
        context.session = AsyncMock()
        context.user_data = {
            'postfix_for_cancel': 'CANCEL',
            'reserve_user_data': {
                'client_data': {},
            },
        }
        # Mock db_postgres.get_email
        async def fake_get_email(session, user_id):
            return admin_email
        return context, fake_get_email

    def test_send_email_step_sends_message(self, monkeypatch):
        """send_email_step sends the email prompt message."""
        update = self._make_update()
        context, fake_get_email = self._make_context()

        monkeypatch.setattr('handlers.reserve_common_hl.db_postgres.get_email', fake_get_email)

        message, state = asyncio.run(send_email_step(update, context))
        assert state == 'EMAIL'
        assert message.message_id == 888
        update.effective_chat.send_message.assert_awaited_once()

    def test_send_email_step_no_admin_email(self, monkeypatch):
        """When no admin email, the prompt is sent without confirm button."""
        update = self._make_update()
        context, fake_get_email = self._make_context(admin_email=None)

        monkeypatch.setattr('handlers.reserve_common_hl.db_postgres.get_email', fake_get_email)

        message, state = asyncio.run(send_email_step(update, context))
        assert state == 'EMAIL'


# ─── proceed_to_forma_step ─────────────────────────────────────────────────────


class TestProceedToFormaStep:

    def _make_update(self):
        update = MagicMock()
        update.effective_user.id = 555
        update.effective_chat.send_message = AsyncMock(return_value=MagicMock(message_id=888))
        update.callback_query = None
        return update

    def _make_context(self, adult_name: str | None = 'Иван Иванов'):
        context = MagicMock()
        context.session = AsyncMock()
        context.user_data = {
            'postfix_for_cancel': 'CANCEL',
            'reserve_user_data': {
                'message_id': 100,
                'client_data': {},
            },
        }

        async def fake_get_adult_name(session, user_id):
            return adult_name

        return context, fake_get_adult_name

    def test_proceed_to_forma_sends_message(self, monkeypatch):
        """proceed_to_forma_step sends the adult name prompt."""
        update = self._make_update()
        context, fake_get_adult = self._make_context()
        reserve_user_data = context.user_data['reserve_user_data']

        monkeypatch.setattr('handlers.reserve_common_hl.db_postgres.get_adult_name', fake_get_adult)

        state = asyncio.run(proceed_to_forma_step(update, context, reserve_user_data))
        assert state == 'FORMA'
        update.effective_chat.send_message.assert_awaited_once()

    def test_proceed_to_forma_with_adult_name(self, monkeypatch):
        """When adult name exists, it is saved to client_data."""
        update = self._make_update()
        context, fake_get_adult = self._make_context(adult_name='Мария Петрова')
        reserve_user_data = context.user_data['reserve_user_data']

        monkeypatch.setattr('handlers.reserve_common_hl.db_postgres.get_adult_name', fake_get_adult)

        state = asyncio.run(proceed_to_forma_step(update, context, reserve_user_data))
        assert state == 'FORMA'
        assert reserve_user_data['client_data']['name_adult'] == 'Мария Петрова'

    def test_proceed_to_forma_no_adult_name(self, monkeypatch):
        """When no adult name, client_data.name_adult is not set."""
        update = self._make_update()
        context, fake_get_adult = self._make_context(adult_name=None)
        reserve_user_data = context.user_data['reserve_user_data']

        monkeypatch.setattr('handlers.reserve_common_hl.db_postgres.get_adult_name', fake_get_adult)

        state = asyncio.run(proceed_to_forma_step(update, context, reserve_user_data))
        assert state == 'FORMA'
        assert 'name_adult' not in reserve_user_data['client_data']


# ─── create_email_keyboard ─────────────────────────────────────────────────────


class TestCreateEmailKeyboard:

    def test_keyboard_with_email(self):
        """When email is provided, keyboard includes email_confirm button."""
        keyboard = asyncio.run(create_email_keyboard(
            email='user@example.com',
            postfix_for_cancel='CANCEL',
            postfix_for_back='TICKET',
        ))
        # inline_keyboard is the attribute name in python-telegram-bot
        assert len(keyboard.inline_keyboard) == 2

    def test_keyboard_without_email(self):
        """When email is None, keyboard only has back_and_cancel row."""
        keyboard = asyncio.run(create_email_keyboard(
            email=None,
            postfix_for_cancel='CANCEL',
            postfix_for_back='TICKET',
        ))
        # Only one row: [back_and_cancel]
        assert len(keyboard.inline_keyboard) == 1

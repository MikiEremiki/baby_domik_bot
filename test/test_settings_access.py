import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update, User, Chat, Message, CallbackQuery

from handlers import support_hl, main_hl
from permissions import is_privileged
from settings.settings import ADMIN_ID, CHAT_ID_KOCHETKOVA


def create_fake_update(user_id: int, callback_data: str = None, text: str = None) -> Update:
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = user_id
    user.full_name = f"User_{user_id}"
    user.username = f"user_{user_id}"

    chat = MagicMock(spec=Chat)
    chat.id = user_id
    chat.send_message = AsyncMock()

    message = MagicMock(spec=Message)
    message.id = 100
    message.message_thread_id = None
    message.reply_text = AsyncMock()
    message.from_user = user

    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message
    update.message = message if text else None

    if callback_data is not None:
        query = MagicMock(spec=CallbackQuery)
        query.data = callback_data
        query.from_user = user
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
    else:
        update.callback_query = None

    return update


def test_is_privileged_admin():
    for admin_id in ADMIN_ID:
        assert is_privileged(admin_id) is True


def test_is_privileged_kochetkova():
    # KOCHETKOVA is NOT privileged — she gets access via user_command_access, not settings.py
    assert is_privileged(CHAT_ID_KOCHETKOVA) is False


def test_is_privileged_regular():
    assert is_privileged(999999999) is False


def test_start_settings_admin_keyboard():
    async def _test():
        admin_id = ADMIN_ID[0]
        update = create_fake_update(admin_id)
        context = MagicMock()
        context.user_data = {}

        with patch('handlers.support_hl.init_conv_hl_dialog', new_callable=AsyncMock), \
             patch('handlers.support_hl.set_back_context', new_callable=AsyncMock):
            state = await support_hl.start_settings(update, context)

        assert state == 1
        assert update.effective_chat.send_message.called
        kwargs = update.effective_chat.send_message.call_args[1]
        keyboard = kwargs['reply_markup'].inline_keyboard

        callback_datas = [btn.callback_data for row in keyboard for btn in row]
        assert 'db' in callback_datas
        assert 'update_data' in callback_datas
        assert 'user_status_help' in callback_datas
        assert any('Отменить' in cb for cb in callback_datas)

    asyncio.run(_test())


def _start_settings_keys(user_id, granted):
    async def _run():
        update = create_fake_update(user_id)
        context = MagicMock()
        context.user_data = {}

        with patch('handlers.support_hl.init_conv_hl_dialog', new_callable=AsyncMock), \
             patch('handlers.support_hl.set_back_context', new_callable=AsyncMock), \
             patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = set(granted)
            state = await support_hl.start_settings(update, context)

        assert state == 1
        kwargs = update.effective_chat.send_message.call_args[1]
        keyboard = kwargs['reply_markup'].inline_keyboard
        return [btn.callback_data for row in keyboard for btn in row]

    return asyncio.run(_run())


def test_start_settings_kochetkova_with_schedule_grant():
    """KOCHETKOVA (not privileged) with settings:schedule_event sees only the db button."""
    callback_datas = _start_settings_keys(
        CHAT_ID_KOCHETKOVA, {'settings', 'settings:schedule_event'})
    assert 'db' in callback_datas
    assert 'update_data' not in callback_datas
    assert 'user_status_help' not in callback_datas
    assert any('Отменить' in cb for cb in callback_datas)


def test_start_settings_without_section_grants_hides_db():
    callback_datas = _start_settings_keys(CHAT_ID_KOCHETKOVA, {'settings'})
    assert 'db' not in callback_datas
    assert 'update_data' not in callback_datas
    assert any('Отменить' in cb for cb in callback_datas)


def test_start_settings_update_data_grant_only():
    callback_datas = _start_settings_keys(
        CHAT_ID_KOCHETKOVA, {'settings:update_data'})
    assert 'update_data' in callback_datas
    assert 'db' not in callback_datas
    assert 'user_status_help' not in callback_datas


def test_choice_db_settings_admin_keyboard():
    async def _test():
        admin_id = ADMIN_ID[0]
        update = create_fake_update(admin_id, callback_data='db')
        context = MagicMock()
        context.user_data = {}

        with patch('handlers.support_hl.set_back_context', new_callable=AsyncMock):
            state = await support_hl.choice_db_settings(update, context)

        assert state == 2
        assert update.callback_query.edit_message_text.called
        kwargs = update.callback_query.edit_message_text.call_args[1]
        keyboard = kwargs['reply_markup'].inline_keyboard

        callback_datas = [btn.callback_data for row in keyboard for btn in row]
        assert 'db|schedule_event' in callback_datas
        assert 'db|theater_event' in callback_datas
        assert 'db|base_ticket' in callback_datas
        assert 'db|event_type' in callback_datas
        assert 'db|promotion' in callback_datas
        assert 'db|place' in callback_datas
        assert 'db|auto_sending' in callback_datas
        assert 'access' in callback_datas

    asyncio.run(_test())


def test_choice_db_settings_kochetkova_keyboard():
    async def _test():
        update = create_fake_update(CHAT_ID_KOCHETKOVA, callback_data='db')
        context = MagicMock()
        context.user_data = {}

        with patch('handlers.support_hl.set_back_context', new_callable=AsyncMock), \
             patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'settings:schedule_event'}
            state = await support_hl.choice_db_settings(update, context)

        assert state == 2
        assert update.callback_query.edit_message_text.called
        kwargs = update.callback_query.edit_message_text.call_args[1]
        keyboard = kwargs['reply_markup'].inline_keyboard

        callback_datas = [btn.callback_data for row in keyboard for btn in row]
        assert 'db|schedule_event' in callback_datas
        assert 'db|theater_event' not in callback_datas
        assert 'db|base_ticket' not in callback_datas
        assert 'db|event_type' not in callback_datas
        assert 'db|promotion' not in callback_datas
        assert 'access' not in callback_datas

    asyncio.run(_test())


def test_choice_db_settings_database_grant_shows_access_only():
    async def _test():
        update = create_fake_update(CHAT_ID_KOCHETKOVA, callback_data='db')
        context = MagicMock()
        context.user_data = {}

        with patch('handlers.support_hl.set_back_context', new_callable=AsyncMock), \
             patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'settings:database'}
            await support_hl.choice_db_settings(update, context)

        kwargs = update.callback_query.edit_message_text.call_args[1]
        keyboard = kwargs['reply_markup'].inline_keyboard
        callback_datas = [btn.callback_data for row in keyboard for btn in row]
        assert 'access' in callback_datas
        assert not any(cb.startswith('db|') for cb in callback_datas)

    asyncio.run(_test())


def test_get_settings_access_control():
    async def _test():
        # Non-admin with only settings:schedule_event: other sections are denied
        kochetkova_update = create_fake_update(CHAT_ID_KOCHETKOVA, callback_data='db|theater_event')
        context = MagicMock()
        context.user_data = {'STATE': 2}

        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc, \
             patch('handlers.support_hl.theater_event_select', new_callable=AsyncMock) as mock_te:
            acc.return_value = {'settings:schedule_event'}
            state = await support_hl.get_settings(kochetkova_update, context)
            assert state == 2
            assert not mock_te.called

            # ... but schedule_event is allowed
            schedule_update = create_fake_update(CHAT_ID_KOCHETKOVA, callback_data='db|schedule_event')
            with patch('handlers.support_hl.schedule_event_select', new_callable=AsyncMock) as mock_sch:
                mock_sch.return_value = 3
                state = await support_hl.get_settings(schedule_update, context)
                assert mock_sch.called
                assert state == 3

            # Without any grant even schedule_event is denied
            acc.return_value = set()
            with patch('handlers.support_hl.schedule_event_select', new_callable=AsyncMock) as mock_sch:
                state = await support_hl.get_settings(schedule_update, context)
                assert not mock_sch.called
                assert state == 2

    asyncio.run(_test())


def test_get_updates_option_access_control():
    async def _test():
        kochetkova_update = create_fake_update(CHAT_ID_KOCHETKOVA, callback_data='update_data')
        context = MagicMock()
        context.user_data = {'STATE': 1}

        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'settings:schedule_event'}
            state = await support_hl.get_updates_option(kochetkova_update, context)
        assert state == 1
        assert not kochetkova_update.callback_query.edit_message_text.called

        # With settings:update_data the menu opens
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc, \
             patch('handlers.support_hl.set_back_context', new_callable=AsyncMock):
            acc.return_value = {'settings:update_data'}
            state = await support_hl.get_updates_option(kochetkova_update, context)
        assert state == 'updates'
        assert kochetkova_update.callback_query.edit_message_text.called

    asyncio.run(_test())


def test_help_cmd_output_for_kochetkova_and_regular():
    async def _test():
        # Admin — sees all commands
        admin_update = create_fake_update(ADMIN_ID[0])
        admin_context = MagicMock()
        admin_context.user_data = {}
        admin_context.session = AsyncMock()
        # Mock get_available_commands to return all commands for privileged users
        with patch('handlers.main_hl.get_available_commands', new_callable=AsyncMock) as mock_avail:
            from settings.settings import COMMAND_DICT
            mock_avail.return_value = list(COMMAND_DICT.items())
            await main_hl.help_cmd(admin_update, admin_context)
            admin_text = admin_update.effective_chat.send_message.call_args[0][0]
            assert '/settings' in admin_text

        # Regular user — sees only public commands
        regular_update = create_fake_update(999999999)
        regular_context = MagicMock()
        regular_context.user_data = {}
        regular_context.session = AsyncMock()
        with patch('handlers.main_hl.get_available_commands', new_callable=AsyncMock) as mock_avail:
            # Only public commands
            public_items = [(k, v) for k, v in COMMAND_DICT.items() if v.public]
            mock_avail.return_value = public_items
            await main_hl.help_cmd(regular_update, regular_context)
            regular_text = regular_update.effective_chat.send_message.call_args[0][0]
            assert '/settings' not in regular_text
            assert '/start' in regular_text

    asyncio.run(_test())

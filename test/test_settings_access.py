import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update, User, Chat, Message, CallbackQuery

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from custom_filters.admin import filter_settings, filter_admin
from conv_hl.support_conv_hl import support_conv_hl
from handlers import support_hl, main_hl
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


def test_filter_settings_membership():
    for admin_id in ADMIN_ID:
        assert admin_id in filter_settings.user_ids
    assert CHAT_ID_KOCHETKOVA in filter_settings.user_ids

    regular_user_id = 999999999
    assert regular_user_id not in filter_settings.user_ids


def test_filter_settings_check_update():
    admin_update = create_fake_update(ADMIN_ID[0])
    assert filter_settings.check_update(admin_update) is True

    kochetkova_update = create_fake_update(CHAT_ID_KOCHETKOVA)
    assert filter_settings.check_update(kochetkova_update) is True

    regular_update = create_fake_update(999999999)
    assert filter_settings.check_update(regular_update) is False


def test_support_conv_hl_entry_point():
    entry_point = support_conv_hl.entry_points[0]
    assert entry_point.filters == filter_settings


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


def test_start_settings_kochetkova_keyboard():
    async def _test():
        update = create_fake_update(CHAT_ID_KOCHETKOVA)
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
        assert 'update_data' not in callback_datas
        assert 'user_status_help' not in callback_datas
        assert any('Отменить' in cb for cb in callback_datas)

    asyncio.run(_test())


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

    asyncio.run(_test())


def test_choice_db_settings_kochetkova_keyboard():
    async def _test():
        update = create_fake_update(CHAT_ID_KOCHETKOVA, callback_data='db')
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
        assert 'db|theater_event' not in callback_datas
        assert 'db|base_ticket' not in callback_datas
        assert 'db|event_type' not in callback_datas
        assert 'db|promotion' not in callback_datas

    asyncio.run(_test())


def test_get_settings_access_control():
    async def _test():
        # Non-admin trying to access restricted sections
        kochetkova_update = create_fake_update(CHAT_ID_KOCHETKOVA, callback_data='db|theater_event')
        context = MagicMock()
        context.user_data = {'STATE': 2}

        state = await support_hl.get_settings(kochetkova_update, context)
        assert state == 2

        # Non-admin accessing schedule_event
        schedule_update = create_fake_update(CHAT_ID_KOCHETKOVA, callback_data='db|schedule_event')
        with patch('handlers.support_hl.schedule_event_select', new_callable=AsyncMock) as mock_sch:
            mock_sch.return_value = 3
            state = await support_hl.get_settings(schedule_update, context)
            assert mock_sch.called
            assert state == 3

    asyncio.run(_test())


def test_get_updates_option_access_control():
    async def _test():
        kochetkova_update = create_fake_update(CHAT_ID_KOCHETKOVA, callback_data='update_data')
        context = MagicMock()
        context.user_data = {'STATE': 1}

        state = await support_hl.get_updates_option(kochetkova_update, context)
        assert state == 1
        assert not kochetkova_update.callback_query.edit_message_text.called

    asyncio.run(_test())


def test_help_cmd_output_for_kochetkova_and_regular():
    async def _test():
        # Admin
        admin_update = create_fake_update(ADMIN_ID[0])
        admin_context = MagicMock()
        admin_context.user_data = {}
        await main_hl.help_cmd(admin_update, admin_context)
        admin_text = admin_update.effective_chat.send_message.call_args[0][0]
        assert '/settings' in admin_text

        # Kochetkova
        kochetkova_update = create_fake_update(CHAT_ID_KOCHETKOVA)
        kochetkova_context = MagicMock()
        kochetkova_context.user_data = {}
        await main_hl.help_cmd(kochetkova_update, kochetkova_context)
        kochetkova_text = kochetkova_update.effective_chat.send_message.call_args[0][0]
        assert '/settings' in kochetkova_text
        assert '/list' in kochetkova_text
        assert '/send_msg' in kochetkova_text

        # Regular user
        regular_update = create_fake_update(999999999)
        regular_context = MagicMock()
        regular_context.user_data = {}
        await main_hl.help_cmd(regular_update, regular_context)
        regular_text = regular_update.effective_chat.send_message.call_args[0][0]
        assert '/settings' not in regular_text

    asyncio.run(_test())

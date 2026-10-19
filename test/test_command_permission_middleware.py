import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update, User, Chat, CallbackQuery, Message
from telegram.ext import ApplicationHandlerStop

from middleware import command_permission as cp
from permissions import can
from settings.settings import (
    ADMIN_ID, SETTINGS_SECTIONS, SETTINGS_PREFIX, SETTINGS_DATABASE_KEY,
    ACCESS_INTENT_ID,
)

REGULAR = 999999999


def _section_names():
    return [key[len(SETTINGS_PREFIX):] for key in SETTINGS_SECTIONS
            if key != SETTINGS_DATABASE_KEY]


@pytest.mark.parametrize('name', _section_names())
def test_callback_to_command_returns_settings_key(name):
    key = f'{SETTINGS_PREFIX}{name}'
    assert cp._callback_to_command(f'db|{name}') == key
    assert cp._callback_to_command(name) == key


def test_callback_to_command_access_screen_maps_to_database():
    assert cp._callback_to_command('access') == SETTINGS_DATABASE_KEY
    assert cp._callback_to_command(f'{ACCESS_INTENT_ID}|grp|1') == SETTINGS_DATABASE_KEY
    assert cp._callback_to_command(f'{ACCESS_INTENT_ID}|tg|tech|3') == SETTINGS_DATABASE_KEY


def test_callback_to_command_ignores_foreign_intent_and_menu():
    assert cp._callback_to_command('db') is None
    assert cp._callback_to_command('other|place') is None
    assert cp._callback_to_command('') is None


def test_callback_to_command_foreign_intent_access_returns_none():
    """Foreign intent + 'access' must NOT map to settings:database.

    Only bare 'access' (no intent_id) or the ACCESS_INTENT_ID prefix should map.
    """
    assert cp._callback_to_command('other|access') is None
    assert cp._callback_to_command('random|access') is None


def test_every_settings_key_known_to_can():
    """Every key in SETTINGS_SECTIONS is understood by can(): denied without grant, allowed with."""
    async def _test():
        for key in SETTINGS_SECTIONS:
            with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
                acc.return_value = set()
                assert await can(REGULAR, key, AsyncMock()) is False
                acc.return_value = {key}
                assert await can(REGULAR, key, AsyncMock()) is True
            assert await can(ADMIN_ID[0], key, AsyncMock()) is True

    asyncio.run(_test())


def _get_middleware():
    application = MagicMock()
    config = MagicMock()
    config.bot.username = 'test_bot'
    cp.add_command_permission_middleware(application, config)
    handler = application.add_handler.call_args[0][0]
    return handler.callback


def _callback_update(user_id, data, msg_text='Выберите раздел'):
    """Create a callback update that mimics a real Telegram callback.

    On real updates effective_message is the bot message with the button,
    not None — it always has text.
    """
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = user_id
    user.is_bot = False
    update.effective_user = user
    update.effective_chat = MagicMock(spec=Chat)
    msg = MagicMock(spec=Message)
    msg.text = msg_text
    msg.message_thread_id = None
    msg.reply_text = AsyncMock()
    update.effective_message = msg
    query = MagicMock(spec=CallbackQuery)
    query.data = data
    query.answer = AsyncMock()
    update.callback_query = query
    return update


def _run_middleware(user_id, data, granted):
    middleware = _get_middleware()
    update = _callback_update(user_id, data)
    context = MagicMock()
    context.session = AsyncMock()

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = set(granted)
            await middleware(update, context)

    return update, _call


def test_middleware_blocks_section_callback_without_grant():
    update, call = _run_middleware(REGULAR, 'db|place', set())
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(call())
    assert update.callback_query.answer.called


def test_middleware_allows_section_callback_with_grant():
    _, call = _run_middleware(REGULAR, 'db|place', {'settings:place'})
    asyncio.run(call())


def test_middleware_blocks_access_screen_without_database_grant():
    _, call = _run_middleware(REGULAR, f'{ACCESS_INTENT_ID}|grp|1', {'settings:place'})
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(call())


def test_middleware_allows_access_screen_with_database_grant():
    _, call = _run_middleware(REGULAR, f'{ACCESS_INTENT_ID}|grp|1', {SETTINGS_DATABASE_KEY})
    asyncio.run(call())


def test_middleware_privileged_always_passes():
    _, call = _run_middleware(ADMIN_ID[0], f'{ACCESS_INTENT_ID}|grp|1', set())
    asyncio.run(call())


def test_middleware_blocks_super_admin_root_only():
    """super_admin is blocked from root_only (tech) commands by the middleware.

    Uses a fixture COMMAND_DICT entry so the test is independent of the real
    settings.py. The fake user is patched into SUPERADMIN_CHAT_ID (making
    is_privileged return True) but is NOT in ADMIN_ID, so can() blocks root_only.
    """
    from settings.settings import CommandEntry

    fake_super_admin = 999999999
    # Use a real CommandEntry so get_command_entry matches entry[0] == cmd
    fixture_entry = CommandEntry('techcmd', 'Tech Command', public=False, root_only=True)

    middleware = _get_middleware()
    update = _command_update(fake_super_admin, '/techcmd')
    context = MagicMock()
    context.session = AsyncMock()

    async def _call():
        with patch('permissions.COMMAND_DICT', {'TECHCMD': fixture_entry}), \
             patch('permissions.SUPERADMIN_CHAT_ID', [fake_super_admin]), \
             patch('permissions.ADMIN_ID', []), \
             patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = set()
            await middleware(update, context)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(_call())
    assert update.effective_message.reply_text.called


def test_middleware_allows_root_root_only():
    """root (ADMIN_ID) is allowed root_only (tech) commands."""
    _, call = _run_command_middleware(ADMIN_ID[0], '/clean_bd', set())
    asyncio.run(call())


# ─── Command message branch ───────────────────────────────────────────────────

def _command_update(user_id, text, bot_username='test_bot'):
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = user_id
    user.is_bot = False
    update.effective_user = user
    update.effective_chat = MagicMock(spec=Chat)
    msg = MagicMock()
    msg.text = text
    msg.message_thread_id = None
    msg.reply_text = AsyncMock()
    update.effective_message = msg
    update.callback_query = None
    return update


def _run_command_middleware(user_id, text, granted):
    middleware = _get_middleware()
    update = _command_update(user_id, text)
    context = MagicMock()
    context.session = AsyncMock()

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = set(granted)
            await middleware(update, context)

    return update, _call


def test_middleware_blocks_command_without_grant():
    update, call = _run_command_middleware(REGULAR, '/list', set())
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(call())
    assert update.effective_message.reply_text.called


def test_middleware_allows_command_with_grant():
    _, call = _run_command_middleware(REGULAR, '/list', {'list'})
    asyncio.run(call())


def test_middleware_blocks_unknown_command_fail_closed():
    """Unknown commands are blocked (fail-closed) for non-root users."""
    from telegram.ext import ApplicationHandlerStop
    _, call = _run_command_middleware(REGULAR, '/unknown_xyz', set())
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(call())


def test_middleware_allows_unknown_command_for_root():
    """Unknown commands are allowed for root (ADMIN_ID)."""
    _, call = _run_command_middleware(ADMIN_ID[0], '/unknown_xyz', set())
    asyncio.run(call())


def test_middleware_allows_command_for_other_bot():
    _, call = _run_command_middleware(REGULAR, '/list@other_bot', set())
    asyncio.run(call())


def test_middleware_allows_non_command_text():
    _, call = _run_command_middleware(REGULAR, 'hello world', set())
    asyncio.run(call())


# ─── UP_* callback ────────────────────────────────────────────────────────────

def test_middleware_blocks_up_callback_without_grant():
    """UP_* callbacks (e.g. update_places) are blocked without a grant."""
    # COMMAND_DICT['UP_PLACE_DATA'][0] == 'update_places'
    update, call = _run_middleware(REGULAR, 'update_places', set())
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(call())
    assert update.callback_query.answer.called


def test_middleware_allows_up_callback_with_grant():
    """UP_* callback passes when the user has the command grant."""
    _, call = _run_middleware(REGULAR, 'update_places', {'update_places'})
    asyncio.run(call())


# ─── Regression: callback with /-text goes through callback branch ────────────

def test_callback_with_slash_text_uses_callback_branch():
    """Regression test: callback whose message text starts with / must NOT
    go through the command branch — reply_text must not be called."""
    update, call = _run_middleware(REGULAR, 'db|place', '/list')
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(call())
    # The callback branch uses answer(), not reply_text()
    assert update.callback_query.answer.called
    assert not update.effective_message.reply_text.called


# ─── Edge cases: None data and None effective_message ──────────────────────────

def test_callback_data_none_passes():
    """Callback with data=None is not blocked — _callback_to_command('') returns None."""
    middleware = _get_middleware()
    update = _callback_update(REGULAR, 'db|place')
    update.callback_query.data = None
    context = MagicMock()
    context.session = AsyncMock()

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = set()
            await middleware(update, context)

    asyncio.run(_call())


def test_callback_effective_message_none_passes():
    """Callback without effective_message (None) still goes through callback branch."""
    middleware = _get_middleware()
    update = _callback_update(REGULAR, 'db|place')
    update.effective_message = None
    context = MagicMock()
    context.session = AsyncMock()

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = set()
            await middleware(update, context)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(_call())
    assert update.callback_query.answer.called


# ─── Ticket 02: completeness tests ─────────────────────────────────────────────

def test_no_legacy_filters_in_src():
    """No filter_admin, filter_list_cmd, filter_to_send_msg, filter_settings imports in src."""
    import os
    import re
    src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
    forbidden = ['filter_admin', 'filter_list_cmd', 'filter_to_send_msg', 'filter_settings']
    found = []
    for root, _, files in os.walk(src_dir):
        for fname in files:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(root, fname)
            # Skip the admin.py file itself — it's the definition, now empty
            if fname == 'admin.py' and 'custom_filters' in fpath:
                continue
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
            for name in forbidden:
                if name in content:
                    found.append(f'{fpath}: {name}')
    assert not found, f'Legacy filters still referenced in src: {found}'


def test_all_command_handlers_in_command_dict():
    """Every CommandHandler command (including conv_hl entry points) is in COMMAND_DICT."""
    from telegram.ext import CommandHandler
    from settings.settings import COMMAND_DICT

    cmd_names_in_dict = {entry[0] for entry in COMMAND_DICT.values()}

    # Collect commands from setup_bot_handlers
    from setup_bot_handlers import _add_admin_commands, _add_public_commands

    app = MagicMock()
    _add_admin_commands(app)
    _add_public_commands(app)

    cmd_names_in_handlers = set()
    for call in app.add_handlers.call_args_list:
        handlers = call[0][0] if isinstance(call[0][0], (list, tuple)) else [call[0][0]]
        for h in handlers:
            if isinstance(h, CommandHandler):
                for cmd in h.commands:
                    cmd_names_in_handlers.add(cmd)

    # Collect commands from conv_hl entry points
    from conv_hl import (
        reserve_conv_hl, reserve_admin_conv_hl, list_wait_conv_hl,
        afisha_conv_hl, support_conv_hl, migration_admin_conv_hl,
        sales_conv_hl, birthday_conv_hl, profile_conv_hl,
    )
    conv_handlers = [
        reserve_conv_hl, reserve_admin_conv_hl, list_wait_conv_hl,
        afisha_conv_hl, support_conv_hl, migration_admin_conv_hl,
        sales_conv_hl, birthday_conv_hl, profile_conv_hl,
    ]
    for conv in conv_handlers:
        for entry in conv.entry_points:
            if isinstance(entry, CommandHandler):
                for cmd in entry.commands:
                    cmd_names_in_handlers.add(cmd)

    missing = cmd_names_in_handlers - cmd_names_in_dict
    assert not missing, f'Commands in handlers but missing from COMMAND_DICT: {missing}'


def test_no_filters_user_in_command_handlers():
    """No CommandHandler has filters.User (legacy ID filter) attached."""
    from telegram.ext import CommandHandler, filters
    from setup_bot_handlers import _add_admin_commands, _add_public_commands

    app = MagicMock()
    _add_admin_commands(app)
    _add_public_commands(app)

    for call in app.add_handlers.call_args_list:
        handlers = call[0][0] if isinstance(call[0][0], (list, tuple)) else [call[0][0]]
        for h in handlers:
            if isinstance(h, CommandHandler) and h.filters is not None:
                # Check if it's a filters.User instance
                if isinstance(h.filters, filters.User):
                    pytest.fail(f'CommandHandler for {h.commands} still has filters.User')


# ─── Ticket 03: DB error vs no-access ──────────────────────────────────────────

def test_callback_db_error_shows_temporary_error():
    """Callback with DB error shows 'temporary error' message, not 'no access'."""
    from permissions import PermissionBackendError
    middleware = _get_middleware()
    update = _callback_update(REGULAR, 'db|place')
    context = MagicMock()
    context.session = AsyncMock()

    async def _call():
        with patch('middleware.command_permission.can', new_callable=AsyncMock) as mock_can:
            mock_can.side_effect = PermissionBackendError('DB down')
            try:
                await middleware(update, context)
                assert False, 'Expected ApplicationHandlerStop'
            except ApplicationHandlerStop:
                pass
            assert update.callback_query.answer.called
            call_args = update.callback_query.answer.call_args
            assert 'Временная ошибка' in call_args[0][0]

    asyncio.run(_call())


def test_command_db_error_shows_temporary_error():
    """Command message with DB error shows 'temporary error', not 'no access'."""
    from permissions import PermissionBackendError
    middleware = _get_middleware()
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = REGULAR
    user.is_bot = False
    update.effective_user = user
    update.effective_chat = MagicMock(spec=Chat)
    msg = MagicMock(spec=Message)
    msg.text = '/list'
    msg.message_thread_id = None
    msg.reply_text = AsyncMock()
    update.effective_message = msg
    update.callback_query = None
    context = MagicMock()
    context.session = AsyncMock()
    context.bot.username = 'test_bot'

    async def _call():
        with patch('middleware.command_permission.can', new_callable=AsyncMock) as mock_can:
            mock_can.side_effect = PermissionBackendError('DB down')
            try:
                await middleware(update, context)
                assert False, 'Expected ApplicationHandlerStop'
            except ApplicationHandlerStop:
                pass
            assert msg.reply_text.called
            call_args = msg.reply_text.call_args
            assert 'Временная ошибка' in call_args[0][0]

    asyncio.run(_call())


def test_callback_no_access_shows_denied():
    """Callback without permission shows 'no access' message, not 'temporary error'."""
    middleware = _get_middleware()
    update = _callback_update(REGULAR, 'db|place')
    context = MagicMock()
    context.session = AsyncMock()

    async def _call():
        with patch('middleware.command_permission.can', new_callable=AsyncMock) as mock_can:
            mock_can.return_value = False
            try:
                await middleware(update, context)
                assert False, 'Expected ApplicationHandlerStop'
            except ApplicationHandlerStop:
                pass
            assert update.callback_query.answer.called
            call_args = update.callback_query.answer.call_args
            assert 'нет доступа' in call_args[0][0].lower()

    asyncio.run(_call())


def test_command_no_access_shows_denied():
    """Command message without permission shows 'no access', not 'temporary error'."""
    middleware = _get_middleware()
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = REGULAR
    user.is_bot = False
    update.effective_user = user
    update.effective_chat = MagicMock(spec=Chat)
    msg = MagicMock(spec=Message)
    msg.text = '/list'
    msg.message_thread_id = None
    msg.reply_text = AsyncMock()
    update.effective_message = msg
    update.callback_query = None
    context = MagicMock()
    context.session = AsyncMock()
    context.bot.username = 'test_bot'

    async def _call():
        with patch('middleware.command_permission.can', new_callable=AsyncMock) as mock_can:
            mock_can.return_value = False
            try:
                await middleware(update, context)
                assert False, 'Expected ApplicationHandlerStop'
            except ApplicationHandlerStop:
                pass
            assert msg.reply_text.called
            call_args = msg.reply_text.call_args
            assert 'нет доступа' in call_args[0][0].lower()

    asyncio.run(_call())


def test_can_raises_permission_backend_error():
    """can() raises PermissionBackendError when get_user_access fails."""
    from permissions import can, PermissionBackendError

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.side_effect = PermissionBackendError('DB down')
            with pytest.raises(PermissionBackendError):
                await can(REGULAR, 'list', AsyncMock())

    asyncio.run(_call())


def test_get_available_commands_db_error_fallback():
    """get_available_commands falls back to public commands on DB error."""
    from permissions import get_available_commands, PermissionBackendError

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.side_effect = PermissionBackendError('DB down')
            result = await get_available_commands(REGULAR, AsyncMock())
            # Should contain only public commands
            for key, entry in result:
                assert entry.public is True

    asyncio.run(_call())


def test_get_user_menu_commands_db_error_fallback():
    """get_user_menu_commands falls back to public in_menu commands on DB error."""
    from permissions import get_user_menu_commands, PermissionBackendError

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.side_effect = PermissionBackendError('DB down')
            result = await get_user_menu_commands(REGULAR, AsyncMock())
            # All returned commands should be public
            from settings.settings import COMMAND_DICT
            for cmd in result:
                entry = get_command_entry_from_dict(cmd.command)
                if entry is not None:
                    assert entry.public is True

    asyncio.run(_call())


def get_command_entry_from_dict(cmd_name):
    """Helper to look up COMMAND_DICT entry by command name."""
    from settings.settings import COMMAND_DICT
    for entry in COMMAND_DICT.values():
        if entry[0] == cmd_name:
            return entry
    return None


# ─── Ticket 03 code-review fixes ──────────────────────────────────────────────

def test_can_or_false_returns_false_on_db_error():
    """can_or_false catches PermissionBackendError and returns False."""
    from permissions import can_or_false, PermissionBackendError

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.side_effect = PermissionBackendError('DB down')
            result = await can_or_false(REGULAR, 'list', AsyncMock())
            assert result is False

    asyncio.run(_call())


def test_can_or_false_returns_true_on_grant():
    """can_or_false returns True when the user has a grant."""
    from permissions import can_or_false

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'list'}
            result = await can_or_false(REGULAR, 'list', AsyncMock())
            assert result is True

    asyncio.run(_call())


def test_get_user_access_or_empty_returns_empty_on_db_error():
    """get_user_access_or_empty catches PermissionBackendError and returns set()."""
    from permissions import get_user_access_or_empty, PermissionBackendError

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.side_effect = PermissionBackendError('DB down')
            result = await get_user_access_or_empty(REGULAR, AsyncMock())
            assert result == set()

    asyncio.run(_call())


def test_get_user_access_or_empty_returns_grants_on_success():
    """get_user_access_or_empty returns grants when DB is available."""
    from permissions import get_user_access_or_empty

    async def _call():
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'list', 'settings:place'}
            result = await get_user_access_or_empty(REGULAR, AsyncMock())
            assert result == {'list', 'settings:place'}

    asyncio.run(_call())


def test_get_user_access_raises_on_sqlalchemy_error():
    """get_user_access raises PermissionBackendError on SQLAlchemyError."""
    from permissions import get_user_access, PermissionBackendError
    from sqlalchemy.exc import SQLAlchemyError

    async def _call():
        session = AsyncMock()
        session.execute.side_effect = SQLAlchemyError('connection refused')
        with pytest.raises(PermissionBackendError):
            await get_user_access(REGULAR, session)

    asyncio.run(_call())


def test_get_user_access_raises_on_os_error():
    """get_user_access raises PermissionBackendError on OSError."""
    from permissions import get_user_access, PermissionBackendError

    async def _call():
        session = AsyncMock()
        session.execute.side_effect = OSError('disk full')
        with pytest.raises(PermissionBackendError):
            await get_user_access(REGULAR, session)

    asyncio.run(_call())


def test_can_debug_logging_root():
    """can() logs debug message for root user decision."""
    from permissions import can, permissions_logger
    from settings.settings import ADMIN_ID
    root_id = ADMIN_ID[0] if ADMIN_ID else 1

    async def _call():
        with patch.object(permissions_logger, 'isEnabledFor', return_value=True):
            with patch.object(permissions_logger, 'debug') as mock_debug:
                await can(root_id, 'list', None)
                calls = [str(c) for c in mock_debug.call_args_list]
                assert any('root' in c for c in calls)

    asyncio.run(_call())


def test_can_debug_logging_public():
    """can() logs debug message for public command decision."""
    from permissions import can, permissions_logger

    async def _call():
        with patch.object(permissions_logger, 'isEnabledFor', return_value=True):
            with patch.object(permissions_logger, 'debug') as mock_debug:
                await can(REGULAR, 'start', None)
                calls = [str(c) for c in mock_debug.call_args_list]
                assert any('public' in c for c in calls)

    asyncio.run(_call())

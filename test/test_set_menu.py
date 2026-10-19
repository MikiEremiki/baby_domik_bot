"""Unit tests for set_menu() – verify in_menu-based menu construction.

Tests check that:
- Only commands with in_menu=True are sent to each scope.
- root_only commands are excluded from non-root scopes.
- Admin group members get admin_group commands merged with their grants.
- Per-user menus are set for users with grants.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from settings.settings import CommandEntry


def test_set_menu_only_in_menu_commands():
    """set_menu should only send commands with in_menu=True to scopes."""
    fixture_dict = {
        'PUBLIC_CMD': CommandEntry('public_cmd', 'Public Command', in_menu=True),
        'NOT_IN_MENU': CommandEntry('not_in_menu', 'Not in menu', in_menu=False),
        'ADMIN_CMD': CommandEntry('admin_cmd', 'Admin Command', public=False, in_menu=True),
        'ROOT_CMD': CommandEntry('root_cmd', 'Root Command', public=False, root_only=True, in_menu=True, group='tech'),
    }

    bot = AsyncMock()

    async def _run():
        with patch('utilities.utl_func.COMMAND_DICT', fixture_dict), \
             patch('utilities.utl_func.ADMIN_GROUP_ID', []), \
             patch('utilities.utl_func.ADMIN_CHAT_ID', []), \
             patch('utilities.utl_func.SUPERADMIN_CHAT_ID', []):
            from utilities.utl_func import set_menu
            await set_menu(bot)

    asyncio.run(_run())

    calls = bot.set_my_commands.call_args_list
    default_calls = [c for c in calls if isinstance(c.kwargs['scope'], BotCommandScopeDefault)]
    assert len(default_calls) == 1

    default_cmds = default_calls[0].kwargs['commands']
    cmd_names = {cmd.command for cmd in default_cmds}
    assert 'public_cmd' in cmd_names
    assert 'not_in_menu' not in cmd_names
    assert 'admin_cmd' not in cmd_names
    assert 'root_cmd' not in cmd_names


def test_set_menu_root_only_excluded_from_non_root():
    """root_only commands should only appear in superadmin scope."""
    fixture_dict = {
        'PUBLIC_CMD': CommandEntry('public_cmd', 'Public Command', in_menu=True),
        'ROOT_CMD': CommandEntry('root_cmd', 'Root Command', public=False, root_only=True, in_menu=True, group='tech'),
    }

    fake_superadmin_id = 123456
    bot = AsyncMock()

    async def _run():
        with patch('utilities.utl_func.COMMAND_DICT', fixture_dict), \
             patch('utilities.utl_func.ADMIN_GROUP_ID', []), \
             patch('utilities.utl_func.ADMIN_CHAT_ID', []), \
             patch('utilities.utl_func.SUPERADMIN_CHAT_ID', [fake_superadmin_id]):
            from utilities.utl_func import set_menu
            await set_menu(bot)

    asyncio.run(_run())

    calls = bot.set_my_commands.call_args_list

    superadmin_calls = [
        c for c in calls
        if isinstance(c.kwargs['scope'], BotCommandScopeChat)
        and c.kwargs['scope'].chat_id == fake_superadmin_id
    ]
    assert len(superadmin_calls) == 1

    superadmin_cmds = superadmin_calls[0].kwargs['commands']
    cmd_names = {cmd.command for cmd in superadmin_cmds}
    assert 'root_cmd' in cmd_names
    assert 'public_cmd' in cmd_names

    default_calls = [c for c in calls if isinstance(c.kwargs['scope'], BotCommandScopeDefault)]
    default_cmds = default_calls[0].kwargs['commands']
    default_cmd_names = {cmd.command for cmd in default_cmds}
    assert 'root_cmd' not in default_cmd_names


def test_set_menu_per_user_grants():
    """Users with grants should get per-user menus via BotCommandScopeChat."""
    fixture_dict = {
        'PUBLIC_CMD': CommandEntry('public_cmd', 'Public Command', in_menu=True),
        'GRANTED_CMD': CommandEntry('granted_cmd', 'Granted Command', public=False, in_menu=True),
    }

    fake_user_id = 987654
    bot = AsyncMock()
    mock_session = AsyncMock()

    async def mock_list_users_with_access(session):
        return [(fake_user_id, 1)]

    async def mock_get_user_menu_commands(user_id, session):
        return [
            BotCommand('public_cmd', 'Public Command'),
            BotCommand('granted_cmd', 'Granted Command'),
        ]

    async def _run():
        with patch('utilities.utl_func.COMMAND_DICT', fixture_dict), \
             patch('utilities.utl_func.ADMIN_GROUP_ID', []), \
             patch('utilities.utl_func.ADMIN_CHAT_ID', []), \
             patch('utilities.utl_func.SUPERADMIN_CHAT_ID', []), \
             patch('utilities.utl_func.list_users_with_access', new=mock_list_users_with_access), \
             patch('utilities.utl_func.get_user_menu_commands', new=mock_get_user_menu_commands):
            from utilities.utl_func import set_menu
            await set_menu(bot, mock_session)

    asyncio.run(_run())

    user_calls = [
        c for c in bot.set_my_commands.call_args_list
        if isinstance(c.kwargs['scope'], BotCommandScopeChat)
        and c.kwargs['scope'].chat_id == fake_user_id
    ]
    assert len(user_calls) == 1

    user_cmds = user_calls[0].kwargs['commands']
    cmd_names = {cmd.command for cmd in user_cmds}
    assert 'public_cmd' in cmd_names
    assert 'granted_cmd' in cmd_names


def test_set_menu_admin_group_merges_grants():
    """Admin group members should get admin_group commands + their grants.

    Admin group membership is determined by bot.get_chat_administrators(),
    not by comparing user_id with ADMIN_GROUP_ID (which contains chat IDs).
    """
    from telegram import ChatMemberAdministrator

    fixture_dict = {
        'PUBLIC_CMD': CommandEntry('public_cmd', 'Public Command', in_menu=True),
        'ADMIN_CMD': CommandEntry('admin_cmd', 'Admin Command', public=False, in_menu=True),
        'GRANTED_CMD': CommandEntry('granted_cmd', 'Granted Command', public=False, in_menu=True),
    }

    fake_group_chat_id = -1001234567890
    fake_admin_group_user = 111222
    bot = AsyncMock()
    mock_session = AsyncMock()

    # Mock get_chat_administrators to return the user as an admin of the group
    mock_user = MagicMock()
    mock_user.id = fake_admin_group_user
    mock_user.is_bot = False
    mock_admin_member = MagicMock(spec=ChatMemberAdministrator)
    mock_admin_member.user = mock_user
    bot.get_chat_administrators.return_value = [mock_admin_member]

    async def mock_list_users_with_access(session):
        return [(fake_admin_group_user, 1)]

    async def mock_get_user_menu_commands(user_id, session):
        return [
            BotCommand('public_cmd', 'Public Command'),
            BotCommand('granted_cmd', 'Granted Command'),
        ]

    async def _run():
        with patch('utilities.utl_func.COMMAND_DICT', fixture_dict), \
             patch('utilities.utl_func.ADMIN_GROUP_ID', [fake_group_chat_id]), \
             patch('utilities.utl_func.ADMIN_CHAT_ID', []), \
             patch('utilities.utl_func.SUPERADMIN_CHAT_ID', []), \
             patch('utilities.utl_func.list_users_with_access', new=mock_list_users_with_access), \
             patch('utilities.utl_func.get_user_menu_commands', new=mock_get_user_menu_commands):
            from utilities.utl_func import set_menu
            await set_menu(bot, mock_session)

    asyncio.run(_run())

    # Verify get_chat_administrators was called for the group
    bot.get_chat_administrators.assert_called_once_with(fake_group_chat_id)

    user_calls = [
        c for c in bot.set_my_commands.call_args_list
        if isinstance(c.kwargs['scope'], BotCommandScopeChat)
        and c.kwargs['scope'].chat_id == fake_admin_group_user
    ]
    assert len(user_calls) == 1

    merged_cmds = user_calls[0].kwargs['commands']
    cmd_names = {cmd.command for cmd in merged_cmds}
    assert 'admin_cmd' in cmd_names, "Admin group commands should be included"
    assert 'granted_cmd' in cmd_names, "Granted commands should be included"
    assert 'public_cmd' in cmd_names, "Public commands should be included"

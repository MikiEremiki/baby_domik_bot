import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import permissions
from permissions import (
    can, grant, revoke, grantable_items, list_users_with_access, is_privileged,
    get_allowed_settings, get_available_commands, normalize_key, _is_granted,
    get_user_menu_commands, PermissionBackendError,
)
from settings.settings import (
    ADMIN_ID, SETTINGS_SECTIONS, SETTINGS_DATABASE_KEY, COMMAND_DICT,
)

REGULAR = 999999999


def _run(coro):
    return asyncio.run(coro)


def test_can_settings_key_root_always_true():
    assert _run(can(ADMIN_ID[0], 'settings:place', AsyncMock())) is True


def test_can_settings_key_without_grant_false():
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = set()
        assert _run(can(REGULAR, 'settings:place', AsyncMock())) is False


def test_can_settings_key_with_grant_true():
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = {'settings:place'}
        assert _run(can(REGULAR, 'settings:place', AsyncMock())) is True
        assert _run(can(REGULAR, 'settings:promotion', AsyncMock())) is False


def test_can_settings_key_without_session_false():
    assert _run(can(REGULAR, 'settings:place', None)) is False


def test_can_unknown_settings_key_false_even_if_granted():
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = {'settings:nope'}
        assert _run(can(REGULAR, 'settings:nope', AsyncMock())) is False


def test_can_unknown_plain_command_fail_closed():
    """Unknown plain commands are denied (fail-closed) for non-root users."""
    assert _run(can(REGULAR, 'definitely_unknown_cmd', AsyncMock())) is False
    # ADMIN_ID still passes
    assert _run(can(ADMIN_ID[0], 'definitely_unknown_cmd', AsyncMock())) is True
    # super_admin also passes (unknown commands are not root_only)
    from settings.settings import SUPERADMIN_CHAT_ID
    assert _run(can(SUPERADMIN_CHAT_ID[0], 'definitely_unknown_cmd', AsyncMock())) is True


def test_can_plain_command_returns_bool_not_none():
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = set()
        result = _run(can(REGULAR, 'list', AsyncMock()))
        assert result is False
        acc.return_value = {'list'}
        assert _run(can(REGULAR, 'list', AsyncMock())) is True


def test_can_public_command_allowed():
    assert _run(can(REGULAR, 'start', None)) is True


def test_grantable_items_excludes_public_and_root_only():
    items = grantable_items(ADMIN_ID[0])
    plain_keys = {i.key for i in items if not i.key.startswith('settings:')}
    for entry in COMMAND_DICT.values():
        if entry.public or entry.root_only:
            assert entry[0] not in plain_keys
        elif entry[0] == 'settings':
            # 'settings' is excluded — it is derived from settings:* sections
            assert entry[0] not in plain_keys
        else:
            assert entry[0] in plain_keys


def test_grantable_items_database_key_only_for_privileged():
    root_keys = {i.key for i in grantable_items(ADMIN_ID[0])}
    other_keys = {i.key for i in grantable_items(REGULAR)}
    assert SETTINGS_DATABASE_KEY in root_keys
    assert SETTINGS_DATABASE_KEY not in other_keys
    assert set(SETTINGS_SECTIONS) - {SETTINGS_DATABASE_KEY} <= other_keys


def test_grantable_items_deterministic_and_unique():
    a = grantable_items(ADMIN_ID[0])
    b = grantable_items(ADMIN_ID[0])
    assert a == b
    assert len({i.key for i in a}) == len(a)
    # 'tech' group is empty because all tech commands are root_only
    assert {i.group for i in a} == {'commands', 'settings', 'update'}


def _session_with_existing(existing=None):
    session = MagicMock()
    session.get = AsyncMock(return_value=existing)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.rollback = AsyncMock()
    return session


def test_grant_database_rejected_for_non_privileged_actor():
    session = _session_with_existing()
    assert _run(grant(1, SETTINGS_DATABASE_KEY, session, actor_id=REGULAR)) is False
    assert _run(grant(1, SETTINGS_DATABASE_KEY, session)) is False
    session.add.assert_not_called()


def test_grant_database_allowed_for_root():
    session = _session_with_existing()
    assert _run(grant(1, SETTINGS_DATABASE_KEY, session, actor_id=ADMIN_ID[0])) is True
    session.add.assert_called_once()


def test_grant_regular_key_by_non_privileged_actor_ok():
    session = _session_with_existing()
    assert _run(grant(1, 'settings:place', session, actor_id=REGULAR)) is True


def test_grant_idempotent_when_exists():
    session = _session_with_existing(existing=object())
    assert _run(grant(1, 'settings:place', session, actor_id=REGULAR)) is False
    session.add.assert_not_called()


def test_revoke_database_rejected_for_non_privileged_actor():
    session = _session_with_existing(existing=object())
    assert _run(revoke(1, SETTINGS_DATABASE_KEY, session, actor_id=REGULAR)) is False
    session.delete.assert_not_called()


def test_revoke_removes_existing():
    session = _session_with_existing(existing=object())
    assert _run(revoke(1, 'settings:place', session, actor_id=REGULAR)) is True
    session.delete.assert_called_once()


def test_list_users_with_access():
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = [(1, 2), (5, 1)]
    session.execute = AsyncMock(return_value=result)
    assert _run(list_users_with_access(session)) == [(1, 2), (5, 1)]


def test_is_privileged_unchanged():
    assert is_privileged(ADMIN_ID[0]) is True
    assert is_privileged(REGULAR) is False
    assert permissions.is_privileged is is_privileged


# ─── get_allowed_settings ─────────────────────────────────────────────────────

def test_get_allowed_settings_root_returns_all():
    result = _run(get_allowed_settings(ADMIN_ID[0], AsyncMock()))
    assert result == set(SETTINGS_SECTIONS)


def test_get_allowed_settings_regular_with_grants():
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = {'settings:place', 'settings:schedule_event'}
        result = _run(get_allowed_settings(REGULAR, AsyncMock()))
        assert result == {'settings:place', 'settings:schedule_event'}


def test_get_allowed_settings_regular_no_grants():
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = set()
        result = _run(get_allowed_settings(REGULAR, AsyncMock()))
        assert result == set()


def test_get_allowed_settings_no_session():
    result = _run(get_allowed_settings(REGULAR, None))
    assert result == set()


def test_get_allowed_settings_db_error_returns_empty():
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.side_effect = PermissionBackendError('DB down')
        result = _run(get_allowed_settings(REGULAR, AsyncMock()))
        assert result == set()


def test_get_allowed_settings_filters_to_known_sections():
    """If the DB has a grant for an unknown settings key, it's excluded."""
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = {'settings:place', 'settings:unknown_xyz'}
        result = _run(get_allowed_settings(REGULAR, AsyncMock()))
        assert 'settings:place' in result
        assert 'settings:unknown_xyz' not in result


# ─── Ticket 01: fail-closed, root_only, grantable_items ──────────────────────

from settings.settings import SUPERADMIN_CHAT_ID

SUPERADMIN = SUPERADMIN_CHAT_ID[0]


def test_can_tech_command_denied_to_granted_user():
    """root_only tech commands are denied even if granted."""
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = {'clean_bd'}
        assert _run(can(REGULAR, 'clean_bd', AsyncMock())) is False


def test_can_tech_command_denied_to_super_admin():
    """root_only tech commands are denied to super_admin (not ADMIN_ID)."""
    # Use a user ID that is privileged but NOT in ADMIN_ID
    fake_super = 999_000_001
    with patch('permissions.SUPERADMIN_CHAT_ID', [fake_super]):
        assert is_privileged(fake_super) is True
        assert fake_super not in ADMIN_ID
        assert _run(can(fake_super, 'clean_bd', AsyncMock())) is False


def test_can_tech_command_allowed_to_root():
    """root_only tech commands are allowed for ADMIN_ID."""
    assert _run(can(ADMIN_ID[0], 'clean_bd', AsyncMock())) is True


def test_can_receipt_granted_true():
    """/receipt is grantable: True with grant, False without."""
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = set()
        assert _run(can(REGULAR, 'receipt', AsyncMock())) is False
        acc.return_value = {'receipt'}
        assert _run(can(REGULAR, 'receipt', AsyncMock())) is True


def test_can_receipt_denied_to_super_admin():
    """/receipt is not root_only, so super_admin gets it."""
    fake_super = 999_000_001
    with patch('permissions.SUPERADMIN_CHAT_ID', [fake_super]):
        assert _run(can(fake_super, 'receipt', AsyncMock())) is True


def test_can_tickets_denied_to_granted_user():
    """/tickets is root_only (in development), denied even with grant."""
    with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
        acc.return_value = {'tickets'}
        assert _run(can(REGULAR, 'tickets', AsyncMock())) is False


def test_can_tickets_denied_to_super_admin():
    """/tickets is root_only, denied to super_admin."""
    fake_super = 999_000_001
    with patch('permissions.SUPERADMIN_CHAT_ID', [fake_super]):
        assert _run(can(fake_super, 'tickets', AsyncMock())) is False


def test_can_public_commands_stay_open():
    """Public commands (/help, /echo, /start, /reset) are still open to everyone."""
    for cmd in ('help', 'echo', 'start'):
        assert _run(can(REGULAR, cmd, None)) is True


def test_grantable_items_no_tech():
    """grantable_items does not contain tech group items."""
    items = grantable_items(ADMIN_ID[0])
    tech_keys = {i.key for i in items if i.group == 'tech'}
    assert len(tech_keys) == 0


def test_grantable_items_no_settings_command():
    """grantable_items does not contain the 'settings' command."""
    items = grantable_items(ADMIN_ID[0])
    plain_keys = {i.key for i in items if not i.key.startswith('settings:')}
    assert 'settings' not in plain_keys


def test_grantable_items_has_receipt():
    """grantable_items contains 'receipt' (grantable command)."""
    items = grantable_items(ADMIN_ID[0])
    plain_keys = {i.key for i in items if not i.key.startswith('settings:')}
    assert 'receipt' in plain_keys


def test_studio_admin_not_in_command_dict():
    """STUDIO_ADMIN was removed from COMMAND_DICT."""
    assert 'STUDIO_ADMIN' not in COMMAND_DICT


def test_get_available_commands_super_admin_no_root_only():
    """super_admin gets all commands except root_only."""
    fake_super = 999_000_001
    async def _go():
        with patch('permissions.SUPERADMIN_CHAT_ID', [fake_super]):
            result = await get_available_commands(fake_super, None)
            keys = {k for k, _ in result}
            # Should have RECEIPT (not root_only)
            assert 'RECEIPT' in keys
            # Should NOT have tech root_only commands
            assert 'CLEAN_BD' not in keys
            assert 'TICKETS' not in keys
            assert 'PROFILE' not in keys
    _run(_go())


def test_get_available_commands_root_has_everything():
    """root (ADMIN_ID) gets all commands, including root_only."""
    async def _go():
        result = await get_available_commands(ADMIN_ID[0], None)
        keys = {k for k, _ in result}
        assert 'CLEAN_BD' in keys
        assert 'TICKETS' in keys
        assert 'RECEIPT' in keys
        assert len(keys) == len(COMMAND_DICT)
    _run(_go())


# ─── Ticket 02: normalize_key and _is_granted ────────────────────────────────

class TestNormalizeKey:
    """normalize_key maps COMMAND_DICT keys to entry[0] (command name)."""

    def test_command_name_unchanged(self):
        assert normalize_key('list') == 'list'

    def test_command_dict_key_maps_to_name(self):
        """normalize_key('LIST') → 'list' (entry[0])."""
        assert normalize_key('LIST') == 'list'

    def test_command_dict_key_non_trivial(self):
        """normalize_key('UP_PLACE_DATA') → 'update_places' (entry[0])."""
        assert normalize_key('UP_PLACE_DATA') == 'update_places'

    def test_settings_key_unchanged(self):
        assert normalize_key('settings:place') == 'settings:place'

    def test_empty_string(self):
        assert normalize_key('') == ''

    def test_none_unchanged(self):
        assert normalize_key(None) is None

    def test_unknown_key_lowered(self):
        """Unknown key falls back to lowered form."""
        assert normalize_key('UNKNOWN_XYZ') == 'unknown_xyz'


class TestIsGranted:
    """_is_granted checks entry[0] against the granted set."""

    def _make_entry(self):
        """Find the RECEIPT entry for testing."""
        return COMMAND_DICT['RECEIPT']

    def test_by_command_name(self):
        entry = self._make_entry()
        assert _is_granted(entry, {'receipt'}) is True

    def test_not_granted(self):
        entry = self._make_entry()
        assert _is_granted(entry, set()) is False

    def test_other_grant_only(self):
        entry = self._make_entry()
        assert _is_granted(entry, {'list'}) is False


class TestCanNormalizeKey:
    """can() normalizes the key so COMMAND_DICT keys and command names both work."""

    def test_command_dict_key_with_grant(self):
        """can(user, 'RECEIPT') with grant 'receipt' → True."""
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'receipt'}
            assert _run(can(REGULAR, 'RECEIPT', AsyncMock())) is True

    def test_command_name_with_grant(self):
        """can(user, 'receipt') with grant 'receipt' → True."""
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'receipt'}
            assert _run(can(REGULAR, 'receipt', AsyncMock())) is True

    def test_up_place_data_key_with_grant(self):
        """can(user, 'UP_PLACE_DATA') with grant 'update_places' → True."""
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'update_places'}
            assert _run(can(REGULAR, 'UP_PLACE_DATA', AsyncMock())) is True

    def test_update_places_name_with_grant(self):
        """can(user, 'update_places') with grant 'update_places' → True."""
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'update_places'}
            assert _run(can(REGULAR, 'update_places', AsyncMock())) is True


class TestGetAvailableCommandsNormalized:
    """get_available_commands uses _is_granted with normalized keys."""

    def test_grant_matches_entry(self):
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'receipt'}
            result = _run(get_available_commands(REGULAR, AsyncMock()))
            keys = {k for k, _ in result}
            assert 'RECEIPT' in keys


class TestGetUserMenuCommandsNormalized:
    """get_user_menu_commands uses _is_granted with normalized keys."""

    def test_grant_matches_entry(self):
        with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
            acc.return_value = {'list'}
            result = _run(get_user_menu_commands(REGULAR, AsyncMock()))
            names = {cmd.command for cmd in result}
            # list has in_menu=True and is not public
            assert 'list' in names


class TestGrantNormalizeOnWrite:
    """grant() normalizes the key before writing to DB."""

    def test_grant_command_dict_key_normalized(self):
        """grant('RECEIPT') stores 'receipt' (entry[0])."""
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        _run(grant(1, 'RECEIPT', session, actor_id=ADMIN_ID[0]))
        call_args = session.add.call_args[0][0]
        assert call_args.command == 'receipt'

    def test_grant_command_name_unchanged(self):
        """grant('receipt') stores 'receipt'."""
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        _run(grant(1, 'receipt', session, actor_id=ADMIN_ID[0]))
        call_args = session.add.call_args[0][0]
        assert call_args.command == 'receipt'


class TestRevokeNormalizeOnWrite:
    """revoke() normalizes the key before looking up in DB."""

    def test_revoke_command_dict_key_normalized(self):
        """revoke('RECEIPT') looks up 'receipt' (entry[0])."""
        obj = object()
        session = MagicMock()
        session.get = AsyncMock(return_value=obj)
        session.delete = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        _run(revoke(1, 'RECEIPT', session, actor_id=ADMIN_ID[0]))
        get_call = session.get.call_args[0][1]
        assert get_call['command'] == 'receipt'


class TestEntryUniqueness:
    """entry[0] values are unique and do not collide with COMMAND_DICT keys."""

    def test_entry0_uniqueness(self):
        """All entry[0] values in COMMAND_DICT must be unique."""
        names = [entry[0] for entry in COMMAND_DICT.values()]
        assert len(names) == len(set(names)), "Duplicate entry[0] found"

    def test_entry0_no_collision_with_keys(self):
        """No entry[0] should match another COMMAND_DICT key."""
        keys = set(COMMAND_DICT.keys())
        names = {entry[0] for entry in COMMAND_DICT.values()}
        # entry[0] may match its own key's name, but not another key
        for name in names:
            if name in keys:
                # The name is itself a key — that's the same entry, not a collision
                continue
            assert name not in keys, f"entry[0] '{name}' collides with a COMMAND_DICT key"


class TestGetUserAccessNormalizeOnRead:
    """get_user_access normalizes keys read from the database."""

    def _make_session(self, rows):
        """Create a mock session that returns the given rows from .all()."""
        from unittest.mock import MagicMock
        result_mock = MagicMock()
        result_mock.all.return_value = rows
        session = MagicMock()
        session.execute = AsyncMock(return_value=result_mock)
        return session

    def test_grant_uppercase_normalized(self):
        """Grant stored as 'LIST' is read as 'list' (normalized)."""
        from permissions import get_user_access
        session = self._make_session([('LIST',)])
        result = _run(get_user_access(999, session))
        assert 'list' in result
        assert 'LIST' not in result

    def test_grant_mixed_case_normalized(self):
        """Grant stored as 'UP_PLACE_DATA' is read as 'update_places'."""
        from permissions import get_user_access
        session = self._make_session([('UP_PLACE_DATA',)])
        result = _run(get_user_access(999, session))
        assert 'update_places' in result

    def test_settings_key_not_normalized(self):
        """settings:* keys are not changed by normalize_key on read."""
        from permissions import get_user_access
        session = self._make_session([('settings:place',)])
        result = _run(get_user_access(999, session))
        assert 'settings:place' in result


# ─── Ticket 04: is_privileged_update and is_allowed ──────────────────────────

class TestIsPrivilegedUpdate:
    """is_privileged_update delegates to is_privileged from permissions."""

    def test_root_is_privileged(self):
        from utilities.utl_func import is_privileged_update
        update = MagicMock()
        update.effective_user.id = ADMIN_ID[0]
        assert is_privileged_update(update) is True

    def test_superadmin_is_privileged(self):
        from utilities.utl_func import is_privileged_update
        fake_super = 999_000_001
        with patch('permissions.SUPERADMIN_CHAT_ID', [fake_super]):
            update = MagicMock()
            update.effective_user.id = fake_super
            assert is_privileged_update(update) is True

    def test_regular_user_not_privileged(self):
        from utilities.utl_func import is_privileged_update
        update = MagicMock()
        update.effective_user.id = REGULAR
        assert is_privileged_update(update) is False

    def test_missing_user_returns_false(self):
        from utilities.utl_func import is_privileged_update
        update = MagicMock()
        update.effective_user = None
        assert is_privileged_update(update) is False


class TestIsAllowed:
    """is_allowed(update, context, command) delegates to can_or_false."""

    def test_allowed_with_grant(self):
        from utilities.utl_func import is_allowed

        async def _go():
            update = MagicMock()
            update.effective_user.id = REGULAR
            context = MagicMock()
            context.session = AsyncMock()
            with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
                acc.return_value = {'list'}
                result = await is_allowed(update, context, 'list')
                assert result is True

        _run(_go())

    def test_denied_without_grant(self):
        from utilities.utl_func import is_allowed

        async def _go():
            update = MagicMock()
            update.effective_user.id = REGULAR
            context = MagicMock()
            context.session = AsyncMock()
            with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
                acc.return_value = set()
                result = await is_allowed(update, context, 'list')
                assert result is False

        _run(_go())

    def test_db_error_returns_false(self):
        """is_allowed treats DB error as no access (fail-closed)."""
        from utilities.utl_func import is_allowed
        from permissions import PermissionBackendError

        async def _go():
            update = MagicMock()
            update.effective_user.id = REGULAR
            context = MagicMock()
            context.session = AsyncMock()
            with patch('permissions.get_user_access', new_callable=AsyncMock) as acc:
                acc.side_effect = PermissionBackendError('DB down')
                result = await is_allowed(update, context, 'list')
                assert result is False

        _run(_go())

    def test_missing_user_returns_false(self):
        from utilities.utl_func import is_allowed

        async def _go():
            update = MagicMock()
            update.effective_user = None
            context = MagicMock()
            result = await is_allowed(update, context, 'list')
            assert result is False

        _run(_go())


class TestIsAdminDeprecated:
    """is_admin is deprecated and delegates to is_privileged_update."""

    def test_is_admin_delegates_to_is_privileged_update(self):
        from utilities.utl_func import is_admin, is_privileged_update
        update = MagicMock()
        update.effective_user.id = ADMIN_ID[0]
        assert is_admin(update) is True
        assert is_privileged_update(update) is True

    def test_is_admin_superadmin(self):
        """is_admin now includes superadmin (delegates to is_privileged_update)."""
        from utilities.utl_func import is_admin
        fake_super = 999_000_001
        with patch('permissions.SUPERADMIN_CHAT_ID', [fake_super]):
            update = MagicMock()
            update.effective_user.id = fake_super
            assert is_admin(update) is True

    def test_is_admin_regular_user(self):
        from utilities.utl_func import is_admin
        update = MagicMock()
        update.effective_user.id = REGULAR
        assert is_admin(update) is False


# ─── Ticket 06: bot_is_admin_in_chat ─────────────────────────────────────────

class TestBotIsAdminInChat:
    """bot_is_admin_in_chat checks bot admin rights in the chat."""

    def test_bot_is_admin_returns_true(self):
        from permissions import bot_is_admin_in_chat

        async def _go():
            bot_id = 12345
            admin_mock = MagicMock()
            admin_mock.user.id = bot_id

            chat = AsyncMock()
            chat.get_administrators.return_value = [admin_mock]

            update = MagicMock()
            update.effective_chat = chat
            update.effective_message.id = 1
            update.effective_message.message_thread_id = None

            context = MagicMock()
            context.bot.id = bot_id

            result = await bot_is_admin_in_chat(update, context)
            assert result is True

        _run(_go())

    def test_bot_is_admin_returns_false_and_sends_message(self):
        from permissions import bot_is_admin_in_chat

        async def _go():
            bot_id = 12345
            admin_mock = MagicMock()
            admin_mock.user.id = 99999  # different bot

            chat = AsyncMock()
            chat.get_administrators.return_value = [admin_mock]

            message = AsyncMock()
            message.id = 1
            message.message_thread_id = None

            update = MagicMock()
            update.effective_chat = chat
            update.effective_message = message

            context = MagicMock()
            context.bot.id = bot_id

            result = await bot_is_admin_in_chat(update, context)
            assert result is False
            # Should have sent a warning message
            message.reply_text.assert_called_once()
            call_kwargs = message.reply_text.call_args
            assert 'права' in call_kwargs[1]['text'].lower()

        _run(_go())

    def test_bot_is_admin_not_in_empty_admins_list(self):
        """When no admins are present, the bot is not an admin."""
        from permissions import bot_is_admin_in_chat

        async def _go():
            chat = AsyncMock()
            chat.get_administrators.return_value = []

            message = AsyncMock()
            message.id = 1
            message.message_thread_id = None

            update = MagicMock()
            update.effective_chat = chat
            update.effective_message = message

            context = MagicMock()
            context.bot.id = 12345

            result = await bot_is_admin_in_chat(update, context)
            assert result is False

        _run(_go())

    def test_bot_is_admin_callback_falls_back_to_answer(self):
        """When effective_message is None (callback), use callback.answer instead."""
        from permissions import bot_is_admin_in_chat

        async def _go():
            chat = AsyncMock()
            chat.get_administrators.return_value = []

            callback_query = AsyncMock()

            update = MagicMock()
            update.effective_chat = chat
            update.effective_message = None  # Callback has no effective_message
            update.callback_query = callback_query

            context = MagicMock()
            context.bot.id = 12345

            result = await bot_is_admin_in_chat(update, context)
            assert result is False
            # Should use callback.answer, not reply_text
            callback_query.answer.assert_called_once()
            assert callback_query.answer.call_args[1].get('show_alert') is True

        _run(_go())


# ─── Ticket 07: single extract_command ────────────────────────────────────────

class TestExtractCommand:
    """extract_command — unified command parser from utl_func."""

    def test_simple_command(self):
        from utilities.utl_func import extract_command
        assert extract_command('/list') == 'list'

    def test_command_with_args(self):
        from utilities.utl_func import extract_command
        assert extract_command('/list 123') == 'list'

    def test_command_uppercase_normalized(self):
        from utilities.utl_func import extract_command
        assert extract_command('/LIST') == 'list'

    def test_command_with_bot_username_match(self):
        from utilities.utl_func import extract_command
        assert extract_command('/list@mybot', 'mybot') == 'list'

    def test_command_with_bot_username_case_insensitive(self):
        from utilities.utl_func import extract_command
        assert extract_command('/list@MyBot', 'mybot') == 'list'

    def test_command_with_other_bot_username(self):
        from utilities.utl_func import extract_command
        assert extract_command('/list@otherbot', 'mybot') is None

    def test_command_with_at_no_bot_username(self):
        """When bot_username is not provided, @ suffix is stripped but command is returned."""
        from utilities.utl_func import extract_command
        assert extract_command('/list@otherbot') == 'list'

    def test_not_a_command(self):
        from utilities.utl_func import extract_command
        assert extract_command('hello') is None

    def test_empty_string(self):
        from utilities.utl_func import extract_command
        assert extract_command('') is None

    def test_none_text(self):
        from utilities.utl_func import extract_command
        assert extract_command(None) is None

    def test_slash_only(self):
        from utilities.utl_func import extract_command
        assert extract_command('/') is None

    def test_command_with_at_and_args(self):
        from utilities.utl_func import extract_command
        assert extract_command('/list@mybot 42', 'mybot') == 'list'

    def test_command_with_at_and_args_other_bot(self):
        from utilities.utl_func import extract_command
        assert extract_command('/list@otherbot 42', 'mybot') is None

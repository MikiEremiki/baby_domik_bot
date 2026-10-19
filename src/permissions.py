"""Centralized command permission logic.

Provides `can()` — the single source of truth for command access checks.
Used by middleware, handlers, help_cmd, set_my_commands, and settings menu.
"""
import logging
from dataclasses import dataclass

from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from telegram import BotCommand
from telegram.ext import ContextTypes
from telegram import Update

from db.models import UserCommandAccess
from settings.settings import (
    COMMAND_DICT, ADMIN_ID, SUPERADMIN_CHAT_ID,
    SETTINGS_SECTIONS, SETTINGS_PREFIX, SETTINGS_DATABASE_KEY,
)

permissions_logger = logging.getLogger('bot.permissions')


class PermissionBackendError(Exception):
    """Raised when the permission backend (database) is unavailable.

    ``can()`` propagates this exception so the caller can distinguish
    "no access" from "temporary error". The middleware catches it and
    shows a user-friendly message. Handlers that call ``get_user_access``
    directly should also catch it.
    """
    pass


def is_privileged(user_id: int) -> bool:
    """Check if user is root or super_admin (from settings.py, no DB needed)."""
    return user_id in (ADMIN_ID + SUPERADMIN_CHAT_ID)


async def bot_is_admin_in_chat(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> bool:
    """Check whether the *bot* is an admin in the current chat.

    This is **not** a user-permission check — it verifies that the bot
    has administrator rights in the chat (needed for managing forum topics).
    Returns ``False`` and sends a warning message if the bot is not an admin.

    Works for both regular messages and callback queries.
    """
    admins = await update.effective_chat.get_administrators()
    admin_ids = [admin.user.id for admin in admins]
    if context.bot.id not in admin_ids:
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(
                text='Предоставьте боту права на управление темами',
                reply_to_message_id=msg.id,
                message_thread_id=msg.message_thread_id
            )
        else:
            # Callback query without effective_message — use callback.answer
            cq = update.callback_query
            if cq is not None:
                await cq.answer('Предоставьте боту права на управление темами', show_alert=True)
        return False
    return True


def normalize_key(cmd: str) -> str:
    """Normalize a permission key to the canonical command-name form.

    - 'settings:*' keys are left as-is.
    - A COMMAND_DICT key (e.g. 'UP_PLACE_DATA') is mapped to its command
      name (entry[0], e.g. 'update_places').
    - A plain command name (e.g. 'list') is returned as-is.
    - If *cmd* is not a known key, it is lowered as a best-effort fallback.
    """
    if not cmd:
        return cmd
    if cmd.startswith(SETTINGS_PREFIX):
        return cmd
    # Direct COMMAND_DICT key → command name
    entry = COMMAND_DICT.get(cmd)
    if entry is not None:
        return entry[0]
    # Already a command name or unknown — return lowered
    return cmd.lower()


def _is_granted(entry, granted: set) -> bool:
    """Check whether *entry* is covered by the set of granted keys.

    After :func:`normalize_key` maps all keys to the command-name form
    (entry[0]), a single membership test is enough.
    """
    return entry[0] in granted


def get_command_entry(cmd: str):
    """Look up a command entry in COMMAND_DICT by key or by cmd name.

    Uses :func:`normalize_key` to resolve any form of the key to the
    canonical command name, then searches by that name.
    """
    name = normalize_key(cmd)
    if name is None:
        return None
    # Direct key match after normalization
    if name in COMMAND_DICT:
        return COMMAND_DICT[name]
    # Reverse lookup by command name (entry[0])
    for entry in COMMAND_DICT.values():
        if entry[0] == name:
            return entry
    return None


async def get_user_access(user_id: int, session: AsyncSession) -> set:
    """Return the set of commands granted to a user via user_command_access.

    All keys are normalized on read so that old rows stored in a different
    case do not silently disappear.

    Raises:
        PermissionBackendError: when the database query fails.
    """
    try:
        stmt = select(UserCommandAccess.command).where(
            UserCommandAccess.user_id == user_id
        )
        result = await session.execute(stmt)
        raw = {row[0] for row in result.all()}
        # Normalize every key read from the database
        return {normalize_key(c) for c in raw}
    except (SQLAlchemyError, OSError) as e:
        permissions_logger.error(
            f'get_user_access DB error for user {user_id}: {e}', exc_info=True)
        raise PermissionBackendError(
            f'Database error while fetching grants for user {user_id}') from e


async def can(user_id: int, command: str, session: AsyncSession = None) -> bool:
    """Check if a user has access to a command.

    Logic:
    1. root (ADMIN_ID only) → True for everything
    2. super_admin → True for everything except root_only
    3. command.public → True
    4. command.root_only → False (even granted users can't access)
    5. (user_id, command) in user_command_access → True
    6. Unknown plain command → False (fail-closed), except ADMIN_ID

    On DB error: raises ``PermissionBackendError`` so the caller can
    distinguish "no access" from "temporary error". The middleware catches
    it and shows a user-friendly message.

    When DEBUG logging is enabled, the reason for each decision is logged.
    """
    # Normalize the key so all lookups use one canonical form
    command = normalize_key(command)

    # Rule 1: root (ADMIN_ID only) has access to everything
    if user_id in ADMIN_ID:
        if permissions_logger.isEnabledFor(logging.DEBUG):
            permissions_logger.debug(
                f'can({user_id}, {command!r}) -> True (root)')
        return True

    # Rule 2: super_admin has access to everything except root_only
    if is_privileged(user_id):
        entry = get_command_entry(command)
        if entry is None:
            if permissions_logger.isEnabledFor(logging.DEBUG):
                permissions_logger.debug(
                    f'can({user_id}, {command!r}) -> False (super_admin, unknown command)')
            return False  # Unknown command — fail-closed for super_admin too
        if entry.root_only:
            if permissions_logger.isEnabledFor(logging.DEBUG):
                permissions_logger.debug(
                    f'can({user_id}, {command!r}) -> False (super_admin, root_only)')
            return False
        if permissions_logger.isEnabledFor(logging.DEBUG):
            permissions_logger.debug(
                f'can({user_id}, {command!r}) -> True (super_admin)')
        return True

    # settings:<section> keys are never public: a grant is required.
    # Unknown settings keys are denied.
    if command.startswith(SETTINGS_PREFIX):
        if command not in SETTINGS_SECTIONS or session is None:
            if permissions_logger.isEnabledFor(logging.DEBUG):
                permissions_logger.debug(
                    f'can({user_id}, {command!r}) -> False (settings key, not in SETTINGS_SECTIONS or no session)')
            return False
        granted = await get_user_access(user_id, session)
        result = command in granted
        if permissions_logger.isEnabledFor(logging.DEBUG):
            permissions_logger.debug(
                f'can({user_id}, {command!r}) -> {result} (settings grant check)')
        return result

    entry = get_command_entry(command)

    # Rule 6: unknown plain command — fail-closed
    if entry is None:
        if permissions_logger.isEnabledFor(logging.DEBUG):
            permissions_logger.debug(
                f'can({user_id}, {command!r}) -> False (unknown command)')
        return False

    # Rule 3: public commands are always accessible
    if entry.public:
        if permissions_logger.isEnabledFor(logging.DEBUG):
            permissions_logger.debug(
                f'can({user_id}, {command!r}) -> True (public)')
        return True

    # Rule 4: root_only commands are only for ADMIN_ID (checked above)
    if entry.root_only:
        if permissions_logger.isEnabledFor(logging.DEBUG):
            permissions_logger.debug(
                f'can({user_id}, {command!r}) -> False (root_only)')
        return False

    # Rule 5: check DB grant (no session available — fail-closed)
    if session is None:
        if permissions_logger.isEnabledFor(logging.DEBUG):
            permissions_logger.debug(
                f'can({user_id}, {command!r}) -> False (no session)')
        return False
    granted = await get_user_access(user_id, session)
    result = _is_granted(entry, granted)
    if permissions_logger.isEnabledFor(logging.DEBUG):
        permissions_logger.debug(
            f'can({user_id}, {command!r}) -> {result} (grant check)')
    return result


async def can_or_false(user_id: int, command: str, session: AsyncSession = None) -> bool:
    """Call ``can()`` and return ``False`` on ``PermissionBackendError``.

    Use this in handlers that need a simple boolean but want to treat
    a DB error as "no access" instead of showing a temporary-error message.
    """
    try:
        return await can(user_id, command, session)
    except PermissionBackendError:
        return False


async def get_user_access_or_empty(user_id: int, session: AsyncSession) -> set:
    """Call ``get_user_access()`` and return ``set()`` on ``PermissionBackendError``.

    Use this in handlers that read grants directly (e.g., to render UI)
    but want to treat a DB error as "no grants" instead of crashing.
    """
    try:
        return await get_user_access(user_id, session)
    except PermissionBackendError:
        return set()


async def get_available_commands(user_id: int, session: AsyncSession = None) -> list:
    """Return list of (key, entry) tuples the user can access.

    On DB error: returns only public commands (fail-closed).
    """
    # root (ADMIN_ID) gets everything
    if user_id in ADMIN_ID:
        return list(COMMAND_DICT.items())

    # super_admin gets everything except root_only
    if is_privileged(user_id):
        return [(k, e) for k, e in COMMAND_DICT.items() if not e.root_only]

    granted = set()
    if session is not None:
        try:
            granted = await get_user_access(user_id, session)
        except PermissionBackendError:
            permissions_logger.warning(
                f'get_available_commands DB error for user {user_id}, '
                'falling back to public commands only')

    available = []
    for key, entry in COMMAND_DICT.items():
        if entry.public:
            available.append((key, entry))
        elif entry.root_only:
            continue
        elif _is_granted(entry, granted):
            available.append((key, entry))

    return available


async def get_allowed_settings(user_id: int, session: AsyncSession = None) -> set:
    """Return the set of `settings:<section>` keys the user may use (one DB query).

    On DB error: returns empty set (fail-closed).
    """
    # root (ADMIN_ID) gets all settings
    if user_id in ADMIN_ID:
        return set(SETTINGS_SECTIONS)
    # super_admin gets all settings (not root_only)
    if is_privileged(user_id):
        return set(SETTINGS_SECTIONS)
    if session is None:
        return set()
    try:
        granted = await get_user_access(user_id, session)
        return {key for key in SETTINGS_SECTIONS if key in granted}
    except PermissionBackendError:
        permissions_logger.warning(
            f'get_allowed_settings DB error for user {user_id}, '
            'falling back to empty set')
        return set()


def _actor_may_manage(command: str, actor_id: int | None) -> bool:
    """Only root/super_admin may grant or revoke 'settings:database'."""
    if command == SETTINGS_DATABASE_KEY:
        return actor_id is not None and is_privileged(actor_id)
    return True


async def grant(user_id: int, command: str, session: AsyncSession,
                actor_id: int | None = None) -> bool:
    """Grant a command to a user. Returns True if inserted, False if already exists
    or the actor is not allowed to manage this command."""
    # Normalize before any check so the stored key is always canonical
    command = normalize_key(command)
    if not _actor_may_manage(command, actor_id):
        permissions_logger.warning(
            f'Actor {actor_id} denied granting {command} to user {user_id}')
        return False
    try:
        existing = await session.get(UserCommandAccess, {'user_id': user_id, 'command': command})
        if existing:
            return False
        session.add(UserCommandAccess(user_id=user_id, command=command))
        await session.flush()
        await session.commit()
        permissions_logger.info(f'Granted {command} to user {user_id}')
        return True
    # Wide except is intentional: write-operations with rollback may fail
    # not only with DB errors but also with constraint violations,
    # connection timeouts, or unexpected state — all should be caught
    # and rolled back without crashing the handler.
    except Exception as e:
        await session.rollback()
        permissions_logger.error(f'grant() error: {e}', exc_info=True)
        return False


async def revoke(user_id: int, command: str, session: AsyncSession,
                 actor_id: int | None = None) -> bool:
    """Revoke a command from a user. Returns True if removed, False if not found
    or the actor is not allowed to manage this command."""
    # Normalize before any check so the stored key is always canonical
    command = normalize_key(command)
    if not _actor_may_manage(command, actor_id):
        permissions_logger.warning(
            f'Actor {actor_id} denied revoking {command} from user {user_id}')
        return False
    try:
        existing = await session.get(UserCommandAccess, {'user_id': user_id, 'command': command})
        if not existing:
            return False
        await session.delete(existing)
        await session.commit()
        permissions_logger.info(f'Revoked {command} from user {user_id}')
        return True
    # Wide except is intentional: same reason as grant() — any failure
    # during delete + commit must be rolled back without crashing.
    except Exception as e:
        await session.rollback()
        permissions_logger.error(f'revoke() error: {e}', exc_info=True)
        return False


@dataclass(frozen=True)
class AccessItem:
    key: str    # 'list' | 'settings:place'
    label: str
    group: str  # 'commands' | 'settings' | 'update' | 'tech'


ACCESS_GROUPS = (
    ('commands', 'Команды'),
    ('settings', 'Разделы /settings'),
    ('update', 'Обновление данных'),
    ('tech', 'Технические'),
)


def grantable_items(actor_id: int) -> list[AccessItem]:
    """Deterministic list of items the actor may grant/revoke.

    Excludes public and root_only commands. 'settings:database' is only
    included for root/super_admin. 'settings' (the command) is excluded
    because it is derived from settings:* sections.
    """
    items: list[AccessItem] = []
    by_group: dict[str, list[AccessItem]] = {g: [] for g, _ in ACCESS_GROUPS}

    for entry in COMMAND_DICT.values():
        if entry.public or entry.root_only:
            continue
        # Exclude the 'settings' command — it is derived from settings:* sections
        if entry[0] == 'settings':
            continue
        group = entry.group if entry.group in by_group else 'commands'
        label = entry[1] if group == 'update' else f'/{entry[0]} — {entry[1]}'
        by_group[group].append(AccessItem(entry[0], label, group))

    for key, label in SETTINGS_SECTIONS.items():
        if key == SETTINGS_DATABASE_KEY and not is_privileged(actor_id):
            continue
        by_group['settings'].append(AccessItem(key, label, 'settings'))

    for group, _ in ACCESS_GROUPS:
        items.extend(by_group[group])
    return items


async def list_users_with_access(session: AsyncSession) -> list[tuple[int, int]]:
    """Return [(user_id, grants_count)] for users that have any grant."""
    stmt = (select(UserCommandAccess.user_id, func.count(UserCommandAccess.command))
            .group_by(UserCommandAccess.user_id)
            .order_by(UserCommandAccess.user_id))
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]




async def get_user_menu_commands(user_id: int, session: AsyncSession) -> list:
    """Build a list of telegram.BotCommand for the user's Telegram menu.

    Returns only commands marked with in_menu=True that the user has access to
    (public or granted). Root (ADMIN_ID) gets all in_menu commands.
    On DB error: returns only public in_menu commands (fail-closed).
    """
    # root gets all in_menu commands
    if user_id in ADMIN_ID:
        commands = []
        for entry in COMMAND_DICT.values():
            if entry.in_menu:
                commands.append(BotCommand(entry[0], entry[1]))
        return commands

    # super_admin gets all in_menu except root_only
    if is_privileged(user_id):
        commands = []
        for entry in COMMAND_DICT.values():
            if entry.in_menu and not entry.root_only:
                commands.append(BotCommand(entry[0], entry[1]))
        return commands

    granted = set()
    if session is not None:
        try:
            granted = await get_user_access(user_id, session)
        except PermissionBackendError:
            permissions_logger.warning(
                f'get_user_menu_commands DB error for user {user_id}, '
                'falling back to public in_menu commands only')

    commands = []
    for entry in COMMAND_DICT.values():
        if not entry.in_menu:
            continue
        if entry.public:
            commands.append(BotCommand(entry[0], entry[1]))
        elif entry.root_only:
            continue
        else:
            # Check if granted
            if _is_granted(entry, granted):
                commands.append(BotCommand(entry[0], entry[1]))

    return commands

"""Access management UI: /settings -> База данных -> Доступ к командам.

Admin picks a user (text user_id or forwarded message) and toggles command /
settings-section access with autosave. The DB (`user_command_access`) is the
single source of truth: ✅/⬜ are read from it on every render.

The entry screen shows a list of users with access (paginated) along with the
prompt to enter a user_id or forward a message. No extra button is needed.

Callback data (after `add_intent_id(..., 'acc')`):
    grp                 — groups screen of the selected user
    pg|<group>|<page>   — group screen with pagination
    tg|<group>|<idx>    — toggle item #idx of grantable_items(actor)
    usr|<page>          — page of users that already have access (entry screen)
    pick|<user_id>      — select user from the list
    home                — back to the entry screen (users list)
"""
import functools
import logging

from telegram import Update, BotCommandScopeChat, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from db import db_postgres
from handlers.command_mgmt.keyboards import (
    ENTRY_TEXT, GROUP_TITLES, PAGE_SIZE,
    _get_grants, _render_entry, _render_groups, _render_group,
)
from handlers.command_mgmt.parsers import (
    _parse_target_input, _parse_toggle,
)
from permissions import (
    can, get_user_menu_commands, grant, grantable_items, is_privileged,
    revoke, PermissionBackendError,
)
from settings.settings import SETTINGS_DATABASE_KEY
from utilities.utl_kbd import add_btn_back_and_cancel, remove_intent_id

command_mgmt_hl_logger = logging.getLogger('bot.command_mgmt_hl')

ACCESS_ASK_USER = 120
TARGET_KEY = 'access_target_id'

NO_ACCESS_TEXT = 'У вас нет доступа к этому разделу.'
STALE_TEXT = 'Список устарел, откройте экран заново'


async def _safe_answer(query, text: str | None = None, show_alert: bool = False):
    try:
        await query.answer(text, show_alert=show_alert)
    except BadRequest:
        pass


async def _edit(query, text: str | None = None, reply_markup=None):
    """Edit text and/or keyboard, ignoring 'Message is not modified'."""
    try:
        if text is None:
            await query.edit_message_reply_markup(reply_markup=reply_markup)
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if 'not modified' not in str(e).lower():
            raise


async def _actor_allowed(update: Update, context) -> bool:
    """Server-side check on every access-screen event."""
    try:
        allowed = await can(
            update.effective_user.id, SETTINGS_DATABASE_KEY, context.session)
    except PermissionBackendError:
        query = update.callback_query
        if query:
            await _safe_answer(query, 'Временная ошибка, попробуйте позже.', show_alert=True)
        elif update.effective_chat:
            await update.effective_chat.send_message('Временная ошибка, попробуйте позже.')
        return False
    if not allowed:
        command_mgmt_hl_logger.warning(
            'User %s denied access screen', update.effective_user.id)
        query = update.callback_query
        if query:
            await _safe_answer(query, NO_ACCESS_TEXT, show_alert=True)
        elif update.effective_chat:
            await update.effective_chat.send_message(NO_ACCESS_TEXT)
    return allowed


async def _get_user_label_if_exists(session, user_id: int) -> str | None:
    """Return label if the user exists in `users`, otherwise None."""
    usernames = await db_postgres.get_usernames_by_ids(session, [user_id])
    if user_id not in usernames:
        return None
    username = usernames.get(user_id)
    return f'@{username} ({user_id})' if username else str(user_id)


async def _apply_toggle(target_id, item, actor_id, session) -> tuple[bool, bool, str | None]:
    """Apply a toggle: grant or revoke the item for the target user.

    For settings:* sections, also manages the derived 'settings' command grant:
    - Granting the first settings:* section auto-grants 'settings'.
    - Revoking the last settings:* section auto-revokes 'settings'.

    Returns (done, was_granted, note) where done indicates the state actually changed,
    was_granted indicates whether the item was granted (True) or revoked (False),
    and note is an optional message about the derived grant (e.g. '+ /settings').
    Includes idempotent fallback for race conditions.
    """
    was_granted = item.key in await _get_grants(target_id, session)
    note: str | None = None

    if was_granted:
        done = await revoke(target_id, item.key, session, actor_id=actor_id)
    else:
        done = await grant(target_id, item.key, session, actor_id=actor_id)

    if not done:
        # idempotent: double click / race may have already produced the desired state
        now_granted = item.key in await _get_grants(target_id, session)
        done = now_granted != was_granted

    # Derived settings grant: auto-manage the 'settings' command
    if item.key.startswith('settings:') and done:
        current_access = await _get_grants(target_id, session)
        settings_sections = {k for k in current_access if k.startswith('settings:')}
        has_settings_cmd = 'settings' in current_access

        if not was_granted and not has_settings_cmd:
            # Just granted a settings:* section, auto-grant 'settings'
            granted_settings = await grant(target_id, 'settings', session, actor_id=actor_id)
            if granted_settings:
                note = '+ /settings'
        elif was_granted and not settings_sections:
            # Just revoked the last settings:* section, auto-revoke 'settings'
            if has_settings_cmd:
                revoked_settings = await revoke(target_id, 'settings', session, actor_id=actor_id)
                if revoked_settings:
                    note = '− /settings'

    return done, was_granted, note


def _require_actor(handler):
    """Decorator: check actor permission before running the handler.

    If the actor is not allowed, returns ACCESS_ASK_USER without calling the handler.
    Preserves __name__ and __doc__ for patching compatibility.
    """
    @functools.wraps(handler)
    async def wrapper(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
        if not await _actor_allowed(update, context):
            return ACCESS_ASK_USER
        return await handler(update, context)
    return wrapper


# ─── Handlers ──────────────────────────────────────────────────────────────────

async def access_start(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """Entry: /settings -> База данных -> Доступ к командам.

    Shows the entry screen with a list of users with access.
    Falls back to ENTRY_TEXT only if the DB is unavailable.
    """
    query = update.callback_query
    await _safe_answer(query)
    if not await _actor_allowed(update, context):
        return context.user_data.get('STATE', 2)

    context.user_data.pop(TARGET_KEY, None)

    try:
        text, reply_markup = await _render_entry(0, context.session)
    except Exception:
        command_mgmt_hl_logger.error(
            'Failed to render entry screen: DB error', exc_info=True)
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='settings', postfix_for_back='2')
        text = ENTRY_TEXT
        reply_markup = InlineKeyboardMarkup([keyboard])
    await _edit(query, text, reply_markup)

    context.user_data['STATE'] = ACCESS_ASK_USER
    return ACCESS_ASK_USER


async def access_home(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """Back from groups to the entry screen (users list)."""
    return await access_start(update, context)


@_require_actor
async def access_receive_user(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """Text user_id or forwarded message -> selects the target user."""
    message = update.effective_message
    chat = update.effective_chat

    target_id, error = _parse_target_input(message)
    if target_id is None:
        await chat.send_message(error)
        return ACCESS_ASK_USER

    label = await _get_user_label_if_exists(context.session, target_id)
    if label is None:
        await chat.send_message(
            f'Пользователь {target_id} не найден в базе. '
            f'Введите другой user_id или перешлите сообщение пользователя')
        return ACCESS_ASK_USER

    context.user_data[TARGET_KEY] = target_id
    text, reply_markup = await _render_groups(
        update.effective_user.id, target_id, label, context.session)
    await chat.send_message(text, reply_markup=reply_markup)

    context.user_data['STATE'] = ACCESS_ASK_USER
    return ACCESS_ASK_USER


@_require_actor
async def access_users_list(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """Paginate the entry screen (users with access list)."""
    query = update.callback_query
    await _safe_answer(query)

    _, payload = remove_intent_id(query.data)
    page = int(payload.split('|')[1])
    text, reply_markup = await _render_entry(page, context.session)
    await _edit(query, text, reply_markup)
    return ACCESS_ASK_USER


@_require_actor
async def access_pick_user(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query

    _, payload = remove_intent_id(query.data)
    target_id = int(payload.split('|')[1])
    label = await _get_user_label_if_exists(context.session, target_id)
    if label is None:
        await _safe_answer(query, 'Пользователь не найден', show_alert=True)
        return ACCESS_ASK_USER
    await _safe_answer(query)

    context.user_data[TARGET_KEY] = target_id
    text, reply_markup = await _render_groups(
        update.effective_user.id, target_id, label, context.session)
    await _edit(query, text, reply_markup)
    return ACCESS_ASK_USER


async def _get_target(update: Update, context) -> tuple[int, str] | None:
    """Selected target (validated in `users`) or None after notifying the actor."""
    query = update.callback_query
    target_id = context.user_data.get(TARGET_KEY)
    if target_id is None:
        await _safe_answer(query, 'Сначала выберите пользователя', show_alert=True)
        return None
    label = await _get_user_label_if_exists(context.session, target_id)
    if label is None:
        context.user_data.pop(TARGET_KEY, None)
        await _safe_answer(query, 'Пользователь не найден', show_alert=True)
        return None
    return target_id, label


@_require_actor
async def access_show_groups(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    target = await _get_target(update, context)
    if target is None:
        return ACCESS_ASK_USER
    await _safe_answer(query)

    target_id, label = target
    text, reply_markup = await _render_groups(
        update.effective_user.id, target_id, label, context.session)
    await _edit(query, text, reply_markup)
    return ACCESS_ASK_USER


@_require_actor
async def access_show_group(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    target = await _get_target(update, context)
    if target is None:
        return ACCESS_ASK_USER

    _, payload = remove_intent_id(query.data)
    _, group, page = payload.split('|')
    if group not in GROUP_TITLES or is_privileged(target[0]):
        await _safe_answer(query, STALE_TEXT, show_alert=True)
        return ACCESS_ASK_USER
    await _safe_answer(query)

    target_id, label = target
    text, reply_markup = await _render_group(
        update.effective_user.id, target_id, label, group, int(page),
        context.session)
    await _edit(query, text, reply_markup)
    return ACCESS_ASK_USER


@_require_actor
async def access_toggle(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """Autosave: every click immediately grants or revokes the item."""
    query = update.callback_query
    actor_id = update.effective_user.id

    _, payload = remove_intent_id(query.data)
    item = _parse_toggle(payload, grantable_items(actor_id))
    if item is None:
        await _safe_answer(query, STALE_TEXT, show_alert=True)
        return ACCESS_ASK_USER

    target = await _get_target(update, context)
    if target is None:
        return ACCESS_ASK_USER
    target_id, label = target

    if is_privileged(target_id):
        await _safe_answer(query, 'Пользователь имеет полный доступ', show_alert=True)
        return ACCESS_ASK_USER

    session = context.session
    done, was_granted, note = await _apply_toggle(target_id, item, actor_id, session)
    if not done:
        await _safe_answer(query, 'Не удалось изменить доступ', show_alert=True)
        return ACCESS_ASK_USER

    command_mgmt_hl_logger.info(
        'Actor %s %s %s for user %s', actor_id,
        'revoked' if was_granted else 'granted', item.key, target_id)
    answer = 'Забрано' if was_granted else 'Выдано'
    if note:
        answer += f' ({note})'
    await _safe_answer(query, answer)

    items = grantable_items(actor_id)
    _, payload = remove_intent_id(query.data)
    _, group, idx_str = payload.split('|')
    idx = int(idx_str)
    pos = [i for i, it in enumerate(items) if it.group == group].index(idx)
    _, reply_markup = await _render_group(
        actor_id, target_id, label, group, pos // PAGE_SIZE, session)
    await _edit(query, None, reply_markup)
    return ACCESS_ASK_USER


async def access_noop(update: Update, _context: 'ContextTypes.DEFAULT_TYPE'):
    await _safe_answer(update.callback_query)
    return ACCESS_ASK_USER


@_require_actor
async def access_reload_menu(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """Reload Telegram menu for the target user via bot.set_my_commands."""
    query = update.callback_query
    target = await _get_target(update, context)
    if target is None:
        return ACCESS_ASK_USER
    target_id, label = target

    if is_privileged(target_id):
        await _safe_answer(query, 'Пользователь имеет полный доступ, меню не нужно настраивать', show_alert=True)
        return ACCESS_ASK_USER

    try:
        menu_commands = await get_user_menu_commands(target_id, context.session)
        await context.bot.set_my_commands(
            commands=menu_commands,
            scope=BotCommandScopeChat(chat_id=target_id),
        )
        command_mgmt_hl_logger.info(
            'Actor %s reloaded menu for user %s (%d commands)',
            update.effective_user.id, target_id, len(menu_commands))
        await _safe_answer(query, f'Меню для {label} обновлено ({len(menu_commands)} команд)')
    except Exception as e:
        command_mgmt_hl_logger.error(
            'Failed to reload menu for user %s: %s', target_id, e, exc_info=True)
        await _safe_answer(query, 'Не удалось обновить меню', show_alert=True)

    return ACCESS_ASK_USER

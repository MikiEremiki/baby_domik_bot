"""Command permission middleware — enforces can() before handlers run.

Position: group=-55, between user_status (-60) and glob_on_off (-50).

Intercepts:
- Commands: parses /cmd@botname and /cmd args, checks against COMMAND_DICT.
- Callbacks: strips intent_id prefix via remove_intent_id, checks settings sections.

Unknown commands are blocked (fail-closed) for non-root users. On DB error — fail-closed.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes, TypeHandler, ApplicationHandlerStop

from permissions import can, PermissionBackendError
from settings.settings import (
    COMMAND_DICT, SETTINGS_SECTIONS, SETTINGS_PREFIX, SETTINGS_DATABASE_KEY,
    ACCESS_INTENT_ID,
)
from utilities.utl_func import extract_command
from utilities.utl_kbd import remove_intent_id

cmd_perm_logger = logging.getLogger('bot.middleware.command_permission')

# intent_id of the /settings -> База данных section buttons
SETTINGS_DB_INTENT_ID = 'db'
# callback_data of the "Доступ к командам" entry button
ACCESS_ENTRY_CALLBACK = 'access'


def _callback_to_command(callback_data: str) -> str | None:
    """Convert a callback_data to a command key for permission checking.

    Strips intent_id prefix first, then checks against known settings sections
    (returned as `settings:<section>`), the access-management screen
    (`settings:database`) and direct command names.
    """
    intent_id, clean_data = remove_intent_id(callback_data or '')

    # Access-management screen: entry button and all its inner callbacks
    # The entry button ("access") maps only when there is no intent_id prefix,
    # so that foreign intents like "other|access" are not matched.
    if intent_id == ACCESS_INTENT_ID or (intent_id is None and clean_data == ACCESS_ENTRY_CALLBACK):
        return SETTINGS_DATABASE_KEY

    # Check if it's a settings section
    if intent_id in (None, SETTINGS_DB_INTENT_ID):
        section_key = f'{SETTINGS_PREFIX}{clean_data}'
        if section_key in SETTINGS_SECTIONS:
            return section_key

    # Check if callback_data matches a command name in COMMAND_DICT
    for key, entry in COMMAND_DICT.items():
        if clean_data == entry[0]:
            return key

    return None


async def _check_callback(update: Update, context: 'ContextTypes.DEFAULT_TYPE', user_id: int) -> None:
    """Check callback_query permissions. Raises ApplicationHandlerStop on denial."""
    cq = update.callback_query
    cmd_key = _callback_to_command(cq.data)

    if cmd_key is None:
        return  # Not a known permissioned callback

    session = getattr(context, 'session', None)
    try:
        allowed = await can(user_id, cmd_key, session)
    except PermissionBackendError:
        cmd_perm_logger.warning(
            f'User {user_id} callback {cq.data} blocked by DB error')
        await cq.answer('Временная ошибка, попробуйте позже.', show_alert=True)
        raise ApplicationHandlerStop

    if not allowed:
        cmd_perm_logger.info(
            f'User {user_id} denied callback {cq.data}')
        await cq.answer('У вас нет доступа к этому разделу.', show_alert=True)
        raise ApplicationHandlerStop


async def _check_command_message(update: Update, context: 'ContextTypes.DEFAULT_TYPE',
                                  user_id: int, bot_username: str) -> None:
    """Check command message permissions. Raises ApplicationHandlerStop on denial."""
    msg = update.effective_message
    if not msg or not msg.text:
        return

    cmd = extract_command(msg.text, bot_username)
    if cmd is None:
        return  # Not a command, skip

    # Check permission — can() handles unknown commands with fail-closed
    session = getattr(context, 'session', None)
    try:
        allowed = await can(user_id, cmd, session)
    except PermissionBackendError:
        cmd_perm_logger.warning(
            f'User {user_id} command /{cmd} blocked by DB error')
        await msg.reply_text(
            'Временная ошибка, попробуйте позже.',
            message_thread_id=msg.message_thread_id,
        )
        raise ApplicationHandlerStop

    if not allowed:
        cmd_perm_logger.info(
            f'User {user_id} denied command /{cmd}')
        await msg.reply_text(
            'У вас нет доступа к этой команде.',
            message_thread_id=msg.message_thread_id,
        )
        raise ApplicationHandlerStop


def add_command_permission_middleware(application, _config):
    """Register the command permission middleware at group -55."""

    async def check_command_permission(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE',
    ):
        bot_username = context.bot.username
        user = update.effective_user
        if not user or user.is_bot or not update.effective_chat:
            return

        user_id = user.id

        # Callback queries are checked first — on real Telegram updates
        # effective_message for a callback is the bot message with the button,
        # not the user's command. The branches must be mutually exclusive.
        if update.callback_query:
            await _check_callback(update, context, user_id)
            return

        await _check_command_message(update, context, user_id, bot_username)

    application.add_handler(
        TypeHandler(Update, check_command_permission), group=-55
    )

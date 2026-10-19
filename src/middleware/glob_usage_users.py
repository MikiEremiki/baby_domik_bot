import logging

from sulguk import transform_html
from telegram import Update
from telegram.ext import ContextTypes, TypeHandler, ApplicationHandlerStop

from middleware.command_permission import _callback_to_command
from permissions import can_or_false, get_command_entry
from utilities.utl_func import extract_command, is_privileged_update

glob_on_off_logger = logging.getLogger('bot.middleware.glob_on_off')


def add_glob_on_off_middleware(application, config):
    async def check_permissions(
            update: Update,
            context: 'ContextTypes.DEFAULT_TYPE'
    ):
        # Always pass admin group chats
        if update.effective_chat and update.effective_chat.id == config.bot.admin_group:
            return
        if is_privileged_update(update):
            return

        # global_on_off is enabled — no restrictions
        if context.bot_data['global_on_off']:
            return

        # Mode is OFF — check if the user has access via can()
        user_id = update.effective_user.id if update.effective_user else None
        if user_id is None:
            return

        session = getattr(context, 'session', None)

        # Parse the command: callbacks first, then text
        cmd = None
        # Callbacks first — on real Telegram updates effective_message is
        # the bot message with the button, not the user's command.
        if update.callback_query:
            cmd = _callback_to_command(update.callback_query.data)
        elif update.effective_message and update.effective_message.text:
            cmd = extract_command(update.effective_message.text)

        if cmd:
            entry = get_command_entry(cmd)
            if entry is not None and not entry.public:
                # Non-public command: let can() decide (checks root, super_admin, public, grant)
                # DB error treated as "no access" — user sees maintenance message
                allowed = await can_or_false(user_id, cmd, session)
                if allowed:
                    return

        # Send maintenance message and block
        text = (
            'Проводятся технические работы, сроки завершения уточняются.<br>'
            'Приносим свои извинения за возможные неудобства.<br><br>'
            'Вы можете написать свой вопрос мне и я перешлю его '
            'администратору или вы можете связаться с ним '
            'самостоятельно:<br>'
            f'{context.bot_data['admin']['contacts_html']}<br><br>'
            'или через группы:<br>'
            '<ul>'
            '<li><a href="https://t.me/theater_domik">Телеграм</a></li>'
            '<li><a href="https://vk.com/baby_theater_domik">ВКонтакте</a></li>'
            '</ul>'
        )
        res_text = transform_html(text)

        # Send the message without returning, then block
        if update.callback_query:
            await update.callback_query.answer(
                'Проводятся технические работы.', show_alert=True)
        elif update.effective_message:
            try:
                await update.effective_message.reply_text(
                    text=res_text.text,
                    entities=res_text.entities,
                    parse_mode=None,
                )
            except Exception as e:
                glob_on_off_logger.warning(
                    f'Failed to send maintenance message: {e}')

        raise ApplicationHandlerStop

    application.add_handler(TypeHandler(Update, check_permissions), group=-50)

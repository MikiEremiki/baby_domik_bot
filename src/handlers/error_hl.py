import html
import json
import logging
import traceback
from pprint import pformat

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from handlers.sub_hl import write_old_seat_info
from settings.settings import CHAT_ID_MIKIEREMIKI
from utilities.schemas.ticket import BaseTicket
from utilities.utl_func import clean_context, split_message

error_hl_logger = logging.getLogger('bot.error_hl')


async def error_handler(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    error_hl_logger.error("Exception while handling an update:",
                          exc_info=context.error)

    await update.effective_chat.send_message(
        'Произошла не предвиденная ошибка\n'
        'Выполните команду /start и повторите операцию заново')

    clean_context(context)

    tb_list = traceback.format_exception(None, context.error,
                                         context.error.__traceback__)
    tb_string = "".join(tb_list)

    update_str = update.to_dict() if isinstance(update, Update) else str(update)

    message = (
        "An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str,
                                                indent=2,
                                                ensure_ascii=False))}</pre>"
    )
    await context.bot.send_message(
        chat_id=CHAT_ID_MIKIEREMIKI,
        text=message,
        parse_mode=ParseMode.HTML
    )

    message = f"<pre>{html.escape(tb_string)}</pre>\n\n"
    await split_message(context, message)

    message = pformat(context.bot_data)
    error_hl_logger.info(message)
    await split_message(context, message)

    message = pformat(context.user_data)
    error_hl_logger.info(message)
    await split_message(context, message)

    user = context.user_data['user']
    if context.user_data['STATE'] == 'PAID':
        error_hl_logger.info('Отправка чека об оплате не была совершена')
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['common_data']['message_id_buy_info']
        )

        reserve_admin_data = context.user_data['reserve_admin_data']
        payment_id = reserve_admin_data['payment_id']
        payment_data = reserve_admin_data[payment_id]
        chose_ticket = payment_data['chose_ticket']
        event_id = payment_data['event_id']

        await write_old_seat_info(user,
                                  event_id,
                                  chose_ticket)

import html
import json
import logging
import traceback
from pprint import pformat

from requests import HTTPError
from telegram import Update
from telegram.ext import ContextTypes

from utilities.utl_func import (
    clean_context, split_message, write_to_return_seats_for_sale)

error_hl_logger = logging.getLogger('bot.error_hl')


async def error_handler(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    error_hl_logger.error("Exception while handling an update:",
                          exc_info=context.error)

    chat_id = context.config.bot.developer_chat_id
    if isinstance(context.error, HTTPError):
        await context.bot.send_message(
            chat_id=chat_id,
            text=context.error.response.text,
        )
        if context.user_data['STATE'] == 'ORDER':
            await write_to_return_seats_for_sale(context)
    else:
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
            chat_id=chat_id,
            text=message,
        )

        message = f"<pre>{html.escape(tb_string)}</pre>\n\n"
        await split_message(context, message)

        message = pformat(context.bot_data)
        error_hl_logger.info(message)

        message = pformat(context.user_data)
        error_hl_logger.info(message)

        states_for_cancel = [
            'PAID', 'EMAIL', 'FORMA', 'PHONE', 'CHILDREN', 'ORDER']
        if context.user_data['STATE'] in states_for_cancel:
            error_hl_logger.info('Отправка чека об оплате не была совершена')
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['common_data']['message_id_buy_info']
            )

            await write_to_return_seats_for_sale(context)

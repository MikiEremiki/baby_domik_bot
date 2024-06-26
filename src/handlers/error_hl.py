import html
import json
import logging
import traceback
from pprint import pformat

from requests import HTTPError
from telegram import Update
from telegram.ext import ContextTypes

from utilities.utl_db import open_session
from utilities.utl_func import clean_context, split_message
from utilities.utl_ticket import cancel_tickets

error_hl_logger = logging.getLogger('bot.error_hl')


async def error_handler(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    error_hl_logger.error("Exception while handling an update:",
                          exc_info=context.error)

    context.session = await open_session(context.config)

    chat_id = context.config.bot.developer_chat_id
    if isinstance(context.error, HTTPError):
        await context.bot.send_message(
            chat_id=chat_id,
            text=context.error.response.text,
        )
    else:
        await update.effective_chat.send_message(
            'Произошла не предвиденная ошибка\n'
            'Выполните команду /start и повторите операцию заново')


        tb_list = traceback.format_exception(None,
                                             context.error,
                                             context.error.__traceback__)
        tb_string = "".join(tb_list)

        update_str = (
            update.to_dict() if isinstance(update, Update) else str(update)
        )

        message = (
            "An exception was raised while handling an update\n"
            f"<pre>"
            f"update = {html.escape(json.dumps(update_str,
                                               indent=2,
                                               ensure_ascii=False))}"
            f"</pre>"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
        )

        message = f"{html.escape(tb_string)}\n\n"

        await split_message(context, message)

        message = pformat(context.bot_data)
        error_hl_logger.info(message)

        message = pformat(context.user_data)
        error_hl_logger.info(message)

    await cancel_tickets(update, context)

    await clean_context(context)

    await context.session.close()

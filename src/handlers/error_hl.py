import html
import json
import logging
import traceback
from pprint import pformat

from requests import HTTPError
from telegram import Update
from telegram.error import TimedOut, NetworkError, BadRequest
from telegram.ext import ContextTypes, ApplicationHandlerStop

from utilities.utl_db import open_session
from utilities.utl_func import (
    clean_context, clean_context_on_end_handler, split_message,
)
from utilities.utl_ticket import cancel_tickets_db_and_gspread

error_hl_logger = logging.getLogger('bot.error_hl')


async def error_handler(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    error_hl_logger.error(f'UPDATE: {update}')
    error_hl_logger.error("Exception while handling an update:",
                          exc_info=context.error)

    context.session = await open_session(context.config)

    chat_id = context.config.bot.developer_chat_id
    outdated_err_msg = (
        'Query is too old and response timeout expired or query id is invalid')
    del_err_msg = "Message can't be deleted for everyone"
    if isinstance(context.error, HTTPError):
        await context.bot.send_message(
            chat_id=chat_id,
            text=context.error.response.text,
        )
    elif (hasattr(context.error, 'message') and
          (context.error.message == outdated_err_msg)):
        error_hl_logger.error(context.error.message)
        raise ApplicationHandlerStop
    elif (hasattr(context.error, 'message') and
          (context.error.message == del_err_msg)):
        error_hl_logger.error(context.error.message)
        text = 'Пожалуйста, выполните команду /start и повторите операцию заново'
        message_thread_id = update.effective_message.message_thread_id
        try:
            await update.effective_message.reply_text(
                text=text,
                message_thread_id=message_thread_id,
            )
        except BadRequest as e:
            error_hl_logger.error(e)
            await update.effective_chat.send_message(
                text=text,
                message_thread_id=message_thread_id,
            )
    elif (isinstance(context.error, TimedOut) or
          isinstance(context.error, NetworkError) and
          not isinstance(context.error, BadRequest)):
        error_hl_logger.error(context.error.message)
        error_hl_logger.error('Выполнение запроса занимает много времени')
        context.user_data['last_update'] = None
        text = ('Пожалуйста, подождите 3 секунды и повторите последнее '
                'действие, если проблема остается, вызовите /start и '
                'повторите запрос заново.')
        message_thread_id = update.effective_message.message_thread_id
        try:
            await update.effective_message.reply_text(
                text=text,
                message_thread_id=message_thread_id,
            )
        except BadRequest as e:
            error_hl_logger.error(e)
            await update.effective_chat.send_message(
                text=text,
                message_thread_id=message_thread_id,
            )
        raise ApplicationHandlerStop
    else:
        text = ('Произошла не предвиденная ошибка\n'
                'Пожалуйста, пробуйте повторить последнее действие, '
                'или выполните команду /start и повторите операцию заново')
        message_thread_id = update.effective_message.message_thread_id
        try:
            await update.effective_message.reply_text(
                text=text,
                message_thread_id=message_thread_id,
            )
        except BadRequest as e:
            error_hl_logger.error(e)
            await update.effective_chat.send_message(
                text=text,
                message_thread_id=message_thread_id,
            )
        except TimedOut as e:
            error_hl_logger.error(e)

        tb_list = traceback.format_exception(None,
                                             context.error,
                                             context.error.__traceback__)
        tb_string = "".join(tb_list)

        update_str = (
            update.to_dict() if isinstance(update, Update) else str(update)
        )

        message = (
            "An exception was raised while handling an update\n"
            f"update = {html.escape(json.dumps(update_str,
                                               indent=2,
                                               ensure_ascii=False))}"
        )
        try:
            await split_message(context, message)
        except TimedOut as e:
            error_hl_logger.error(e)

        message = f"{html.escape(tb_string)}\n\n"
        try:
            await split_message(context, message)
        except TimedOut as e:
            error_hl_logger.error(e)

    await cancel_tickets_db_and_gspread(update, context)

    await clean_context(context)
    await clean_context_on_end_handler(error_hl_logger, context)

    message = pformat(context.bot_data, compact=True)
    error_hl_logger.info('bot_data')
    error_hl_logger.info(message)

    message = pformat(context.user_data)
    error_hl_logger.info('user_data')
    error_hl_logger.info(message)

    await context.session.close()

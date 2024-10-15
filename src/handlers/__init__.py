import logging

from telegram.ext import ContextTypes

from db import db_postgres
from utilities import clean_context, extract_command


async def init_conv_hl_dialog(update, context: ContextTypes.DEFAULT_TYPE):
    await clean_context(context)
    state = 'START'
    context.user_data['STATE'] = state
    command = extract_command(update.effective_message.text)
    if command:
        context.user_data['command'] = command
    context.user_data.setdefault('common_data', {})

    context.user_data.setdefault('reserve_admin_data', {})

    context.user_data.setdefault('reserve_user_data', {})
    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data.setdefault('back', {})
    reserve_user_data.setdefault('client_data', {})

    return state


async def check_user_db(update, context):
    logger = logging.getLogger(__name__)
    res = await db_postgres.get_user(context.session, update.effective_user.id)
    if not res:
        res = await db_postgres.create_user(
            context.session,
            update.effective_user.id,
            update.effective_chat.id,
            username=update.effective_user.username
        )
        if res:
            logger.info(
                f'Пользователь {res} начал общение с ботом')
    else:
        logger.info('Пользователь уже в есть в базе')

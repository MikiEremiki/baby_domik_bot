import logging

from .sub_hl import write_old_seat_info
from db import db_postgres
import utilities as utl


def init_conv_hl_dialog(update, context):
    utl.clean_context(context)
    state = 'START'
    context.user_data['STATE'] = state
    context.user_data['command'] = utl.extract_command(
        update.effective_message.text)
    context.user_data.setdefault('common_data', {})
    context.user_data.setdefault('reserve_admin_data', {})
    context.user_data['reserve_user_data'] = {}
    context.user_data['reserve_user_data']['back'] = {}
    context.user_data['reserve_user_data']['client_data'] = {}
    context.user_data['reserve_user_data']['choose_event_info'] = {}
    context.user_data['reserve_admin_data']['payment_data'] = {}

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

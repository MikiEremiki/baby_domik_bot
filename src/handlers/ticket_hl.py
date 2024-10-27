import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from db import db_postgres
from handlers.sub_hl import (
    send_info_about_individual_ticket, send_request_email, send_agreement)
from utilities.utl_kbd import remove_intent_id
from utilities.utl_ticket import get_ticket_and_price
from utilities.utl_func import set_back_context, get_back_context

ticket_hl_logger = logging.getLogger('bot.ticket_hl')

async def get_ticket(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.edit_message_reply_markup()

    _, callback_data = remove_intent_id(query.data)
    base_ticket_id = int(callback_data)

    try:
        chose_base_ticket, price = await get_ticket_and_price(context,
                                                              base_ticket_id)
    except AttributeError as e:
        await query.answer()
        ticket_hl_logger.error(e)
        state = 'TIME'
        text, reply_markup, _ = await get_back_context(context, state)
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
        )
        return state

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['chose_price'] = price
    reserve_user_data['chose_base_ticket_id'] = chose_base_ticket.base_ticket_id

    await query.answer()
    if chose_base_ticket.flag_individual:
        await send_info_about_individual_ticket(update, context)
        state = ConversationHandler.END
        context.user_data['STATE'] = state
        return state

    user = await db_postgres.get_user(context.session, update.effective_chat.id)
    if user.agreement_received:
        text, reply_markup = await send_request_email(update, context)
        state = 'EMAIL'
    else:
        text, reply_markup = await send_agreement(update, context)
        state = 'OFFER'

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

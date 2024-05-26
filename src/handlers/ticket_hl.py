from telegram import Update
from telegram.ext import ContextTypes

from handlers.sub_hl import send_info_about_individual_ticket
from utilities.utl_check import check_and_get_agreement
from utilities.utl_ticket import get_ticket_and_price
from utilities.utl_func import set_back_context


async def get_ticket(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    base_ticket_id = int(query.data)

    chose_base_ticket, price = await get_ticket_and_price(context, base_ticket_id)

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['chose_price'] = price
    reserve_user_data['chose_base_ticket_id'] = chose_base_ticket.base_ticket_id

    if chose_base_ticket.flag_individual:
        return await send_info_about_individual_ticket(update, context)

    reply_markup, state, text = await check_and_get_agreement(update, context)

    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

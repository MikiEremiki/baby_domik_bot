from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from db import db_postgres
from handlers.sub_hl import send_request_email
from utilities.utl_func import set_back_context


async def get_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db_postgres.update_user(context.session,
                                  update.effective_chat.id,
                                  agreement_received=date.today())

    await update.effective_chat.delete_message(
        context.user_data['reserve_user_data']['accept_message_id']
    )
    await context.bot.edit_message_reply_markup(
        chat_id=update.effective_chat.id,
        message_id=context.user_data['reserve_user_data']['message_id'],
    )

    text, reply_markup = await send_request_email(update, context)

    state = 'EMAIL'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

from telegram import InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import db_postgres
from utilities import add_btn_back_and_cancel
from utilities.utl_check import check_email


async def check_email_and_update_user(update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=context.user_data['reserve_user_data']['message_id']
    )
    email = update.effective_message.text
    if not check_email(email):
        await retry_get_email(update, context)
    await db_postgres.update_user(
        session=context.session,
        user_id=update.effective_user.id,
        email=email
    )


async def retry_get_email(update, context):
    state = 'EMAIL'
    email = update.effective_message.text
    keyboard = [add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back=state)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.effective_chat.send_message(
        text=f'Вы написали: {email}\n'
             f'Пожалуйста проверьте и введите почту еще раз.',
        reply_markup=reply_markup
    )
    context.user_data['reserve_user_data']['message_id'] = message.message_id
    context.user_data['STATE'] = state
    return state

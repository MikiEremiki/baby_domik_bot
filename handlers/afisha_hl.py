import logging

from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update

from utilities.hlp_func import create_replay_markup_with_number_btn

afisha_hl_logger = logging.getLogger('bot.afisha_hl')


async def load_afisha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    afisha_hl_logger.info(f'Пользователь загружает афишу:'
                          f' {update.message.from_user}')

    state = 'START'
    context.user_data['STATE'] = state
    context.user_data['user'] = update.message.from_user

    reply_markup = create_replay_markup_with_number_btn(12, 6)

    await update.effective_chat.send_message(
        text='Укажите месяц с которым будет связана афиша',
        reply_markup=reply_markup
    )

    state = 1
    context.user_data['STATE'] = state
    return state


async def set_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    month = int(query.data)

    afisha_hl_logger.info(f'Пользователь выбрал месяц: {month}')

    context.user_data['month_afisha'] = month

    await update.effective_chat.send_message('Отправьте картинку')

    state = 2
    context.user_data['STATE'] = state
    return state


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = update.message.photo[0].file_id

    afisha_hl_logger.info(f'Пользователь прислал картинку: {file_id}')

    context.bot_data.setdefault('afisha', {})
    context.bot_data['afisha'].setdefault(
        context.user_data['month_afisha'],
        file_id
    )
    context.user_data.pop('month_afisha')

    await update.effective_chat.send_message(
        text='Афиша успешно загружена, для просмотра афиши выполните команду '
             '/show_afisha (Пока не работает)',
        reply_markup=None
    )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state

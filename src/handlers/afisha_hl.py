import logging

from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton

from utilities.utl_kbd import (
    create_kbd_with_number_btn, adjust_kbd, add_btn_back_and_cancel
)

afisha_hl_logger = logging.getLogger('bot.afisha_hl')


async def load_afisha(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    context.user_data['conv_hl_run'] = True
    afisha_hl_logger.info(f'Пользователь загружает афишу:'
                          f' {update.message.from_user}')

    state = 'START'
    context.user_data['STATE'] = state
    if not context.bot_data.get('afisha', False):
        context.bot_data['afisha'] = {}

    keyboard = create_kbd_with_number_btn(12)
    keyboard = adjust_kbd(keyboard, 6)
    reply_markup = InlineKeyboardMarkup(keyboard +
        [[InlineKeyboardButton(text='Просмотр',
                               callback_data='show_data')]]
    )

    await update.effective_chat.send_message(
        text='Выберите месяц для настройки афиши\n',
        reply_markup=reply_markup
    )

    state = 1
    context.user_data['STATE'] = state
    return state


async def set_month(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    query = update.callback_query

    month = int(query.data)

    afisha_hl_logger.info(f'Пользователь выбрал месяц: {month}')

    context.user_data['month_afisha'] = month

    text = 'Отправьте картинку или нажмите "Пропустить" для удаления афиши'
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(text='Пропустить', callback_data='skip')],
        add_btn_back_and_cancel(
            postfix_for_cancel='afisha', add_back_btn=False)
    ])
    await query.edit_message_text(text, reply_markup=reply_markup)

    state = 2
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def skip(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    query = update.callback_query

    month = context.user_data['month_afisha']

    afisha_hl_logger.info(f'Пользователь удаляет картинку из месяца: {month}')

    try:
        context.bot_data['afisha'].pop(month)
        await query.edit_message_text(text='Афиша успешно сброшена')
    except KeyError:
        await query.edit_message_text(text='Афиша для данного месяца не задана')

    context.user_data.pop('month_afisha')

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    await query.answer()
    context.user_data['conv_hl_run'] = False
    return state


async def show_data(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    query = update.callback_query

    await update.effective_chat.send_message(
        text='Технические данные по афишам:\n' +
             context.bot_data['afisha'].__str__(),
    )

    state = 1
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def check(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    month = context.user_data['month_afisha']
    file_id = update.message.photo[0].file_id

    afisha_hl_logger.info(f'Пользователь прислал картинку: {file_id}')

    context.bot_data['afisha'][month] = file_id

    context.user_data.pop('month_afisha')

    await update.effective_chat.send_message(
        text='Афиша успешно загружена, для просмотра афиши выполните команду '
             '/show_afisha (Пока не работает)',
        reply_markup=None
    )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    context.user_data['conv_hl_run'] = False
    return state

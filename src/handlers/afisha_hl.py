import logging
import os
from datetime import date

from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest

from db import db_postgres
from utilities.utl_kbd import add_btn_back_and_cancel

from pathlib import Path

afisha_hl_logger = logging.getLogger('bot.afisha_hl')

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_AFISHA_DIR = BASE_DIR / 'static' / 'img' / 'afisha'
os.makedirs(STATIC_AFISHA_DIR, exist_ok=True)


async def load_afisha(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    afisha_hl_logger.info(f'Пользователь загружает афишу: {update.effective_user.full_name}')

    state = 'START'
    context.user_data['STATE'] = state

    year = date.today().year
    afishas = await db_postgres.get_afishas(context.session, year)
    existing_months = [a.month for a in afishas]

    keyboard = []
    row = []
    for m in range(1, 13):
        text = f"{m} 🖼" if m in existing_months else str(m)
        row.append(InlineKeyboardButton(text=text, callback_data=str(m)))
        if len(row) == 6:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.effective_chat.send_message(
        text='Выберите месяц для настройки афиши.\n🖼 - афиша уже загружена',
        reply_markup=reply_markup
    )

    state = 1
    context.user_data['STATE'] = state
    return state


async def set_month(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    month = int(query.data)
    year = date.today().year

    afisha_hl_logger.info(f'Пользователь выбрал месяц: {month}')
    context.user_data['month_afisha'] = month

    afisha = await db_postgres.get_afisha(context.session, month, year)

    if afisha:
        text = f'Афиша для {month} месяца {year} года уже существует. Выберите действие:'
        keyboard = [
            [InlineKeyboardButton(text='Посмотреть', callback_data='view_afisha')],
            [InlineKeyboardButton(text='Обновить', callback_data='update_afisha')],
            [InlineKeyboardButton(text='Удалить', callback_data='delete_afisha')],
            add_btn_back_and_cancel(postfix_for_cancel='afisha', add_back_btn=False)
        ]
        state = 2
    else:
        text = f'Афиши для {month} месяца {year} года нет. Отправьте картинку для загрузки афиши:'
        keyboard = [
            add_btn_back_and_cancel(postfix_for_cancel='afisha', add_back_btn=False)
        ]
        state = 3

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def view_afisha(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    month = context.user_data['month_afisha']
    year = date.today().year

    afisha = await db_postgres.get_afisha(context.session, month, year)
    if afisha:
        try:
            await query.delete_message()
        except BadRequest:
            pass
        
        keyboard = [
            [InlineKeyboardButton(text='Обновить', callback_data='update_afisha')],
            [InlineKeyboardButton(text='Удалить', callback_data='delete_afisha')],
            add_btn_back_and_cancel(postfix_for_cancel='afisha', add_back_btn=False)
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.effective_chat.send_photo(
            photo=afisha.file_id,
            caption=f'Афиша для {month} месяца {year} года. Выберите действие:',
            reply_markup=reply_markup
        )
    await query.answer()
    return context.user_data['STATE']


async def request_update_afisha(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    text = 'Отправьте новую картинку для загрузки афиши:'
    keyboard = [
        add_btn_back_and_cancel(postfix_for_cancel='afisha', add_back_btn=False)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest:
        try:
            await query.delete_message()
        except BadRequest:
            pass
        await update.effective_chat.send_message(text=text, reply_markup=reply_markup)

    state = 3
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def delete_afisha_action(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    month = context.user_data['month_afisha']
    year = date.today().year

    afisha = await db_postgres.get_afisha(context.session, month, year)
    if afisha:
        file_name = f'{year}_{month:02d}.jpg'
        file_path = STATIC_AFISHA_DIR / file_name
        if file_path.exists():
            os.remove(file_path)
        await db_postgres.delete_afisha(context.session, month, year)
        text_message = f'Афиша на {month} месяц удалена.'
    else:
        text_message = 'Афиша не найдена.'

    try:
        await query.edit_message_text(text=text_message)
    except BadRequest:
        try:
            await query.delete_message()
        except BadRequest:
            pass
        await update.effective_chat.send_message(text=text_message)

    context.user_data.pop('month_afisha', None)
    
    state = ConversationHandler.END
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def upload_afisha(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    month = context.user_data['month_afisha']
    year = date.today().year

    # Get largest photo
    photo = update.effective_message.photo[-1]
    file_id = photo.file_id

    afisha_hl_logger.info(f'Пользователь прислал картинку: {file_id}')

    # Download file
    new_file = await context.bot.get_file(file_id)
    file_name = f'{year}_{month:02d}.jpg'
    file_path = STATIC_AFISHA_DIR / file_name
    await new_file.download_to_drive(custom_path=str(file_path))

    stored_path = f'static/img/afisha/{file_name}'

    await db_postgres.create_or_update_afisha(
        context.session, month=month, year=year, file_id=file_id, file_path=stored_path
    )

    context.user_data.pop('month_afisha', None)

    await update.effective_chat.send_message(
        text=f'Афиша на {month}.{year} успешно загружена и сохранена.',
        reply_markup=None
    )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state



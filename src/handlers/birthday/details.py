import logging

from sulguk import transform_html

from telegram.ext import ContextTypes
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from db import db_postgres
from handlers.common_hl import validate_phone_or_request
from utilities.schemas import birthday_data
from utilities.utl_func import (
    set_back_context, del_keyboard_messages, append_message_ids_back_context,
    get_full_name_event,
)
from utilities.utl_kbd import (
    add_btn_back_and_cancel
)

birthday_hl_logger = logging.getLogger('bot.birthday_hl')

async def get_name(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    name = update.effective_message.text
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    await del_keyboard_messages(update, context)
    del_message_ids = []

    text = f'<b>Ваше имя для связи:</b> {name}'
    message = await update.effective_chat.send_message(text)
    await append_message_ids_back_context(
        context, [message.message_id])

    text = 'Напишите контактный телефон для связи с вами'
    keyboard = [add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back=context.user_data['STATE']
    )]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )
    del_message_ids.append(message.message_id)

    common_data = context.user_data['common_data']
    common_data['del_keyboard_message_ids'].append(message.message_id)

    context.user_data['birthday_user_data']['name'] = name

    state = 'PHONE'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    return state


async def get_phone(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    phone = update.effective_message.text
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    context.user_data['common_data']['del_keyboard_message_ids'].append(
        update.effective_message.message_id)
    await del_keyboard_messages(update, context)
    del_message_ids = []

    phone, message = await validate_phone_or_request(update, context, phone)
    if phone is None:
        await append_message_ids_back_context(
            context, [message.message_id])
        return 'PHONE'

    text = f'<b>Телефон для связи:</b> {phone}'
    message = await update.effective_chat.send_message(text)
    await append_message_ids_back_context(
        context, [message.message_id])

    text = 'Напишите прочую дополнительную информацию или нажмите Далее'
    keyboard = [
        [InlineKeyboardButton('Далее', callback_data='bd|Next')],
        add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back=context.user_data['STATE']
        )
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )
    del_message_ids.append(message.message_id)

    common_data = context.user_data['common_data']
    common_data['del_keyboard_message_ids'].append(message.message_id)

    context.user_data['birthday_user_data']['phone'] = phone

    state = 'NOTE'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    return state


async def get_note(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    if query:
        await query.answer()
    else:
        note = update.effective_message.text
        text = f'<b>Прочая информация:</b> {note}'
        message = await update.effective_chat.send_message(text)
        await append_message_ids_back_context(
            context, [message.message_id])

        context.user_data['birthday_user_data']['note'] = note
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    await del_keyboard_messages(update, context)
    del_message_ids = []

    text_header = '<b>Заявка:</b><br>'
    text = ''
    for key, item in context.user_data['birthday_user_data'].items():
        match key:
            case 'place':
                item = 'На выезде' if item else 'В «Домике»'
            case 'theater_event_id':
                theater_event = await db_postgres.get_theater_event(
                    context.session, item)
                item = get_full_name_event(theater_event)
            case 'custom_made_format_id':
                custom_made_format = await db_postgres.get_custom_made_format(
                    context.session, item)
                item = (f'{custom_made_format.name}<br>'
                        f'<i>Стоимость:</i> {custom_made_format.price} руб')
            case 'phone':
                item = f'+7{item}'
        try:
            text += f'<br><i>{birthday_data[key]}:</i> {item}'
        except KeyError as e:
            birthday_hl_logger.error(e)

    text = text_header + text
    res = transform_html(text)
    message_1 = await update.effective_chat.send_message(
        text=res.text, entities=res.entities, parse_mode=None
    )
    await append_message_ids_back_context(
        context, [message_1.message_id])
    context.user_data['common_data']['text_for_notification_massage'] = text

    text = ('Проверьте и нажмите подтвердить\n'
             'или вернитесь и исправьте необходимые данные')
    keyboard = [
        [InlineKeyboardButton('Подтвердить', callback_data='confirm')],
        add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back=context.user_data['STATE'])
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_2 = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
    )
    del_message_ids.append(message_2.message_id)

    common_data = context.user_data['common_data']
    common_data['del_keyboard_message_ids'].append(message_2.message_id)
    common_data['message_id_for_reply'] = message_1.message_id

    state = 'CONFIRM'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    return state

import logging

from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    TypeHandler,
)
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction

from db import db_postgres
from handlers import init_conv_hl_dialog, check_user_db
from handlers.sub_hl import request_phone_number, send_message_to_admin
from api.googlesheets import write_client_cme
from settings.settings import (
    DICT_OF_EMOJI_FOR_BUTTON,
    ADMIN_GROUP,
    ADDRESS_OFFICE,
    COMMAND_DICT,
)
from utilities.schemas.context import birthday_data
from utilities.utl_func import (
    extract_phone_number_from_text,
    check_phone_number,
    create_approve_and_reject_replay,
    send_and_del_message_to_remove_kb, set_back_context, del_keyboard_messages, append_message_ids_back_context,
    get_full_name_event,
)
from utilities.utl_kbd import (
    create_kbd_with_number_btn, create_replay_markup, remove_intent_id,
    add_btn_back_and_cancel
)

birthday_hl_logger = logging.getLogger('bot.birthday_hl')


async def choice_place(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю выбор - где провести день рождения.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state PLACE
    """
    await init_conv_hl_dialog(update, context)
    await check_user_db(update, context)

    birthday_hl_logger.info(f'Пользователь начал бронирование ДР:'
                            f' {update.message.from_user}')

    message = await send_and_del_message_to_remove_kb(update)
    await update.effective_chat.send_action(ChatAction.TYPING)

    command = context.user_data['command']
    postfix_for_cancel = command
    context.user_data['postfix_for_cancel'] = postfix_for_cancel

    one_option = f'{DICT_OF_EMOJI_FOR_BUTTON[1]} В «Домике»'
    two_option = f'{DICT_OF_EMOJI_FOR_BUTTON[2]} На «Выезде»'

    # Отправка сообщения пользователю
    text = (f'<b>Выберите место проведения Дня рождения</b>\n\n'
            f'{one_option}\n'
            f'<i>В театре, {ADDRESS_OFFICE}</i>\n\n'
            f'{two_option}\n'
            f'<i>Ваше место (дом, квартира или другая площадка)</i>')
    # Определение кнопок для inline клавиатуры
    keyboard = [
        [InlineKeyboardButton(one_option, callback_data=0)],
        [InlineKeyboardButton(two_option, callback_data=1)],
        add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            add_back_btn=False
        )
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=message.message_id
    )
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
    )

    state = 'PLACE'
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    del_message_ids = []

    one_option = f'{DICT_OF_EMOJI_FOR_BUTTON[1]} В «Домике»'
    text = f'<b>Вы выбрали</b>\n\n'
    text += f'{one_option}\n'
    text += f'<i>День рождения в {ADDRESS_OFFICE}</i>'
    message = await query.edit_message_text(text)
    await append_message_ids_back_context(
        context, [message.message_id])

    place = query.data

    text = 'Напишите желаемую дату проведения праздника'
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

    context.user_data['birthday_user_data']['place'] = int(place)
    context.user_data['birthday_user_data']['address'] = ADDRESS_OFFICE

    state = 'DATE'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    del_message_ids = []

    two_option = f'{DICT_OF_EMOJI_FOR_BUTTON[2]} На «Выезде»'
    text = f'<b>Вы выбрали</b>\n\n'
    text += f'{two_option}\n'
    text += '<i>День рождения в предложенном вами месте\n\n</i>'
    message = await query.edit_message_text(text)
    await append_message_ids_back_context(
        context, [message.message_id])

    place = query.data

    text = 'Напишите адрес проведения дня рождения'
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

    context.user_data['birthday_user_data']['place'] = int(place)

    state = 'ADDRESS'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.effective_message.text
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    await del_keyboard_messages(update, context)
    del_message_ids = []

    text = f'<b>Адрес:</b> {address}'
    message = await update.effective_chat.send_message(text)
    await append_message_ids_back_context(
        context, [message.message_id])

    text = 'Напишите желаемую дату проведения праздника'
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

    context.user_data['birthday_user_data']['address'] = address

    state = 'DATE'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state

    return state


async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = update.effective_message.text
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    await del_keyboard_messages(update, context)
    del_message_ids = []

    text = f'<b>Дата:</b> {date}'
    message = await update.effective_chat.send_message(text)
    await append_message_ids_back_context(
        context, [message.message_id])

    text = f'Напишите желаемое время начала'
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

    context.user_data['birthday_user_data']['date'] = date

    state = 'TIME'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    return state


async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_action(ChatAction.TYPING)
    time = update.effective_message.text
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    await del_keyboard_messages(update, context)
    del_message_ids = []

    theater_events = await db_postgres.get_theater_events_on_cme(
        context.session)

    text = f'<b>Время:</b> {time}'
    message = await update.effective_chat.send_message(text)
    await append_message_ids_back_context(
        context, [message.message_id])

    keyboard = []
    text = (
        f'<b>Выберите мероприятие</b>\n'
        f'{context.bot_data['texts']['text_legend']}'
    )
    for i, theater_event in enumerate(theater_events):
        full_name = get_full_name_event(theater_event.name,
                                        theater_event.flag_premier,
                                        theater_event.min_age_child,
                                        theater_event.max_age_child,
                                        theater_event.duration)
        text += f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]} '
        text += f'{full_name}\n'
        keyboard.append(InlineKeyboardButton(
            text=f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]}',
            callback_data=theater_event.id
        ))
    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back=context.user_data['STATE'],
        size_row=4
    )

    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
    )
    del_message_ids.append(message.message_id)

    common_data = context.user_data['common_data']
    common_data['del_keyboard_message_ids'].append(message.message_id)

    context.user_data['birthday_user_data']['time'] = time

    state = 'CHOOSE'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    return state


async def get_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    del_message_ids = []
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])

    _, callback_data = remove_intent_id(query.data)
    theater_event_id = int(callback_data)
    theater_event = await db_postgres.get_theater_event(context.session,
                                                        theater_event_id)
    full_name = get_full_name_event(theater_event.name,
                                    theater_event.flag_premier,
                                    theater_event.min_age_child,
                                    theater_event.max_age_child,
                                    theater_event.duration)
    await query.edit_message_text(
        f'<b>Вы выбрали мероприятие:</b>\n{full_name}')

    keyboard = []
    for i in range(2, 7):  # Фиксированно можно выбрать только от 2 до 6 лет
        keyboard.append(InlineKeyboardButton(str(i), callback_data=str(i)))

    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back=context.user_data['STATE'],
    )
    text = 'Выберите сколько исполняется лет имениннику?'
    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )
    del_message_ids.append(message.message_id)

    common_data = context.user_data['common_data']
    common_data['del_keyboard_message_ids'].append(message.message_id)

    context.user_data['birthday_user_data'][
        'theater_event_id'] = theater_event_id

    state = 'AGE'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    del_message_ids = []

    _, callback_data = remove_intent_id(query.data)
    age = callback_data
    await query.edit_message_text(f'<b>Исполнится лет имениннику:</b> {age}')

    custom_made_formats = await db_postgres.get_all_custom_made_format(
        context.session)
    birthday_place = context.user_data['birthday_user_data']['place']
    custom_made_formats = [item for item in custom_made_formats
                           if item.flag_outside == birthday_place]

    text = '<b>Выберите формат проведения Дня рождения</b>\n\n'
    keyboard = []
    for i, item in enumerate(custom_made_formats):
        text += (
            f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]} {item.name}\n'
            f' {item.price} руб\n\n'
        )
        keyboard.append(InlineKeyboardButton(
            f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]}',
            callback_data=item.id
        ))
    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back=context.user_data['STATE'],
    )
    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
    )
    del_message_ids.append(message.message_id)

    common_data = context.user_data['common_data']
    common_data['del_keyboard_message_ids'].append(message.message_id)

    context.user_data['birthday_user_data']['age'] = int(age)

    state = 'FORMAT_BD'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def get_format_bd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    del_message_ids = []

    _, callback_data = remove_intent_id(query.data)
    custom_made_format_id = int(callback_data)
    custom_made_format = await db_postgres.get_custom_made_format(
        context.session, custom_made_format_id)

    text = '<b>Выбранный формат проведения Дня рождения:</b>\n'
    text += f'{custom_made_format.name}\n {custom_made_format.price} руб'
    await query.edit_message_text(text)

    if custom_made_format.flag_outside:
        max_qty_child = 15
    else:
        max_qty_child = 10
    text = ('Выберите сколько будет гостей-детей\n\n'
            f'Праздник рассчитан до {max_qty_child} детей.')
    keyboard = create_kbd_with_number_btn(max_qty_child)
    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back=context.user_data['STATE'],
        size_row=5
    )
    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )
    del_message_ids.append(message.message_id)

    common_data = context.user_data['common_data']
    common_data['del_keyboard_message_ids'].append(message.message_id)

    context.user_data['birthday_user_data']['custom_made_format_id'] = int(
        custom_made_format_id)

    state = 'QTY_CHILD'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def get_qty_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    del_message_ids = []

    _, callback_data = remove_intent_id(query.data)
    qty_child = callback_data
    text = f'<b>Выбранное кол-во детей:</b> {qty_child}'
    await query.edit_message_text(text)

    text = ('Выберите сколько будет гостей-взрослых\n\n'
            'Праздник рассчитан до 10 взрослых.')
    keyboard = create_kbd_with_number_btn(10)
    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back=context.user_data['STATE'],
        size_row=5
    )
    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )
    del_message_ids.append(message.message_id)

    common_data = context.user_data['common_data']
    common_data['del_keyboard_message_ids'].append(message.message_id)

    context.user_data['birthday_user_data']['qty_child'] = int(qty_child)

    state = 'QTY_ADULT'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def get_qty_adult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    del_message_ids = []

    _, callback_data = remove_intent_id(query.data)
    qty_adult = callback_data
    text = f'<b>Выбранное кол-во взрослых:</b> {qty_adult}'
    await query.edit_message_text(text)

    text = 'Напишите как зовут именинника'
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

    context.user_data['birthday_user_data']['qty_adult'] = int(qty_adult)

    state = 'NAME_CHILD'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def get_name_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name_child = update.effective_message.text
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    await del_keyboard_messages(update, context)
    del_message_ids = []

    text = f'<b>Имя именинника:</b> {name_child}'
    message = await update.effective_chat.send_message(text)
    await append_message_ids_back_context(
        context, [message.message_id])

    text = 'Напишите как вас зовут'
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

    context.user_data['birthday_user_data']['name_child'] = name_child

    state = 'NAME'
    await set_back_context(context, state, text, reply_markup, del_message_ids)
    context.user_data['STATE'] = state
    return state


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.effective_message.text
    await append_message_ids_back_context(
        context, [update.effective_message.message_id])
    context.user_data['common_data']['del_keyboard_message_ids'].append(
        update.effective_message.message_id)
    await del_keyboard_messages(update, context)
    del_message_ids = []

    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        message = await request_phone_number(update, context)
        await append_message_ids_back_context(
            context, [message.message_id])
        return 'PHONE'

    text = f'<b>Телефон для связи:</b> {phone}'
    message = await update.effective_chat.send_message(text)
    await append_message_ids_back_context(
        context, [message.message_id])

    text = 'Напишите прочую дополнительную информацию или нажмите Далее'
    keyboard = [
        [InlineKeyboardButton('Далее', callback_data='Next')],
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


async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
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

    text_header = '<b>Заявка:</b>\n'
    text = ''
    for key, item in context.user_data['birthday_user_data'].items():
        match key:
            case 'place':
                item = 'На выезде' if item else 'В «Домике»'
            case 'theater_event_id':
                theater_event = await db_postgres.get_theater_event(
                    context.session, item)
                item = get_full_name_event(theater_event.name,
                                           theater_event.flag_premier,
                                           theater_event.min_age_child,
                                           theater_event.max_age_child,
                                           theater_event.duration)
            case 'custom_made_format_id':
                custom_made_format = await db_postgres.get_custom_made_format(
                    context.session, item)
                item = (f'{custom_made_format.name}\n'
                        f'<i>Стоимость:</i> {custom_made_format.price} руб')
            case 'phone':
                item = '+7' + item
        try:
            text += f'\n<i>{birthday_data[key]}:</i> {item}'
        except KeyError as e:
            birthday_hl_logger.error(e)

    if query:
        await query.answer()
    message_1 = await update.effective_chat.send_message(
        text=text_header + text,
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


async def get_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.delete_message()
    await del_keyboard_messages(update, context)
    user_id = update.effective_user.id

    context.user_data['birthday_user_data']['user_id'] = user_id
    custom_made_event_data = context.user_data['birthday_user_data']
    custom_made_event = await db_postgres.create_custom_made_event(
        context.session,
        **custom_made_event_data
    )

    common_data = context.user_data['common_data']
    message_id_for_reply = common_data['message_id_for_reply']

    text = (f'\n\nВаша заявка: {custom_made_event.id}\n\n'
            f'Заявка находится на рассмотрении.\n'
            'После вам придет подтверждение '
            'или администратор свяжется с вами для уточнения деталей.')
    await update.effective_chat.send_message(
        text, reply_to_message_id=message_id_for_reply)

    reply_markup = create_approve_and_reject_replay(
        'birthday-1',
        f'{user_id} {message_id_for_reply} {custom_made_event.id}'
    )

    user = context.user_data['user']
    text = ('#День_рождения\n'
            f'Запрос пользователя @{user.username} {user.full_name}\n')
    text += f'Номер заявки: {custom_made_event.id}\n\n'
    text += context.user_data['common_data'][
        'text_for_notification_massage']
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Выездные мероприятия', None))
    message = await context.bot.send_message(
        text=text,
        chat_id=ADMIN_GROUP,
        reply_markup=reply_markup,
        message_thread_id=thread_id
    )

    context.user_data['common_data'][
        'message_id_for_admin'] = message.message_id
    context.user_data['birthday_user_data'][
            'custom_made_event_id'] = custom_made_event.id

    sheet_id_cme = context.config.sheets.sheet_id_cme
    write_client_cme(sheet_id_cme, custom_made_event)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    await query.answer()
    context.user_data['conv_hl_run'] = False
    return state


async def paid_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['conv_hl_run'] = True
    state = 'START'
    context.user_data['STATE'] = state

    keyboard = []
    button_cancel = InlineKeyboardButton(
        "Отменить",
        callback_data=f'Отменить-{context.user_data['postfix_for_cancel']}'
    )
    keyboard.append([button_cancel])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = ('    Внесите предоплату 5000 руб\n\n'
            'Оплатить можно:\n'
            ' - Переводом на карту Сбербанка по номеру телефона'
            '+79159383529 Татьяна Александровна Б.\n\n'
            'ВАЖНО! Прислать сюда электронный чек об оплате (или скриншот)\n'
            'Пожалуйста внесите оплату в течении 30 минут или нажмите '
            'отмена и повторите в другое удобное для вас время\n\n'
            '__________\n'
            'В случае переноса или отмены свяжитесь с Администратором:\n'
            f'{context.bot_data['admin']['contacts']}')

    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['common_data']['message_id_buy_info'] = message.message_id

    state = 'PAID'
    context.user_data['STATE'] = state
    return state


async def forward_photo_or_file(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Пересылает картинку или файл.
    """
    user = context.user_data['user']
    common_data = context.user_data['common_data']
    message_id = common_data['message_id_buy_info']
    chat_id = update.effective_chat.id

    # Убираем у старого сообщения кнопку отмены
    await context.bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=message_id
    )

    try:
        message_id_for_reply = common_data['message_id_for_reply']
        cme_id = context.user_data['birthday_user_data']['custom_made_event_id']
        text = (f'Предоплата по заявке {cme_id} принята\n'
                f'В ближайшее время вам так же поступит подтверждение о '
                f'забронированном мероприятии')
        await update.effective_chat.send_message(
            text=text,
            reply_to_message_id=message_id_for_reply
        )
        await update.effective_chat.pin_message(message_id_for_reply)

        text = f'Квитанция покупателя @{user.username} {user.full_name}\n'
        message_id_for_admin = context.user_data['common_data'][
            'message_id_for_admin']
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Выездные мероприятия', None))
        await send_message_to_admin(ADMIN_GROUP,
                                    text,
                                    message_id_for_admin,
                                    context,
                                    thread_id)

        await update.effective_message.forward(
            chat_id=ADMIN_GROUP,
            message_thread_id=thread_id
        )

        reply_markup = create_approve_and_reject_replay(
            'birthday-2',
            f'{update.effective_user.id} {message_id} {cme_id}'
        )

        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=f'Пользователь @{user.username} {user.full_name}\n'
                 f'Запросил подтверждение брони на сумму 5000 руб\n',
            reply_markup=reply_markup,
            message_thread_id=thread_id
        )

    except KeyError as err:
        birthday_hl_logger.error(err)

        await update.effective_chat.send_message(
            'Сначала необходимо оформить запрос\n'
            f'Это можно сделать по команде /{COMMAND_DICT['BD_ORDER'][0]}'
        )
        birthday_hl_logger.error(
            f'Пользователь {user}: '
            'Не оформил заявку, '
            f'а сразу использовал команду /{COMMAND_DICT['BD_PAID'][0]}'
        )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    context.user_data['conv_hl_run'] = False
    return state


async def conversation_timeout(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Informs the user that the operation has timed out,
    calls :meth:`remove_reply_markup` and ends the conversation.
    :return:
        int: :attr:`telegram.ext.ConversationHandler.END`.
    """
    user = context.user_data['user']
    if context.user_data['STATE'] == 'PAID':
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, бронь отменена, пожалуйста выполните '
            'новый запрос'
        )
    else:
        # TODO Прописать дополнительную обработку states, для этапов опроса
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос'
        )

    birthday_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'AFK уже 30 мин'
        ]
    ))
    birthday_hl_logger.info(f'Для пользователя {user}')
    birthday_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')
    context.user_data['common_data'].clear()
    context.user_data['birthday_user_data'].clear()
    context.user_data['conv_hl_run'] = False
    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)

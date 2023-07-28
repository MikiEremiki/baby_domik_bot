import logging

from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    TypeHandler
)
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from handlers.sub_hl import (
    request_phone_number,
    send_and_del_message_to_remove_kb
)

from utilities.context import birthday_data
from utilities.log_func import join_for_log_info
from utilities.googlesheets import write_client_bd
from utilities.settings import (
    DICT_OF_EMOJI_FOR_BUTTON,
    CHAT_ID_MIKIEREMIKI,
    ADDRESS_OFFICE,
    COMMAND_DICT
)
from utilities.utl_func import (
    extract_phone_number_from_text,
    send_message_to_admin,
    load_list_show
)
from utilities.hlp_func import (
    check_phone_number,
    create_approve_and_reject_replay,
    create_replay_markup_for_list_of_shows,
    create_replay_markup_with_number_btn
)

birthday_hl_logger = logging.getLogger('bot.birthday_hl')
ADMIN_GROUP = CHAT_ID_GROUP_ADMIN_1


async def choice_place(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю выбор - где провести день рождения.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state PLACE
    """
    birthday_hl_logger.info(f'Пользователь начал бронирование ДР:'
                            f' {update.message.from_user}')

    message = await send_and_del_message_to_remove_kb(update)

    state = 'START'
    context.user_data['STATE'] = state
    context.user_data['user'] = update.message.from_user

    one_option = f'{DICT_OF_EMOJI_FOR_BUTTON[1]} В «Домике»'
    two_option = f'{DICT_OF_EMOJI_FOR_BUTTON[2]} На выезде'

    # Отправка сообщения пользователю
    text = 'Выберите место проведения Дня рождения\n\n' \
           f'{one_option}\nВ театре, {ADDRESS_OFFICE}\n\n' \
           f'{two_option}\nВаше место (дом, квартира или другая площадка)'
    # Определение кнопок для inline клавиатуры
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(one_option, callback_data=1)],
        [InlineKeyboardButton(two_option, callback_data=2)],
    ])

    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=message.message_id
    )
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['birthday_data'] = {}

    state = 'PLACE'
    context.user_data['STATE'] = state
    return state


async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    one_option = f'{DICT_OF_EMOJI_FOR_BUTTON[1]} В Домике'
    text = f'Вы выбрали\n\n{one_option}\nДень рождения в {ADDRESS_OFFICE}'
    await query.edit_message_text(text)

    place = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'Домик', place))

    await update.effective_chat.send_message(
        text='Напишите желаемую дату проведения праздника',
    )

    context.user_data['birthday_data']['place'] = int(place)
    context.user_data['birthday_data']['address'] = ADDRESS_OFFICE

    state = 'DATE'
    context.user_data['STATE'] = state
    return state


async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    two_option = f'{DICT_OF_EMOJI_FOR_BUTTON[2]} На выезде'
    text = f'Вы выбрали\n\n{two_option}\nДень рождения в предложенном вами месте\n\n'
    await query.edit_message_text(text)

    place = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'Выезд', place))

    await update.effective_chat.send_message(
        text='Напишите адрес проведения дня рождения',
    )

    context.user_data['birthday_data']['place'] = int(place)

    state = 'ADDRESS'
    context.user_data['STATE'] = state
    return state


async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.effective_message.text

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'адрес', address))

    await update.effective_chat.send_message(
        text='Напишите желаемую дату проведения праздника',
    )

    context.user_data['birthday_data']['address'] = address

    state = 'DATE'
    context.user_data['STATE'] = state

    return state


async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = update.effective_message.text

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'дату', date))

    await update.effective_chat.send_message(
        text='Напишите желаемое время начала'
    )

    context.user_data['birthday_data']['date'] = date

    state = 'TIME'
    context.user_data['STATE'] = state
    return state


async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time = update.effective_message.text

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'время', time))

    dict_of_shows: dict = load_list_show()

    dict_of_shows_for_bd: dict = dict_of_shows.copy()
    for key, item in dict_of_shows.items():
        if not item['birthday']['flag']:
            dict_of_shows_for_bd.pop(key)

    # Отправка сообщения пользователю
    text = 'Выберите спектакль\n'
    for key, item in dict_of_shows.items():
        if item['birthday']['flag']:
            text += f'{DICT_OF_EMOJI_FOR_BUTTON[key]} {item["full_name_of_show"]}\n'

    reply_markup = create_replay_markup_for_list_of_shows(
        dict_of_shows, 3, 2, False)

    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['birthday_data']['time'] = time
    context.user_data['dict_of_shows'] = dict_of_shows

    state = 'CHOOSE'
    context.user_data['STATE'] = state
    return state


async def get_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    id_show = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'Спектакль', id_show))

    keyboard_btn = []
    for i in range(2, 7):  # Фиксированно можно выбрать только от 2 до 6 лет
        keyboard_btn.append(InlineKeyboardButton(i, callback_data=i))

    reply_markup = InlineKeyboardMarkup([
        keyboard_btn,
    ])
    await query.edit_message_text(
        text='Выберите сколько исполняется лет имениннику?',
        reply_markup=reply_markup
    )

    context.user_data['birthday_data']['id_show'] = int(id_show)

    state = 'AGE'
    context.user_data['STATE'] = state
    return state


async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    age = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'возраст', age))

    text = 'Выберите сколько будет гостей-детей?\n\n' \
           'Праздник рассчитан от 1 до 10 детей.'
    reply_markup = create_replay_markup_with_number_btn(10, 5)
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['birthday_data']['age'] = int(age)

    state = 'QTY_CHILD'
    context.user_data['STATE'] = state
    return state


async def get_qty_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    qty_child = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'кол-во детей', qty_child))

    text = 'Выберите сколько будет гостей-взрослых\n\nНе более 10 взрослых.'
    reply_markup = create_replay_markup_with_number_btn(10, 5)
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['birthday_data']['qty_child'] = int(qty_child)

    state = 'QTY_ADULT'
    context.user_data['STATE'] = state
    return state


async def get_qty_adult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    qty_adult = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'кол-во взрослых', qty_adult))

    one_option = f'{DICT_OF_EMOJI_FOR_BUTTON[1]}'
    two_option = f'{DICT_OF_EMOJI_FOR_BUTTON[2]}'

    text = 'Выберите формат проведения Дня рождения\n\n' \
           f'{one_option} Спектакль (40 минут) + аренда комнаты под чаепитие (1 час)\n ' \
           f'15000 руб\n\n' \
           f'{two_option} Спектакль (40 минут) + аренда комнаты под чаепитие + серебряная дискотека (1 час)\n ' \
           f'25000 руб'
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(one_option, callback_data=1),
         InlineKeyboardButton(two_option, callback_data=2)],
    ])

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['birthday_data']['qty_adult'] = int(qty_adult)

    state = 'FORMAT_BD'
    context.user_data['STATE'] = state
    return state


async def get_format_bd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    format_bd = query.data

    one_option = f'{DICT_OF_EMOJI_FOR_BUTTON[1]}'
    two_option = f'{DICT_OF_EMOJI_FOR_BUTTON[2]}'

    text = 'Вы выбрали формат проведения Дня рождения\n\n'
    match format_bd:
        case '1':
            text += f'{one_option} Спектакль + чаепитие\n 15000 руб'
        case '2':
            text += f'{two_option} Спектакль + чаепитие + дискотека\n 20000 руб'
    await query.edit_message_text(text)

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'формат праздника', format_bd))

    await update.effective_chat.send_message(
        text='Напишите как зовут именинника',
    )

    context.user_data['birthday_data']['format_bd'] = int(format_bd)

    state = 'NAME_CHILD'
    context.user_data['STATE'] = state
    return state


async def get_name_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name_child = update.effective_message.text

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'имя ребенка', name_child))

    await update.effective_chat.send_message(
        text='Напишите как вас зовут',
    )

    context.user_data['birthday_data']['name_child'] = name_child

    state = 'NAME'
    context.user_data['STATE'] = state
    return state


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_message.text

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'имя для связи', name))

    await update.effective_chat.send_message(
        text='Напишите контактный телефон для связи с вами',
    )

    context.user_data['birthday_data']['name'] = name

    state = 'PHONE'
    context.user_data['STATE'] = state
    return state


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.effective_message.text

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'телефон для связи', phone))

    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        await request_phone_number(update, phone)
        return 'PHONE'

    chat_id = update.effective_chat.id
    context.user_data['birthday_data']['phone'] = phone

    try:
        text = 'Ваша заявка: '
        for key, item in context.user_data['birthday_data'].items():
            text += '\n' + key + ': ' + str(item)

        context.user_data['text_for_notification_massage'] = text

        text += '\n\nПринята, после ее рассмотрения администратор свяжется с вами'
        message = await update.effective_chat.send_message(text)
        message_id = message.message_id

        data_for_callback = [
            row_in_googlesheet := 1,
            key_option_for_reserve := 2
        ]

        reply_markup = create_approve_and_reject_replay(
            'birthday-1',
            chat_id,
            message_id,
            data_for_callback
        )

        user = context.user_data['user']
        text = '#День_рождения\n' \
               f'Запрос пользователя @{user.username} {user.full_name}'
        for key, item in context.user_data['birthday_data'].items():
            text += '\n' + key + ': ' + str(item)
        message = await context.bot.send_message(
            text=text,
            chat_id=ADMIN_GROUP,
            reply_markup=reply_markup
        )

        context.user_data['message_id_for_admin'] = message.message_id

        write_client_bd(context.user_data['birthday_data'])

    except Exception as e:
        birthday_hl_logger.error(e)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def paid_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = 'START'
    context.user_data['STATE'] = state

    keyboard = []
    button_cancel = InlineKeyboardButton(
        "Отменить",
        callback_data=f'Отменить-bd'
    )
    keyboard.append([button_cancel])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = '    Внесите предоплату 5000 руб\n\n' \
           'Оплата осуществляется переводом на карту Сбербанка по номеру ' \
           'телефона +79159383529 - Татьяна Александровна Б.\n\n' \
           'ВАЖНО! Прислать сюда электронный чек об оплате (или скриншот)\n' \
           'Пожалуйста внесите оплату в течении 30 минут или нажмите ' \
           'отмена\n\n' \
           '__________\n' \
           'В случае переноса или отмены необходимо связаться с администратором:' \
           'Татьяна Бурганова @Tanya_domik +79159383529'

    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    context.chat_data['message_id'] = message.message_id

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
    message_id = context.chat_data['message_id']
    chat_id = update.effective_chat.id

    # Убираем у старого сообщения кнопку отмены
    await context.bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=message_id
    )

    try:
        # text = context.user_data['text_for_notification_massage']
        # TODO Создать сообщение для закрепа
        # TODO Дополнить запись в гугл-таблице о факте оплаты

        text = f'Квитанция пользователя @{user.username} {user.full_name}\n'
        message_id_for_admin = context.user_data['message_id_for_admin']
        await send_message_to_admin(ADMIN_GROUP,
                                    text,
                                    message_id_for_admin,
                                    context)

        await update.effective_message.forward(
            chat_id=ADMIN_GROUP,
        )

        data_for_callback = [
            row_in_googlesheet := 1,
            key_option_for_reserve := 2
        ]

        reply_markup = create_approve_and_reject_replay(
            'birthday-2',
            chat_id,
            message_id,
            data_for_callback
        )

        answer = await context.bot.send_message(
            chat_id=CHAT_ID_GROUP_ADMIN_1,
            text=f'Пользователь @{user.username} {user.full_name}\n'
                 f'Запросил подтверждение брони на сумму 5000 руб\n',
            reply_markup=reply_markup
        )

        context.user_data['message_id_for_admin'] = answer.message_id
    except KeyError:
        await update.effective_chat.send_message('Сначала необходимо оформить запрос')
        birthday_hl_logger.error(
            f'Пользователь {user}: '
            f'Не оформил заявку, а сразу использовал команду /{COMMAND_DICT["BD_PAID"][0]}'
        )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def conversation_timeout(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Informs the user that the operation has timed out, calls :meth:`remove_reply_markup` and
    ends the conversation.
    :return:
        int: :attr:`telegram.ext.ConversationHandler.END`.
    """

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
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
            'AFK уже 30 мин'
        ]
    ))
    birthday_hl_logger.info(f'Для пользователя {context.user_data["user"]}')
    birthday_hl_logger.info(f'Обработчик завершился на этапе {context.user_data["STATE"]}')
    context.user_data.clear()

    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)

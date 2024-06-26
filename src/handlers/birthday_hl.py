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
from telegram.constants import ParseMode, ChatAction
from telegram.helpers import escape_markdown

from handlers.sub_hl import (
    request_phone_number, send_message_to_admin
)
from db.db_googlesheets import load_list_show
from utilities.schemas.context import birthday_data
from utilities.log_func import join_for_log_info
from api.googlesheets import write_client_bd, set_approve_order
from settings.settings import (
    DICT_OF_EMOJI_FOR_BUTTON,
    ADMIN_GROUP,
    ADDRESS_OFFICE,
    COMMAND_DICT, FILE_ID_QR
)
from utilities.utl_func import (
    extract_phone_number_from_text,
    clean_context, check_phone_number,
    create_approve_and_reject_replay,
    create_replay_markup_for_list_of_shows,
    do_italic,
    do_bold, send_and_del_message_to_remove_kb
)
from utilities.utl_kbd import create_kbd_with_number_btn

birthday_hl_logger = logging.getLogger('bot.birthday_hl')


async def choice_place(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю выбор - где провести день рождения.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state PLACE
    """
    birthday_hl_logger.info(f'Пользователь начал бронирование ДР:'
                            f' {update.message.from_user}')

    message = await send_and_del_message_to_remove_kb(update)
    await update.effective_chat.send_action(ChatAction.TYPING)

    await clean_context(context)

    state = 'START'
    context.user_data['STATE'] = state
    context.user_data['birthday_user_data'] = {}
    context.user_data.setdefault('common_data', {})

    one_option = f'{DICT_OF_EMOJI_FOR_BUTTON[1]} В «Домике»'
    two_option = f'{DICT_OF_EMOJI_FOR_BUTTON[2]} На «Выезде»'

    # Отправка сообщения пользователю
    text = do_bold('Выберите место проведения Дня рождения\n\n')
    text += f'{one_option}\n'
    text += do_italic(f'В театре, {ADDRESS_OFFICE}\n\n')
    text += f'{two_option}\n'
    text += do_italic('Ваше место (дом, квартира или другая площадка)')
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
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

    state = 'PLACE'
    context.user_data['STATE'] = state
    return state


async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    one_option = f'{DICT_OF_EMOJI_FOR_BUTTON[1]} В «Домике»'
    text = f'Вы выбрали\n\n'
    text += f'{one_option}\n'
    text += do_italic(f'День рождения в {ADDRESS_OFFICE}')
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    place = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'Домик', place))

    text = 'Напишите желаемую дату проведения праздника'
    await update.effective_chat.send_message(
        text=text,
    )

    context.user_data['birthday_user_data']['place'] = int(place)
    context.user_data['birthday_user_data']['address'] = ADDRESS_OFFICE

    state = 'DATE'
    context.user_data['STATE'] = state
    return state


async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    two_option = f'{DICT_OF_EMOJI_FOR_BUTTON[2]} На «Выезде»'
    text = f'Вы выбрали\n\n'
    text += f'{two_option}\n'
    text += do_italic('День рождения в предложенном вами месте\n\n')
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    place = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'Выезд', place))

    text = 'Напишите адрес проведения дня рождения\n'
    await update.effective_chat.send_message(
        text=text,
    )

    context.user_data['birthday_user_data']['place'] = int(place)

    state = 'ADDRESS'
    context.user_data['STATE'] = state
    return state


async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.effective_message.text

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'адрес', address))

    text = 'Напишите желаемую дату проведения праздника'
    await update.effective_chat.send_message(
        text=text,
    )

    context.user_data['birthday_user_data']['address'] = address

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

    context.user_data['birthday_user_data']['date'] = date

    state = 'TIME'
    context.user_data['STATE'] = state
    return state


async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_action(ChatAction.TYPING)
    time = update.effective_message.text

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'время', time))
    try:
        dict_of_shows: dict = load_list_show()

        dict_of_shows_for_bd: dict = dict_of_shows.copy()
        for key, item in dict_of_shows.items():
            if not item['birthday']['flag']:
                dict_of_shows_for_bd.pop(key)

        # Отправка сообщения пользователю
        text = do_bold('Выберите мероприятие') + '\n\n'
        for i, item in enumerate(dict_of_shows_for_bd.values()):
            if item['birthday']['flag']:
                text += f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]} '
                text += escape_markdown(f'{item['full_name']}\n', 2)

        reply_markup = create_replay_markup_for_list_of_shows(
            dict_of_shows_for_bd,
            3,
            2,
            add_cancel_btn=False,
            add_back_btn=False,
        )

        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )

        context.user_data['common_data']['dict_of_shows'] = dict_of_shows
    except TimeoutError as err:
        birthday_hl_logger.error(err)
        await update.effective_chat.send_message(
            'Произошел разрыв соединения, попробуйте еще раз\n'
            'Если проблема повторится вы можете оформить заявку напрямую у '
            'Администратора:\n'
            f'{context.bot_data['admin']['contacts']}'
        )
        return ConversationHandler.END

    context.user_data['birthday_user_data']['time'] = time

    state = 'CHOOSE'
    context.user_data['STATE'] = state
    return state


async def get_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    theater_event_id = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'Спектакль', theater_event_id))

    keyboard_btn = []
    for i in range(2, 7):  # Фиксированно можно выбрать только от 2 до 6 лет
        keyboard_btn.append(InlineKeyboardButton(str(i), callback_data=str(i)))

    reply_markup = InlineKeyboardMarkup([
        keyboard_btn,
    ])
    await query.edit_message_text(
        text='Выберите сколько исполняется лет имениннику?',
        reply_markup=reply_markup
    )

    context.user_data['birthday_user_data']['theater_event_id'] = int(theater_event_id)

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
    keyboard = create_kbd_with_number_btn(10, 5)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['birthday_user_data']['age'] = int(age)

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
    keyboard = create_kbd_with_number_btn(10, 5)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['birthday_user_data']['qty_child'] = int(qty_child)

    state = 'QTY_ADULT'
    context.user_data['STATE'] = state
    return state


async def get_qty_adult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    qty_adult = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'кол-во взрослых', qty_adult))

    text = 'Следующий вопрос'
    reply_markup = None

    birthday_place = context.user_data['birthday_user_data']['place']
    birthday_price = context.bot_data.get(
        'birthday_price',
        {1: 0, 2: 0, 3: 0}
    )
    if birthday_place == 1:
        one_option = f'{DICT_OF_EMOJI_FOR_BUTTON[1]}'
        two_option = f'{DICT_OF_EMOJI_FOR_BUTTON[2]}'

        text = do_bold('Выберите формат проведения Дня рождения\n\n')
        text += escape_markdown(
            f'{one_option} Спектакль (40 минут) + '
            'аренда комнаты под чаепитие (1 час)\n'
            f' {birthday_price[1]} руб\n\n'
            f'{two_option} Спектакль (40 минут) + '
            'аренда комнаты под чаепитие + серебряная дискотека (1 час)\n'
            f' {birthday_price[2]} руб',
            2
        )

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(one_option, callback_data=1),
             InlineKeyboardButton(two_option, callback_data=2)],
        ])
    elif birthday_place == 2:
        text = escape_markdown(
            'Формат «На выезде»:\n\n'
            'Спектакль (40 минут) + Свободная игра с персонажами и '
            'фотосессия (20 минут)\n'
            f' {birthday_price[3]} руб\n\n',
            2
        )
        text += do_italic('Нажмите Далее')

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton('Далее', callback_data=3)]
        ])

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

    context.user_data['birthday_user_data']['qty_adult'] = int(qty_adult)

    state = 'FORMAT_BD'
    context.user_data['STATE'] = state
    return state


async def get_format_bd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    format_bd = query.data

    birthday_hl_logger.info(join_for_log_info(
        context.user_data['user'].id, 'формат праздника', format_bd))
    birthday_price = context.bot_data.get(
        'birthday_price',
        {1: 0, 2: 0, 3: 0}
    )

    text = 'Формат проведения Дня рождения\n\n'
    match format_bd:
        case '1':
            text += f'Спектакль + чаепитие\n {birthday_price[1]} руб'
        case '2':
            text += f'Спектакль + чаепитие + дискотека\n {birthday_price[2]} руб'
        case '3':
            text += f'Спектакль + игра + фотосессия\n {birthday_price[3]} руб'
    await query.edit_message_text(text)

    await update.effective_chat.send_message(
        text='Напишите как зовут именинника',
    )

    context.user_data['birthday_user_data']['format_bd'] = int(format_bd)

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

    context.user_data['birthday_user_data']['name_child'] = name_child

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

    context.user_data['birthday_user_data']['name'] = name

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

    user_id = update.effective_user.id
    context.user_data['birthday_user_data']['phone'] = phone

    try:
        text = do_bold('Ваша заявка: ')
        for key, item in context.user_data['birthday_user_data'].items():
            match key:
                case 'place':
                    if item == 1:
                        item = 'В «Домике»'
                    elif item == 2:
                        item = 'На выезде'
                case 'theater_event_id':
                    dict_of_shows = context.user_data['common_data'][
                        'dict_of_shows']
                    item = dict_of_shows[item]['full_name']
                case 'format_bd':
                    birthday_price = context.bot_data.get(
                        'birthday_price',
                        {1: 0, 2: 0, 3: 0}
                    )
                    if item == 1:
                        item = ('Спектакль (40 минут) + '
                                'аренда комнаты под чаепитие (1 час) '
                                f'-> {birthday_price[1]} руб')
                    elif item == 2:
                        item = ('Спектакль (40 минут) + '
                                'аренда комнаты под чаепитие + '
                                'серебряная дискотека (1 час) '
                                f'-> {birthday_price[2]} руб')
                    elif item == 3:
                        item = ('Спектакль (40 минут) + '
                                'Свободная игра с персонажами и '
                                'фотосессия (20 минут)'
                                f'-> {birthday_price[3]} руб')
                case 'phone':
                    item = '+7' + item

            text += '\n' + do_italic(birthday_data[key])
            text += ': ' + escape_markdown(str(item), 2)

        context.user_data['common_data']['text_for_notification_massage'] = text

        text += ('\n\nПринята, '
                 'после ее рассмотрения администратор свяжется с вами')
        message = await update.effective_chat.send_message(
            text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        message_id = message.message_id

        reply_markup = create_approve_and_reject_replay(
            'birthday-1',
            user_id,
            message_id
        )

        user = context.user_data['user']
        text = escape_markdown(
            '#День_рождения\n'
            f'Запрос пользователя @{user.username} {user.full_name}\n',
            2
        )
        text += context.user_data['common_data'][
            'text_for_notification_massage']
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Выездные мероприятия', None))
        message = await context.bot.send_message(
            text=text,
            chat_id=ADMIN_GROUP,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2,
            message_thread_id=thread_id
        )

        context.user_data['common_data'][
            'message_id_for_admin'] = message.message_id

        write_client_bd(context.user_data)

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

    text = ('    Внесите предоплату 5000 руб\n\n'
            'Оплатить можно:\n'
            ' - Переводом на карту Сбербанка по номеру телефона'
            '+79159383529 Татьяна Александровна Б.\n\n'
            'ВАЖНО! Прислать сюда электронный чек об оплате (или скриншот)\n'
            'Пожалуйста внесите оплату в течении 30 минут или нажмите '
            'отмена\n\n'
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
    message_id = context.user_data['common_data']['message_id_buy_info']
    chat_id = update.effective_chat.id

    # Убираем у старого сообщения кнопку отмены
    await context.bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=message_id
    )

    try:
        text = context.user_data['common_data']['text_for_notification_massage']
        message = await update.effective_chat.send_message(
            text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        await message.pin()

        set_approve_order(context.user_data['birthday_user_data'], 1)

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
            update.effective_user.id,
            message_id
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
            'Сначала необходимо оформить запрос'
        )
        birthday_hl_logger.error(
            f'Пользователь {user}: '
            'Не оформил заявку, '
            f'а сразу использовал команду /{COMMAND_DICT['BD_PAID'][0]}'
        )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
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

    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)

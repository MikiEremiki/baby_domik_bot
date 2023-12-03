import logging
import pprint
import re
from datetime import datetime

from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    TypeHandler
)
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode, ChatType, ChatAction

from handlers.sub_hl import (
    request_phone_number,
    send_and_del_message_to_remove_kb,
    write_old_seat_info,
)
from db.db_googlesheets import (
    load_clients_data,
    load_show_data,
    load_list_show,
)
from utilities.googlesheets import (
    write_data_for_reserve,
    write_client,
    write_client_list_waiting,
    get_quality_of_seats,
)
from utilities.utl_func import (
    extract_phone_number_from_text,
    add_btn_back_and_cancel,
    send_message_to_admin,
    set_back_context, get_back_context, clean_context,
)
from utilities.hlp_func import (
    check_phone_number,
    create_replay_markup_for_list_of_shows,
    create_approve_and_reject_replay,
    enum_current_show_by_month,
    add_text_of_show_and_numerate
)
from utilities.settings import (
    ADMIN_GROUP,
    COMMAND_DICT,
    DICT_OF_EMOJI_FOR_BUTTON,
    FILE_ID_QR,
    TICKET_COST,
    DICT_CONVERT_MONTH_NUMBER_TO_STR,
    SUPPORT_DATA,
    RESERVE_TIMEOUT,
)
from utilities.schemas.ticket import BaseTicket

reserve_hl_logger = logging.getLogger('bot.reserve_hl')


async def choice_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю список месяцев.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state MONTH
    """
    state = 'START'
    context.user_data['STATE'] = state
    context.user_data['reserve_user_data'] = {}
    context.user_data['reserve_user_data']['back'] = {}
    context.user_data['reserve_user_data']['client_data'] = {}
    context.user_data['reserve_user_data']['choose_show_info'] = {}
    context.user_data.setdefault('common_data', {})
    context.user_data.setdefault('reserve_admin_data', {'payment_id': 0})
    if not isinstance(
            context.user_data['reserve_admin_data']['payment_id'],
            int):
        context.user_data['reserve_admin_data'] = {'payment_id': 0}

    user = context.user_data.setdefault('user', update.effective_user)

    clean_context(context)

    if update.effective_message.is_topic_message:
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Списки на показы', None))
        if update.effective_message.message_thread_id != thread_id:
            await update.effective_message.reply_text(
                'Выполните команду в правильном топике')
            return ConversationHandler.END

    reserve_hl_logger.info(f'Пользователь начал выбор месяца:'
                           f' {user}')

    message = await send_and_del_message_to_remove_kb(update)
    await update.effective_chat.send_action(ChatAction.TYPING)

    try:
        (
            dict_of_shows,
            dict_of_name_show,
            dict_of_name_show_flip,
            dict_of_date_show
        ) = load_show_data()
    except ConnectionError or ValueError:
        reserve_hl_logger.info(
            f'Для пользователя {user}')
        reserve_hl_logger.info(
            f'Обработчик завершился на этапе {state}')
        await update.effective_chat.send_message(
            text='К сожалению я сегодня на техническом обслуживании\n'
                 'Но вы можете забронировать место связавшись напрямую с '
                 'Администратором:\n'
                 f'{context.bot_data['admin']['contacts']}',
            message_thread_id=update.message.message_thread_id
        )
        return ConversationHandler.END
    except TimeoutError:
        reserve_hl_logger.info(
            f'Для пользователя {user}')
        reserve_hl_logger.info(
            f'Обработчик завершился на этапе {state}')
        await update.effective_chat.send_message(
            text='Произошел разрыв соединения, попробуйте еще раз\n'
                 'Если проблема повторится вы можете оформить заявку напрямую у '
                 'Администратора:\n'
                 f'{context.bot_data['admin']['contacts']}',
            message_thread_id=update.message.message_thread_id
        )
        return ConversationHandler.END

    list_of_months = []
    for item in dict_of_date_show.keys():
        if int(item[3:5]) not in list_of_months:
            list_of_months.append(int(item[3:5]))

    keyboard = []

    for item in list_of_months:
        button_tmp = InlineKeyboardButton(
            text=DICT_CONVERT_MONTH_NUMBER_TO_STR[item],
            callback_data=str(item)
        )
        keyboard.append([button_tmp])

    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel='res',
        add_back_btn=False
    ))
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите месяц'

    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=message.message_id
    )
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.message.message_thread_id
    )

    context.user_data['common_data']['dict_of_shows'] = dict_of_shows
    context.user_data['reserve_user_data'][
        'dict_of_name_show'] = dict_of_name_show
    context.user_data['reserve_user_data'][
        'dict_of_name_show_flip'] = dict_of_name_show_flip
    context.user_data['reserve_user_data'][
        'dict_of_date_show'] = dict_of_date_show

    state = 'MONTH'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_show_or_date(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Функция отправляет пользователю список спектаклей с датами.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state DATE
    """
    query = update.callback_query
    await query.answer()
    await query.delete_message()

    user = context.user_data['user']

    reserve_hl_logger.info(f'Пользователь начал выбор спектакля:'
                           f' {user}')

    reserve_user_data = context.user_data['reserve_user_data']
    dict_of_name_show = reserve_user_data['dict_of_name_show']
    dict_of_date_show = reserve_user_data['dict_of_date_show']

    number_of_month_str = query.data
    filter_show_id = enum_current_show_by_month(dict_of_date_show,
                                                number_of_month_str)

    if number_of_month_str == '12':
        text = 'Выберите спектакль\n'
        text = add_text_of_show_and_numerate(text,
                                             dict_of_name_show,
                                             filter_show_id)
        keyboard = []
        for key, item in dict_of_name_show.items():
            if item in filter_show_id.keys():
                button_tmp = InlineKeyboardButton(
                    text=f'{DICT_OF_EMOJI_FOR_BUTTON[filter_show_id[item]]}',
                    callback_data=str(item)
                )
                if len(keyboard) == 0:
                    keyboard.append([button_tmp])
                else:
                    keyboard[0].append(button_tmp)

        keyboard.append(add_btn_back_and_cancel(
            postfix_for_cancel='res',
            add_back_btn=True,
            postfix_for_back='MONTH'
        ))
        reply_markup = InlineKeyboardMarkup(keyboard)

        state = 'SHOW'
        set_back_context(context, state, text, reply_markup)
    else:
        text = 'Выберите спектакль и дату\n'
        text = add_text_of_show_and_numerate(text,
                                             dict_of_name_show,
                                             filter_show_id)
        reply_markup = create_replay_markup_for_list_of_shows(
            dict_of_date_show,
            add_cancel_btn=True,
            postfix_for_cancel='res',
            postfix_for_back='MONTH',
            number_of_month=number_of_month_str,
        )
        state = 'DATE'
        set_back_context(context, state, text, reply_markup)

    photo = (
        context.bot_data
        .get('afisha', {})
        .get(int(number_of_month_str), False)
    )
    if update.effective_chat.type == ChatType.PRIVATE and photo:
        await update.effective_chat.send_photo(
            photo=photo,
            caption=text,
            reply_markup=reply_markup
        )
    else:
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=update.callback_query.message.message_thread_id
        )

    reserve_user_data['number_of_month_str'] = number_of_month_str

    context.user_data['STATE'] = state
    return state


async def choice_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю варианты
    времени и кол-во свободных мест

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state TIME
    """
    query = update.callback_query
    await query.answer()

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    number_of_show = int(query.data)
    reserve_user_data = context.user_data['reserve_user_data']
    dict_of_date_show = reserve_user_data['dict_of_date_show']
    dict_of_name_show_flip = reserve_user_data['dict_of_name_show_flip']
    number_of_month_str = reserve_user_data['number_of_month_str']
    dict_of_shows = context.user_data['common_data']['dict_of_shows']
    name_of_show = dict_of_name_show_flip[number_of_show]

    reply_markup = create_replay_markup_for_list_of_shows(
        dict_of_date_show,
        ver=3,
        add_cancel_btn=True,
        postfix_for_cancel='res',
        postfix_for_back='SHOW',
        number_of_month=number_of_month_str,
        number_of_show=number_of_show,
        dict_of_events_show=dict_of_shows
    )

    text = f'Вы выбрали\n <b>{name_of_show}</b>\n<i>Выберите дату</i>\n\n'
    flag_gift = False
    flag_christmas_tree = False
    flag_santa = False

    for event in dict_of_shows.values():
        if name_of_show == event['name_show']:
            if event['flag_gift']:
                flag_gift = True
            if event['flag_christmas_tree']:
                flag_christmas_tree = True
            if event['flag_santa']:
                flag_santa = True

    if flag_gift:
        text += f'{SUPPORT_DATA['Подарок'][0]} - {SUPPORT_DATA['Подарок'][1]}\n'
    if flag_christmas_tree:
        text += f'{SUPPORT_DATA['Елка'][0]} - {SUPPORT_DATA['Елка'][1]}\n'
    if flag_santa:
        text += f'{SUPPORT_DATA['Дед'][0]} - {SUPPORT_DATA['Дед'][1]}\n'

    photo = (
        context.bot_data
        .get('afisha', {})
        .get(int(number_of_month_str), False)
    )
    if update.effective_chat.type == ChatType.PRIVATE and photo:
        await query.edit_message_caption(
            caption=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    else:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

    state = 'DATE'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю варианты
    времени и кол-во свободных мест

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state TIME
    """
    query = update.callback_query
    await query.answer()
    await query.delete_message()

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    key_of_name_show, date_show = query.data.split(' | ')
    key_of_name_show = int(key_of_name_show)

    dict_of_shows: dict = context.user_data['common_data']['dict_of_shows']
    reserve_user_data = context.user_data['reserve_user_data']
    dict_of_name_show_flip = reserve_user_data['dict_of_name_show_flip']
    name_show: str = dict_of_name_show_flip[key_of_name_show]

    keyboard = []

    # Определение кнопок для inline клавиатуры с исключением вариантов где
    # свободных мест уже не осталось
    for key, item in dict_of_shows.items():
        if item['name_show'] == name_show and item['date_show'] == date_show:
            show_id = item['show_id']
            time = item['time_show']
            qty_child = item['qty_child_free_seat']
            qty_adult = item['qty_adult_free_seat']
            if int(qty_child) < 0:
                qty_child = 0
            text = time
            text_emoji = ''
            if item['flag_gift']:
                text_emoji += f'{SUPPORT_DATA['Подарок'][0]}'
            if item['flag_christmas_tree']:
                text_emoji += f'{SUPPORT_DATA['Елка'][0]}'
            if item['flag_santa']:
                text_emoji += f'{SUPPORT_DATA['Дед'][0]}'
            text += text_emoji
            # TODO вместо key использовать event_id, и кол-во мест на
            #  следующих этапах доставать из контекста по event_id вместо
            #  callback_data
            text += ' | ' + str(qty_child) + ' дет'
            text += ' | ' + str(qty_adult) + ' взр'

            callback_data = time
            callback_data += ' | ' + str(key)
            callback_data += ' | ' + str(qty_child)
            callback_data += ' | ' + str(qty_adult)
            button_tmp = InlineKeyboardButton(
                text=text,
                callback_data=callback_data
            )
            keyboard.append([button_tmp])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='res',
                                            postfix_for_back='DATE'))
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = f'Вы выбрали:\n <b>{name_show}\n{date_show}</b>\n'
    if update.effective_chat.id == ADMIN_GROUP:
        # Отправка сообщения в админский чат
        text += 'Выберите время'
    else:
        # Отправка сообщения пользователю
        text += ('<i>Выберите удобное время\n'
                 '1 ребенок = 1 место</i>\n\n'
                 'Вы также можете выбрать вариант с 0 кол-вом мест '
                 'и записаться в лист ожидания на данное время\n\n'
                 'Кол-во свободных мест:\n'
                 '⬇️<i>Время</i> | <i>Взрослых</i> | <i>Детских</i>⬇️')

    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        message_thread_id=update.callback_query.message.message_thread_id
    )

    reserve_user_data['show_id'] = int(show_id)
    reserve_user_data['name_show'] = name_show
    reserve_user_data['date_show'] = date_show

    if update.effective_chat.id == ADMIN_GROUP:
        state = 'LIST'
    else:
        state = 'TIME'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_option_of_reserve(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю,
    дате, времени и варианты бронирования

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state ORDER
    """
    query = update.callback_query
    await query.answer()
    await query.edit_message_text('Загружаю данные по билетам...')

    await update.effective_chat.send_action(ChatAction.TYPING)

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    time, row_in_googlesheet, qty_child, qty_adult = query.data.split(' | ')
    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['time_show'] = time

    reserve_admin_data: dict = context.user_data['reserve_admin_data']
    payment_id = reserve_admin_data['payment_id']
    reserve_hl_logger.info(f'Бронирование: {payment_id}')
    reserve_admin_data[payment_id] = {}
    reserve_admin_data[payment_id]['row_in_googlesheet'] = row_in_googlesheet

    dict_of_shows = context.user_data['common_data']['dict_of_shows']
    date: str = reserve_user_data['date_show']
    event = dict_of_shows[int(row_in_googlesheet)]
    reserve_user_data['event_id'] = event['event_id']
    text_emoji = ''
    option = ''
    if event['flag_gift']:
        text_emoji += f'{SUPPORT_DATA['Подарок'][0]}'
        option = 'Подарок'
    if event['flag_christmas_tree']:
        text_emoji += f'{SUPPORT_DATA['Елка'][0]}'
        option = 'Ёлка'
    if event['flag_santa']:
        text_emoji += f'{SUPPORT_DATA['Дед'][0]}'
    if event['show_id'] == '10' or event['show_id'] == '8':
        option = 'Базовая стоимость'

    reserve_user_data['option'] = option
    reserve_user_data['text_emoji'] = text_emoji

    if int(qty_child) == 0 or int(qty_adult) == 0:
        reserve_hl_logger.info('Мест нет')
        reserve_hl_logger.info(f'qty_child: {qty_child}')
        reserve_hl_logger.info(f'qty_adult: {qty_adult}')

        name_show = reserve_user_data['name_show']
        text = (f'Вы выбрали:\n'
                f'<b>{name_show}\n'
                f'{date}\n'
                f'В {time}</b>\n'
                f'{text_emoji}\n')
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML
        )

        reserve_user_data['event_info_for_list_waiting'] = text
        reply_keyboard = [
            ['Выбрать другое время'],
            ['Записаться в лист ожидания'],
        ]
        reply_markup = ReplyKeyboardMarkup(
            reply_keyboard,
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await update.effective_chat.send_message(
            text='Вы хотите выбрать другое время '
                 'или записаться в лист ожидания на эту дату и время?',
            reply_markup=reply_markup
        )
        state = 'CHOOSING'
        context.user_data['STATE'] = state
        return state

    availibale_number_of_seats_now = update_quality_of_seats(
        row_in_googlesheet, 'qty_child_free_seat')

    dict_of_shows: dict = load_list_show()
    show_id = reserve_user_data['show_id']
    flag_indiv_cost = False
    for key, item in dict_of_shows.items():
        if key == show_id:
            flag_indiv_cost = item['flag_indiv_cost']
            reserve_user_data['flag_indiv_cost'] = flag_indiv_cost

    list_of_tickets = context.bot_data['list_of_tickets']
    keyboard = []
    list_btn_of_numbers = []
    for i, ticket in enumerate(list_of_tickets):
        key = ticket.base_ticket_id
        if flag_indiv_cost and key // 100 != 1:
            continue
        quality_of_children = ticket.quality_of_children

        # Если свободных мест меньше, чем требуется для варианта
        # бронирования, то кнопку с этим вариантом не предлагать
        if int(quality_of_children) <= int(availibale_number_of_seats_now):
            button_tmp = InlineKeyboardButton(
                text=str(i + 1),
                callback_data=str(key)
            )
            list_btn_of_numbers.append(button_tmp)

            # Позволяет управлять кол-вом кнопок в ряду
            # Максимальное кол-во кнопок в ряду равно 8
            if (i + 1) % 5 == 0:
                keyboard.append(list_btn_of_numbers)
                list_btn_of_numbers = []
    if len(list_btn_of_numbers):
        keyboard.append(list_btn_of_numbers)

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='res',
                                            postfix_for_back='TIME'))
    reply_markup = InlineKeyboardMarkup(keyboard)

    name_show = reserve_user_data['name_show']
    text = (f'Вы выбрали:\n'
            f'<b>{name_show}\n'
            f'{date}\n'
            f'В {time}</b>\n'
            f'{text_emoji}\n'
            f'Кол-во свободных мест: <i>{qty_adult_free_seat_now} взр</i> '
            f'| <i>{qty_child_free_seat_now} дет</i>\n')
    text += 'Выберите подходящий вариант бронирования:\n'

    date_now = datetime.now().date()
    date_tmp = date.split()[0] + f'.{date_now.year}'
    date_for_price: datetime = datetime.strptime(date_tmp, f'%d.%m.%Y')

    for i, ticket in enumerate(list_of_tickets):
        key = ticket.base_ticket_id
        name = ticket.name

        ticket.date_show = date  # Для расчета стоимости в периоде или нет
        price = ticket.price

        if flag_indiv_cost:
            if key // 100 == 1:
                if event['ticket_price_type'] == '':
                    if date_for_price.weekday() in range(5):
                        type_ticket_price = 'будни'
                    else:
                        type_ticket_price = 'выходные'
                else:
                    type_ticket_price = event['ticket_price_type']
                reserve_user_data['type_ticket_price'] = type_ticket_price

                price = TICKET_COST[option][type_ticket_price][key]
                text += (f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]} {name} | '
                         f'{price} руб\n')
        else:
            text += (f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]} {name} | '
                     f'{price} руб\n')

            if key == 5:
                text += "__________\n    Варианты со скидками:\n"

    text += """__________
<i>Если вы хотите оформить несколько билетов, то каждая бронь оформляется 
отдельно.</i>
__________
<i>Если нет желаемых вариантов для выбора, значит нехватает мест для их оформления. 
В таком случае вернитесь назад и выберете другое время.</i>
"""

    await query.message.edit_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

    state = 'ORDER'
    context.user_data['STATE'] = state
    return state


async def check_and_send_buy_info(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Проверяет кол-во доступных мест, для выбранного варианта пользователем и
    отправляет сообщение об оплате

    :return:
        возвращает state PAID,
        если проверка не пройдена, то state ORDER
    """
    query = update.callback_query
    await query.answer()
    await query.edit_message_text('Готовлю информацию об оплате...')

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    try:
        key_option_for_reserve = int(query.data)
    except ValueError as e:
        reserve_hl_logger.error(e)
        state = 'TIME'
        text_back, reply_markup = get_back_context(context, state)
        text = '<i>Произошла ошибка. Выберите время еще раз</i>\n'
        text += text_back
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        context.user_data['STATE'] = state
        return state

    reserve_user_data = context.user_data['reserve_user_data']
    name_show = reserve_user_data['name_show']
    date = reserve_user_data['date_show']
    time = reserve_user_data['time_show']
    option = reserve_user_data['option']
    text_emoji = reserve_user_data['text_emoji']
    flag_indiv_cost = reserve_user_data['flag_indiv_cost']
    list_of_tickets = context.bot_data['list_of_tickets']
    chose_ticket: BaseTicket = list_of_tickets[0]
    price = chose_ticket.price
    for ticket in list_of_tickets:
        if ticket.base_ticket_id == key_option_for_reserve:
            chose_ticket = ticket
            price = chose_ticket.price

            key = chose_ticket.base_ticket_id
            if flag_indiv_cost:
                if key // 100 == 1:
                    type_ticket_price = reserve_user_data['type_ticket_price']
                    price = TICKET_COST[option][type_ticket_price][key]

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            chose_ticket.name,
            str(price),
        ]
    ))

    # Если пользователь выбрал не стандартный вариант
    if chose_ticket.flag_individual:
        text = ('Для оформления данного варианта обратитесь к Администратору:\n'
                f'{context.bot_data['admin']['contacts']}')
        await query.message.edit_text(
            text=text
        )

        reserve_hl_logger.info(
            f'Для пользователя {user}')
        reserve_hl_logger.info(
            f'Обработчик завершился на этапе {context.user_data['STATE']}')
        context.user_data['common_data'].clear()
        context.user_data['reserve_user_data'].clear()

        state = ConversationHandler.END
        context.user_data['STATE'] = state
        return state
    # Для все стандартных вариантов
    else:
        # Отправляем сообщение пользователю, которое он будет использовать как
        # памятку
        text = (f'Вы выбрали:\n'
                f'{name_show}\n'
                f'{date}\n'
                f'В {time}\n'
                f'{text_emoji}\n'
                f'Вариант бронирования:\n'
                f'{chose_ticket.name} '
                f'{price}руб\n')

        context.user_data['common_data']['text_for_notification_massage'] = text

        await query.message.edit_text(
            text=text
        )
        message = await update.effective_chat.send_message(
            'Проверяю наличие свободных мест...')
        await update.effective_chat.send_action(ChatAction.TYPING)
        # Номер строки для извлечения актуального числа доступных мест
        reserve_admin_data = context.user_data['reserve_admin_data']
        payment_id = reserve_admin_data['payment_id']
        row_in_googlesheet = reserve_admin_data[payment_id][
            'row_in_googlesheet']

        # Обновляем кол-во доступных мест
        availibale_number_of_seats_now = update_quality_of_seats(
            row_in_googlesheet, 'qty_child_free_seat')
        nonconfirm_number_of_seats_now = update_quality_of_seats(
            row_in_googlesheet, 'qty_child_nonconfirm_seat')

        # Проверка доступности нужного кол-ва мест, за время взаимодействия с
        # ботом, могли изменить базу в ручную или забронировать места раньше
        if (int(availibale_number_of_seats_now) <
                int(chose_ticket.quality_of_children)):
            reserve_hl_logger.info(": ".join(
                [
                    'Мест не достаточно',
                    'Кол-во доступных мест',
                    availibale_number_of_seats_now,
                    'Для',
                    f'{name_show} {date} в {time}',
                ]
            ))

            await query.message.delete()
            text = (f'Вы выбрали:\n'
                    f'{name_show}\n'
                    f'{date}\n'
                    f'В {time}\n'
                    f'{text_emoji}\n')
            reserve_user_data['event_info_for_list_waiting'] = text
            text = ('К сожалению места уже забронировали и свободных мест для\n'
                    f'{name_show}\n'
                    f'{date} в {time}\n'
                    f'{text_emoji}\n'
                    f' Осталось: {availibale_number_of_seats_now}шт\n\n'
                    'Вы хотите выбрать другое время '
                    'или записаться в лист ожидания на эту дату и время?')
            reply_keyboard = [
                ['Выбрать другое время'],
                ['Записаться в лист ожидания'],
            ]
            reply_markup = ReplyKeyboardMarkup(
                reply_keyboard,
                resize_keyboard=True,
                one_time_keyboard=True
            )
            await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup
            )
            state = 'CHOOSING'
            context.user_data['STATE'] = state
            return state
        else:
            reserve_hl_logger.info(": ".join(
                [
                    'Пользователь',
                    f'{user}',
                    'получил разрешение на бронирование'
                ]
            ))

            new_number_of_seats = int(
                availibale_number_of_seats_now) - int(
                chose_ticket.quality_of_children)
            new_nonconfirm_number_of_seats = int(
                nonconfirm_number_of_seats_now) + int(
                chose_ticket.quality_of_children)

            try:
                write_data_for_reserve(
                    row_in_googlesheet,
                    [new_number_of_seats, new_nonconfirm_number_of_seats]
                )
            except TimeoutError:
                reserve_hl_logger.error(": ".join(
                    [
                        'Для пользователя подтверждение не сработало, гугл не отвечает',
                        f'{user}',
                        'Номер строки для обновления',
                        row_in_googlesheet,
                    ]
                ))

                keyboard = [add_btn_back_and_cancel('res')]
                reply_markup = InlineKeyboardMarkup(keyboard)

                text = ('К сожалению произошла непредвиденная ошибка\n'
                        'Нажмите "Назад" и выберите время повторно.\n'
                        'Если ошибка повторяется свяжитесь с Администратором:\n'
                        f'{context.bot_data['admin']['contacts']}')
                await query.message.edit_text(
                    text=text,
                    reply_markup=reply_markup
                )
                state = 'ORDER'
                context.user_data['STATE'] = state
                return state

        keyboard = []
        button_cancel = InlineKeyboardButton(
            'Отменить',
            callback_data=f'Отменить-res|'
                          f'{query.message.chat_id} {query.message.message_id}'
        )
        keyboard.append([button_cancel])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await message.delete()
        message = await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=FILE_ID_QR,
            caption=f"""Забронировать билет можно только по 100% предоплате.
Но вы не переживайте, если вдруг вы не сможете прийти, просто сообщите нам об этом за 24 часа, мы перенесём вашу дату визита. 

    К оплате {price} руб

Оплатить можно:
 - По qr-коду
 - Переводом в банк Точка по номеру телефона +79159383529 
- Татьяна Александровна Б.

ВАЖНО! Прислать сюда электронный чек/квитанцию об оплате (файл или скриншот)
Необходимо отправить чек в течении {RESERVE_TIMEOUT} мин или бронь будет 
ОТМЕНЕНА!
__________
Для подтверждения брони администратором, после отправки чека, необходимо 
заполнить анкету (она придет автоматически)""",
            reply_markup=reply_markup
        )
        common_data = context.user_data['common_data']
        common_data['message_id_buy_info'] = message.message_id
        common_data['dict_of_shows'].clear()

        reserve_user_data = context.user_data['reserve_user_data']
        reserve_user_data['chose_price'] = price
        reserve_user_data['dict_of_name_show'].clear()
        reserve_user_data['dict_of_name_show_flip'].clear()
        reserve_user_data['dict_of_date_show'].clear()
        reserve_user_data['back'].clear()

        reserve_admin_data = context.user_data['reserve_admin_data']
        payment_id = reserve_admin_data['payment_id']
        reserve_admin_data[payment_id]['chose_ticket'] = chose_ticket

    state = 'PAID'
    context.user_data['STATE'] = state
    return state


async def forward_photo_or_file(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Пересылает картинку или файл.
    Запускает цепочку вопросов для клиентской базы, если пользователь нажал
    кнопку подтвердить.
    """

    message_id = context.user_data['common_data']['message_id_buy_info']
    chat_id = update.effective_chat.id

    # Убираем у старого сообщения кнопки
    await context.bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=message_id
    )

    user = context.user_data['user']
    text = context.user_data['common_data']['text_for_notification_massage']

    thread_id = (context.bot_data['dict_topics_name']
                 .get('Бронирование спектаклей', None))
    res = await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=f'#Бронирование\n'
             f'Квитанция пользователя @{user.username} {user.full_name}\n',
        message_thread_id=thread_id
    )
    await update.effective_message.forward(
        chat_id=ADMIN_GROUP,
        message_thread_id=thread_id
    )
    message_id_for_admin = res.message_id
    await send_message_to_admin(ADMIN_GROUP,
                                text,
                                message_id_for_admin,
                                context,
                                thread_id)

    # Сообщение для опроса
    await update.effective_chat.send_message("""Для подтверждения брони 
заполните пожалуйста анкету.
Чтобы мы знали на кого оформлена бронь и как с вами связаться.
__________
Пожалуйста не пишите лишней информации/дополнительных слов в сообщении. 
Вопросы будут приходить последовательно (их будет всего 3)""")
    await update.effective_chat.send_message(
        'Напишите фамилию и имя (взрослого) на кого оформляете бронь'
    )

    # Сообщение для администратора
    payment_id = context.user_data['reserve_admin_data']['payment_id']
    reply_markup = create_approve_and_reject_replay(
        'reserve',
        update.effective_user.id,
        message_id,
        payment_id
    )

    chose_price = context.user_data['reserve_user_data']['chose_price']

    message = await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=f'Пользователь @{user.username} {user.full_name}\n'
             f'Запросил подтверждение брони на сумму {chose_price} руб\n'
             f'Ждем заполнения анкеты, если всё хорошо, то только после '
             f'нажимаем подтвердить',
        reply_markup=reply_markup,
        message_thread_id=thread_id
    )

    context.user_data['common_data'][
        'message_id_for_admin'] = message.message_id

    state = 'FORMA'
    context.user_data['STATE'] = state
    return state


async def get_name_adult(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    text = update.effective_message.text

    context.user_data['reserve_user_data']['client_data']['name_adult'] = text

    await update.effective_chat.send_message(
        text='Напишите контактный номер телефона'
    )

    state = 'PHONE'
    context.user_data['STATE'] = state
    return state


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        await request_phone_number(update, phone)
        return context.user_data['STATE']

    context.user_data['reserve_user_data']['client_data']['phone'] = phone

    await update.effective_chat.send_message(
        text="""Напишите, имя и возраст ребенка.
Возможные форматы записи:
Сергей 26.08.2019
Иван 1.5
Юля 1г10м
Оля 1год 8мес
__________
Если детей несколько, то напишите пожалуйста всех в одном сообщении (один ребенок = одна строка)
Пожалуйста не используйте дополнительные слова и пунктуацию, кроме тех, что указаны в примерах"""
    )

    state = 'CHILDREN'
    context.user_data['STATE'] = state
    return state


async def get_name_children(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_action(ChatAction.TYPING)

    text = update.effective_message.text
    text_for_message = """Проверьте, что указали дату или возраст правильно
Возможные форматы записи:
Сергей 26.08.2019
Иван 1.5
Юля 1г10м
__________
Если детей несколько, то напишите пожалуйста всех в одном сообщении (один ребенок = одна строка)
Пожалуйста не используйте дополнительные слова и пунктуацию, кроме тех, что указаны в примерах"""

    # Проверка корректности ввода
    count = text.count('\n')
    result = re.findall(
        r'(^\w+ \d ?\w+ ?и? ?\d ?\w+)+|(\w+ (\d+(?:[.,]\d+){0,2}))+',
        text
    )

    if len(result) < count + 1:
        reserve_hl_logger.info('Не верный формат текста')
        await update.effective_chat.send_message(text=text_for_message)
        return context.user_data['STATE']

    reserve_hl_logger.info('Проверка пройдена успешно')

    list_message_text = []
    if '\n' in text:
        message_text = text.split('\n')
        for item in message_text:
            list_message_text.append(item.split())
    else:
        message_text = text.split()
        list_message_text.append(message_text)

    try:
        reserve_admin_data = context.user_data['reserve_admin_data']
        payment_id = reserve_admin_data['payment_id']
        chose_ticket = reserve_admin_data[payment_id]['chose_ticket']
    except KeyError:
        await update.effective_chat.send_message(
            'Произошел технический сбой.\n'
            f'Повторите, пожалуйста, бронирование еще раз\n'
            f'/{COMMAND_DICT['RESERVE'][0]}\n'
            'Приносим извинения за предоставленные неудобства.'
        )
        state = ConversationHandler.END
        context.user_data['STATE'] = state
        return state

    if not isinstance(list_message_text[0], list):
        await update.effective_chat.send_message(f'Вы ввели:\n{text}')
        await update.effective_chat.send_message(text=text_for_message)
        state = 'CHILDREN'
        context.user_data['STATE'] = state
        return state

    if len(list_message_text) != chose_ticket.quality_of_children:
        await update.effective_chat.send_message(
            f'Кол-во детей, которое определено: {len(list_message_text)}\n'
            f'Кол-во детей, согласно выбранному билету: '
            f'{chose_ticket.quality_of_children}\n'
            f'Повторите ввод еще раз, проверьте что каждый ребенок на '
            f'отдельной строке.\n\nНапример:\nИван 1\nСергей 01.01.2000')
        state = 'CHILDREN'
        context.user_data['STATE'] = state
        return state

    reserve_user_data = context.user_data['reserve_user_data']
    client_data = reserve_user_data['client_data']
    client_data['data_children'] = list_message_text

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'отправил:',
        ],
    ))
    reserve_hl_logger.info(client_data)

    chose_price = reserve_user_data['chose_price']
    record_ids = write_client(
        client_data,
        reserve_admin_data[payment_id]['row_in_googlesheet'],
        chose_ticket,
        chose_price,
    )

    text = '\n'.join([
        client_data['name_adult'],
        '+7' + client_data['phone'],
        text,
    ])
    text += '\n\n'
    for record in record_ids:
        text += f'#id{record} '
    message_id_for_admin = context.user_data['common_data'][
        'message_id_for_admin']

    thread_id = (context.bot_data['dict_topics_name']
                 .get('Бронирование спектаклей', None))
    await send_message_to_admin(ADMIN_GROUP,
                                text,
                                message_id_for_admin,
                                context,
                                thread_id)

    await update.effective_chat.send_message(
        'Благодарим за ответы.\nОжидайте, когда администратор подтвердить '
        'бронь.\nЕсли всё хорошо, то вам придет сообщение: "Ваша бронь '
        'подтверждена"\n'
        'В противном случае с вами свяжутся для уточнения деталей')

    text = context.user_data['common_data']['text_for_notification_massage']
    text += f"""__________
Место проведения:
Офис-центр Малая Покровская, д18, 2 этаж
__________
По вопросам обращайтесь к Администратору:
{context.bot_data['admin']['contacts']}
__________
Если вы хотите оформить еще одну бронь, используйте команду /{COMMAND_DICT[
        'RESERVE'][0]}"""
    message = await update.effective_chat.send_message(
        text=text
    )
    await message.pin()

    reserve_admin_data['payment_id'] += 1

    reserve_hl_logger.info(f'Для пользователя {user}')
    reserve_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')

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
        reserve_hl_logger.info('Отправка чека об оплате не была совершена')
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['common_data']['message_id_buy_info']
        )
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, бронь отменена, '
            'пожалуйста выполните новый запрос\n'
            'Если вы уже сделали оплату, но не отправили чек об оплате, '
            'выполните оформление повторно и приложите данный чек\n'
            f'/{COMMAND_DICT['RESERVE'][0]}\n\n'
            'Если свободных мест не будет свяжитесь с Администратором:\n'
            f'{context.bot_data['admin']['contacts']}'
        )
        reserve_hl_logger.info(pprint.pformat(context.user_data))
        reserve_admin_data = context.user_data['reserve_admin_data']
        payment_id = reserve_admin_data['payment_id']
        chose_ticket = reserve_admin_data[payment_id]['chose_ticket']
        row_in_googlesheet = reserve_admin_data[payment_id][
            'row_in_googlesheet']

        await write_old_seat_info(update,
                                  user,
                                  row_in_googlesheet,
                                  chose_ticket)
    else:
        # TODO Прописать дополнительную обработку states, для этапов опроса
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос',
            message_thread_id=update.effective_message.message_thread_id
        )

    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            f'AFK уже {RESERVE_TIMEOUT} мин'
        ]
    ))
    reserve_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')

    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)


async def send_clients_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    name = context.user_data['reserve_user_data']['name_show']
    date = context.user_data['reserve_user_data']['date_show']
    dict_of_shows = context.user_data['common_data']['dict_of_shows']
    time, row_in_googlesheet, number = query.data.split(' | ')
    event = dict_of_shows[int(row_in_googlesheet)]
    event_id = event['event_id']

    clients_data, name_column = load_clients_data(event_id)
    text = f'#Показ\n'
    text += f'Список людей для\n{name}\n{date}\n{time}\nОбщее кол-во детей: '
    text += str(len(clients_data))
    for i, item1 in enumerate(clients_data):
        text += '\n__________\n'
        text += str(i + 1) + '| '
        text += '<b>' + item1[name_column['callback_name']] + '</b>'
        text += '\n+7' + item1[name_column['callback_phone']]
        if item1[name_column['child_name']] != '':
            text += '\nИмя ребенка: '
            text += item1[name_column['child_name']] + ' '
        if item1[name_column['child_age']] != '':
            text += '\nВозраст: '
            text += item1[name_column['child_age']] + ' '
        if item1[name_column['name']] != '':
            text += '\nСпособ брони:\n'
            text += item1[name_column['name']] + ' '
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML
    )
    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def write_list_of_waiting(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        text='Напишите контактный номер телефона',
        reply_markup=ReplyKeyboardRemove()
    )
    state = 'PHONE_FOR_WAITING'
    context.user_data['STATE'] = state
    return state


async def get_phone_for_waiting(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        await request_phone_number(update, phone)
        return context.user_data['STATE']

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['client_data']['phone'] = phone
    text = reserve_user_data['event_info_for_list_waiting'] + '+7' + phone

    user = context.user_data['user']
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Лист ожидания', None))
    text = f'#Лист_ожидания\n' \
           f'Пользователь @{user.username} {user.full_name}\n' \
           f'Запросил добавление в лист ожидания\n' + text
    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=text,
        parse_mode=ParseMode.HTML,
        message_thread_id=thread_id
    )
    write_client_list_waiting(context)
    await update.effective_chat.send_message(
        text='Вы добавлены в лист ожидания, '
             'если место освободится, то с вами свяжутся. '
             'Если у вас есть вопросы, вы можете связаться с Администратором:\n'
             f'{context.bot_data['admin']['contacts']}'
    )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state

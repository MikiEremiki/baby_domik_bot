import logging
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
from telegram.helpers import escape_markdown

from handlers.sub_hl import (
    request_phone_number,
    send_and_del_message_to_remove_kb,
    write_old_seat_info,
)
from db.db_googlesheets import (
    load_clients_data,
    load_show_data,
    load_ticket_data,
    load_list_show,
)
from utilities.googlesheets import (
    write_data_for_reserve,
    write_client,
    update_quality_of_seats
)
from utilities.utl_func import (
    extract_phone_number_from_text,
    add_btn_back_and_cancel,
    send_message_to_admin,
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

    reserve_hl_logger.info(f'Пользователь начал выбор месяца:'
                           f' {update.message.from_user}')

    context.user_data.setdefault('reserve_data', {})
    user = update.message.from_user

    message = await send_and_del_message_to_remove_kb(update)

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
            'К сожалению я сегодня на техническом обслуживании\n'
            'Но вы можете забронировать место по старинке в ЛС telegram или по '
            'телефону:\n'
            'Татьяна Бурганова @Tanya_domik +79159383529'
        )
        return ConversationHandler.END
    except TimeoutError:
        reserve_hl_logger.info(
            f'Для пользователя {user}')
        reserve_hl_logger.info(
            f'Обработчик завершился на этапе {state}')
        await update.effective_chat.send_message(
            'Произошел разрыв соединения, попробуйте еще раз\n'
            'Если проблема повторится вы можете забронировать место в ЛС '
            'telegram или по телефону:\n'
            'Татьяна Бурганова @Tanya_domik +79159383529'
        )
        return ConversationHandler.END

    list_of_months = sorted(set(int(item[3:5]) for item in
                                dict_of_date_show.keys()))

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
        reply_markup=reply_markup
    )

    context.user_data['user'] = user

    # Контекст для возврата назад
    context.user_data['text_month'] = text
    context.user_data['keyboard_month'] = reply_markup

    context.user_data['dict_of_shows'] = dict_of_shows
    context.user_data['dict_of_name_show'] = dict_of_name_show
    context.user_data['dict_of_name_show_flip'] = dict_of_name_show_flip
    context.user_data['dict_of_date_show'] = dict_of_date_show

    state = 'MONTH'
    context.user_data['STATE'] = state
    return state


async def choice_show_and_date(
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

    dict_of_name_show = context.user_data['dict_of_name_show']
    dict_of_date_show = context.user_data['dict_of_date_show']

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
            postfix_for_back='month'
        ))
        reply_markup = InlineKeyboardMarkup(keyboard)

        state = 'SHOW'
        context.user_data['text_show'] = text
        context.user_data['keyboard_show'] = reply_markup
    else:
        text = 'Выберите спектакль и дату\n'
        text = add_text_of_show_and_numerate(text,
                                             dict_of_name_show,
                                             filter_show_id)
        reply_markup = create_replay_markup_for_list_of_shows(
            dict_of_date_show,
            add_cancel_btn=True,
            postfix_for_cancel='res',
            postfix_for_back='month',
            number_of_month=number_of_month_str,
        )
        state = 'DATE'
        context.user_data['text_date'] = text
        context.user_data['keyboard_date'] = reply_markup

    photo = (
        context.bot_data
        .get('afisha', {})
        .get(int(number_of_month_str), False)
    )
    if update.effective_chat.type == ChatType.PRIVATE and photo:
        message = await update.effective_chat.send_photo(
            photo=photo,
            caption=text,
            reply_markup=reply_markup
        )
        context.user_data['afisha_media'] = [message]
    else:
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup
        )

    context.user_data['number_of_month_str'] = number_of_month_str

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

    dict_of_shows = context.user_data['dict_of_shows']
    dict_of_date_show = context.user_data['dict_of_date_show']
    dict_of_name_show_flip = context.user_data['dict_of_name_show_flip']
    number_of_month_str = context.user_data['number_of_month_str']
    name_of_show = dict_of_name_show_flip[int(query.data)]
    number_of_show = int(query.data)

    reply_markup = create_replay_markup_for_list_of_shows(
        dict_of_date_show,
        ver=3,
        add_cancel_btn=True,
        postfix_for_cancel='res',
        postfix_for_back='show',
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
        text += f'{SUPPORT_DATA["Подарок"][0]} - {SUPPORT_DATA["Подарок"][1]}\n'
    if flag_christmas_tree:
        text += f'{SUPPORT_DATA["Елка"][0]} - {SUPPORT_DATA["Елка"][1]}\n'
    if flag_santa:
        text += f'{SUPPORT_DATA["Дед"][0]} - {SUPPORT_DATA["Дед"][1]}\n'

    photo = (
        context.bot_data
        .get('afisha', {})
        .get(int(number_of_month_str), False)
    )
    if update.effective_chat.type == ChatType.PRIVATE and photo:
        message = await query.edit_message_caption(
            caption=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        context.user_data['afisha_media'] = [message]
    else:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

    # Контекст для возврата назад
    context.user_data['text_date'] = text
    context.user_data['keyboard_date'] = reply_markup

    state = 'DATE'
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
    context.user_data["STATE"] = 'DATE'

    key_of_name_show, date_show = query.data.split(' | ')
    key_of_name_show = int(key_of_name_show)

    dict_of_shows: dict = context.user_data['dict_of_shows']
    dict_of_name_show_flip = context.user_data['dict_of_name_show_flip']
    name_show: str = dict_of_name_show_flip[key_of_name_show]

    keyboard = []

    # Определение кнопок для inline клавиатуры с исключением вариантов где
    # свободных мест уже не осталось
    for key, item in dict_of_shows.items():
        if item['name_show'] == name_show and item['date_show'] == date_show:
            show_id = item['show_id']
            time = item['time_show']
            number = item['qty_child_free_seat']
            text = time
            text_emoji = ''
            if item['flag_gift']:
                text_emoji += f'{SUPPORT_DATA["Подарок"][0]}'
            if item['flag_christmas_tree']:
                text_emoji += f'{SUPPORT_DATA["Елка"][0]}'
            if item['flag_santa']:
                text_emoji += f'{SUPPORT_DATA["Дед"][0]}'
            text += text_emoji
            text += ' | ' + str(number) + ' шт свободно'
            button_tmp = InlineKeyboardButton(
                text=text,
                callback_data=time + ' | ' + str(key) + ' | ' + str(number)
            )
            keyboard.append([button_tmp])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='res',
                                            postfix_for_back='date'))
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
                 'и записаться в лист ожидания на данное время')

    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    context.user_data['date_show'] = date_show
    context.user_data['name_show'] = name_show
    context.user_data['show_id'] = int(show_id)

    # Контекст для возврата назад
    context.user_data['text_time'] = text
    context.user_data['keyboard_time'] = reply_markup

    if update.effective_chat.id == ADMIN_GROUP:
        return 'LIST'
    else:
        return 'TIME'


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
    context.user_data["STATE"] = 'TIME'

    time, row_in_googlesheet, number = query.data.split(' | ')
    date: str = context.user_data['date_show']

    context.user_data['row_in_googlesheet'] = row_in_googlesheet
    context.user_data['time_show'] = time

    dict_of_shows = context.user_data['dict_of_shows']
    event = dict_of_shows[int(row_in_googlesheet)]
    text_emoji = ''
    option = ''
    if event['flag_gift']:
        text_emoji += f'{SUPPORT_DATA["Подарок"][0]}'
        option = 'Подарок'
    if event['flag_christmas_tree']:
        text_emoji += f'{SUPPORT_DATA["Елка"][0]}'
        option = 'Ёлка'
    if event['flag_santa']:
        text_emoji += f'{SUPPORT_DATA["Дед"][0]}'
    if event['show_id'] == '10' or event['show_id'] == '8':
        option = 'Чтение'

    context.user_data['option'] = option
    context.user_data['text_emoji'] = text_emoji

    if int(number) == 0:
        reserve_hl_logger.info('Мест нет')

        name_show = context.user_data['name_show']
        text = (f'Вы выбрали:\n'
                f'<b>{name_show}\n'
                f'{date}\n'
                f'В {time}</b>\n'
                f'{text_emoji}\n')
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML
        )

        context.user_data['text_for_list_waiting'] = text
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
        return 'CHOOSING'

    availibale_number_of_seats_now = update_quality_of_seats(
        row_in_googlesheet, 'qty_child_free_seat')

    dict_of_shows: dict = load_list_show()
    show_id = context.user_data['show_id']
    flag_indiv_cost = False
    for key, item in dict_of_shows.items():
        if key == show_id:
            flag_indiv_cost = item['flag_indiv_cost']
            context.user_data['flag_indiv_cost'] = flag_indiv_cost

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
                                            postfix_for_back='time'))
    reply_markup = InlineKeyboardMarkup(keyboard)

    name_show = context.user_data['name_show']
    text = (f'Вы выбрали:\n'
            f'<b>{name_show}\n'
            f'{date}\n'
            f'В {time}</b>\n'
            f'{text_emoji}\n')
    text += 'Выберите подходящий вариант бронирования:\n'

    date_now = datetime.now().date()
    date_tmp = date.split()[0] + f'.{date_now.year}'
    date_for_price: datetime = datetime.strptime(date_tmp, f'%d.%m.%Y')
    context.user_data['date_for_price'] = date_for_price

    for i, ticket in enumerate(list_of_tickets):
        key = ticket.base_ticket_id
        name = ticket.name

        ticket.date_show = date  # Для расчета стоимости в периоде или нет
        price = ticket.price

        if flag_indiv_cost:
            if key // 100 == 1:
                if date_for_price.weekday() in range(5):
                    price = TICKET_COST[option]['будни'][key]
                else:
                    price = TICKET_COST[option]['выходные'][key]
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

    return 'ORDER'


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

    context.user_data['STATE'] = 'ORDER'

    try:
        key_option_for_reserve = int(query.data)
    except ValueError as e:
        reserve_hl_logger.error(e)
        text = '<i>Произошла ошибка. Выберите время еще раз</i>\n'
        text += context.user_data['text_time']
        reply_markup = context.user_data['keyboard_time']
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return 'TIME'

    date = context.user_data['date_show']
    time = context.user_data['time_show']
    name_show = context.user_data['name_show']
    flag_indiv_cost = context.user_data['flag_indiv_cost']
    option = context.user_data['option']
    text_emoji = context.user_data['text_emoji']
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
                    date_for_price = context.user_data['date_for_price']
                    if date_for_price.weekday() in range(5):
                        price = TICKET_COST[option]['будни'][key]
                    else:
                        price = TICKET_COST[option]['выходные'][key]

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            chose_ticket.name,
        ]
    ))

    # Если пользователь выбрал не стандартный вариант
    if chose_ticket.flag_individual:
        text = 'Для оформления данного варианта обращайтесь в ЛС в telegram ' \
               'или по телефону:\n Татьяна Бурганова @Tanya_domik +79159383529'
        await query.message.edit_text(
            text=text
        )

        reserve_hl_logger.info(
            f'Для пользователя {user}')
        reserve_hl_logger.info(
            f'Обработчик завершился на этапе {context.user_data["STATE"]}')
        context.user_data.clear()

        return ConversationHandler.END
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

        context.user_data['text_for_notification_massage'] = text

        await query.message.edit_text(
            text=text
        )
        message = await update.effective_chat.send_message(
            'Проверяю наличие свободных мест...')
        # Номер строки для извлечения актуального числа доступных мест
        row_in_googlesheet = context.user_data['row_in_googlesheet']

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
            context.user_data['text_for_list_waiting'] = text
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
            return 'CHOOSING'
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

                text = 'К сожалению произошла непредвиденная ошибка\n' \
                       'Нажмите "Назад" и выберите время повторно.\n' \
                       'Если ошибка повторяется напишите в ЛС в telegram или ' \
                       'по телефону:\n' \
                       'Татьяна Бурганова @Tanya_domik +79159383529'
                await query.message.edit_text(
                    text=text,
                    reply_markup=reply_markup
                )
                return 'ORDER'

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
Но вы не переживайте, если вдруг вы не сможете придти, просто сообщите нам об этом за 24 часа, мы перенесём вашу дату визита. 

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

        context.user_data['chose_ticket'] = chose_ticket
        context.user_data['chose_price'] = price
        context.user_data['message_id'] = message.message_id

        context.user_data['dict_of_shows'].clear()
        context.user_data['dict_of_name_show_flip'].clear()

    return 'PAID'


async def forward_photo_or_file(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Пересылает картинку или файл.
    Запускает цепочку вопросов для клиентской базы, если пользователь нажал
    кнопку подтвердить.
    """
    context.user_data['STATE'] = 'PAID'

    message_id = context.user_data['message_id']
    chat_id = update.effective_chat.id

    # Убираем у старого сообщения кнопки
    await context.bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=message_id
    )

    user = context.user_data['user']
    text = context.user_data['text_for_notification_massage']

    res = await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=f'#Бронирование\n'
             f'Квитанция пользователя @{user.username} {user.full_name}\n'
    )
    await update.effective_message.forward(
        chat_id=ADMIN_GROUP,
    )
    message_id_for_admin = res.message_id
    await send_message_to_admin(ADMIN_GROUP,
                                text,
                                message_id_for_admin,
                                context)

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
    reply_markup = create_approve_and_reject_replay(
        'reserve',
        update.effective_user.id,
        message_id
    )

    chose_price = context.user_data['chose_price']

    message = await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=f'Пользователь @{user.username} {user.full_name}\n'
             f'Запросил подтверждение брони на сумму {chose_price} руб\n'
             f'Ждем заполнения анкеты, если всё хорошо, то только после '
             f'нажимаем подтвердить',
        reply_markup=reply_markup
    )

    context.user_data['message_id_for_admin'] = message.message_id

    return 'FORMA'


async def get_name_adult(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["STATE"] = 'PHONE'

    text = update.effective_message.text

    context.user_data['client_data'] = {}
    context.user_data['client_data']['name_adult'] = text

    await update.effective_chat.send_message(
        text='Напишите контактный номер телефона'
    )

    return 'PHONE'


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["STATE"] = 'PHONE'

    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        await request_phone_number(update, phone)
        return 'PHONE'

    context.user_data['client_data']['phone'] = phone

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

    return 'CHILDREN'


async def get_name_children(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["STATE"] = 'CHILDREN'

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
        return 'CHILDREN'

    reserve_hl_logger.info('Проверка пройдена успешно')

    list_message_text = []
    if '\n' in text:
        message_text = text.split('\n')
        for item in message_text:
            list_message_text.append(item.split())
    else:
        message_text = text.split()
        list_message_text.append(message_text)

    chose_ticket = context.user_data['chose_ticket']
    chose_price = context.user_data['chose_price']
    if not isinstance(list_message_text[0], list):
        await update.effective_chat.send_message(f'Вы ввели:\n{text}')
        await update.effective_chat.send_message(text=text_for_message)
        return 'CHILDREN'
    if len(list_message_text) != chose_ticket.quality_of_children:
        await update.effective_chat.send_message(
            f'Кол-во детей, которое определено: {len(list_message_text)}\n'
            f'Кол-во детей, согласно выбранному билету: '
            f'{chose_ticket.quality_of_children}\n'
            f'Повторите ввод еще раз, проверьте что каждый ребенок на '
            f'отдельной строке.\n\nНапример:\nИван 1\nСергей 01.01.2000')
        return 'CHILDREN'

    context.user_data['client_data']['data_children'] = list_message_text

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'отправил:',
        ],
    ))
    reserve_hl_logger.info(context.user_data['client_data'])

    write_client(
        context.user_data['client_data'],
        context.user_data['row_in_googlesheet'],
        context.user_data['chose_ticket'],
        context.user_data['chose_price'],
    )

    text = '\n'.join([
        context.user_data['client_data']['name_adult'],
        '+7' + context.user_data['client_data']['phone'],
        text,
    ])
    message_id_for_admin = context.user_data['message_id_for_admin']

    # Возникла ошибка, когда сообщение удалено, то бот по кругу находится в
    # 'CHILDREN' state, написал обходной путь для этого
    await send_message_to_admin(ADMIN_GROUP,
                                text,
                                message_id_for_admin,
                                context)

    await update.effective_chat.send_message(
        'Благодарим за ответы.\nОжидайте, когда администратор подтвердить '
        'бронь.\nЕсли всё хорошо, то вам придет сообщение: "Ваша бронь '
        'подтверждена"\n'
        'В противном случае с вами свяжутся для уточнения деталей')

    text = context.user_data['text_for_notification_massage']
    text += f"""__________
Место проведения:
Офис-центр Малая Покровская, д18, 2 этаж
__________
По вопросам обращайтесь в ЛС в telegram или по телефону:
Татьяна Бурганова @Tanya_domik +79159383529
__________
Если вы хотите оформить еще одну бронь, используйте команду /{COMMAND_DICT[
        "RESERVE"][0]}"""
    message = await update.effective_chat.send_message(
        text=text
    )
    await message.pin()

    reserve_hl_logger.info(f'Для пользователя {user}')
    reserve_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data["STATE"]}')

    return ConversationHandler.END


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
    if context.user_data['STATE'] == 'ORDER':
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, бронь отменена, пожалуйста выполните '
            'новый запрос'
        )

        chose_ticket = context.user_data['chose_ticket']

        # Номер строки для извлечения актуального числа доступных мест
        row_in_googlesheet = context.user_data['row_in_googlesheet']

        await write_old_seat_info(update,
                                  user,
                                  row_in_googlesheet,
                                  chose_ticket)
    else:
        # TODO Прописать дополнительную обработку states, для этапов опроса
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос'
        )

    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            f'AFK уже {RESERVE_TIMEOUT} мин'
        ]
    ))
    reserve_hl_logger.info(f'Для пользователя {user}')
    reserve_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data["STATE"]}')

    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)


async def send_clients_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    name = context.user_data['name_show']
    date = context.user_data['date_show']
    show_id = context.user_data['show_id']
    time = query.data.split(' | ')[0]

    clients_data, name_column = load_clients_data(show_id, date, time)
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
    return ConversationHandler.END


async def write_list_of_waiting(
        update: Update,
        _: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        text='Напишите контактный номер телефона',
        reply_markup=ReplyKeyboardRemove()
    )
    return 'PHONE_FOR_WAITING'


async def get_phone_for_waiting(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        await request_phone_number(update, phone)
        return 'PHONE'

    text = context.user_data['text_for_list_waiting'] + '+7' + phone

    user = context.user_data['user']
    text = f'#Лист_ожидания\n' \
           f'Пользователь @{user.username} {user.full_name}\n' \
           f'Запросил добавление в лист ожидания\n' + text
    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=text,
    )
    await update.effective_chat.send_message(
        text="""Вы добавлены в лист ожидания, если место освободится, то с вами свяжутся.
    Если у вас есть вопросы, вы можете связаться самостоятельно в telegram @Tanya_domik или по телефону +79159383529"""
    )

    return ConversationHandler.END

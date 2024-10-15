from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import BaseTicket, ScheduleEvent
from settings.settings import (
    DICT_OF_EMOJI_FOR_BUTTON, DICT_CONVERT_WEEKDAY_NUMBER_TO_STR,
    SUPPORT_DATA, DICT_CONVERT_MONTH_NUMBER_TO_STR)
from utilities import add_btn_back_and_cancel
from utilities.utl_func import get_time_with_timezone
from utilities.utl_ticket import get_spec_ticket_price


def adjust_kbd(keyboard: list, size: int = 8):
    markup = []
    row = []
    for button in keyboard:
        if len(row) >= size:
            markup.append(row)
            row = []
        row.append(button)
    if row:
        markup.append(row)

    return markup


async def create_kbd_and_text_tickets_for_choice(
        context,
        text,
        base_tickets_filtered,
        schedule_event,
        theater_event,
        date_for_price
):
    flag_indiv_cost_sep = False
    keyboard = []
    for i, ticket in enumerate(base_tickets_filtered):
        ticket: BaseTicket
        ticket_id = ticket.base_ticket_id
        name_ticket = ticket.name
        price, price_privilege = await get_spec_ticket_price(context,
                                                             ticket,
                                                             schedule_event,
                                                             theater_event,
                                                             date_for_price)

        if 8 > ticket_id // 100 >= 3 and not flag_indiv_cost_sep:
            text += "__________\n    Варианты со скидками:\n"
            flag_indiv_cost_sep = True

        text += (f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]} {name_ticket} | '
                 f'{price} руб\n')

        button_tmp = InlineKeyboardButton(
            text=f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]}',
            callback_data=str(ticket_id)
        )
        keyboard.append(button_tmp)
    return keyboard, text


async def create_kbd_schedule_and_date(schedule_events_filter_by_month,
                                       enum_theater_events):
    checked_event = {}

    keyboard = []
    for event in schedule_events_filter_by_month:
        event: ScheduleEvent
        tmp_checked_event_by_type = checked_event.setdefault(
            event.theater_event_id, [])
        if (
                event.datetime_event.date() in tmp_checked_event_by_type
        ):
            continue
        index = 1
        for i, theater_event in enum_theater_events:
            if event.theater_event_id == theater_event.id:
                index = i
        weekday = int(event.datetime_event.strftime('%w'))
        button_tmp = InlineKeyboardButton(
            text=DICT_OF_EMOJI_FOR_BUTTON[index] +
                 event.datetime_event.strftime('%d.%m ') +
                 f'({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]})',
            callback_data=str(event.theater_event_id) + '|' +
                          event.datetime_event.date().isoformat()
        )
        keyboard.append(button_tmp)

        tmp_checked_event_by_type.append(event.datetime_event.date())
    return keyboard


async def create_kbd_schedule(enum_theater_events):
    keyboard = []
    for i, theater_event in enum_theater_events:
        button_tmp = InlineKeyboardButton(
            text=DICT_OF_EMOJI_FOR_BUTTON[i],
            callback_data=str(theater_event.id)
        )
        keyboard.append(button_tmp)
    return keyboard


async def create_kbd_for_time_in_studio(schedule_events):
    keyboard = []
    for event in schedule_events:
        qty_child = event.qty_child_free_seat
        if int(qty_child) < 0:
            qty_child = 0

        text = await get_time_with_timezone(event)
        text += ' | ' + str(qty_child) + ' дет'

        callback_data = event.id
        button_tmp = InlineKeyboardButton(
            text=text,
            callback_data=callback_data
        )
        keyboard.append(button_tmp)
    return keyboard


async def create_kbd_for_time_in_reserve(schedule_events):
    keyboard = []
    for event in schedule_events:
        qty_child = event.qty_child_free_seat
        qty_adult = event.qty_adult_free_seat
        if int(qty_child) < 0:
            qty_child = 0
        if int(qty_adult) < 0:
            qty_adult = 0

        text_emoji = ''
        if event.flag_gift:
            text_emoji += f'{SUPPORT_DATA['Подарок'][0]}'
        if event.flag_christmas_tree:
            text_emoji += f'{SUPPORT_DATA['Елка'][0]}'
        if event.flag_santa:
            text_emoji += f'{SUPPORT_DATA['Дед'][0]}'

        text = await get_time_with_timezone(event)
        text += text_emoji
        text += ' | ' + str(qty_child) + ' дет'
        text += ' | ' + str(qty_adult) + ' взр'

        callback_data = event.id
        button_tmp = InlineKeyboardButton(
            text=text,
            callback_data=callback_data
        )
        keyboard.append(button_tmp)
    return keyboard


async def create_kbd_with_months(months):
    keyboard = []
    for item in months:
        button_tmp = InlineKeyboardButton(
            text=DICT_CONVERT_MONTH_NUMBER_TO_STR[item],
            callback_data=str(item)
        )
        keyboard.append(button_tmp)

    return keyboard


def create_kbd_crud(name: str):
    button_create = InlineKeyboardButton(text='Добавить',
                                         callback_data=f'{name}_create')
    button_update = InlineKeyboardButton(text='Изменить',
                                         callback_data=f'{name}_update')
    button_delete = InlineKeyboardButton(text='Удалить',
                                         callback_data=f'{name}_delete')
    button_select = InlineKeyboardButton(text='Посмотреть',
                                         callback_data=f'{name}_select')
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back='2')
    keyboard = [
        [button_create, ],
        [button_update, ],
        [button_delete, ],
        [button_select, ],
        [*button_cancel, ],
    ]

    return InlineKeyboardMarkup(keyboard)


def create_kbd_confirm():
    button_accept = InlineKeyboardButton(text='Подтвердить',
                                         callback_data='accept')
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=False)
    keyboard = [
        [button_accept, ],
        [*button_cancel, ],
    ]

    return InlineKeyboardMarkup(keyboard)


async def create_replay_markup(
        keyboard,
        add_cancel_btn: bool = True,
        postfix_for_cancel: Any = None,
        add_back_btn: bool = True,
        postfix_for_back: Any = None,
        size_row: int = 8
):
    keyboard = adjust_kbd(keyboard, size_row)
    keyboard.append(
        add_btn_back_and_cancel(add_cancel_btn=add_cancel_btn,
                                postfix_for_cancel=postfix_for_cancel,
                                add_back_btn=add_back_btn,
                                postfix_for_back=postfix_for_back)
    )
    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup


async def create_email_confirm_btn(text, email):
    email_confirm_btn = None
    if email:
        text += f'Последний введенный email:\n<code>{email}</code>\n\n'
        text += 'Использовать последнюю введенную почту?'
        email_confirm_btn = [
            InlineKeyboardButton('Да', callback_data='email_confirm')]
    return email_confirm_btn, text


def create_kbd_with_number_btn(
        qty_btn,
        num_colum=8,
):
    """
    Создает inline клавиатуру
    :param qty_btn: диапазон кнопок
    :param num_colum: Кол-во кнопок в строке, по умолчанию 8
    :return: InlineKeyboardMarkup
    """
    # Определение кнопок для inline клавиатуры
    keyboard = []
    list_btn_of_numbers = []

    i = 0
    for num in range(qty_btn):
        button_tmp = InlineKeyboardButton(str(num + 1),
                                          callback_data=str(num + 1))
        list_btn_of_numbers.append(button_tmp)

        i += 1
        # Две кнопки в строке так как для узких экранов телефонов дни недели
        # обрезаются
        if i % num_colum == 0:
            i = 0
            keyboard.append(list_btn_of_numbers)
            list_btn_of_numbers = []
    if len(list_btn_of_numbers):
        keyboard.append(list_btn_of_numbers)

    return keyboard

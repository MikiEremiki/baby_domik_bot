import random
import string
import time
from typing import Any, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import BaseTicket, ScheduleEvent
from settings.settings import (
    DICT_OF_EMOJI_FOR_BUTTON, DICT_CONVERT_WEEKDAY_NUMBER_TO_STR,
    SUPPORT_DATA, DICT_CONVERT_MONTH_NUMBER_TO_STR)
from utilities.utl_func import (
    get_time_with_timezone, get_formatted_date_and_time_of_event)
from utilities.utl_ticket import get_spec_ticket_price

_ID_SYMS = string.digits + string.ascii_letters
CB_SEP = '|'


def new_int_id() -> int:
    return int(time.time()) % 100000000 + random.randint(0, 99) * 100000000


def id_to_str(int_id: int) -> str:
    if not int_id:
        return _ID_SYMS[0]
    base = len(_ID_SYMS)
    res = ""
    while int_id:
        int_id, mod = divmod(int_id, base)
        res += _ID_SYMS[mod]
    return res


def new_id():
    return id_to_str(new_int_id())


def intent_callback_data(
        intent_id: str, callback_data: Optional[str],
) -> Optional[str]:
    if callback_data is None:
        return None
    prefix = intent_id + CB_SEP
    if callback_data.startswith(prefix):
        return callback_data
    return prefix + callback_data


def add_intent_id(keyboard: List[List[InlineKeyboardButton]], intent_id: str):
    new_keyboard = []
    for row in keyboard:
        new_row = []
        for button in row:
            if isinstance(button, InlineKeyboardButton):
                new_callback_data = intent_callback_data(
                    intent_id, str(button.callback_data))
                new_row.append(
                    InlineKeyboardButton(
                        button.text, callback_data=new_callback_data))
        new_keyboard.append(new_row)
    return new_keyboard


def remove_intent_id(callback_data: str) -> Tuple[Optional[str], str]:
    if CB_SEP in callback_data:
        intent_id, new_data = callback_data.split(CB_SEP, maxsplit=1)
        return intent_id, new_data
    return None, callback_data


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


def add_btn_back_and_cancel(
        add_cancel_btn=True,
        postfix_for_cancel=None,
        add_back_btn=True,
        postfix_for_back=None
) -> List[InlineKeyboardButton]:
    """
    :param add_cancel_btn: Опциональное добавление кнопки Отменить.
    :param add_back_btn: Опциональное добавление кнопки Назад
    :param postfix_for_cancel: Добавление дополнительной приписки для
    корректного определения случая при использовании Отменить.
    :param postfix_for_back: Добавление дополнительной приписки для
    корректного определения случая при использовании Назад
    :return: List[InlineKeyboardButton]
    """
    keyboard = []
    if add_back_btn:
        keyboard.append(
            create_btn('Назад', postfix_for_back))
    if add_cancel_btn:
        keyboard.append(
            create_btn('Отменить', postfix_for_cancel))
    return keyboard


def create_btn(text, postfix_for_callback, intent_id: str | None = None):
    callback_data = text
    if postfix_for_callback:
        callback_data += f'-{postfix_for_callback}'
    if intent_id:
        callback_data = intent_callback_data(intent_id, str(callback_data))
    btn = InlineKeyboardButton(text=text, callback_data=callback_data)
    return btn


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
        if event.datetime_event.date() in tmp_checked_event_by_type:
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


async def create_kbd_for_date_in_reserve(schedule_events: List[ScheduleEvent]):
    keyboard = []
    checked_event = []
    for i, event in enumerate(schedule_events, start=1):
        date = event.datetime_event.date()
        if event.datetime_event.date() in checked_event:
            continue
        checked_event.append(date)

        text_emoji = ''
        if event.flag_gift:
            text_emoji += f'{SUPPORT_DATA['Подарок'][0]}'
        if event.flag_christmas_tree:
            text_emoji += f'{SUPPORT_DATA['Елка'][0]}'
        if event.flag_santa:
            text_emoji += f'{SUPPORT_DATA['Дед'][0]}'

        date_event, time_event = await get_formatted_date_and_time_of_event(
            event)
        text = f'{date_event}'
        text += text_emoji

        button_tmp = InlineKeyboardButton(
            text=text,
            callback_data=str(event.theater_event_id) + '|' +
                          event.datetime_event.date().isoformat()
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
        keyboard: List[InlineKeyboardButton],
        intent_id: str,
        add_cancel_btn: bool = True,
        postfix_for_cancel: Any = None,
        add_back_btn: bool = True,
        postfix_for_back: Any = None,
        size_row: int = 8
):
    keyboard = adjust_kbd(keyboard, size_row)
    keyboard = add_intent_id(keyboard, intent_id)
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


def create_kbd_with_number_btn(qty_btn):
    keyboard = []

    for num in range(qty_btn):
        keyboard.append(
            InlineKeyboardButton(str(num + 1), callback_data=str(num + 1)))

    return keyboard

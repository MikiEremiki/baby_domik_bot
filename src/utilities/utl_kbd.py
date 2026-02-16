import random
import string
import time
from typing import Any, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import BaseTicket, ScheduleEvent
from settings.settings import (
    DICT_OF_EMOJI_FOR_BUTTON, DICT_CONVERT_WEEKDAY_NUMBER_TO_STR,
    DICT_CONVERT_MONTH_NUMBER_TO_STR)
from utilities.utl_func import (
    get_time_with_timezone, get_formatted_date_and_time_of_event, get_emoji)
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
        theater_event
):
    flag_indiv_cost_sep = False
    keyboard = []
    for i, ticket in enumerate(base_tickets_filtered):
        ticket: BaseTicket
        ticket_id = ticket.base_ticket_id
        name_ticket = ticket.name
        price, price_privilege = await get_spec_ticket_price(
            context, ticket, schedule_event, theater_event)

        if 8 > ticket_id // 100 >= 3 and not flag_indiv_cost_sep:
            text += "__________<br>    Варианты со скидками:<br>"
            flag_indiv_cost_sep = True

        text += (f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]} {name_ticket} | '
                 f'{price} руб<br>')

        button_tmp = InlineKeyboardButton(
            text=f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]}',
            callback_data=str(ticket_id)
        )
        keyboard.append(button_tmp)
    return keyboard, text


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

        text_emoji = await get_emoji(event)

        date_event, time_event = await get_formatted_date_and_time_of_event(
            event)
        text = f'{date_event}'
        text += text_emoji

        button_tmp = InlineKeyboardButton(
            text=text,
            callback_data=event.datetime_event.date().isoformat()
        )
        keyboard.append(button_tmp)
    return keyboard


async def create_kbd_unique_dates(schedule_events: List[ScheduleEvent]):
    """
    Создает список уникальных дат (без привязки к спектаклям) для выбранного месяца.
    callback_data = ISO-дата (YYYY-MM-DD)
    """
    keyboard: List[InlineKeyboardButton] = []
    seen_dates = []
    for event in schedule_events:
        d = event.datetime_event.date()
        if d in seen_dates:
            continue
        seen_dates.append(d)
        weekday = int(event.datetime_event.strftime('%w'))
        text = d.strftime('%d.%m ') + f"({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]})"
        keyboard.append(InlineKeyboardButton(text=text, callback_data=d.isoformat()))
    return keyboard


async def create_kbd_for_time_by_date(schedule_events: List[ScheduleEvent], enum_theater_events):
    """
    Создает клавиатуру вариантов (спектакль + время) для выбранной даты.
    Каждая кнопка соответствует конкретному событию расписания (schedule_event.id)
    и отображает эмодзи спектакля, время и кол-во мест.
    """
    # Сопоставление спектакль -> индекс эмодзи
    index_map = {}
    for i, theater_event in enum_theater_events:
        index_map[theater_event.id] = i

    keyboard: List[InlineKeyboardButton] = []
    for event in schedule_events:
        # Эмодзи спектакля по индексу
        idx = index_map.get(event.theater_event_id, 1)
        prefix = DICT_OF_EMOJI_FOR_BUTTON.get(idx, '') + ' '

        # Эмодзи подарков/ёлок/Дед Мороз
        text_emoji = await get_emoji(event)

        # Время + кол-во мест
        time_txt = await get_time_with_timezone(event)
        qty_child = max(int(event.qty_child_free_seat), 0)
        qty_adult = max(int(event.qty_adult_free_seat), 0)
        text = prefix + time_txt + text_emoji + f' | {qty_child} дет | {qty_adult} взр'

        keyboard.append(
            InlineKeyboardButton(text=text, callback_data=event.id)
        )
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

        text_emoji = await get_emoji(event)

        text = await get_time_with_timezone(event)
        text += text_emoji
        text += f' | {qty_child} дет'
        text += f' | {qty_adult} взр'

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


async def create_phone_confirm_btn(text, phone: str):
    """
    Если phone есть (10 цифр без +7), добавляет в текст сообщение о последнем
    введенном телефоне и возвращает ряд кнопок с подтверждением.
    'callback_data' содержит сам телефон: 'phone_confirm|{phone}'
    """
    phone_confirm_btn = None
    if phone:
        pretty_phone = f'+7{phone}' if not phone.startswith('+7') else phone
        text += f'Последний введенный телефон:<br><code>{pretty_phone}</code><br><br>'
        text += 'Использовать последний введенный телефон?'
        phone_confirm_btn = [
            InlineKeyboardButton('Да', callback_data=f'phone_confirm|{phone}')
        ]
    return phone_confirm_btn, text


async def create_adult_confirm_btn(text, adult_name: str):
    """
    Если adult есть, добавляет в текст сообщение о последнем
    введенном телефоне и возвращает ряд кнопок с подтверждением.
    callback_data содержит сам телефон: 'adult_confirm|{adult}'
    """
    adult_confirm_btn = None
    if adult_name:
        text += f'Последнее введенное имя взрослого:\n<code>{adult_name}</code>\n\n'
        text += 'Использовать последнее введенное имя?'
        adult_confirm_btn = [
            InlineKeyboardButton('Да', callback_data=f'adult_confirm')
        ]
    return adult_confirm_btn, text


def create_kbd_with_number_btn(qty_btn):
    keyboard = []

    for num in range(qty_btn):
        keyboard.append(
            InlineKeyboardButton(str(num + 1), callback_data=str(num + 1)))

    return keyboard




def create_kbd_edit_children(children, page=0, selected_children=None, limit=1):
    """
    Создает клавиатуру для редактирования и выбора детей.
    """
    if selected_children is None:
        selected_children = []

    keyboard = []
    items_per_page = 10
    start = page * items_per_page
    end = start + items_per_page

    page_children = children[start:end]

    for i, child in enumerate(page_children):
        actual_index = start + i
        name = child[0]
        age = int(child[1])
        person_id = child[2]

        is_selected = actual_index in selected_children
        mark = "✅" if is_selected else "☐"

        keyboard.append([
            InlineKeyboardButton(
                mark,
                callback_data=f"CHLD_SEL|{actual_index}"
            ),
            InlineKeyboardButton(
                f"{name} {age}",
                callback_data=f"CHLD_EDIT_ONE|{actual_index}"
            ),
            InlineKeyboardButton(
                "❌",
                callback_data=f"CHLD_DEL|{person_id}"
            )
        ])

    # Пагинация
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(
            "⬅️",
            callback_data=f"CHLD_EDIT_PAGE|{page - 1}"))

    if end < len(children):
        pagination_row.append(InlineKeyboardButton(
            "➡️",
            callback_data=f"CHLD_EDIT_PAGE|{page + 1}"))

    if pagination_row:
        keyboard.append(pagination_row)

    # Кнопки действия
    keyboard.append([InlineKeyboardButton(
        "➕ Добавить ребенка",
        callback_data="CHLD_ADD")])

    # Кнопка подтверждения
    if len(selected_children) == limit:
        keyboard.append([InlineKeyboardButton(
            "Подтвердить выбор",
            callback_data="CHLD_CONFIRM")])

    return keyboard

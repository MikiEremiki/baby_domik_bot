"""Keyboard builders for /tickets_admin."""
from __future__ import annotations

from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db.enum import TicketStatus
from utilities.utl_kbd import add_btn_back_and_cancel


def ticket_card_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления в карточке билета, по 2 в ряд."""
    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton('Статус', callback_data=f'ta:status:{ticket_id}'),
         InlineKeyboardButton('Email', callback_data=f'ta:email:{ticket_id}')],
        [InlineKeyboardButton('Телефон', callback_data=f'ta:phone:{ticket_id}'),
         InlineKeyboardButton('Примечание', callback_data=f'ta:notes:{ticket_id}')],
        [InlineKeyboardButton('Базовый', callback_data=f'ta:base:{ticket_id}'),
         InlineKeyboardButton('Покупатель', callback_data=f'ta:buyer:{ticket_id}')],
        [InlineKeyboardButton('Билеты покупателя', callback_data=f'ta:buyer_tickets:{ticket_id}'),
         InlineKeyboardButton('🧾 Чек', callback_data=f'ta:receipt:{ticket_id}')],
        [InlineKeyboardButton('Перенести', callback_data=f'ta:transfer:{ticket_id}')],
        add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='MENU',
            add_back_btn=True,
        ),
    ]
    return InlineKeyboardMarkup(keyboard)


def status_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора статуса."""
    rows: List[List[InlineKeyboardButton]] = []
    current_row: List[InlineKeyboardButton] = []
    for status in TicketStatus:
        current_row.append(InlineKeyboardButton(
            status.value, callback_data=f'ta:set_status:{status.value}'))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append(add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='TICKET_CARD',
        add_back_btn=True,
    ))
    return InlineKeyboardMarkup(rows)


def email_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Кнопки для редактирования email."""
    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton('Очистить', callback_data=f'ta:clear_email:{ticket_id}')],
        add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='TICKET_CARD',
            add_back_btn=True,
        ),
    ]
    return InlineKeyboardMarkup(keyboard)

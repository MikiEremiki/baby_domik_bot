"""Callback handlers for /tickets_admin."""
from __future__ import annotations

from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import db_postgres
from utilities.utl_func import set_back_context
from utilities.utl_kbd import add_btn_back_and_cancel
from sulguk import transform_html
from handlers.receipt_hl import show_receipt_to_chat

from .constants import (
    MENU, SEARCH_USER, SEARCH_TICKET_ID, SEARCH_CONTACT_PHONE,
    STATUS_PICK, INPUT_EMAIL, INPUT_PHONE, INPUT_NOTES, NOTES_MODE,
    INPUT_BASE_TICKET, TICKET_CARD, TICKET_LIST,
)
from .keyboards import status_keyboard, email_keyboard
from .display import show_ticket_card
from .ticket_list import show_compact_ticket_list
from .buyer import show_buyer_card, show_buyer_tickets
from .status import set_ticket_status
from .transfer import cb_transfer_start


async def edit_and_set_state(
    query,
    context: 'ContextTypes.DEFAULT_TYPE',
    state: str,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> int:
    """Common pattern: edit message, set back context, set state."""
    res = transform_html(text)
    await query.edit_message_text(
        text=res.text, entities=res.entities,
        reply_markup=reply_markup, parse_mode=None)
    await set_back_context(context, state, res.text, reply_markup)
    context.user_data['STATE'] = state
    return state


# ── Menu callbacks ──────────────────────────────────────────────────────────

async def cb_search_user(query, context: 'ContextTypes.DEFAULT_TYPE') -> int:
    """Show prompt for searching by user."""
    text = 'Введите user_id или @username пользователя:'
    keyboard = add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='MENU',
        add_back_btn=True,
    )
    return await edit_and_set_state(query, context, SEARCH_USER, text,
                                    InlineKeyboardMarkup([keyboard]))


async def cb_search_ticket(query, context: 'ContextTypes.DEFAULT_TYPE') -> int:
    """Show prompt for searching by ticket ID."""
    text = 'Введите ID билета:'
    keyboard = add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        add_back_btn=False,
    )
    return await edit_and_set_state(query, context, SEARCH_TICKET_ID, text,
                                    InlineKeyboardMarkup([keyboard]))


async def cb_search_contact(query, context: 'ContextTypes.DEFAULT_TYPE') -> int:
    """Show prompt for searching by contacts."""
    text = 'Введите телефон (10 цифр без +7) и/или email:<br><br>Оставьте поле пустым, если не нужно искать по нему.'
    keyboard = add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='MENU',
        add_back_btn=True,
    )
    context.user_data['tickets_admin']['search_contact_email'] = None
    return await edit_and_set_state(query, context, SEARCH_CONTACT_PHONE, text,
                                    InlineKeyboardMarkup([keyboard]))


async def cb_status(query, context: 'ContextTypes.DEFAULT_TYPE', ticket_id: int) -> int:
    """Show status picker."""
    text = 'Выберите новый статус:'
    return await edit_and_set_state(query, context, STATUS_PICK, text,
                                    status_keyboard())


async def cb_email(query, context: 'ContextTypes.DEFAULT_TYPE', ticket_id: int) -> int:
    """Show email input prompt."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    current = ticket.email if ticket else '—'
    text = f'Текущий email: {current}<br><br>Введите новый email:'
    return await edit_and_set_state(query, context, INPUT_EMAIL, text,
                                    email_keyboard(ticket_id))


async def cb_phone(query, context: 'ContextTypes.DEFAULT_TYPE', ticket_id: int) -> int:
    """Show phone input prompt."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    current = f'+7{ticket.phone}' if ticket and ticket.phone else '—'
    text = f'Текущий телефон: {current}<br><br>Введите новый телефон (10 цифр без +7):'
    keyboard = add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='TICKET_CARD',
        add_back_btn=True,
    )
    return await edit_and_set_state(query, context, INPUT_PHONE, text,
                                    InlineKeyboardMarkup([keyboard]))


async def cb_notes(query, context: 'ContextTypes.DEFAULT_TYPE', ticket_id: int) -> int:
    """Show notes edit prompt — either mode choice or direct input."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    context.user_data['tickets_admin']['ticket_id'] = ticket_id

    if ticket.notes:
        current = ticket.notes.replace('\n', '<br>')
        text = f'Текущее примечание:<br><code>{current}</code><br><br>Что сделать?'
        keyboard: List[List[InlineKeyboardButton]] = [
            [InlineKeyboardButton('Дополнить', callback_data='ta:notes_mode:append'),
             InlineKeyboardButton('Перезаписать', callback_data='ta:notes_mode:replace')],
            [InlineKeyboardButton('Удалить', callback_data=f'ta:clear_notes:{ticket_id}')],
            add_btn_back_and_cancel(
                postfix_for_cancel='tickets_admin',
                postfix_for_back='TICKET_CARD',
                add_back_btn=True,
            ),
        ]
        return await edit_and_set_state(query, context, NOTES_MODE, text,
                                        InlineKeyboardMarkup(keyboard))
    else:
        text = 'Примечание отсутствует.<br><br>Введите примечание:'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='TICKET_CARD',
            add_back_btn=True,
        )
        context.user_data['tickets_admin']['notes_mode'] = 'replace'
        return await edit_and_set_state(query, context, INPUT_NOTES, text,
                                        InlineKeyboardMarkup([keyboard]))


async def cb_notes_mode(query, context: 'ContextTypes.DEFAULT_TYPE', mode: str) -> int:
    """Save notes mode (append/replace) and show input prompt."""
    context.user_data['tickets_admin']['notes_mode'] = mode
    label = 'Дополните' if mode == 'append' else 'Введите новое'
    text = f'{label} примечание:'
    keyboard = add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='TICKET_CARD',
        add_back_btn=True,
    )
    return await edit_and_set_state(query, context, INPUT_NOTES, text,
                                    InlineKeyboardMarkup([keyboard]))


async def cb_base(query, context: 'ContextTypes.DEFAULT_TYPE', ticket_id: int) -> int:
    """Show base ticket input prompt."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    base_ticket = await db_postgres.get_base_ticket(
        context.session, ticket.base_ticket_id) if ticket else None
    current = f'{base_ticket.base_ticket_id} ({base_ticket.name})' if base_ticket else '—'
    text = f'Текущий базовый билет: {current}<br><br>Введите номер нового базового билета:'
    keyboard = add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='TICKET_CARD',
        add_back_btn=True,
    )
    return await edit_and_set_state(query, context, INPUT_BASE_TICKET, text,
                                    InlineKeyboardMarkup([keyboard]))


async def cb_toggle_filter(update: Update, context: 'ContextTypes.DEFAULT_TYPE') -> int:
    """Toggle relevant/all filter on ticket list."""
    all_tickets = context.user_data['tickets_admin'].get('ticket_list_all', [])
    header = context.user_data['tickets_admin'].get('ticket_list_header', 'Билеты')
    current_filter = context.user_data['tickets_admin'].get('ticket_list_relevant_filter', True)
    return await show_compact_ticket_list(update, context, all_tickets, header,
                                          page=0, relevant_filter=not current_filter)


async def cb_page(query, context: 'ContextTypes.DEFAULT_TYPE',
                  page: int, update: Update) -> int:
    """Navigate to a specific page in ticket list."""
    tickets = context.user_data['tickets_admin'].get('ticket_list_all', [])
    header = context.user_data['tickets_admin'].get('ticket_list_header', 'Билеты')
    relevant_filter = context.user_data['tickets_admin'].get('ticket_list_relevant_filter', True)
    return await show_compact_ticket_list(
        update, context, tickets, header, page, relevant_filter)


async def cb_clear_email(query, context: 'ContextTypes.DEFAULT_TYPE',
                         ticket_id: int, update: Update) -> int:
    """Clear email on ticket and show card."""
    await db_postgres.update_ticket(context.session, ticket_id, email=None)
    await query.answer('Email очищен')
    return await show_ticket_card(update, context, ticket_id)


async def cb_clear_notes(query, context: 'ContextTypes.DEFAULT_TYPE',
                         ticket_id: int, update: Update) -> int:
    """Clear notes on ticket and show card."""
    await db_postgres.update_ticket(context.session, ticket_id, notes=None)
    await query.answer('Примечание удалено')
    return await show_ticket_card(update, context, ticket_id)


async def cb_set_status(query, context: 'ContextTypes.DEFAULT_TYPE',
                        status_value: str, update: Update) -> int:
    """Set new status on ticket."""
    ticket_id = context.user_data['tickets_admin'].get('ticket_id')
    if not ticket_id:
        await query.answer('Ошибка: билет не выбран', show_alert=True)
        return TICKET_CARD
    return await set_ticket_status(update, context, ticket_id, status_value)


async def cb_receipt(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
) -> int:
    """Show receipt card."""
    await show_receipt_to_chat(update, context, ticket_id)
    return TICKET_CARD


# ── Main callback dispatcher ────────────────────────────────────────────────

async def tickets_admin_callback(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Обработчик callback-кнопок меню /tickets_admin."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(':')
    action = parts[1] if len(parts) > 1 else ''

    # ── Стартовое меню ──
    if action == 'search_user':
        return await cb_search_user(query, context)
    if action == 'search_ticket':
        return await cb_search_ticket(query, context)
    if action == 'search_contact':
        return await cb_search_contact(query, context)

    # ── Карточка билета: переход к действию ──
    if action == 'status':
        return await cb_status(query, context, int(parts[2]))
    if action == 'email':
        return await cb_email(query, context, int(parts[2]))
    if action == 'phone':
        return await cb_phone(query, context, int(parts[2]))
    if action == 'notes':
        return await cb_notes(query, context, int(parts[2]))
    if action == 'notes_mode':
        return await cb_notes_mode(query, context, parts[2])
    if action == 'base':
        return await cb_base(query, context, int(parts[2]))
    if action == 'buyer':
        return await show_buyer_card(update, context, int(parts[2]))
    if action == 'buyer_tickets':
        return await show_buyer_tickets(update, context, int(parts[2]))
    if action == 'receipt':
        return await cb_receipt(update, context, int(parts[2]))
    if action == 'transfer':
        return await cb_transfer_start(update, context, int(parts[2]))

    # ── Список билетов ──
    if action == 'toggle_filter':
        return await cb_toggle_filter(update, context)
    if action == 'page':
        return await cb_page(query, context, int(parts[2]), update)
    if action == 'ticket':
        return await show_ticket_card(update, context, int(parts[2]))

    # ── Статус / email ──
    if action == 'set_status':
        return await cb_set_status(query, context, ':'.join(parts[2:]), update)
    if action == 'clear_email':
        return await cb_clear_email(query, context, int(parts[2]), update)
    if action == 'clear_notes':
        return await cb_clear_notes(query, context, int(parts[2]), update)

    return context.user_data.get('STATE', MENU)

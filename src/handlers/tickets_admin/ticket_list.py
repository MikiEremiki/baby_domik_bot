"""Compact ticket list with pagination for /tickets_admin."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from db import db_postgres
from db.enum import TicketStatus
from utilities.utl_func import set_back_context
from utilities.utl_kbd import add_btn_back_and_cancel
from sulguk import transform_html

from .constants import (
    TICKET_LIST, MENU, PAGE_SIZE_TICKETS_ADMIN, TICKET_CARD,
)

tickets_admin_list_logger = logging.getLogger('bot.tickets_admin_list')


async def _filter_tickets_admin(
    tickets: List, relevant_filter: bool, session: Any,
) -> List:
    """Filter tickets: relevant (future events) or all except canceled."""
    if relevant_filter:
        now = datetime.now(timezone.utc)
        se_ids = list({t.schedule_event_id for t in tickets if t.schedule_event_id})
        se_map: dict[int, Any] = {}
        if se_ids:
            try:
                ses = await db_postgres.get_schedule_events_by_ids(session, se_ids)
                se_map = {se.id: se for se in ses}
            except Exception as e:
                tickets_admin_list_logger.debug(e)
        return [
            t for t in tickets
            if t.schedule_event_id
            and t.schedule_event_id in se_map
            and se_map[t.schedule_event_id].datetime_event > now
        ]
    else:
        return [t for t in tickets if t.status != TicketStatus.CANCELED]


def _build_ticket_list_text(
    page_tickets: List, pages: int, page: int,
    header: str, relevant_filter: bool,
) -> str:
    """Build header text with status info for each ticket on the page."""
    filter_label = ' (актуальные)' if relevant_filter else ' (все)'
    text = f'<b>{header}{filter_label}</b>'
    if pages > 1:
        text += f'<br>Страница {page + 1}/{pages}'
    text += '<br>'
    for t in page_tickets:
        text += f'<code>#{t.id}</code> — {t.status.value}<br>'
    return text


def _build_ticket_list_keyboard(
    page_tickets: List, pages: int, page: int, relevant_filter: bool,
) -> InlineKeyboardMarkup:
    """Build keyboard: 4 ID buttons per row, pagination, filter toggle, back/cancel."""
    keyboard: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for t in page_tickets:
        row.append(InlineKeyboardButton(
            f'#{t.id}', callback_data=f'ta:ticket:{t.id}'
        ))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    nav_row: List[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton('◀️ Предыдущая', callback_data=f'ta:page:{page - 1}'))
    if page < pages - 1:
        nav_row.append(InlineKeyboardButton('Следующая ▶️', callback_data=f'ta:page:{page + 1}'))
    if nav_row:
        keyboard.append(nav_row)

    toggle_label = 'Все' if relevant_filter else 'Актуальные'
    keyboard.append([InlineKeyboardButton(toggle_label, callback_data='ta:toggle_filter')])

    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='MENU',
        add_back_btn=True,
    ))
    return InlineKeyboardMarkup(keyboard)


async def show_compact_ticket_list(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    tickets: List,
    header: str,
    page: int = 0,
    relevant_filter: bool = True,
) -> int:
    """Компактный список билетов с кнопками #ID по 4 в ряд, пагинация по 24, фильтр актуальных."""
    filtered = await _filter_tickets_admin(tickets, relevant_filter, context.session)
    sorted_tickets = sorted(filtered, key=lambda t: t.id, reverse=True)

    total = len(sorted_tickets)
    if total == 0:
        return await _show_empty_list(update, context, relevant_filter)

    page_size = PAGE_SIZE_TICKETS_ADMIN
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, pages - 1))

    start = page * page_size
    end = min(total, start + page_size)
    page_tickets = sorted_tickets[start:end]

    text = _build_ticket_list_text(page_tickets, pages, page, header, relevant_filter)
    reply_markup = _build_ticket_list_keyboard(page_tickets, pages, page, relevant_filter)

    res = transform_html(text)
    await _send_or_edit(update, res.text, res.entities, reply_markup)

    context.user_data['tickets_admin']['ticket_list_all'] = tickets
    context.user_data['tickets_admin']['ticket_list'] = sorted_tickets
    context.user_data['tickets_admin']['ticket_list_header'] = header
    context.user_data['tickets_admin']['ticket_list_page'] = page
    context.user_data['tickets_admin']['ticket_list_relevant_filter'] = relevant_filter
    await set_back_context(context, TICKET_LIST, res.text, reply_markup)
    context.user_data['STATE'] = TICKET_LIST
    return TICKET_LIST


async def show_user_tickets(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    user,
    relevant_filter: bool = True,
) -> int:
    """Список билетов пользователя — компактный с кнопками #ID."""
    username_part = f'@{user.username} ' if user.username else ''
    display = username_part + (user.username or str(user.user_id))
    return await show_compact_ticket_list(update, context, user.tickets, f'Билеты: {display}', relevant_filter=relevant_filter)


async def _show_empty_list(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    relevant_filter: bool,
) -> int:
    """Show empty ticket list message."""
    text = 'Билеты не найдены.'
    keyboard = [
        [InlineKeyboardButton(
            'Все' if relevant_filter else 'Актуальные',
            callback_data='ta:toggle_filter'
        )]
    ]
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='MENU',
        add_back_btn=True,
    ))
    reply_markup = InlineKeyboardMarkup(keyboard)
    res = transform_html(text)
    await _send_or_edit(update, res.text, res.entities, reply_markup)
    await set_back_context(context, TICKET_LIST, res.text, reply_markup)
    context.user_data['STATE'] = TICKET_LIST
    return TICKET_LIST


async def _send_or_edit(
    update: Update,
    text: str,
    entities: list,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    """Send or edit message based on update type."""
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=text, entities=entities,
                reply_markup=reply_markup, parse_mode=None)
        except BadRequest:
            await update.effective_chat.send_message(
                text=text, entities=entities,
                reply_markup=reply_markup, parse_mode=None)
    else:
        await update.effective_chat.send_message(
            text=text, entities=entities,
            reply_markup=reply_markup, parse_mode=None)

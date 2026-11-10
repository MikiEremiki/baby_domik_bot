"""User-facing ticket viewing: /tickets command, list, detail, receipt."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Tuple

from sulguk import transform_html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from db import db_postgres
from db.enum import TicketStatus
from handlers import init_conv_hl_dialog
from handlers.receipt_hl import show_receipt_to_chat
from utilities.utl_func import create_str_info_by_schedule_event_id, extract_command, set_back_context
from utilities.utl_kbd import add_btn_back_and_cancel

tickets_user_logger = logging.getLogger('bot.tickets_user')

TICKETS_MENU = 10
PAGE_SIZE_TICKETS = 24

TICKETS_NOTE = (
    "<br><br>"
    "Билеты отображаются, если покупка была совершена:<br>"
    " - через бота<br>"
    "  -через сайт с авторизацией через Telegram.<br>"
    "В остальных случаях ищите на сайте: "
    '<a href="https://baby-theater-domik.ru/tickets">Мои билеты</a>.<br>'
    "Если билеты не найдены — обратитесь к администратору."
)


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_dt(t: Any, session: Any) -> datetime | None:
    """Get scheduled event datetime for a ticket."""
    if t.schedule_event_id:
        se = await db_postgres.get_schedule_event(session, t.schedule_event_id)
        return se.datetime_event if se else None
    return None


def _resolve_user_id(
    update: Update, context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Resolve user ID from command args, user_data, or effective user."""
    is_admin_chat = context.config.bot.developer_chat_id == update.effective_chat.id
    if context.args and is_admin_chat:
        return int(context.args[0])
    if is_admin_chat and context.user_data.get('profile_user_id', False):
        return context.user_data['profile_user_id']
    return update.effective_user.id


async def _filter_tickets(
    all_tickets: List[Any], relevant_filter: bool, session: Any,
) -> List[Any]:
    """Filter tickets: relevant (future events) or all except canceled."""
    if relevant_filter:
        now = datetime.now(timezone.utc)
        # Batch-load schedule events to avoid N+1
        se_ids = list({t.schedule_event_id for t in all_tickets if t.schedule_event_id})
        se_map: dict[int, Any] = {}
        if se_ids:
            try:
                ses = await db_postgres.get_schedule_events_by_ids(session, se_ids)
                se_map = {se.id: se for se in ses}
            except Exception as e:
                tickets_user_logger.debug(e)
        return [
            t for t in all_tickets
            if t.schedule_event_id
            and t.schedule_event_id in se_map
            and se_map[t.schedule_event_id].datetime_event > now
        ]
    else:
        return [t for t in all_tickets if t.status != TicketStatus.CANCELED]


def _build_tickets_text(
    page_tickets: List[Tuple[datetime | None, Any]],
    pages: int, page: int, relevant_filter: bool,
) -> str:
    """Build header text with status info for each ticket on the page."""
    filter_label = ' (актуальные)' if relevant_filter else ' (все)'
    text = f'<b>Мои билеты{filter_label}</b>'
    if pages > 1:
        text += f'<br>Страница {page + 1}/{pages}'
    text += '<br>'
    for dt, ticket in page_tickets:
        text += f'<code>#{ticket.id}</code> — {ticket.status.value}<br>'
    text += TICKETS_NOTE
    return text


def _build_tickets_keyboard(
    page_tickets: List[Tuple[datetime | None, Any]],
    pages: int, page: int, relevant_filter: bool, command: str | None,
) -> InlineKeyboardMarkup:
    """Build keyboard: 4 ID buttons per row, pagination, filter toggle, back/cancel."""
    keyboard: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for dt, ticket in page_tickets:
        row.append(InlineKeyboardButton(
            f'#{ticket.id}',
            callback_data=f'tickets:detail:{ticket.id}'
        ))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Pagination navigation
    nav_row: List[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton('◀️ Предыдущая', callback_data=f'tickets:page:{page - 1}'))
    if page < pages - 1:
        nav_row.append(InlineKeyboardButton('Следующая ▶️', callback_data=f'tickets:page:{page + 1}'))
    if nav_row:
        keyboard.append(nav_row)

    # Filter toggle
    toggle_label = 'Все' if relevant_filter else 'Актуальные'
    keyboard.append([InlineKeyboardButton(toggle_label, callback_data='tickets:toggle_filter')])

    # Back / Cancel
    if command == 'profile':
        keyboard.append(add_btn_back_and_cancel(
            postfix_for_back='MENU', add_cancel_btn=False,
        ))
    else:
        keyboard.append(add_btn_back_and_cancel(
            postfix_for_cancel='tickets', add_back_btn=False,
        ))

    return InlineKeyboardMarkup(keyboard)


async def _send_or_edit_tickets(
    update: Update, text: str, entities: list, reply_markup: InlineKeyboardMarkup,
) -> None:
    """Send or edit message based on update type."""
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=text, entities=entities,
                reply_markup=reply_markup, parse_mode=None)
        except Exception:
            await update.effective_chat.send_message(
                text=text, entities=entities,
                reply_markup=reply_markup, parse_mode=None)
    else:
        await update.effective_chat.send_message(
            text=text, entities=entities,
            reply_markup=reply_markup, parse_mode=None)


# ── Public functions ─────────────────────────────────────────────────────────

async def show_tickets(update: Update, context: 'ContextTypes.DEFAULT_TYPE') -> int:
    """Show compact list of user's tickets with ID buttons, pagination, newest first."""
    command = context.user_data.get('command', None)
    if not command and update.effective_message:
        command = extract_command(update.effective_message.text)
    # Initialize dialog only on entry (command message), not on callback
    if command == 'tickets' and not update.callback_query:
        await init_conv_hl_dialog(update, context)
    elif command == 'profile' and update.callback_query:
        await update.callback_query.answer()

    if not update.callback_query:
        try:
            await update.effective_chat.send_action(ChatAction.TYPING)
        except Exception as e:
            tickets_user_logger.debug(e)

    user_id = _resolve_user_id(update, context)
    user = await db_postgres.get_user(context.session, user_id)

    page = context.user_data.get('tickets_page', 0)
    relevant_filter = context.user_data.get('tickets_relevant_filter', True)

    all_tickets: List[Any] = []
    if user:
        try:
            all_tickets = user.tickets
        except Exception as e:
            tickets_user_logger.error(e)

    tickets = await _filter_tickets(all_tickets, relevant_filter, context.session)

    if not tickets:
        return await _show_empty_tickets_list(update, context, command, relevant_filter)

    # Sort by datetime descending (newest first, None last)
    dt_list: List[Tuple[datetime | None, Any]] = []
    for t in tickets:
        try:
            dt = await _get_dt(t, context.session)
        except Exception as e:
            tickets_user_logger.debug(e)
            dt = None
        dt_list.append((dt, t))

    dt_list.sort(key=lambda x: (not (x[0] is None), x[0]), reverse=True)

    total = len(dt_list)
    page_size = PAGE_SIZE_TICKETS
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, pages - 1))

    start = page * page_size
    end = min(total, start + page_size)
    page_tickets = dt_list[start:end]

    text = _build_tickets_text(page_tickets, pages, page, relevant_filter)
    reply_markup = _build_tickets_keyboard(page_tickets, pages, page, relevant_filter, command)

    res = transform_html(text)
    await _send_or_edit_tickets(update, res.text, res.entities, reply_markup)

    await set_back_context(context, TICKETS_MENU, res.text, reply_markup)
    context.user_data['STATE'] = TICKETS_MENU
    context.user_data['tickets_page'] = page
    context.user_data['tickets_relevant_filter'] = relevant_filter
    if context.user_data.get('profile_user_id', False):
        context.user_data.pop('profile_user_id')
    return TICKETS_MENU


async def _show_empty_tickets_list(
    update: Update, context: 'ContextTypes.DEFAULT_TYPE',
    command: str | None, relevant_filter: bool,
) -> int:
    """Show empty tickets list message."""
    keyboard: List[List[InlineKeyboardButton]] = []
    toggle_label = 'Все' if relevant_filter else 'Актуальные'
    keyboard.append([InlineKeyboardButton(toggle_label, callback_data='tickets:toggle_filter')])
    if command == 'profile':
        keyboard.append(add_btn_back_and_cancel(
            postfix_for_back='MENU', add_cancel_btn=False,
        ))
    else:
        keyboard.append(add_btn_back_and_cancel(
            postfix_for_cancel='tickets', add_back_btn=False,
        ))
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        '<b>Мои билеты</b><br><br>'
        'У вас нет купленных билетов.<br><br>'
        'Вы можете забронировать билеты командой /reserve'
    )
    text += TICKETS_NOTE
    res = transform_html(text)
    await _send_or_edit_tickets(update, res.text, res.entities, reply_markup)
    await set_back_context(context, TICKETS_MENU, res.text, reply_markup)
    context.user_data['STATE'] = TICKETS_MENU
    return TICKETS_MENU


async def tickets_callback(update: Update, context: 'ContextTypes.DEFAULT_TYPE') -> int:
    """Handle tickets callbacks: pagination, detail view, filter toggle, and receipt."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(':')
    action = parts[1] if len(parts) > 1 else ''

    if action == 'page':
        page = int(parts[2])
        context.user_data['tickets_page'] = page
        await update.effective_chat.send_action(action=ChatAction.TYPING)
        return await show_tickets(update, context)
    elif action == 'toggle_filter':
        context.user_data['tickets_relevant_filter'] = not context.user_data.get('tickets_relevant_filter', True)
        context.user_data['tickets_page'] = 0
        await update.effective_chat.send_action(action=ChatAction.TYPING)
        return await show_tickets(update, context)
    elif action == 'detail':
        ticket_id = int(parts[2])
        await _show_ticket_detail(update, context, ticket_id)
        return TICKETS_MENU
    elif action == 'receipt':
        ticket_id = int(parts[2])
        await show_receipt_to_chat(update, context, ticket_id)
        return TICKETS_MENU
    else:
        return TICKETS_MENU


async def _show_ticket_detail(
    update: Update, context: 'ContextTypes.DEFAULT_TYPE', ticket_id: int,
) -> None:
    """Show detailed view of a single ticket."""
    user_id = update.effective_user.id
    user = await db_postgres.get_user(context.session, user_id)

    ticket = None
    if user:
        for t in user.tickets:
            if t.id == ticket_id:
                ticket = t
                break

    if not ticket:
        res = transform_html('Билет не найден.')
        try:
            await update.callback_query.edit_message_text(
                text=res.text, entities=res.entities, parse_mode=None)
        except Exception as e:
            tickets_user_logger.debug(e)
            await update.effective_chat.send_message(
                text=res.text, entities=res.entities, parse_mode=None)
        return

    try:
        if ticket.schedule_event_id:
            text_event = await create_str_info_by_schedule_event_id(context, ticket.schedule_event_id)
        else:
            text_event = 'Индивидуальное мероприятие'
        base_ticket = await db_postgres.get_base_ticket(context.session, ticket.base_ticket_id)
        base_name = base_ticket.name if base_ticket else ''
    except Exception as e:
        tickets_user_logger.error(e)
        text_event = 'Неизвестное мероприятие'
        base_name = ''

    people_lines: List[str] = []
    for person in ticket.people:
        if person.age_type.value == 'взрослый':
            people_lines.append(f'  • {person.name} (взрослый)')
        else:
            age = person.child.age if person.child else None
            age_str = f'{age} лет' if age is not None else ''
            people_lines.append(f'  • {person.name} (ребенок, {age_str})')

    people_text = '<br>'.join(people_lines) if people_lines else '  —'

    parts_text: List[str] = [
        f'<b>Билет #{ticket.id}</b>',
        text_event,
        f'Тип: {base_name}',
        f'Стоимость: {int(ticket.price)} руб',
        f'Статус: {ticket.status.value}',
    ]

    if ticket.email:
        parts_text.append(f'Email: {ticket.email}')
    if ticket.phone:
        parts_text.append(f'Телефон: {ticket.phone}')

    parts_text.append(f'Участники:<br>{people_text}')

    text = '<br>'.join(parts_text)

    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton('🧾 Чек', callback_data=f'tickets:receipt:{ticket.id}')],
        add_btn_back_and_cancel(
            postfix_for_back='TICKETS_MENU',
            postfix_for_cancel='tickets',
        ),
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    res = transform_html(text)
    await set_back_context(context, 'TICKET_DETAIL', res.text, reply_markup)

    try:
        await update.callback_query.edit_message_text(
            text=res.text, entities=res.entities,
            reply_markup=reply_markup, parse_mode=None)
    except Exception as e:
        tickets_user_logger.debug(e)
        await update.effective_chat.send_message(
            text=res.text, entities=res.entities,
            reply_markup=reply_markup, parse_mode=None)

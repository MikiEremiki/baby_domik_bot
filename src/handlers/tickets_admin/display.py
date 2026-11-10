"""Ticket card display for /tickets_admin."""
from __future__ import annotations

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from db import db_postgres
from utilities.utl_func import (
    get_formatted_date_and_time_of_event, set_back_context,
)
from utilities.utl_ticket import format_ticket_contacts
from sulguk import transform_html
from api.receipt_service import get_ticket_receipt, ReceiptStatus

from .constants import TICKET_CARD, MENU
from .keyboards import ticket_card_keyboard


def _get_thread_id(update: Update) -> int | None:
    """Извлекает message_thread_id из update для отправки в тему форума."""
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.message_thread_id
    if update.effective_message:
        return update.effective_message.message_thread_id
    return None


async def format_ticket_card(session, ticket) -> str:
    """Формирует текст карточки билета."""
    schedule_event = await db_postgres.get_schedule_event(
        session, ticket.schedule_event_id)
    if schedule_event:
        theater_event = await db_postgres.get_theater_event(
            session, schedule_event.theater_event_id)
        date_event, time_event = await get_formatted_date_and_time_of_event(
            schedule_event)
        event_line = f'{theater_event.name if theater_event else "—"}<br>{date_event} в {time_event}'
    else:
        event_line = '—'

    base_ticket = await db_postgres.get_base_ticket(session, ticket.base_ticket_id)
    contacts_block = format_ticket_contacts(ticket, html=True)

    people_lines = []
    for person in ticket.people:
        if person.age_type.value == 'взрослый':
            people_lines.append(f'  • {person.name} (взрослый)')
        else:
            age = person.child.age if person.child else None
            age_str = f'{age} лет' if age is not None else ''
            people_lines.append(f'  • {person.name} (ребенок, {age_str})')

    # Receipt status info
    receipt_info = await get_ticket_receipt(session, ticket.id)
    receipt_status_text = {
        ReceiptStatus.READY: '✅ Чек готов',
        ReceiptStatus.PENDING: '⏳ Чек формируется',
        ReceiptStatus.CANCELED: '❌ Чек отменён',
        ReceiptStatus.NO_PAYMENT: '💳 Оплата не найдена',
        ReceiptStatus.API_ERROR: '⚠️ Ошибка чека',
    }.get(receipt_info.status, '❓ Чек неизвестен')

    people_text = '<br>'.join(people_lines) if people_lines else '  —'

    notes_text = ticket.notes.replace('\n', '<br>') if ticket.notes else '—'
    text = (
        f'<b>Билет #{ticket.id}</b><br>'
        f'{event_line}<br>'
        f'Тип: {base_ticket.name if base_ticket else "—"}<br>'
        f'Стоимость: {int(ticket.price)} руб<br>'
        f'Статус: {ticket.status.value}<br>'
        f'Платёж: <code>{ticket.payment_id or "—"}</code><br>'
        f'Чек: {receipt_status_text}<br>'
        f'Примечание: {notes_text}<br>'
        f'{contacts_block}'
    )
    text += f'<br>Участники:<br>{people_text}'

    if ticket.user:
        text += f'<br><br>Привязан к профилю: {ticket.user.user_id}'
    else:
        text += '<br><br>Билет не привязан к Telegram-профилю'

    return text


async def show_ticket_card(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
    edit: bool = True,
) -> int:
    """Показывает карточку билета с кнопками управления."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        await update.effective_chat.send_message(
            'Такого билета нет.', message_thread_id=_get_thread_id(update))
        return MENU

    context.user_data['tickets_admin'] = context.user_data.setdefault(
        'tickets_admin', {})
    context.user_data['tickets_admin']['ticket_id'] = ticket_id

    text = await format_ticket_card(context.session, ticket)
    keyboard = ticket_card_keyboard(ticket_id)
    res = transform_html(text)

    thread_id = _get_thread_id(update)
    if update.callback_query and edit:
        try:
            await update.callback_query.edit_message_text(
                text=res.text, entities=res.entities,
                reply_markup=keyboard, parse_mode=None)
        except BadRequest:
            await update.effective_chat.send_message(
                text=res.text, entities=res.entities,
                reply_markup=keyboard, parse_mode=None,
                message_thread_id=thread_id)
    else:
        await update.effective_chat.send_message(
            text=res.text, entities=res.entities,
            reply_markup=keyboard, parse_mode=None,
            message_thread_id=thread_id)

    await set_back_context(context, TICKET_CARD, res.text, keyboard)
    context.user_data['STATE'] = TICKET_CARD
    return TICKET_CARD

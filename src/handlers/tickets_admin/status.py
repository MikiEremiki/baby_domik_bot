"""Status change logic for /tickets_admin."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from db import db_postgres
from db.enum import TicketStatus
from api.gspread_pub import publish_update_ticket
from api.googlesheets import update_ticket_in_gspread
from db.db_googlesheets import (
    decrease_nonconfirm_seat,
    increase_free_seat,
    increase_free_and_decrease_nonconfirm_seat,
)

from .display import show_ticket_card

tickets_admin_status_logger = logging.getLogger('bot.tickets_admin_status')


async def set_ticket_status(
    update: 'Update',
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
    status_value: str,
) -> int:
    """Устанавливает новый статус билета с синхронизацией мест и Google Sheets."""
    query = update.callback_query
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        await query.answer('Билет не найден', show_alert=True)
        return 4  # TICKET_CARD

    try:
        new_status = TicketStatus(status_value)
    except ValueError:
        await query.answer('Неверный статус', show_alert=True)
        return 4  # TICKET_CARD

    old_status = ticket.status
    schedule_event_id = ticket.schedule_event_id

    # Синхронизация свободных мест
    if old_status == TicketStatus.CREATED:
        if new_status in (TicketStatus.CANCELED, TicketStatus.APPROVED, TicketStatus.REJECTED):
            if new_status == TicketStatus.APPROVED:
                await decrease_nonconfirm_seat(context, schedule_event_id)
            else:
                await increase_free_and_decrease_nonconfirm_seat(context, schedule_event_id)
    elif old_status == TicketStatus.PAID:
        if new_status == TicketStatus.APPROVED:
            await decrease_nonconfirm_seat(context, schedule_event_id)
        elif new_status in (TicketStatus.REJECTED, TicketStatus.REFUNDED):
            await increase_free_and_decrease_nonconfirm_seat(context, schedule_event_id)
    elif old_status in (TicketStatus.APPROVED, TicketStatus.RESERVED):
        if new_status in (TicketStatus.REJECTED, TicketStatus.REFUNDED,
                          TicketStatus.TRANSFERRED, TicketStatus.MIGRATED,
                          TicketStatus.CANCELED):
            await increase_free_seat(context, schedule_event_id)

    # Обновление в БД
    await db_postgres.update_ticket(context.session, ticket_id, status=new_status)

    # Google Sheets
    sheet_id_domik = context.config.sheets.sheet_id_domik
    try:
        await publish_update_ticket(sheet_id_domik, ticket_id, str(new_status.value))
    except Exception as e:
        tickets_admin_status_logger.exception(f'Gspread publish failed, fallback: {e}')
        await update_ticket_in_gspread(sheet_id_domik, ticket_id, new_status.value)

    await query.answer(f'Статус: {new_status.value}')
    return await show_ticket_card(update, context, ticket_id)

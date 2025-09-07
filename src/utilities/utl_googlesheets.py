import logging

from api.googlesheets import update_ticket_in_gspread
from db import db_postgres
from db.db_googlesheets import (
    increase_free_and_decrease_nonconfirm_seat, increase_free_seat)
from db.enum import TicketStatus

utl_googlesheets_logger = logging.getLogger('bot.utl_googlesheets')


async def write_to_return_seats_for_sale(context):
    reserve_user_data = context.user_data['reserve_user_data']
    ticket_ids = reserve_user_data.get('ticket_ids', None)
    command = context.user_data['command']
    ticket_status = TicketStatus.CANCELED
    changed_seat = reserve_user_data.get('changed_seat', False)

    if ticket_ids:
        for ticket_id in ticket_ids:
            text = await cancel_ticket_and_return_seat(context, changed_seat,
                                                       command, ticket_id,
                                                       ticket_status)
            await context.bot.send_message(
                chat_id=context.config.bot.developer_chat_id,
                text=text)
    else:
        text = 'Билетов для отмены нет'
    utl_googlesheets_logger.warning(text)


async def cancel_ticket_and_return_seat(
        context,
        changed_seat,
        command,
        ticket_id,
        ticket_status
):
    ticket = await db_postgres.get_ticket(
        context.session, ticket_id)
    if ticket is None:
        text = f'Билет {ticket_id} отсутствует в базе'
    else:
        text = f'Билет|{ticket.id}-{ticket.status.value}|'
        if ticket.status == TicketStatus.CREATED and changed_seat:
            schedule_event_id = ticket.schedule_event_id
            base_ticket_id = ticket.base_ticket_id
            if '_admin' in command:
                result = await increase_free_seat(
                    context, schedule_event_id, base_ticket_id)
                text += f'increase_free|{schedule_event_id=}'
            else:
                result = await increase_free_and_decrease_nonconfirm_seat(
                    context, schedule_event_id, base_ticket_id)
                text += f'increase_free_and_decrease_nonconfirm|{schedule_event_id=}'
            if not result:
                text += '|Надо проверить и возможно отменить билет в ручную'
                await context.bot.send_message(
                    chat_id=context.config.bot.developer_chat_id,
                    text=text)
            else:
                await update_ticket_db_and_gspread(
                    context, ticket_id, status=ticket_status)
        else:
            text += 'Нельзя отменять'
    return text


async def update_ticket_db_and_gspread(context, ticket_id, **kwargs):
    sheet_id_domik = context.config.sheets.sheet_id_domik
    await update_ticket_in_gspread(
        sheet_id_domik, ticket_id, kwargs['status'].value)
    await db_postgres.update_ticket(context.session, ticket_id, **kwargs)

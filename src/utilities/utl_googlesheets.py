import logging

from api.googlesheets import update_ticket_in_gspread
from api.gspread_pub import publish_update_ticket
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

    text = 'Билетов для отмены нет'
    if ticket_ids:
        for ticket_id in ticket_ids:
            text = await cancel_ticket_and_return_seat(context, changed_seat,
                                                       command, ticket_id,
                                                       ticket_status)
            await context.bot.send_message(
                chat_id=context.config.bot.developer_chat_id,
                text=text)
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


async def cancel_ticket_and_return_seat_auto(context, ticket_id: int) -> str:
    """
    Автоматическая отмена билета, созданного более 30 минут назад.
    Поведение аналогично write_to_return_seats_for_sale для не-админа:
    - освобождаем место: increase_free_and_decrease_nonconfirm_seat
    - меняем статус билета на CANCELED и обновляем Google Sheets
    """
    # В автоматическом сценарии всегда освобождаем место и не являемся админом
    changed_seat = True
    command = 'reserve'  # без суффикса '_admin' → уменьшит nonconfirm и увеличит free
    ticket_status = TicketStatus.CANCELED
    text = await cancel_ticket_and_return_seat(
        context=context,
        changed_seat=changed_seat,
        command=command,
        ticket_id=ticket_id,
        ticket_status=ticket_status,
    )
    utl_googlesheets_logger.info(text)
    return text


async def update_ticket_db_and_gspread(context, ticket_id, **kwargs):
    sheet_id_domik = context.config.sheets.sheet_id_domik
    try:
        await publish_update_ticket(
            sheet_id_domik,
            ticket_id,
            kwargs['status'].value,
        )
    except Exception as e:
        utl_googlesheets_logger.exception(
            f"Failed to publish gspread task, fallback to direct call: {e}")
        await update_ticket_in_gspread(
            sheet_id_domik, ticket_id, kwargs['status'].value)
    ticket = await db_postgres.update_ticket(
        context.session, ticket_id, **kwargs)
    return ticket

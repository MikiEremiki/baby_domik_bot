import logging

from api.googlesheets import update_ticket_in_gspread
from db import db_postgres
from db.db_googlesheets import (
    increase_free_and_decrease_nonconfirm_seat, increase_free_seat)

utl_googlesheets_logger = logging.getLogger('bot.utl_googlesheets')


async def write_to_return_seats_for_sale(context, **kwargs):
    reserve_user_data = context.user_data['reserve_user_data']
    choose_schedule_event_ids = reserve_user_data['choose_schedule_event_ids']
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    ticket_ids = reserve_user_data.get('ticket_ids', None)
    command = context.user_data['command']

    for schedule_event_id in choose_schedule_event_ids:
        if '_admin' in command:
            await increase_free_seat(context,
                                     schedule_event_id,
                                     chose_base_ticket_id)
            utl_googlesheets_logger.info(
                f'Места добавлены: {ticket_ids=}: {schedule_event_id=}')
        else:
            await increase_free_and_decrease_nonconfirm_seat(context,
                                                             schedule_event_id,
                                                             chose_base_ticket_id)
            utl_googlesheets_logger.info(
                f'Места добавлены: {ticket_ids=}: {schedule_event_id=}')
    if ticket_ids and 'status' in kwargs.keys():
        for ticket_id in ticket_ids:
            await update_ticket_db_and_gspread(context, ticket_id, **kwargs)


async def update_ticket_db_and_gspread(context, ticket_id, **kwargs):
    update_ticket_in_gspread(ticket_id, kwargs['status'].value)
    await db_postgres.update_ticket(context.session, ticket_id, **kwargs)


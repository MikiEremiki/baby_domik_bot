from telegram.ext import Application

from api.googlesheets import update_ticket_in_gspread
from db import db_googlesheets, db_postgres
from db.db_googlesheets import (
    increase_free_and_decrease_nonconfirm_seat, increase_free_seat)


def set_special_ticket_price(application: Application):
    application.bot_data['special_ticket_price'] = db_googlesheets.load_special_ticket_price()


def load_and_concat_date_of_shows():
    list_of_date_show: list = sorted(db_googlesheets.load_base_tickets(),
                               key=create_keys_for_sort)
    text_date = '\n'.join(item for item in list_of_date_show)
    return ('\n__________\n'
            'В следующие даты проводятся мероприятия, поэтому их не указывайте:'
            f'\n{text_date}')


def create_keys_for_sort(item):
    a, b = item.split()[0].split('.')
    return b + a


async def write_to_return_seats_for_sale(context, **kwargs):
    reserve_user_data = context.user_data['reserve_user_data']
    choose_schedule_event_ids = reserve_user_data['choose_schedule_event_ids']
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    ticket_ids = reserve_user_data.get('ticket_ids', None)
    command = context.user_data['command']

    if ticket_ids and 'status' in kwargs.keys():
        text = 'Проверь билеты:'
        for ticket_id in ticket_ids:
            ticket = await db_postgres.get_ticket(context.session, ticket_id)
            text += f'\n{ticket.id}| {ticket.status.value}'
        await context.bot.send_message(context.config.bot.developer_chat_id, 'a')

    for schedule_event_id in choose_schedule_event_ids:
        if '_admin' in command:
            await increase_free_seat(context,
                                     schedule_event_id,
                                     chose_base_ticket_id)
        else:
            await increase_free_and_decrease_nonconfirm_seat(context,
                                                             schedule_event_id,
                                                             chose_base_ticket_id)
    if ticket_ids and 'status' in kwargs.keys():
        for ticket_id in ticket_ids:
            await update_ticket_db_and_gspread(context, ticket_id, **kwargs)


async def update_ticket_db_and_gspread(context, ticket_id, **kwargs):
    update_ticket_in_gspread(ticket_id, kwargs['status'].value)
    await db_postgres.update_ticket(context.session, ticket_id, **kwargs)


from telegram.ext import Application

from db import db_googlesheets, db_postgres
from db.db_googlesheets import increase_free_and_decrease_nonconfirm_seat, \
    increase_free_seat


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
            await db_postgres.update_ticket(context.session,
                                            ticket_id,
                                            **kwargs)


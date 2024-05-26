import logging

from telegram.ext import ContextTypes

from db import BaseTicket, ScheduleEvent, TheaterEvent, db_postgres
from db.enum import PriceType

utl_ticket_func_hl_logger = logging.getLogger('bot.utl_ticket_func')


async def get_spec_ticket_price(context: ContextTypes.DEFAULT_TYPE,
                                ticket: BaseTicket,
                                schedule_event,
                                theater_event: TheaterEvent,
                                date_for_price=None):
    reserve_user_data = context.user_data['reserve_user_data']

    option = get_option(schedule_event, theater_event)

    price, price_privilege = ticket.get_price_from_date(date_for_price)
    key = ticket.base_ticket_id
    type_ticket_price = await set_type_ticket_price(schedule_event)

    reserve_user_data['type_ticket_price'] = type_ticket_price
    if theater_event.flag_indiv_cost:
        try:
            # TODO Загружать и читать в базу данных, а не из bot_data
            special_ticket_price = context.bot_data['special_ticket_price']
            price = special_ticket_price[option][type_ticket_price][key]
        except KeyError:
            utl_ticket_func_hl_logger.error(
                f'{key=} - данному билету не назначена индив. цена')
            utl_ticket_func_hl_logger.error(theater_event.model_dump())
            if key // 100 != 4:
                text = f'{key=} - данному билету не назначена индив. цена\n'
                text += f'{type_ticket_price=}\n'
                text += f'{theater_event.id=}\n'
                text += f'{schedule_event.id=}\n'
                text += f'{schedule_event.type_event_id=}\n'
                await context.bot.send_message(
                    chat_id=context.config.bot.developer_chat_id,
                    text=text,
                )
    return price, price_privilege


async def set_type_ticket_price(schedule_event: ScheduleEvent,
                                date_for_price=None):
    type_ticket_price = schedule_event.ticket_price_type.value
    if not type_ticket_price:
        if not date_for_price:
            date_for_price = schedule_event.datetime_event.date()
        if date_for_price.weekday() in range(5):
            type_ticket_price = 'будни'
        else:
            type_ticket_price = 'выходные'

    return type_ticket_price


def get_option(
        schedule_event: ScheduleEvent,
        theater_event: TheaterEvent
):
    option = ''
    if schedule_event.flag_gift:
        option = 'Подарок'
    if schedule_event.flag_christmas_tree:
        option = 'Ёлка'

    if not option:
        price_type = theater_event.price_type
        if price_type == PriceType.INDIVIDUAL:
            option = theater_event.id
        else:
            option = price_type
    return option


async def get_ticket_and_price(context, base_ticket_id):
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    theater_event_id = reserve_user_data['choose_theater_event_id']
    date_for_price = reserve_user_data['date_for_price']

    schedule_event = await db_postgres.get_schedule_event(
        context.session, schedule_event_id)
    theater_event = await db_postgres.get_theater_event(
        context.session, theater_event_id)

    ticket = await db_postgres.get_base_ticket(context.session,
                                                     base_ticket_id)
    price, price_privilege = await get_spec_ticket_price(context,
                                                         ticket,
                                                         schedule_event,
                                                         theater_event,
                                                         date_for_price)
    return ticket, price

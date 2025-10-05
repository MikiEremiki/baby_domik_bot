import logging

from telegram.error import BadRequest
from telegram.ext import ContextTypes

from db import BaseTicket, ScheduleEvent, TheaterEvent, db_postgres
from db.enum import PriceType, TicketStatus
from utilities.utl_func import clean_context_on_end_handler
from utilities.utl_googlesheets import write_to_return_seats_for_sale

utl_ticket_logger = logging.getLogger('bot.utl_ticket')


async def get_spec_ticket_price(context: 'ContextTypes.DEFAULT_TYPE',
                                ticket: BaseTicket,
                                schedule_event: ScheduleEvent,
                                theater_event: TheaterEvent):
    reserve_user_data = context.user_data['reserve_user_data']

    option = get_option(schedule_event, theater_event)

    # Переопределил дату определения цены по дате спектакля
    date_for_price = schedule_event.datetime_event
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
            utl_ticket_logger.error(
                f'{key=} - данному билету не назначена индив. цена')
            utl_ticket_logger.error(theater_event.model_dump())
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
            option = price_type.value
    return option


async def get_ticket_and_price(context, base_ticket_id):
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    theater_event_id = reserve_user_data['choose_theater_event_id']

    schedule_event = await db_postgres.get_schedule_event(
        context.session, schedule_event_id)
    theater_event = await db_postgres.get_theater_event(
        context.session, theater_event_id)

    ticket = await db_postgres.get_base_ticket(context.session, base_ticket_id)
    price, price_privilege = await get_spec_ticket_price(
        context, ticket, schedule_event, theater_event)
    return ticket, price


async def cancel_tickets_db_and_gspread(update, context):
    # TODO переделать на более надежный флаг: билет Требует/Не требует отмены.
    #  По сути не должно быть билетов в статусе CREATED
    states_for_cancel = ['CHILDREN', 'PAID']
    state = context.user_data.get('STATE', None)
    if state in states_for_cancel:
        utl_ticket_logger.info(context.user_data['STATE'])

        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['common_data'][
                    'message_id_buy_info']
            )
        except BadRequest as e:
            utl_ticket_logger.error(e)
        except KeyError as e:
            utl_ticket_logger.error(e)
            utl_ticket_logger.error(
                f'state={context.user_data['STATE']}, если это CHILDREN, '
                f'то сообщение с оплатой еще не создалось, '
                f'так как обычно не создается платеж из-за неверного email'
            )

        await write_to_return_seats_for_sale(context)


async def create_tickets_and_people(
        update,
        context,
        ticket_status
):
    reserve_user_data = context.user_data['reserve_user_data']
    client_data = reserve_user_data['client_data']

    ticket_ids = await create_tickets(context, ticket_status)

    people_ids = await db_postgres.create_people(context.session,
                                                 update.effective_user.id,
                                                 client_data)
    for ticket_id in ticket_ids:
        await db_postgres.attach_user_and_people_to_ticket(context.session,
                                                           ticket_id,
                                                           update.effective_user.id,
                                                           people_ids)

    return ticket_ids


async def create_tickets(context, ticket_status):
    ticket_ids = []

    reserve_user_data = context.user_data['reserve_user_data']
    choose_schedule_event_ids = reserve_user_data['choose_schedule_event_ids']
    chose_price = reserve_user_data['chose_price']
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    for event_id in choose_schedule_event_ids:
        ticket = await db_postgres.create_ticket(
            context.session,
            base_ticket_id=chose_base_ticket.base_ticket_id,
            price=chose_price,
            schedule_event_id=event_id,
            status=ticket_status,
        )
        ticket_ids.append(ticket.id)

    reserve_user_data['ticket_ids'] = ticket_ids
    return ticket_ids


async def cancel_ticket_db_when_end_handler(update, context, text):
    reserve_user_data = context.user_data['reserve_user_data']
    ticket_ids = reserve_user_data['ticket_ids']

    for ticket_id in ticket_ids:
        await db_postgres.update_ticket(
            context.session, ticket_id, status=TicketStatus.CANCELED)

    await context.bot.send_message(
        text=text,
        chat_id=update.effective_chat.id,
    )
    await clean_context_on_end_handler(utl_ticket_logger, context)

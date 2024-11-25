import logging
import datetime

from typing import List, Tuple, Dict

from pydantic import ValidationError
from telegram.ext import ContextTypes

from api.googlesheets import (
    get_data_from_spreadsheet,
    get_column_info,
    write_data_reserve,
)
from db import db_postgres
from settings.settings import RANGE_NAME
from utilities.schemas.custom_made_format import CustomMadeFormatDTO
from utilities.schemas.schedule_event import ScheduleEventDTO
from utilities.schemas.theater_event import TheaterEventDTO
from utilities.schemas.ticket import BaseTicketDTO

db_googlesheets_logger = logging.getLogger('bot.db.googlesheets')


def load_base_tickets(only_active=True) -> List[BaseTicketDTO]:
    tickets = []

    dict_column_name, len_column = get_column_info('Варианты стоимости_')

    qty_tickets = len(get_data_from_spreadsheet(
        RANGE_NAME['Варианты стоимости_'] + f'A:A'
    ))

    data = get_data_from_spreadsheet(
        RANGE_NAME['Варианты стоимости_'] +
        f'R2C1:R{qty_tickets}C{len_column}'
    )
    db_googlesheets_logger.info('Данные стоимости броней загружены')

    fields_ticket = [*BaseTicketDTO.model_fields.keys()]
    for item in data[1:]:
        tmp_dict = {}
        for value in fields_ticket:
            try:
                tmp_dict[value] = item[dict_column_name[value]]
            except KeyError as e:
                if e.args[0] != 'date_show_tmp':
                    db_googlesheets_logger.error(item)
                    db_googlesheets_logger.error(e)
        try:
            ticket = BaseTicketDTO(**tmp_dict)
            if only_active and not ticket.flag_active:
                continue
            tickets.append(ticket)
        except ValidationError as exc:
            db_googlesheets_logger.error(repr(exc.errors()[0]['type']))
            db_googlesheets_logger.error(tmp_dict)

    db_googlesheets_logger.info('Список билетов загружен')
    return tickets


def load_schedule_events(
        only_active=True,
        only_actual=True
) -> List[ScheduleEventDTO]:
    events = []

    dict_column_name, len_column = get_column_info('База спектаклей_')

    qty_events = len(get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_'] + f'A:A'
    ))

    data = get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_'] +
        f'R2C1:R{qty_events}C{len_column}',
        value_render_option='UNFORMATTED_VALUE'
    )
    db_googlesheets_logger.info('Данные мероприятий загружены')

    fields_ticket = [*ScheduleEventDTO.model_fields.keys()]
    for item in data[1:]:
        tmp_dict = {}
        for value in fields_ticket:
            try:
                tmp_dict[value] = item[dict_column_name[value]]
            except KeyError as e:
                if e.args[0] != 'date_show_tmp':
                    db_googlesheets_logger.error(item)
                    db_googlesheets_logger.error(e)
            except IndexError as e:
                db_googlesheets_logger.error(item)
                db_googlesheets_logger.error(e)
        try:
            event = ScheduleEventDTO(**tmp_dict)
            if only_active and not event.flag_turn_on_off:
                continue
            if only_actual and event.get_date_event().date() < datetime.date.today():
                continue
            events.append(event)
        except ValidationError as exc:
            db_googlesheets_logger.error(repr(exc.errors()[0]['type']))
            db_googlesheets_logger.error(tmp_dict)

    db_googlesheets_logger.info('Список мероприятий загружен')
    return events


def load_theater_events() -> List[TheaterEventDTO]:
    events = []

    dict_column_name, len_column = get_column_info('Список спектаклей_')

    qty_tickets = len(get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] + f'A:A'
    ))

    data = get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] +
        f'R2C1:R{qty_tickets}C{len_column}',
        value_render_option='UNFORMATTED_VALUE'
    )
    db_googlesheets_logger.info('Данные репертуара загружены')

    fields_ticket = [*TheaterEventDTO.model_fields.keys()]
    for item in data[1:]:
        tmp_dict = {}
        for value in fields_ticket:
            try:
                tmp_dict[value] = item[dict_column_name[value]]
            except KeyError as e:
                if e.args[0] != 'date_show_tmp':
                    db_googlesheets_logger.error(item)
                    db_googlesheets_logger.error(e)
        try:
            event = TheaterEventDTO(**tmp_dict)
            events.append(event)
        except ValidationError as exc:
            db_googlesheets_logger.error(repr(exc.errors()[0]['type']))
            db_googlesheets_logger.error(tmp_dict)

    db_googlesheets_logger.info('Список репертуара загружен')
    return events


def load_custom_made_format() -> List[CustomMadeFormatDTO]:
    formats = []

    dict_column_name, len_column = get_column_info('База ФЗМ_')

    qty_tickets = len(get_data_from_spreadsheet(
        RANGE_NAME['База ФЗМ_'] + f'A:A'
    ))

    data = get_data_from_spreadsheet(
        RANGE_NAME['База ФЗМ_'] +
        f'R2C1:R{qty_tickets}C{len_column}',
        value_render_option='UNFORMATTED_VALUE'
    )
    db_googlesheets_logger.info('Данные форматов заказных мероприятий загружены')

    fields_ticket = [*CustomMadeFormatDTO.model_fields.keys()]
    for item in data[1:]:
        tmp_dict = {}
        for value in fields_ticket:
            try:
                tmp_dict[value] = item[dict_column_name[value]]
            except KeyError as e:
                if e.args[0] != 'date_show_tmp':
                    db_googlesheets_logger.error(item)
                    db_googlesheets_logger.error(e)
        try:
            custom_made_format = CustomMadeFormatDTO(**tmp_dict)
            formats.append(custom_made_format)
        except ValidationError as exc:
            db_googlesheets_logger.error(repr(exc.errors()[0]['type']))
            db_googlesheets_logger.error(tmp_dict)

    db_googlesheets_logger.info('Список репертуара загружен')
    return formats


def load_special_ticket_price() -> Dict:
    special_ticket_price = {}
    first_colum = get_data_from_spreadsheet(
        RANGE_NAME['Индив стоимости']
    )
    dict_column_name, len_column = get_column_info('Индив стоимости_')

    data = get_data_from_spreadsheet(
        RANGE_NAME['Индив стоимости_'] +
        f'RC1:R{len(first_colum)}C{len_column}',
        value_render_option='UNFORMATTED_VALUE'
    )

    for item in data[2:]:
        if item[1]:
            type_price = special_ticket_price.setdefault(item[1], {})
        else:
            type_price = special_ticket_price.setdefault(item[0], {})
        type_price.setdefault('будни', {})
        type_price.setdefault('выходные', {})
        type_price['будни'].setdefault(item[2], item[3])
        type_price['выходные'].setdefault(item[2], item[4])

    db_googlesheets_logger.info('Данные индивидуальных стоимостей загружены')
    return special_ticket_price


def load_clients_data(
        event_id: int
) -> Tuple[List[List[str]], Dict[int | str, int]]:
    data_clients_data = []
    first_colum = get_data_from_spreadsheet(RANGE_NAME['База клиентов'])

    dict_column_name, len_column = get_column_info('База клиентов_')
    sheet = (RANGE_NAME['База клиентов_'] +
             f'R1C1:R{len(first_colum)}C{len_column}')

    data = get_data_from_spreadsheet(sheet)

    for item in data[1:]:
        if item[dict_column_name['event_id']] == str(event_id):
            data_clients_data.append(item)

    return data_clients_data, dict_column_name


def load_clients_wait_data(
        event_ids: List[int]
) -> Tuple[List[List[str]], Dict[int | str, int]]:
    data_clients_data = []
    first_colum = get_data_from_spreadsheet(RANGE_NAME['Лист ожидания'])

    dict_column_name, len_column = get_column_info('Лист ожидания_')

    sheet = (RANGE_NAME['Лист ожидания_'] +
             f'R1C1:R{len(first_colum)}C{len_column}')

    data = get_data_from_spreadsheet(sheet)

    for item in data[2:]:
        if int(item[dict_column_name['event_id']]) in event_ids:
            data_clients_data.append(item)

    return data_clients_data, dict_column_name


async def increase_free_and_decrease_nonconfirm_seat(
        context: ContextTypes.DEFAULT_TYPE,
        event_id,
        chose_base_ticket_id,
):
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    q_child_free_seat = schedule_event.qty_child_free_seat
    q_child_nonconfirm_seat = schedule_event.qty_child_nonconfirm_seat
    q_adult_free_seat = schedule_event.qty_adult_free_seat
    q_adult_nonconfirm_seat = schedule_event.qty_adult_nonconfirm_seat

    q_child = chose_base_ticket.quality_of_children
    q_adult = chose_base_ticket.quality_of_adult
    q_add_adult = chose_base_ticket.quality_of_add_adult

    qty_child_free_seat_new = (
            q_child_free_seat + q_child)
    qty_child_nonconfirm_seat_new = (
            q_child_nonconfirm_seat - q_child)
    qty_adult_free_seat_new = (
            q_adult_free_seat + (q_adult + q_add_adult))
    qty_adult_nonconfirm_seat_new = (
            q_adult_nonconfirm_seat - (q_adult + q_add_adult))

    numbers = [
        qty_child_free_seat_new,
        qty_child_nonconfirm_seat_new,
        qty_adult_free_seat_new,
        qty_adult_nonconfirm_seat_new
    ]

    try:
        write_data_reserve(event_id, numbers)
        await db_postgres.update_schedule_event(
            context.session,
            int(event_id),
            qty_child_free_seat=qty_child_free_seat_new,
            qty_child_nonconfirm_seat=qty_child_nonconfirm_seat_new,
            qty_adult_free_seat=qty_adult_free_seat_new,
            qty_adult_nonconfirm_seat=qty_adult_nonconfirm_seat_new,
        )
        return 1
    except TimeoutError as e:
        db_googlesheets_logger.error(e)
        await context.bot.send_message(
            chat_id=context.config.bot.developer_chat_id,
            text=f'Не уменьшились свободные места и не увеличились '
                 f'неподтвержденные места у {event_id=} в клиентскую базу')
        return 0


async def decrease_free_and_increase_nonconfirm_seat(
        context: ContextTypes.DEFAULT_TYPE,
        event_id,
        chose_base_ticket_id,
):
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    q_child_free_seat = schedule_event.qty_child_free_seat
    q_child_nonconfirm_seat = schedule_event.qty_child_nonconfirm_seat
    q_adult_free_seat = schedule_event.qty_adult_free_seat
    q_adult_nonconfirm_seat = schedule_event.qty_adult_nonconfirm_seat

    q_child = chose_base_ticket.quality_of_children
    q_adult = chose_base_ticket.quality_of_adult
    q_add_adult = chose_base_ticket.quality_of_add_adult

    qty_child_free_seat_new = (
            q_child_free_seat - q_child)
    qty_child_nonconfirm_seat_new = (
            q_child_nonconfirm_seat + q_child)
    qty_adult_free_seat_new = (
            q_adult_free_seat - (q_adult + q_add_adult))
    qty_adult_nonconfirm_seat_new = (
            q_adult_nonconfirm_seat + (q_adult + q_add_adult))

    numbers = [
        qty_child_free_seat_new,
        qty_child_nonconfirm_seat_new,
        qty_adult_free_seat_new,
        qty_adult_nonconfirm_seat_new
    ]

    try:
        write_data_reserve(event_id, numbers)
        await db_postgres.update_schedule_event(
            context.session,
            int(event_id),
            qty_child_free_seat=qty_child_free_seat_new,
            qty_child_nonconfirm_seat=qty_child_nonconfirm_seat_new,
            qty_adult_free_seat=qty_adult_free_seat_new,
            qty_adult_nonconfirm_seat=qty_adult_nonconfirm_seat_new,
        )
        return 1
    except TimeoutError as e:
        db_googlesheets_logger.error(e)
        db_googlesheets_logger.error(
            f'{event_id=} Ошибка при обновлении данных')
        await context.bot.send_message(
            chat_id=context.config.bot.developer_chat_id,
            text=f'Не уменьшились свободные места и не увеличились '
                 f'неподтвержденные места у {event_id=} в клиентскую базу')
        return 0


async def increase_free_seat(
        context: ContextTypes.DEFAULT_TYPE,
        event_id,
        chose_base_ticket_id,
):
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    q_child_free_seat = schedule_event.qty_child_free_seat
    q_adult_free_seat = schedule_event.qty_adult_free_seat

    q_child = chose_base_ticket.quality_of_children
    q_adult = chose_base_ticket.quality_of_adult
    q_add_adult = chose_base_ticket.quality_of_add_adult

    qty_child_free_seat_new = (
            q_child_free_seat + q_child)
    qty_adult_free_seat_new = (
            q_adult_free_seat + (q_adult + q_add_adult))

    numbers = [
        qty_child_free_seat_new,
        qty_adult_free_seat_new,
    ]

    try:
        write_data_reserve(event_id, numbers, 3)
        await db_postgres.update_schedule_event(
            context.session,
            int(event_id),
            qty_child_free_seat=qty_child_free_seat_new,
            qty_adult_free_seat=qty_adult_free_seat_new,
        )
        return 1
    except TimeoutError as e:
        db_googlesheets_logger.error(e)
        await context.bot.send_message(
            chat_id=context.config.bot.developer_chat_id,
            text=f'Не увеличились свободные места у {event_id=}'
                 f' в клиентскую базу')
        return 0


async def decrease_free_seat(
        context: ContextTypes.DEFAULT_TYPE,
        event_id,
        chose_base_ticket_id,
):
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    q_child_free_seat = schedule_event.qty_child_free_seat
    q_adult_free_seat = schedule_event.qty_adult_free_seat

    q_child = chose_base_ticket.quality_of_children
    q_adult = chose_base_ticket.quality_of_adult
    q_add_adult = chose_base_ticket.quality_of_add_adult

    qty_child_free_seat_new = (
            q_child_free_seat - q_child)
    qty_adult_free_seat_new = (
            q_adult_free_seat - (q_adult + q_add_adult))

    numbers = [
        qty_child_free_seat_new,
        qty_adult_free_seat_new,
    ]

    try:
        write_data_reserve(event_id, numbers, 3)
        await db_postgres.update_schedule_event(
            context.session,
            int(event_id),
            qty_child_free_seat=qty_child_free_seat_new,
            qty_adult_free_seat=qty_adult_free_seat_new,
        )
        return 1
    except TimeoutError as e:
        db_googlesheets_logger.error(e)
        await context.bot.send_message(
            chat_id=context.config.bot.developer_chat_id,
            text=f'Не уменьшились свободные места у {event_id=}'
                 f' в клиентскую базу')
        return 0


async def decrease_nonconfirm_seat(
        context: ContextTypes.DEFAULT_TYPE,
        event_id,
        chose_base_ticket_id
):
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    q_child_nonconfirm_seat = schedule_event.qty_child_nonconfirm_seat
    q_adult_nonconfirm_seat = schedule_event.qty_adult_nonconfirm_seat

    q_child = chose_base_ticket.quality_of_children
    q_adult = chose_base_ticket.quality_of_adult
    q_add_adult = chose_base_ticket.quality_of_add_adult

    qty_child_nonconfirm_seat_new = (
            q_child_nonconfirm_seat - q_child)
    qty_adult_nonconfirm_seat_new = (
            q_adult_nonconfirm_seat - (q_adult + q_add_adult))

    numbers = [
        qty_child_nonconfirm_seat_new,
        qty_adult_nonconfirm_seat_new
    ]

    try:
        write_data_reserve(event_id, numbers, 2)
        await db_postgres.update_schedule_event(
            context.session,
            int(event_id),
            qty_child_nonconfirm_seat=qty_child_nonconfirm_seat_new,
            qty_adult_nonconfirm_seat=qty_adult_nonconfirm_seat_new,
        )
        return 1
    except TimeoutError as e:
        db_googlesheets_logger.error(e)
        await context.bot.send_message(
            chat_id=context.config.bot.developer_chat_id,
            text=f'Не уменьшились неподтвержденные места у {event_id=}'
                 f' в клиентскую базу')
        return 0

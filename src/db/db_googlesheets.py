import logging
import datetime

from typing import Any, List, Tuple, Dict

from pydantic import ValidationError
from telegram import Update
from telegram.ext import ContextTypes

from api.googlesheets import (
    get_data_from_spreadsheet,
    get_column_info,
    write_data_reserve
)
from db import db_postgres
from settings.settings import RANGE_NAME
from utilities.schemas.schedule_event import ScheduleEventDTO
from utilities.schemas.theater_event import TheaterEventDTO
from utilities.schemas.ticket import BaseTicketDTO
from utilities.utl_func import get_full_name_event

db_googlesheets_logger = logging.getLogger('bot.db.googlesheets')


def load_list_show() -> dict[int, dict[str, Any]]:
    """
    Возвращает 1 словарь из гугл-таблицы с листа "Список спектаклей"
    Проводит фильтрацию по дате, все прошедшие даты исключаются из выборки

    dict_of_name_show -> key: str, item: Any

    :return: dict
    """
    # TODO Выделить загрузку спектаклей в отдельную задачу и хранить ее сразу в
    #  bot_data
    dict_column_name, len_column = get_column_info('Список спектаклей_')

    qty_shows = len(get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] + f'A:A'
    ))
    data = get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] +
        f'R3C1:R{qty_shows}C{len_column}'
    )
    db_googlesheets_logger.info('Данные загружены')

    dict_of_shows = {}
    for item in data:
        theater_events_id: int = int(item[dict_column_name['theater_events_id']])
        name: str = item[dict_column_name['name']]
        flag_premiere: bool = True if item[dict_column_name[
            'flag_active_premiere']] == 'TRUE' else False
        min_age_child: int = int(item[dict_column_name['min_age_child']])
        max_age_child: int = int(item[dict_column_name['max_age_child']])
        show_emoji: str = item[dict_column_name['show_emoji']]
        duration: int = int(item[dict_column_name['duration']])
        flag_birthday: bool = True if item[dict_column_name[
            'flag_active_bd']] == 'TRUE' else False
        max_num_child: int = int(item[dict_column_name['max_num_child_bd']])
        max_num_adult: int = int(item[dict_column_name['max_num_adult_bd']])
        flag_repertoire: bool = True if item[dict_column_name[
            'flag_active_repertoire']] == 'TRUE' else False
        flag_indiv_cost: bool = True if item[dict_column_name[
            'flag_indiv_cost']] == 'TRUE' else False
        price_type: str = item[dict_column_name['price_type']]

        full_name = get_full_name_event(name,
                                        flag_premiere,
                                        min_age_child,
                                        max_age_child,
                                        duration)

        dict_of_shows[theater_events_id] = {
            'name': name,
            'flag_premiere': flag_premiere,
            'min_age_child': min_age_child,
            'max_age_child': max_age_child,
            'show_emoji': show_emoji,
            'duration': duration,
            'birthday': {
                'flag': flag_birthday,
                'max_num_child': max_num_child,
                'max_num_adult': max_num_adult,
            },
            'flag_repertoire': flag_repertoire,
            'flag_indiv_cost': flag_indiv_cost,
            'full_name': full_name,
            'price_type': price_type,
        }

    return (
        dict_of_shows
    )


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

    qty_child_free_seat_now = schedule_event.qty_child_free_seat
    qty_child_nonconfirm_seat_now = schedule_event.qty_child_nonconfirm_seat
    qty_adult_free_seat_now = schedule_event.qty_adult_free_seat
    qty_adult_nonconfirm_seat_now = schedule_event.qty_adult_nonconfirm_seat

    qty_child_free_seat_new = (
            int(qty_child_free_seat_now) +
            int(chose_base_ticket.quality_of_children))
    qty_child_nonconfirm_seat_new = (
            int(qty_child_nonconfirm_seat_now) -
            int(chose_base_ticket.quality_of_children))
    qty_adult_free_seat_new = (
            int(qty_adult_free_seat_now) +
            int(chose_base_ticket.quality_of_adult +
                chose_base_ticket.quality_of_add_adult))
    qty_adult_nonconfirm_seat_new = (
            int(qty_adult_nonconfirm_seat_now) -
            int(chose_base_ticket.quality_of_adult +
                chose_base_ticket.quality_of_add_adult))

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
    except TimeoutError as e:
        db_googlesheets_logger.error(e)


async def decrease_free_and_increase_nonconfirm_seat(
        context: ContextTypes.DEFAULT_TYPE,
        event_id,
        chose_base_ticket_id,
):
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    qty_child_free_seat_now = schedule_event.qty_child_free_seat
    qty_child_nonconfirm_seat_now = schedule_event.qty_child_nonconfirm_seat
    qty_adult_free_seat_now = schedule_event.qty_adult_free_seat
    qty_adult_nonconfirm_seat_now = schedule_event.qty_adult_nonconfirm_seat

    qty_child_free_seat_new = (
            int(qty_child_free_seat_now) -
            int(chose_base_ticket.quality_of_children))
    qty_child_nonconfirm_seat_new = (
            int(qty_child_nonconfirm_seat_now) +
            int(chose_base_ticket.quality_of_children))
    qty_adult_free_seat_new = (
            int(qty_adult_free_seat_now) -
            int(chose_base_ticket.quality_of_adult +
                chose_base_ticket.quality_of_add_adult))
    qty_adult_nonconfirm_seat_new = (
            int(qty_adult_nonconfirm_seat_now) +
            int(chose_base_ticket.quality_of_adult +
                chose_base_ticket.quality_of_add_adult))

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
    qty_child_free_seat_now = schedule_event.qty_child_free_seat
    qty_adult_free_seat_now = schedule_event.qty_adult_free_seat

    qty_child_free_seat_new = (
            int(qty_child_free_seat_now) +
            int(chose_base_ticket.quality_of_children))
    qty_adult_free_seat_new = (
            int(qty_adult_free_seat_now) +
            int(chose_base_ticket.quality_of_adult +
                chose_base_ticket.quality_of_add_adult))

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
    except TimeoutError as e:
        db_googlesheets_logger.error(e)


async def decrease_free_seat(
        context: ContextTypes.DEFAULT_TYPE,
        event_id,
        chose_base_ticket_id,
):
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)
    qty_child_free_seat_now = schedule_event.qty_child_free_seat
    qty_adult_free_seat_now = schedule_event.qty_adult_free_seat

    qty_child_free_seat_new = (
            int(qty_child_free_seat_now) -
            int(chose_base_ticket.quality_of_children))
    qty_adult_free_seat_new = (
            int(qty_adult_free_seat_now) -
            int(chose_base_ticket.quality_of_adult +
                chose_base_ticket.quality_of_add_adult))

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
    except TimeoutError as e:
        db_googlesheets_logger.error(e)


async def decrease_nonconfirm_seat(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        event_id,
        chose_base_ticket_id
):
    query = update.callback_query
    chat_id = query.data.split('|')[1].split()[0]
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    try:
        schedule_event = await db_postgres.get_schedule_event(
            context.session, event_id)
        chose_base_ticket = await db_postgres.get_base_ticket(
            context.session, chose_base_ticket_id)

        qty_child_nonconfirm_seat_now = schedule_event.qty_child_nonconfirm_seat
        qty_adult_nonconfirm_seat_now = schedule_event.qty_adult_nonconfirm_seat

        qty_child_nonconfirm_seat_new = int(
            qty_child_nonconfirm_seat_now) - int(
            chose_base_ticket.quality_of_children)
        qty_adult_nonconfirm_seat_new = int(
            qty_adult_nonconfirm_seat_now) - int(
            chose_base_ticket.quality_of_adult +
            chose_base_ticket.quality_of_add_adult)

        numbers = [
            qty_child_nonconfirm_seat_new,
            qty_adult_nonconfirm_seat_new
        ]
        write_data_reserve(event_id, numbers, 2)
        await db_postgres.update_schedule_event(
            context.session,
            int(event_id),
            qty_child_nonconfirm_seat=qty_child_nonconfirm_seat_new,
            qty_adult_nonconfirm_seat=qty_adult_nonconfirm_seat_new,
        )

    except TimeoutError:
        await update.effective_chat.send_message(
            text=f'Для пользователя @{user.username} {user.full_name} '
                 f'подтверждение в авто-режиме не сработало\n'
                 f'Номер строки для обновления:\n{event_id}',
            reply_to_message_id=query.message.message_id,
            message_thread_id=query.message.message_thread_id
        )
        db_googlesheets_logger.error(TimeoutError)
        db_googlesheets_logger.error(": ".join(
            [
                f'Для пользователя {user} подтверждение в '
                f'авто-режиме не сработало',
                'event_id для обновления',
                f'{event_id}',
            ]
        ))
    except ConnectionError:
        await update.effective_chat.send_message(
            text=f'Пользователю @{user.username} {user.full_name} '
                 f'не списаны неподтвержденные места\n'
                 f'Номер строки для обновления: {event_id}\n'
                 f'user_id {user.id}',
            reply_to_message_id=query.message.message_id,
            message_thread_id=query.message.message_thread_id
        )
    return query, user

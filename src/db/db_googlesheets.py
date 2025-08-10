import logging
import datetime

from typing import List, Tuple, Dict, Type, Any, Optional, Callable, TypeVar

from pydantic import ValidationError
from telegram.ext import ContextTypes

from api.googlesheets import load_from_gspread, write_data_reserve
from db import db_postgres
from settings import parse_settings
from utilities.schemas import (
    CustomMadeFormatDTO, ScheduleEventDTO, TheaterEventDTO, BaseTicketDTO
)

db_googlesheets_logger = logging.getLogger('bot.db.googlesheets')
config = parse_settings()
sheet_id_domik = config.sheets.sheet_id_domik
sheet_id_cme = config.sheets.sheet_id_cme

T = TypeVar('T')


async def _load_from_gspread(
        sheet_id: str,
        name_sh: str,
        value_render_option: str = 'FORMATTED_VALUE',
):
    """
    Унифицированная загрузка данных из Google Sheets по имени листа.

    Параметры:
      - sheet_id: ID таблицы
      - name_sh: ключ из RANGE_NAME (например, 'База спектаклей_', 'Список спектаклей_', ...)
      - value_render_option: формат данных из гугл-таблицы

    Возвращает кортеж (data, dict_column_name).
    """
    dict_column_name, len_col = await get_column_info(sheet_id, name_sh)

    first_col = await get_data_from_spreadsheet(
        sheet_id, RANGE_NAME[name_sh] + 'A:A')

    len_row = len(first_col)
    sheet_range = f"{RANGE_NAME[name_sh]}R2C1:R{len_row}C{len_col}"

    data = await get_data_from_spreadsheet(
        sheet_id,
        sheet_range,
        value_render_option=value_render_option
    )
    return data, dict_column_name


def _map_row_to_dict(
        row: list,
        column_map: dict,
        field_names: list
) -> dict:
    row_dict = {}
    for field in field_names:
        try:
            row_dict[field] = row[column_map[field]]
        except KeyError as exc:
            if exc.args and exc.args[0] != "date_show_tmp":
                db_googlesheets_logger.error(
                    "Missing column mapping for field")
                db_googlesheets_logger.error("row=%s", row)
                db_googlesheets_logger.error("error=%s", exc)
        except IndexError as exc:
            db_googlesheets_logger.error("Row is shorter than expected")
            db_googlesheets_logger.error("row=%s", row)
            db_googlesheets_logger.error("error=%s", exc)
    return row_dict


def _process_row(
        dto_cls: Type[Any],
        row_dict: dict,
        *,
        only_active: bool = False,
        active_attr: str = None,
        only_actual: bool = False,
        date_getter: Optional[Callable[[Any], datetime.date]] = None,
) -> Any | None:
    """
    Универсальная обработка строки, создаёт DTO класса dto_cls из row_dict,
    логирует ValidationError и выполняет общие фильтры.

    Параметры:
      - dto_cls: класс Pydantic DTO (например, BaseTicketDTO или ScheduleEventDTO)
      - row_dict: словарь с полями для DTO
      - only_active: если True — применяется фильтр по активности (если active_attr указан)
      - active_attr: имя атрибута в DTO, указывающего активность (например, 'flag_active' или 'flag_turn_on_off')
      - only_actual: если True — применяется фильтр по дате (только для DTO, у которых есть date_getter)
      - date_getter: callable(dto) -> date, функция/метод для получения даты события (возвращает datetime.date или datetime.datetime)

    Возвращает экземпляр dto_cls или None (если валидация не прошла или запись отфильтрована).
    """
    try:
        obj = dto_cls(**row_dict)
    except ValidationError as exc:
        err_type = repr(exc.errors()[0]["type"])
        db_googlesheets_logger.error("Validation error: %s", err_type)
        db_googlesheets_logger.error("Invalid row dict: %s", row_dict)
        return None

    # Фильтрация по активности (если задано имя атрибута)
    if only_active and active_attr:
        if not getattr(obj, active_attr, False):
            return None

    # Фильтрация по дате (если требуется и передан date_getter)
    if only_actual and date_getter:
        event_date = date_getter(obj)
        # если возврат — datetime, привести к date
        if hasattr(event_date, "date"):
            event_date = event_date.date()
        if event_date < datetime.date.today():
            return None

    return obj


async def load_entities_from_sheet(
        dto_cls: Type[T],
        *,
        sheet_id: str,
        name_sh: str,
        value_render_option: str = 'UNFORMATTED_VALUE',
        only_active: bool = False,
        active_attr: Optional[str] = None,
        only_actual: bool = False,
        date_getter: Optional[Callable[[Any], datetime.date]] = None,
) -> List[T]:
    """
    Универсальный загрузчик записей из Google Sheets.
    Параметризуется DTO-классом, именем листа и общими фильтрами.
    """
    data, dict_column_name = await _load_from_gspread(
        sheet_id,
        name_sh,
        value_render_option=value_render_option
    )

    field_names = list(dto_cls.model_fields.keys())
    result: List[T] = []

    for row in data[1:]:
        row_dict = _map_row_to_dict(row, dict_column_name, field_names)
        entity = _process_row(
            dto_cls,
            row_dict,
            only_active=only_active,
            active_attr=active_attr,
            only_actual=only_actual,
            date_getter=date_getter
        )
        if entity is None:
            continue
        result.append(entity)

    return result


async def load_base_tickets(only_active=True) -> List[BaseTicketDTO]:
    name_sh = 'Варианты стоимости_'
    tickets = await load_entities_from_sheet(
        BaseTicketDTO,
        sheet_id=sheet_id_domik,
        name_sh=name_sh,
        value_render_option='FORMATTED_VALUE',
        only_active=only_active,
        active_attr='flag_active',
    )
    db_googlesheets_logger.info('Список билетов загружен')
    return tickets


async def load_schedule_events(
        only_active: bool = True,
        only_actual: bool = True
) -> List[ScheduleEventDTO]:
    """
    Загружает события из Google Sheets и возвращает список ScheduleEventDTO.
    Фильтры:
      - only_active: если True — возвращать только включенные события
      - only_actual: если True — возвращать только события с датой >= today
    """
    name_sh = 'База спектаклей_'
    events = await load_entities_from_sheet(
        ScheduleEventDTO,
        sheet_id=sheet_id_domik,
        name_sh=name_sh,
        value_render_option='UNFORMATTED_VALUE',
        only_active=only_active,
        active_attr='flag_turn_on_off',
        only_actual=only_actual,
        date_getter=lambda e: e.get_date_event(),
    )
    db_googlesheets_logger.info("Список мероприятий загружен")
    return events


async def load_theater_events() -> List[TheaterEventDTO]:
    name_sh = 'Список спектаклей_'
    events = await load_entities_from_sheet(
        TheaterEventDTO,
        sheet_id=sheet_id_domik,
        name_sh=name_sh,
        value_render_option='UNFORMATTED_VALUE',
    )
    db_googlesheets_logger.info('Список репертуара загружен')
    return events


async def load_custom_made_format() -> List[CustomMadeFormatDTO]:
    name_sh = 'База ФЗМ_'
    cmfs = await load_entities_from_sheet(
        CustomMadeFormatDTO,
        sheet_id=sheet_id_cme,
        name_sh=name_sh,
        value_render_option='UNFORMATTED_VALUE',
    )
    db_googlesheets_logger.info('Список репертуара загружен')
    return cmfs


async def load_special_ticket_price() -> Dict:
    name_sh = 'Индив стоимости_'
    data, dict_column_name = await _load_from_gspread(
        sheet_id_domik,
        name_sh,
        value_render_option='UNFORMATTED_VALUE')

    special_ticket_price = {}
    for item in data[1:]:
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


async def load_clients_wait_data(
        event_ids: List[int]
) -> Tuple[List[List[str]], Dict[int | str, int]]:
    name_sh = 'Лист ожидания_'
    data, dict_column_name = await _load_from_gspread(
        sheet_id_domik,
        name_sh,
        value_render_option='UNFORMATTED_VALUE')

    data_clients_data = []
    for item in data[1:]:
        if int(item[dict_column_name['event_id']]) in event_ids:
            data_clients_data.append(item)

    return data_clients_data, dict_column_name


async def increase_free_and_decrease_nonconfirm_seat(
        context: "ContextTypes.DEFAULT_TYPE",
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
        await write_data_reserve(sheet_id_domik, event_id, numbers)
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
                 f'неподтвержденные места у {event_id=} в расписании')
        return 0


async def decrease_free_and_increase_nonconfirm_seat(
        context: "ContextTypes.DEFAULT_TYPE",
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
        await write_data_reserve(sheet_id_domik, event_id, numbers)
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
                 f'неподтвержденные места у {event_id=} в расписании')
        return 0


async def increase_free_seat(
        context: "ContextTypes.DEFAULT_TYPE",
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
        await write_data_reserve(sheet_id_domik, event_id, numbers, 3)
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
                 f' в расписании')
        return 0


async def decrease_free_seat(
        context: "ContextTypes.DEFAULT_TYPE",
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
        await write_data_reserve(sheet_id_domik, event_id, numbers, 3)
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
                 f' в расписании')
        return 0


async def decrease_nonconfirm_seat(
        context: "ContextTypes.DEFAULT_TYPE",
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
        await write_data_reserve(sheet_id_domik, event_id, numbers, 2)
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
                 f' в расписании')
        return 0


async def update_free_seat(
        context: "ContextTypes.DEFAULT_TYPE",
        event_id,
        old_base_ticket_id,
        new_base_ticket_id
):
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    old_base_ticket = await db_postgres.get_base_ticket(
        context.session, old_base_ticket_id)
    new_base_ticket = await db_postgres.get_base_ticket(
        context.session, new_base_ticket_id)

    q_child_free_seat = schedule_event.qty_child_free_seat
    q_adult_free_seat = schedule_event.qty_adult_free_seat

    q_child_old = old_base_ticket.quality_of_children
    q_adult_old = old_base_ticket.quality_of_adult
    q_add_adult_old = old_base_ticket.quality_of_add_adult

    q_child_new = new_base_ticket.quality_of_children
    q_adult_new = new_base_ticket.quality_of_adult
    q_add_adult_new = new_base_ticket.quality_of_add_adult

    qty_child_free_seat_new = (
            q_child_free_seat
            + q_child_old
            - q_child_new
    )
    qty_adult_free_seat_new = (
            q_adult_free_seat
            + (q_adult_old + q_add_adult_old)
            - (q_adult_new + q_add_adult_new)
    )

    numbers = [
        qty_child_free_seat_new,
        qty_adult_free_seat_new,
    ]

    try:
        await write_data_reserve(sheet_id_domik, event_id, numbers, 3)
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
            text=f'Не обновились свободные места у {event_id=} в расписании')
        return 0

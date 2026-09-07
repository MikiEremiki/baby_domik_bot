import logging
import datetime

from typing import List, Tuple, Dict, Type, Any, Optional, Callable, TypeVar

from pydantic import ValidationError
from telegram.ext import ContextTypes

from api.googlesheets import load_from_gspread, write_data_reserve
from api.gspread_pub import publish_write_data_reserve
from db import db_postgres
from settings import parse_settings
from utilities.schemas import (
    CustomMadeFormatDTO, ScheduleEventDTO, TheaterEventDTO, BaseTicketDTO
)
from utilities.schemas.promotion import PromotionDTO

db_googlesheets_logger = logging.getLogger('bot.db.googlesheets')
config = parse_settings()
sheet_id_domik = config.sheets.sheet_id_domik
sheet_id_cme = config.sheets.sheet_id_cme

T = TypeVar('T')


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


async def _publish_write_data_reserve(
        event_id, numbers: List[int], option: int = 1):
    try:
        await publish_write_data_reserve(
            sheet_id_domik, event_id, numbers, option)
    except Exception as e:
        db_googlesheets_logger.exception(
            f"Failed to publish gspread task, fallback to direct call: {e}")
        await write_data_reserve(sheet_id_domik, event_id, numbers, option)


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
    data, dict_column_name = await load_from_gspread(
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


def _parse_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in {"1", "да", "true", "y", "yes", "on", "+"}


def _parse_int(val, default=0) -> int:
    try:
        return int(str(val).strip())
    except Exception:
        return default


def _parse_datetime(val) -> datetime.datetime | None:
    if not val:
        return None
    try:
        # Try ISO first
        return datetime.datetime.fromisoformat(str(val))
    except Exception:
        try:
            # Try dd.mm.yyyy
            return datetime.datetime.strptime(str(val).strip(), "%d.%m.%Y")
        except Exception:
            try:
                # Try dd.mm (+current year)
                today = datetime.datetime.now().date()
                return datetime.datetime.strptime(
                    f"{str(val).strip()}.{today.year}", "%d.%m.%Y"
                )
            except Exception:
                return None


async def load_promotions() -> List[PromotionDTO]:
    name_sh = 'Промокоды_'
    try:
        data, dict_column_name = await load_from_gspread(
            sheet_id_domik,
            name_sh,
            value_render_option='UNFORMATTED_VALUE'
        )
    except Exception as e:
        db_googlesheets_logger.exception(f"Не удалось загрузить лист '{name_sh}': {e}")
        return []

    # Expected columns (fallback to optional names)
    col_code = dict_column_name.get('Код') or dict_column_name.get('code')
    col_discount = dict_column_name.get('Скидка') or dict_column_name.get('discount')
    col_type = dict_column_name.get('Тип') or dict_column_name.get('type')
    col_start = dict_column_name.get('Начало') or dict_column_name.get('start')
    col_expire = dict_column_name.get('Срок действия') or dict_column_name.get('expire')
    col_visible = dict_column_name.get('Показывать как кнопку') or dict_column_name.get('visible')
    col_verify = dict_column_name.get('Требует подтверждения') or dict_column_name.get('verify')
    col_vtext = dict_column_name.get('Текст верификации') or dict_column_name.get('verification_text')
    col_min_sum = dict_column_name.get('Мин. сумма заказа') or dict_column_name.get('min_sum')
    col_desc = dict_column_name.get('Описание') or dict_column_name.get('description')

    promotions: List[PromotionDTO] = []
    for row in data[1:]:
        try:
            if col_code is None or col_discount is None:
                continue
            code = str(row[col_code]).strip() if row[col_code] else ''
            if not code:
                continue
            discount_val = _parse_int(row[col_discount], 0)
            dtype_raw = (str(row[col_type]).strip().lower() if col_type is not None and row[col_type] else 'fixed')
            dtype = 'percentage' if ('%' in dtype_raw or 'процент' in dtype_raw) else 'fixed'

            promo = PromotionDTO(
                code=code,
                discount=discount_val,
                discount_type=dtype,
                start_date=_parse_datetime(row[col_start]) if col_start is not None else None,
                expire_date=_parse_datetime(row[col_expire]) if col_expire is not None else None,
                is_visible_as_option=_parse_bool(row[col_visible]) if col_visible is not None else False,
                requires_verification=_parse_bool(row[col_verify]) if col_verify is not None else False,
                verification_text=str(row[col_vtext]).strip() if col_vtext is not None and row[col_vtext] else None,
                min_purchase_sum=_parse_int(row[col_min_sum], 0) if col_min_sum is not None else 0,
                description_user=str(row[col_desc]).strip() if col_desc is not None and row[col_desc] else None,
            )
            promotions.append(promo)
        except Exception as e:
            db_googlesheets_logger.exception(f"Ошибка парсинга строки промокода: {e}")
            continue

    db_googlesheets_logger.info('Список промокодов загружен')
    return promotions


async def load_special_ticket_price() -> Dict:
    name_sh = 'Индив стоимости_'
    data, dict_column_name = await load_from_gspread(
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


async def _sync_schedule_event_seats(
        context: 'ContextTypes.DEFAULT_TYPE',
        event_id: int | str,
        option: int,
        error_msg_title: str
) -> int:
    """
    Вспомогательная функция для синхронизации мест сеанса с Google Sheets.
    Получает актуальные остатки мест из БД Postgres и отправляет задачу на запись в Google Sheets.
    """
    try:
        seats = await db_postgres.get_schedule_event_available_seats(
            context.session, int(event_id))
        match option:
            case 1:
                numbers = [
                    seats['free_child'],
                    seats['nonconfirm_child'],
                    seats['free_adult'],
                    seats['nonconfirm_adult']
                ]
            case 2:
                numbers = [
                    seats['nonconfirm_child'],
                    seats['nonconfirm_adult']
                ]
            case 3:
                numbers = [
                    seats['free_child'],
                    seats['free_adult']
                ]
            case _:
                raise ValueError(f"Unknown seat sync option: {option}")

        await _publish_write_data_reserve(int(event_id), numbers, option)
        return 1
    except Exception as e:
        db_googlesheets_logger.error(f"Error in {error_msg_title}: {e}")
        await context.bot.send_message(
            chat_id=context.config.bot.developer_chat_id,
            text=f'{error_msg_title} у {event_id=} в расписании')
        return 0


async def load_clients_wait_data(
        event_ids: List[int]
) -> Tuple[List[List[str]], Dict[int | str, int]]:
    name_sh = 'Лист ожидания_'
    data, dict_column_name = await load_from_gspread(
        sheet_id_domik,
        name_sh)

    data_clients_data = []
    for item in data[1:]:
        if int(item[dict_column_name['event_id']]) in event_ids:
            data_clients_data.append(item)

    return data_clients_data, dict_column_name


async def increase_free_and_decrease_nonconfirm_seat(
        context: 'ContextTypes.DEFAULT_TYPE',
        event_id: int | str,
) -> int:
    """
    Синхронизирует свободные и неподтвержденные места сеанса (опция 1).
    Используется при отмене/отклонении неоплаченной брони.
    """
    return await _sync_schedule_event_seats(
        context,
        event_id,
        option=1,
        error_msg_title='Не уменьшились свободные места и не увеличились неподтвержденные места'
    )


async def decrease_free_and_increase_nonconfirm_seat(
        context: 'ContextTypes.DEFAULT_TYPE',
        event_id: int | str,
) -> int:
    """
    Синхронизирует свободные и неподтвержденные места сеанса (опция 1).
    Используется при резервировании билета пользователем до оплаты.
    """
    return await _sync_schedule_event_seats(
        context,
        event_id,
        option=1,
        error_msg_title='Не уменьшились свободные места и не увеличились неподтвержденные места'
    )


async def increase_free_seat(
        context: 'ContextTypes.DEFAULT_TYPE',
        event_id: int | str,
) -> int:
    """
    Синхронизирует свободные места сеанса (опция 3).
    Используется при возврате оплаченного билета или освобождении мест.
    """
    return await _sync_schedule_event_seats(
        context,
        event_id,
        option=3,
        error_msg_title='Не увеличились свободные места'
    )


async def decrease_free_seat(
        context: 'ContextTypes.DEFAULT_TYPE',
        event_id: int | str,
) -> int:
    """
    Синхронизирует свободные места сеанса (опция 3).
    Используется при прямом списании свободных мест (например, админом или при оплате).
    """
    return await _sync_schedule_event_seats(
        context,
        event_id,
        option=3,
        error_msg_title='Не уменьшились свободные места'
    )


async def decrease_nonconfirm_seat(
        context: 'ContextTypes.DEFAULT_TYPE',
        event_id: int | str,
) -> int:
    """
    Синхронизирует неподтвержденные места сеанса (опция 2).
    Используется при подтверждении брони (перевод из неподтвержденных в подтвержденные).
    """
    return await _sync_schedule_event_seats(
        context,
        event_id,
        option=2,
        error_msg_title='Не уменьшились неподтвержденные места'
    )


async def update_free_seat(
        context: 'ContextTypes.DEFAULT_TYPE',
        event_id: int | str,
) -> int:
    """
    Синхронизирует свободные места сеанса (опция 3).
    Используется при смене типа билета у существующей брони.
    """
    return await _sync_schedule_event_seats(
        context,
        event_id,
        option=3,
        error_msg_title='Не обновились свободные места'
    )

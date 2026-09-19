import datetime
from typing import Optional, Any

from settings.settings import DICT_CONVERT_WEEKDAY_NUMBER_TO_STR


def convert_sheets_datetime(
        sheets_date: int,
        sheets_time: float = 0,
        utc_offset: int = 0
) -> datetime.datetime:
    hours = int(sheets_time * 24) + utc_offset
    minutes = int(sheets_time * 24 % 1 * 60)
    return (datetime.datetime(1899, 12, 30)
            + datetime.timedelta(days=sheets_date,
                                 hours=hours,
                                 minutes=minutes))


def to_naive(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Приводит datetime к naive (без tzinfo) в локальном времени."""
    if dt is None:
        return None
    if dt.tzinfo:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def datetime_to_sheets_date_time(
        dt_val: datetime.datetime | str,
        utc_offset: int = 3
) -> tuple[int, float]:
    """
    Конвертирует datetime в пару (sheets_date, sheets_time) для Google Sheets.
    """
    if isinstance(dt_val, str):
        dt = datetime.datetime.fromisoformat(dt_val)
        if dt.tzinfo is None:
            dt_local = dt
        else:
            from zoneinfo import ZoneInfo
            dt_local = dt.astimezone(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)
    else:
        dt = dt_val
        if dt.tzinfo is None:
            dt_local = dt + datetime.timedelta(hours=utc_offset)
        else:
            from zoneinfo import ZoneInfo
            dt_local = dt.astimezone(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)

    base_date = datetime.date(1899, 12, 30)
    sheets_date = (dt_local.date() - base_date).days
    sheets_time = (dt_local.hour * 3600 + dt_local.minute * 60 + dt_local.second) / 86400.0
    return sheets_date, sheets_time


def format_cell_value_for_report(column_name: str, val: Any) -> str:
    if val is None or val == '' or val == '—':
        return '—'

    # Форматирование даты: dd.mm (w)
    if column_name == 'date_show':
        try:
            dt = convert_sheets_datetime(int(val))
            weekday = DICT_CONVERT_WEEKDAY_NUMBER_TO_STR.get(int(dt.strftime('%w')), '')
            return f"{dt.strftime('%d.%m')} ({weekday})"
        except Exception:
            return str(val)

    # Форматирование времени: HH:MM
    if column_name == 'time_show':
        try:
            s_time = float(val)
            hours = int(s_time * 24)
            minutes = int(round((s_time * 24 % 1) * 60))
            if minutes >= 60:
                hours += 1
                minutes = 0
            return f"{hours:02d}:{minutes:02d}"
        except Exception:
            return str(val)

    # Булевы флаги
    if column_name in ('flag_turn_on_off', 'flag_gift', 'flag_christmas_tree', 'flag_santa'):
        if isinstance(val, bool):
            return 'Да' if val else 'Нет'
        if str(val).lower() in ('true', '1', 'да'):
            return 'Да'
        if str(val).lower() in ('false', '0', 'нет'):
            return 'Нет'

    return str(val)

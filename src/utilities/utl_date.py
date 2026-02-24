import datetime
from typing import Optional


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

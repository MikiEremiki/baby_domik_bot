import datetime


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

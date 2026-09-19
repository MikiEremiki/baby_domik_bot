import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from db.models import ScheduleEvent
from utilities.utl_func import (
    MOSCOW_TZ,
    to_moscow_dt,
    get_time_with_timezone,
    get_formatted_date_and_time_of_event,
)
from handlers.schedule_hl import handle_datetime


def test_to_moscow_dt_naive():
    # Naive UTC datetime: 2026-10-25 09:00:00 (UTC) -> 12:00:00 MSK (UTC+3)
    dt_naive = datetime(2026, 10, 25, 9, 0, 0)
    dt_msk = to_moscow_dt(dt_naive)
    assert dt_msk.tzinfo == MOSCOW_TZ
    assert dt_msk.hour == 12
    assert dt_msk.day == 25


def test_to_moscow_dt_aware_utc():
    # Aware UTC datetime: 2026-10-25 22:00:00 UTC -> 2026-10-26 01:00:00 MSK
    dt_utc = datetime(2026, 10, 25, 22, 0, 0, tzinfo=timezone.utc)
    dt_msk = to_moscow_dt(dt_utc)
    assert dt_msk.hour == 1
    assert dt_msk.day == 26
    assert dt_msk.month == 10


def test_get_formatted_date_and_time_of_event():
    # Event in UTC: 2026-05-15 08:30:00 UTC -> 11:30:00 MSK (Friday)
    event = ScheduleEvent(
        id=1,
        datetime_event=datetime(2026, 5, 15, 8, 30, 0, tzinfo=timezone.utc)
    )
    time_str = asyncio.run(get_time_with_timezone(event))
    assert time_str == "11:30"

    date_str, time_str = asyncio.run(get_formatted_date_and_time_of_event(event))
    assert time_str == "11:30"
    assert "15.05" in date_str
    assert "пт" in date_str


def test_schedule_hl_handle_datetime_input_msk():
    # Setup Telegram mock update and context
    update = MagicMock()
    update.effective_message.text = "25.10.2026 15:30"
    update.effective_message.delete = AsyncMock()
    update.callback_query = None

    context = MagicMock()
    context.user_data = {
        'reserve_user_data': {'back': {}},
        'new_schedule_event': {
            'data': {},
            'service': {
                'message_id': 123,
            }
        }
    }
    context.bot.edit_message_text = AsyncMock()

    res_state = asyncio.run(handle_datetime(update, context))
    saved_dt = context.user_data['new_schedule_event']['data']['datetime_event']

    assert saved_dt.tzinfo == MOSCOW_TZ
    assert saved_dt.year == 2026
    assert saved_dt.month == 10
    assert saved_dt.day == 25
    assert saved_dt.hour == 15
    assert saved_dt.minute == 30

"""Lightweight utility functions for theater and schedule event models.

This module has no dependency on `permissions`, `telegram.ext`, `schemas`,
or `settings_parser` — it can be safely imported in isolated Docker containers
(sales_worker, fastapi) that do not carry the full bot source tree.
"""
from datetime import time, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from db import ScheduleEvent, TheaterEvent
from settings.settings import DICT_CONVERT_WEEKDAY_NUMBER_TO_STR
from utilities.utl_date import to_moscow_dt


def _format_age_banner(min_age_child: int, max_age_child: Optional[int]) -> str:
    banner = ''
    if min_age_child > 0:
        banner += f'👶🏼{min_age_child}'
    if max_age_child is not None and max_age_child > 0:
        banner += f'-{max_age_child}'
    elif min_age_child > 0:
        # если есть минимальный возраст, но нет максимального
        banner += '+'
    return banner


def _format_duration(duration: Optional[time]) -> str:
    if duration is None:
        return ''
    if isinstance(duration, time):
        duration_minutes = duration.hour * 60 + duration.minute
    else:
        return ''
    if duration_minutes <= 0:
        return ''
    parts = ['⏳']
    hours = duration_minutes // 60
    minutes = duration_minutes % 60
    if hours > 0:
        parts.append(f'{hours}ч')
    if minutes > 0:
        parts.append(f'{minutes}мин')
    return ''.join(parts)


def get_full_name_event(event: TheaterEvent, add_note=False, add_link=False):
    name = event.name
    flag_premiere = event.flag_premier
    min_age_child = event.min_age_child
    max_age_child = event.max_age_child
    duration = event.duration
    note = event.note
    link = event.link

    full_name: str = name
    full_name += '\n'
    if flag_premiere:
        full_name += '📍'
    age_banner = _format_age_banner(min_age_child, max_age_child)
    if age_banner:
        full_name += age_banner
    duration_banner = _format_duration(duration)
    if duration_banner:
        full_name += duration_banner
    if note and add_note:
        full_name += f'\n<i>{note}</i>'
    if link and add_link:
        full_name += f'\n<a href="{link}">Подробнее о спектакле</a>'
    return full_name


async def get_time_with_timezone(event, tz_name='Europe/Moscow'):
    if tz_name == 'Europe/Moscow':
        dt_local = to_moscow_dt(event.datetime_event)
    else:
        dt = event.datetime_event
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_local = dt.astimezone(ZoneInfo(tz_name))
    return dt_local.strftime('%H:%M')


async def get_formatted_date_and_time_of_event(
        schedule_event: ScheduleEvent) -> Tuple[str, str]:
    event = schedule_event
    weekday = int(event.datetime_event.strftime('%w'))
    date_event = (f'{event.datetime_event.strftime('%d.%m ')}'
                  f'({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]})')
    time_event = await get_time_with_timezone(event)
    return date_event, time_event

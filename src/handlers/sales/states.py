import decimal
import re
from datetime import date
from typing import Dict, List

# ─── Constants ────────────────────────────────────────────────────────────────

PAGE_SIZE = 8
SALES_PAGE_SIZE = 30

import pytz
TZ = pytz.timezone('Europe/Moscow')

MAX_MEDIA_COUNT = 10

# ─── Conversation states ──────────────────────────────────────────────────────

MENU = 'MENU'
PICK_EXISTING_CAMPAIGN = 'PICK_EXISTING_CAMPAIGN'
CAMPAIGN_ACTION_MENU = 'CAMPAIGN_ACTION_MENU'
PICK_TYPE = 'PICK_TYPE'
PICK_THEATER = 'PICK_THEATER'
PICK_SCOPE = 'PICK_SCOPE'
PICK_SCHEDULES = 'PICK_SCHEDULES'
PICK_AUDIENCE_THEATER = 'PICK_AUDIENCE_THEATER'
BUILD_AUDIENCE = 'BUILD_AUDIENCE'
GET_MESSAGE = 'GET_MESSAGE'
PREVIEW = 'PREVIEW'
GET_MEDIA = 'GET_MEDIA'
LENGTH_FIX = 'LENGTH_FIX'
PICK_ATTACH_THEATER = 'PICK_ATTACH_THEATER'
PICK_FILTERS = 'PICK_FILTERS'
PICK_FILTER_STATUS = 'PICK_FILTER_STATUS'
PICK_FILTER_TYPE_EVENT = 'PICK_FILTER_TYPE_EVENT'
PICK_FILTER_THEATER_EVENT = 'PICK_FILTER_THEATER_EVENT'
PICK_FILTER_SCHEDULE_EVENT = 'PICK_FILTER_SCHEDULE_EVENT'
PICK_FILTER_BASE_TICKET = 'PICK_FILTER_BASE_TICKET'
PICK_TICKET_IDS = 'PICK_TICKET_IDS'
PICK_FILTER_CHILD_AGE_MIN = 'PICK_FILTER_CHILD_AGE_MIN'
PICK_FILTER_CHILD_AGE_MAX = 'PICK_FILTER_CHILD_AGE_MAX'
PICK_SEASON_START = 'PICK_SEASON_START'
PICK_SEASON_END = 'PICK_SEASON_END'
PICK_SEASON_THEATERS = 'PICK_SEASON_THEATERS'
PICK_SEASON_AGE_MIN = 'PICK_SEASON_AGE_MIN'
PICK_SEASON_AGE_MAX = 'PICK_SEASON_AGE_MAX'
PICK_SEASON_STATUSES = 'PICK_SEASON_STATUSES'

# ─── Sales types registry ─────────────────────────────────────────────────────

SALES_TYPES: Dict[str, Dict] = {
    "WAS_THIS_YEAR_ON_PLAY": {
        "title": ("Рассылка о свободных местах на выбранный спектакль."
                  " По людям, которые посещали спектакль/спектакли"),
        "enabled": True,
        "start_state": PICK_THEATER,
    },
    "TICKET_HOLDERS": {
        "title": "Рассылка по обладателям билетов (с фильтрами)",
        "enabled": True,
        "start_state": PICK_FILTERS,
    },
    "SEASON_TICKET_HOLDERS": {
        "title": "Рассылка посетителям сезона (билеты за период)",
        "enabled": True,
        "start_state": PICK_SEASON_START,
    },
}


# ─── Helper functions ─────────────────────────────────────────────────────────

def _get_usage_text_for_type(type_code: str) -> str:
    """Return a short contextual instruction shown right after type selection."""
    if type_code == "WAS_THIS_YEAR_ON_PLAY":
        return (
            '<b>Как пользоваться этим типом рассылки:</b>\n'
            '1) Выберите спектакль.\n'
            '2) Выберите охват сеансов: все доступные или вручную по датам.\n'
            '3) Выберите спектакль(и), по которым отберём аудиторию — тех, кто уже был в этом году.\n'
            '4) При необходимости выберите сеансы вручную.\n'
            '5) Проверьте сводку аудитории.\n'
            '6) Пришлите медиа (необязательно).\n'
            '7) Отправьте текст сообщения.'
        )
    if type_code == "TICKET_HOLDERS":
        return (
            '<b>Как пользоваться этим типом рассылки:</b>\n'
            '1) Задайте фильтры для отбора аудитории (статус билетов, спектакли, типы, сеансы, возраст детей или конкретные билеты).\n'
            '2) При необходимости прикрепите спектакль со свободными местами.\n'
            '3) Проверьте сводку аудитории.\n'
            '4) Пришлите медиа (необязательно).\n'
            '5) Отправьте текст сообщения.'
        )
    if type_code == "SEASON_TICKET_HOLDERS":
        return (
            '<b>Как пользоваться этим типом рассылки:</b>\n'
            '1) Введите дату начала периода прошедших сеансов (формат ДД.ММ.ГГГГ) или пропустите.\n'
            '2) Введите дату конца периода (формат ДД.ММ.ГГГГ) или пропустите.\n'
            '3) При необходимости выберите конкретные спектакли (только активные).\n'
            '4) При необходимости задайте минимальный возраст ребёнка в билете кнопками.\n'
            '5) При необходимости задайте максимальный возраст ребёнка в билете кнопками.\n'
            '6) При необходимости выберите статусы билетов.\n'
            '7) При необходимости прикрепите спектакль со свободными местами.\n'
            '8) Проверьте сводку аудитории.\n'
            '9) Пришлите медиа (необязательно).\n'
            '10) Отправьте текст сообщения.'
        )
    return (
        '<b>Как пользоваться:</b>\n'
        '1) Следуйте шагам мастера: выберите объект, задайте охват, подготовьте сообщение.\n'
        '2) Проверьте предпросмотр и запустите рассылку.'
    )


def _get_step_info(type_code: str, step_name: str) -> tuple:
    """Return (current_step, total_steps) for a given type and step name."""
    if type_code == 'TICKET_HOLDERS':
        _map = {
            'filters': (1, 5),
            'attach_theater': (2, 5),
            'theater': (2, 5),
            'scope': (2, 5),
            'schedules': (2, 5),
            'build_audience': (3, 5),
            'media': (4, 5),
            'text': (5, 5),
        }
    elif type_code == 'WAS_THIS_YEAR_ON_PLAY':
        _map = {
            'theater': (1, 7),
            'scope': (2, 7),
            'audience_theater': (3, 7),
            'schedules': (4, 7),
            'build_audience': (5, 7),
            'media': (6, 7),
            'text': (7, 7),
        }
    elif type_code == 'SEASON_TICKET_HOLDERS':
        _map = {
            'season_start': (1, 10),
            'season_end': (2, 10),
            'season_theaters': (3, 10),
            'season_age_min': (4, 10),
            'season_age_max': (5, 10),
            'season_statuses': (6, 10),
            'attach_theater': (7, 10),
            'theater': (7, 10),
            'scope': (7, 10),
            'schedules': (7, 10),
            'build_audience': (8, 10),
            'media': (9, 10),
            'text': (10, 10),
        }
    else:
        _map = {step_name: (1, 1) for step_name in ['filters', 'attach_theater', 'build_audience', 'media', 'text']}
    return _map.get(step_name, (1, 1))


def _get_usage_text_with_highlight(type_code: str, current_step: int) -> str:
    """Return usage text with the current step highlighted in bold."""
    if type_code == "TICKET_HOLDERS":
        steps = [
            'Задайте фильтры для отбора аудитории (статус билетов, спектакли, типы, сеансы, возраст детей или конкретные билеты).',
            'При необходимости прикрепите спектакль со свободными местами.',
            'Проверьте сводку аудитории.',
            'Пришлите медиа (необязательно).',
            'Отправьте текст сообщения.',
        ]
    elif type_code == "WAS_THIS_YEAR_ON_PLAY":
        steps = [
            'Выберите спектакль.',
            'Выберите охват сеансов: все доступные или вручную по датам.',
            'Выберите спектакль(и), по которым отберём аудиторию — тех, кто уже был в этом году.',
            'При необходимости выберите сеансы вручную.',
            'Проверьте сводку аудитории.',
            'Пришлите медиа (необязательно).',
            'Отправьте текст сообщения.',
        ]
    elif type_code == "SEASON_TICKET_HOLDERS":
        steps = [
            'Введите дату начала периода прошедших сеансов (формат ДД.ММ.ГГГГ) или пропустите.',
            'Введите дату конца периода (формат ДД.ММ.ГГГГ) или пропустите.',
            'При необходимости выберите конкретные спектакли (только активные).',
            'При необходимости задайте минимальный возраст ребёнка в билете кнопками.',
            'При необходимости задайте максимальный возраст ребёнка в билете кнопками.',
            'При необходимости выберите статусы билетов.',
            'При необходимости прикрепите спектакль со свободными местами.',
            'Проверьте сводку аудитории.',
            'Пришлите медиа (необязательно).',
            'Отправьте текст сообщения.',
        ]
    else:
        return _get_usage_text_for_type(type_code)

    lines: List[str] = ['<b>Как пользоваться этим типом рассылки:</b>']
    for i, step_text in enumerate(steps, start=1):
        if i == current_step:
            lines.append(f'<b>{i}) {step_text}</b>')
        else:
            lines.append(f'{i}) {step_text}')

    return '\n'.join(lines)


def _status_label(status: str) -> str:
    """Return a short emoji label for campaign status."""
    return {'draft': '📝', 'running': '🔄', 'done': '✅'}.get(status, status)


def _parse_date(text: str) -> 'date | None':
    """Parse DD.MM.YYYY date string, return None on failure."""
    m = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})$', text.strip())
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _compress_ids(ids: List[int], max_chars: int = 200) -> str:
    """Convert sorted list of ints to range notation, e.g. [1,2,3,5,7,8] → '1–3, 5, 7–8'."""
    if not ids:
        return ''
    ranges = []
    start = prev = ids[0]
    for n in ids[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append(f"{start}–{prev}" if prev != start else str(start))
            start = prev = n
    ranges.append(f"{start}–{prev}" if prev != start else str(start))
    result = ', '.join(ranges)
    if len(result) > max_chars:
        result = result[:max_chars].rsplit(',', 1)[0] + ', …'
    return result


def _format_label(dt_utc, selected: bool) -> str:
    from settings.settings import DICT_CONVERT_WEEKDAY_NUMBER_TO_STR
    dt_local = dt_utc.astimezone(TZ)
    weekday = int(dt_local.strftime('%w'))
    date_txt = dt_local.strftime('%d.%m ')
    time_txt = dt_local.strftime('%H:%M')
    pref = '✅' if selected else '▫️'
    return f"{pref} {date_txt}({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]}) {time_txt}"


def _serialize_entities(entities):
    try:
        return [e.to_dict() for e in (entities or [])]
    except Exception:
        return None


def _extract_media_info(msg) -> 'dict | None':
    """Extract media type and file_id from a message."""
    if msg.photo:
        return {'type': 'photo', 'file_id': msg.photo[-1].file_id}
    elif msg.video:
        return {'type': 'video', 'file_id': msg.video.file_id}
    elif msg.animation:
        return {'type': 'animation', 'file_id': msg.animation.file_id}
    return None


def _round_half_to_even(value: float) -> int:
    """Round float to nearest even integer on tie (banker's rounding)."""
    d = decimal.Decimal(str(value))
    return int(d.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_EVEN))

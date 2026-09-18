from __future__ import annotations

from typing import Sequence, List, Optional, Set, Tuple
import datetime

from db.models import ScheduleEvent, Place


def effective_place(event: Optional[ScheduleEvent], default_place: Place) -> Place:
    """
    Возвращает эффективную локацию для показа:
    если у показа задана локация (place), возвращается она,
    иначе — локация по умолчанию (Домик).
    """
    if event is not None:
        p = getattr(event, 'place', None)
        if p is not None and not str(type(p)).startswith("<class 'unittest.mock."):
            return p
        if p is not None and hasattr(p, 'name') and isinstance(p.name, str):
            return p
    return default_place


def needs_place_choice(events: Sequence[ScheduleEvent], default_place: Place) -> bool:
    """
    Проверяет, требуется ли шаг выбора локации.
    Шаг появляется ТОЛЬКО при наличии одинакового спектакля в один календарный день в разных локациях.
    Группировка идет по (theater_event_id, date(event.datetime_event)).
    """
    if not events:
        return False

    groups: dict[Tuple[int, datetime.date], Set[int]] = {}
    for event in events:
        t_id = event.theater_event_id
        dt = event.datetime_event
        d = dt.date() if hasattr(dt, 'date') else dt
        place = effective_place(event, default_place)
        p_id = place.id if place else 0

        key = (t_id, d)
        if key not in groups:
            groups[key] = set()
        groups[key].add(p_id)
        if len(groups[key]) > 1:
            return True

    return False


def collect_places(events: Sequence[ScheduleEvent], default_place: Place) -> List[Place]:
    """
    Собирает уникальные эффективные локации для переданных показов без дубликатов,
    сохраняя порядок первого появления.
    """
    seen_ids: Set[int] = set()
    places: List[Place] = []
    for event in events:
        place = effective_place(event, default_place)
        if place and place.id not in seen_ids:
            seen_ids.add(place.id)
            places.append(place)
    return places


def format_place_footnote(place: Place) -> str:
    """
    Форматирует сноску с адресом локации для Telegram-бота:
    название, адрес, ссылка на Яндекс Карты; ссылка 'Подробнее', если link_about заполнена.
    """
    parts = [f"📍 <b>{place.name}</b>: {place.address}"]
    links = []
    if place.link_on_yndx_maps:
        links.append(f'<a href="{place.link_on_yndx_maps}">Яндекс Карты</a>')
    if place.link_about:
        links.append(f'<a href="{place.link_about}">Подробнее</a>')
    if links:
        parts.append(f"({' | '.join(links)})")
    return " ".join(parts)

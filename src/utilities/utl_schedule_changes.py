import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from db.enum import TicketPriceType
from db.models import ScheduleEvent, BaseTicket
from utilities.utl_func import to_moscow_dt, MOSCOW_TZ

TRACKED_SCHEDULE_FIELDS = [
    'type_event_id',
    'theater_event_id',
    'place_id',
    'flag_turn_in_bot',
    'datetime_event',
    'qty_child',
    'qty_adult',
    'flag_gift',
    'flag_christmas_tree',
    'flag_santa',
    'ticket_price_type',
    'base_ticket_ids',
]

# Поля, которые разрешены для выгрузки в Google Таблицу (без base_ticket_ids и без расчетных остатков мест)
EXPORTABLE_SCHEDULE_FIELDS = [
    'type_event_id',
    'theater_event_id',
    'place_id',
    'flag_turn_in_bot',
    'datetime_event',
    'qty_child',
    'qty_adult',
    'flag_gift',
    'flag_christmas_tree',
    'flag_santa',
    'ticket_price_type',
]


def normalize_datetime_str(dt_val: Union[datetime.datetime, str, None]) -> Optional[str]:
    if dt_val is None:
        return None
    if isinstance(dt_val, str):
        # Если уже строка, пробуем распарсить или оставить как есть
        try:
            parsed = datetime.datetime.fromisoformat(dt_val)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=MOSCOW_TZ)
            return to_moscow_dt(parsed).isoformat()
        except ValueError:
            return dt_val
    if isinstance(dt_val, datetime.datetime):
        return to_moscow_dt(dt_val).isoformat()
    return str(dt_val)


def normalize_ticket_price_type(val: Any) -> str:
    if val is None:
        return TicketPriceType.NONE.value
    if isinstance(val, TicketPriceType):
        return val.value
    if hasattr(val, 'value'):
        return str(val.value)
    return str(val)


def normalize_base_ticket_ids(val: Any) -> List[int]:
    if not val:
        return []
    ids: Set[int] = set()
    for item in val:
        if isinstance(item, BaseTicket):
            ids.add(int(item.base_ticket_id))
        elif isinstance(item, dict) and 'base_ticket_id' in item:
            ids.add(int(item['base_ticket_id']))
        else:
            try:
                ids.add(int(item))
            except (ValueError, TypeError):
                continue
    return sorted(list(ids))


def normalize_schedule_snapshot(
        event: Union[ScheduleEvent, Dict[str, Any]],
        base_ticket_ids: Optional[List[int]] = None
) -> Dict[str, Any]:
    """
    Приводит данные сеанса (ORM-объект или словарь) к нормализованному плоскому словарю.
    """
    if isinstance(event, ScheduleEvent):
        bt_ids = base_ticket_ids
        if bt_ids is None and hasattr(event, 'base_tickets') and event.base_tickets is not None:
            bt_ids = [bt.base_ticket_id for bt in event.base_tickets]

        snapshot = {
            'id': event.id,
            'type_event_id': int(event.type_event_id),
            'theater_event_id': int(event.theater_event_id),
            'place_id': int(event.place_id) if event.place_id is not None else None,
            'flag_turn_in_bot': bool(event.flag_turn_in_bot),
            'datetime_event': normalize_datetime_str(event.datetime_event),
            'qty_child': int(event.qty_child),
            'qty_adult': int(event.qty_adult),
            'flag_gift': bool(event.flag_gift),
            'flag_christmas_tree': bool(event.flag_christmas_tree),
            'flag_santa': bool(event.flag_santa),
            'ticket_price_type': normalize_ticket_price_type(event.ticket_price_type),
            'base_ticket_ids': normalize_base_ticket_ids(bt_ids),
        }
    elif isinstance(event, dict):
        bt_ids = base_ticket_ids if base_ticket_ids is not None else event.get('base_ticket_ids')
        snapshot = {
            'id': event.get('id'),
            'type_event_id': int(event['type_event_id']),
            'theater_event_id': int(event['theater_event_id']),
            'place_id': int(event['place_id']) if event.get('place_id') is not None else None,
            'flag_turn_in_bot': bool(event.get('flag_turn_in_bot', False)),
            'datetime_event': normalize_datetime_str(event.get('datetime_event')),
            'qty_child': int(event.get('qty_child', 0)),
            'qty_adult': int(event.get('qty_adult', 0)),
            'flag_gift': bool(event.get('flag_gift', False)),
            'flag_christmas_tree': bool(event.get('flag_christmas_tree', False)),
            'flag_santa': bool(event.get('flag_santa', False)),
            'ticket_price_type': normalize_ticket_price_type(event.get('ticket_price_type')),
            'base_ticket_ids': normalize_base_ticket_ids(bt_ids),
        }
    else:
        raise ValueError(f"Unsupported event type for snapshot: {type(event)}")

    return snapshot


def compute_schedule_diff(
        before: Optional[Dict[str, Any]],
        after: Dict[str, Any]
) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    """
    Вычисляет список изменившихся полей и детальный diff {field: {'before': ..., 'after': ...}}.
    Если before is None (создание), все поля считаются новыми.
    """
    if before is None:
        changed_fields = [f for f in TRACKED_SCHEDULE_FIELDS if f in after]
        diff = {
            f: {'before': None, 'after': after.get(f)}
            for f in changed_fields
        }
        return changed_fields, diff

    changed_fields = []
    diff = {}
    for field in TRACKED_SCHEDULE_FIELDS:
        val_before = before.get(field)
        val_after = after.get(field)
        if val_before != val_after:
            changed_fields.append(field)
            diff[field] = {
                'before': val_before,
                'after': val_after
            }

    return changed_fields, diff

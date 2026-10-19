"""Callback data parsers for command management UI.

Parses the intent-prefixed callback data used by the access management screens:
    tg|<group>|<idx>   — toggle item #idx of grantable_items(actor)
    pg|<group>|<page>  — group screen with pagination
    pick|<user_id>     — select user from the list
    usr|<page>         — page of users that already have access
"""
import re
from typing import Optional

from permissions import AccessItem


def _intent_cb(payload: str) -> str:
    """Build an intent-prefixed callback payload."""
    from settings.settings import ACCESS_INTENT_ID
    return f'{ACCESS_INTENT_ID}|{payload}'


def _parse_target_input(message) -> tuple[int | None, str | None]:
    """Parse user input: forwarded message or text user_id.

    Returns (target_id, None) on success or (None, error_message) on failure.
    """
    origin = getattr(message, 'forward_origin', None)
    if origin is not None:
        sender = getattr(origin, 'sender_user', None)
        if sender is None:
            return None, 'Не удалось определить пользователя, введите user_id'
        return sender.id, None
    else:
        text = (message.text or '').strip()
        if not re.fullmatch(r'\d{1,18}', text, flags=re.ASCII):
            return None, 'Введите числовой user_id или перешлите сообщение пользователя'
        return int(text), None


def _parse_toggle(data: str, items: list[AccessItem]) -> Optional[AccessItem]:
    """Parse a toggle callback data 'tg|<group>|<idx>' and return the AccessItem.

    Returns None if the data is malformed, out of range, or group mismatch.
    """
    parts = data.split('|')
    if len(parts) != 3 or parts[0] != 'tg':
        return None
    group, idx_str = parts[1], parts[2]
    try:
        idx = int(idx_str)
    except ValueError:
        return None
    if not 0 <= idx < len(items) or items[idx].group != group:
        return None
    return items[idx]

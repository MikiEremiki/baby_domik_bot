"""Sales broadcast message building, length analysis, and sending.

Shared by the preview step (sales_hl.py) and the NATS worker (sales_worker.py)
so that both paths produce identical messages.

Structure (3 logical blocks, ~280 lines):
  - Extra block: build_extra() — appends theater info to a message body.
  - Length helpers: visible_len(), char_breakdown(), analyze_length() —
    check Telegram caption/text limits and report overflows.
  - Sending: send_campaign_message() — dispatches media + text via the Bot API.

If this module grows beyond ~400 lines (e.g., when ticket 04 adds media
collection and preview logic), consider splitting into utl_sales_extra.py,
utl_sales_length.py, and utl_sales_send.py.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sulguk import transform_html
from telegram import InputMediaPhoto, InputMediaVideo, InputMediaAnimation

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096


# ─── Extra block ──────────────────────────────────────────────────────────────

def build_extra(
    full_name: str,
    availability_block: str,
    reserve_text: str,
) -> str:
    """Build the theater block appended to the campaign message.

    Returns an empty string when none of the parts is set.
    """
    parts: List[str] = []
    if full_name:
        parts.append(full_name)
    if availability_block:
        parts.append(availability_block)
    if reserve_text:
        parts.append(reserve_text)
    if not parts:
        return ''
    return '\n\n' + '\n\n'.join(parts)


# ─── Length helpers ───────────────────────────────────────────────────────────

def visible_len(text: str) -> int:
    """Return the number of UTF-16 code units Telegram counts for *text*.

    Telegram counts BMP characters as 1 and supplementary-plane characters
    (most emoji) as 2.
    """
    count = 0
    for ch in text:
        cp = ord(ch)
        if cp > 0xFFFF:
            count += 2
        else:
            count += 1
    return count


def _char_category(ch: str) -> str:
    cat = unicodedata.category(ch)
    if cat.startswith('L'):
        return 'letters'
    if cat.startswith('M'):
        return 'letters'
    if cat.startswith('N'):
        return 'digits'
    if cat.startswith('Z') or ch == '\n':
        return 'spaces'
    if cat.startswith('P') or cat.startswith('S'):
        return 'punctuation'
    if cat == 'Co' or cat == 'Cn':
        return 'other'
    # Private use, surrogate, etc.
    if cat.startswith('C'):
        return 'other'
    return 'emoji'


def char_breakdown(text: str) -> Dict[str, int]:
    """Count characters by category for a length report."""
    counts: Dict[str, int] = {
        'letters': 0,
        'spaces': 0,
        'newlines': 0,
        'punctuation': 0,
        'digits': 0,
        'emoji': 0,
        'other': 0,
    }
    for ch in text:
        if ch == '\n':
            counts['newlines'] += 1
        else:
            cat = _char_category(ch)
            if cat in counts:
                counts[cat] += 1
            else:
                counts['other'] += 1
    return counts


@dataclass
class LengthReport:
    limit: int
    total: int
    excess: int
    breakdown: Dict[str, int]


def analyze_length(
    plain_text: str,
    extra: str,
    has_media: bool,
    text_mode: str,
) -> Optional[LengthReport]:
    """Check whether the combined message fits Telegram limits.

    Returns ``None`` when the message is within limits, otherwise a
    :class:`LengthReport` describing the overflow.
    """
    if has_media and text_mode == 'caption':
        # Caption is limited to 1024 UTF-16 code units
        combined = plain_text + extra
        limit = CAPTION_LIMIT
    else:
        # Separate text message or no media — full 4096 limit
        combined = plain_text + extra
        limit = TEXT_LIMIT

    total = visible_len(combined)
    if total <= limit:
        return None

    return LengthReport(
        limit=limit,
        total=total,
        excess=total - limit,
        breakdown=char_breakdown(combined),
    )


def format_length_report(report: LengthReport) -> str:
    """Render a human-readable length overflow report."""
    lines = [
        f'⚠️ Текст превышает лимит на {report.excess} символов.',
        f'Лимит: {report.limit}, текущая длина: {report.total}.',
        '',
        'Разбор символов:',
    ]
    labels = {
        'letters': 'Буквы',
        'spaces': 'Пробелы',
        'newlines': 'Переносы',
        'punctuation': 'Знаки препинания',
        'digits': 'Цифры',
        'emoji': 'Эмодзи',
        'other': 'Другие',
    }
    for key, label in labels.items():
        cnt = report.breakdown.get(key, 0)
        if cnt:
            lines.append(f'  • {label}: {cnt}')
    return '\n'.join(lines)


# ─── Sending ──────────────────────────────────────────────────────────────────

_MEDIA_TYPE_MAP = {
    'photo': InputMediaPhoto,
    'video': InputMediaVideo,
    'animation': InputMediaAnimation,
}

_BOT_SEND_METHOD = {
    'photo': 'send_photo',
    'video': 'send_video',
    'animation': 'send_animation',
}


async def send_campaign_message(
    bot: Any,
    chat_id: int,
    *,
    media: List[Dict[str, str]],
    text: str,
    extra: str,
    text_mode: str = 'caption',
    reply_markup=None,
    message_thread_id: Optional[int] = None,
) -> List[Any]:
    """Send a campaign message using the unified media + text contract.

    Args:
        bot: Telegram Bot instance.
        chat_id: Target chat ID.
        media: List of media dicts, e.g. ``[{"type": "photo", "file_id": "..."}]``.
        text: HTML body of the message.
        extra: Theater block (may be empty).
        text_mode: ``'caption'`` (append to media caption) or
            ``'separate'`` (send as a follow-up text message).
        reply_markup: Optional keyboard (attached to the last message).
        message_thread_id: Optional topic thread ID.

    Returns:
        List of sent :class:`telegram.Message` objects.
    """
    sent: List[Any] = []
    common_kwargs: Dict[str, Any] = {
        'chat_id': chat_id,
    }
    if message_thread_id is not None:
        common_kwargs['message_thread_id'] = message_thread_id

    # Transform HTML to Telegram entities using sulguk
    full_text = text + extra
    res_text = transform_html(full_text)

    if not media:
        # Plain text message
        msg = await bot.send_message(
            text=res_text.text,
            entities=res_text.entities,
            reply_markup=reply_markup,
            parse_mode=None,
            **common_kwargs,
        )
        sent.append(msg)
        return sent

    if len(media) == 1:
        item = media[0]
        mtype = item['type']
        file_id = item['file_id']
        send_fn = getattr(bot, _BOT_SEND_METHOD[mtype])

        if text_mode == 'caption':
            msg = await send_fn(
                **{mtype if mtype != 'animation' else 'animation': file_id},
                caption=res_text.text,
                entities=res_text.entities,
                reply_markup=reply_markup,
                parse_mode=None,
                **common_kwargs,
            )
        else:
            # Separate: media first, then text
            msg = await send_fn(
                **{mtype if mtype != 'animation' else 'animation': file_id},
                **common_kwargs,
            )
            sent.append(msg)
            msg = await bot.send_message(
                text=res_text.text,
                entities=res_text.entities,
                reply_markup=reply_markup,
                parse_mode=None,
                **common_kwargs,
            )
        sent.append(msg)
        return sent

    # Multiple media — send_media_group
    # Note: Telegram API doesn't support reply_markup for media groups,
    # so we send media without caption and text as a separate message with the keyboard.
    input_media = []
    for item in media:
        mtype = item['type']
        InputMediaCls = _MEDIA_TYPE_MAP[mtype]
        im = InputMediaCls(media=item['file_id'])
        input_media.append(im)

    album = await bot.send_media_group(
        media=input_media,
        **common_kwargs,
    )
    sent.extend(album)

    # Text message with reply_markup attached (keyboard won't work on media group)
    msg = await bot.send_message(
        text=res_text.text,
        entities=res_text.entities,
        reply_markup=reply_markup,
        parse_mode=None,
        **common_kwargs,
    )
    sent.append(msg)

    return sent

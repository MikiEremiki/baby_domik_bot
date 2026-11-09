"""Telegram Bot API helpers: safe message editing."""

import logging
from typing import Union

from telegram import CallbackQuery, Message
from telegram.error import BadRequest


def is_not_modified(error: BadRequest) -> bool:
    """Return True if the error means the message content did not change."""
    return "Message is not modified" in str(error)


async def safe_edit_text(
    query_or_msg: Union[CallbackQuery, Message],
    text: str | None = None,
    reply_markup=None,
    logger: logging.Logger | None = None,
    **kwargs,
) -> None:
    """Edit message text, silently ignoring 'Message is not modified'.

    Args:
        query_or_msg: A CallbackQuery (with .edit_message_text) or a Message
            (with .edit_text).
        text: New message text.
        reply_markup: New reply markup.
        logger: Optional logger for info-level note when edit is skipped.
        **kwargs: Additional arguments forwarded to edit_message_text/edit_text.
    """
    try:
        if hasattr(query_or_msg, "edit_message_text"):
            # CallbackQuery path
            await query_or_msg.edit_message_text(
                text=text, reply_markup=reply_markup, **kwargs
            )
        else:
            # Message path
            await query_or_msg.edit_text(
                text=text, reply_markup=reply_markup, **kwargs
            )
    except BadRequest as e:
        if is_not_modified(e):
            if logger:
                logger.info("Игнорируем редактирование без изменений")
        else:
            raise


async def safe_edit_markup(
    query_or_msg: CallbackQuery,
    reply_markup=None,
    logger: logging.Logger | None = None,
    **kwargs,
) -> None:
    """Edit message reply markup, silently ignoring 'Message is not modified'.

    Args:
        query_or_msg: A CallbackQuery (with .edit_message_reply_markup).
        reply_markup: New reply markup (may be None to remove keyboard).
        logger: Optional logger for info-level note when edit is skipped.
        **kwargs: Additional arguments forwarded to edit_message_reply_markup.
    """
    try:
        await query_or_msg.edit_message_reply_markup(
            reply_markup=reply_markup, **kwargs
        )
    except BadRequest as e:
        if is_not_modified(e):
            if logger:
                logger.info("Игнорируем редактирование клавиатуры без изменений")
        else:
            raise


async def safe_edit_caption(
    query_or_msg: CallbackQuery,
    caption: str | None = None,
    reply_markup=None,
    logger: logging.Logger | None = None,
    **kwargs,
) -> None:
    """Edit message caption (for media messages), silently ignoring 'Message is not modified'.

    Args:
        query_or_msg: A CallbackQuery (with .edit_message_caption).
        caption: New caption text.
        reply_markup: New reply markup.
        logger: Optional logger for info-level note when edit is skipped.
        **kwargs: Additional arguments forwarded to edit_message_caption.
    """
    try:
        await query_or_msg.edit_message_caption(
            caption=caption, reply_markup=reply_markup, **kwargs
        )
    except BadRequest as e:
        if is_not_modified(e):
            if logger:
                logger.info("Игнорируем редактирование подписи без изменений")
        else:
            raise

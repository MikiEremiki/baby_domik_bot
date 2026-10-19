"""Receipt handler — /receipt command and callback for admin receipt lookup."""

import logging
import re
from datetime import timezone, timedelta
from typing import Optional

from sulguk import transform_html
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.error import Forbidden, TimedOut
from telegram.ext import ContextTypes

from api.receipt_service import ReceiptInfo, ReceiptStatus, get_ticket_receipt
from utilities.utl_func import is_privileged_update

logger = logging.getLogger('bot.receipt')


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

STATUS_EMOJI = {
    ReceiptStatus.READY: '✅',
    ReceiptStatus.PENDING: '⏳',
    ReceiptStatus.CANCELED: '❌',
    ReceiptStatus.NO_PAYMENT: '💳',
    ReceiptStatus.NOT_FOUND: '🔍',
    ReceiptStatus.API_ERROR: '⚠️',
}

STATUS_TEXT = {
    ReceiptStatus.READY: 'Чек готов',
    ReceiptStatus.PENDING: 'Чек формируется',
    ReceiptStatus.CANCELED: 'Чек отменён',
    ReceiptStatus.NO_PAYMENT: 'Оплата не найдена',
    ReceiptStatus.NOT_FOUND: 'Билет не найден',
    ReceiptStatus.API_ERROR: 'Ошибка получения чека',
}


def format_receipt_card(info: ReceiptInfo) -> str:
    """Format receipt info as an HTML card for Telegram.

    Uses <br> for line breaks. Fiscal data (ФН/ФД/ФП) is wrapped in <code>
    when available.
    """
    emoji = STATUS_EMOJI.get(info.status, '❓')
    status_text = STATUS_TEXT.get(info.status, 'Неизвестно')

    text = f'{emoji} <b>{status_text}</b><br>'
    text += f'Билет: <code>{info.ticket_id}</code><br>'

    if info.price is not None:
        text += f'Сумма: {info.price} ₽<br>'

    if info.ticket_status:
        text += f'Статус билета: {info.ticket_status}<br>'

    if info.status == ReceiptStatus.READY and info.registered_at:
        # Format as Moscow time (UTC+3)
        msk = timezone(timedelta(hours=3))
        msk_time = info.registered_at.astimezone(msk)
        text += f'Дата регистрации: {msk_time.strftime("%d.%m.%Y %H:%M")} (МСК)<br>'

    if info.fn:
        text += f'<code>ФН: {info.fn}</code><br>'
    if info.fd:
        text += f'<code>ФД: {info.fd}</code><br>'
    if info.fp:
        text += f'<code>ФП: {info.fp}</code><br>'

    return text


def build_receipt_card_keyboard(
    info: ReceiptInfo,
    sent_to_client: bool = False,
) -> Optional[InlineKeyboardMarkup]:
    """Build inline keyboard for a receipt card.

    Includes a URL button to the OFD when the receipt is ready.
    If client_chat_id is present and the receipt hasn't been sent yet,
    adds a "📤 Отправить клиенту" button.
    """
    if info.status != ReceiptStatus.READY or not info.ofd_url:
        return None

    row: list[InlineKeyboardButton] = [
        InlineKeyboardButton(
            '🌐 Открыть чек ОФД',
            url=info.ofd_url,
        )
    ]

    if info.client_chat_id is not None and not sent_to_client:
        row.append(
            InlineKeyboardButton(
                '📤 Отправить клиенту',
                callback_data=f'receipt_send|{info.ticket_id}',
            )
        )

    return InlineKeyboardMarkup([row])


def build_receipt_card_keyboard_sent(info: ReceiptInfo) -> Optional[InlineKeyboardMarkup]:
    """Build inline keyboard after receipt has been sent to client.

    Shows only the OFD URL button — the send button is replaced by
    "✅ Отправлено клиенту".
    """
    if info.status != ReceiptStatus.READY or not info.ofd_url:
        return None

    keyboard = [
        [
            InlineKeyboardButton(
                '🌐 Открыть чек ОФД',
                url=info.ofd_url,
            )
        ],
        [
            InlineKeyboardButton(
                '✅ Отправлено клиенту',
                callback_data='receipt_sent|noop',
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_receipt_button_row(ticket_id: int) -> InlineKeyboardMarkup:
    """Build a single-row keyboard with a receipt callback button."""
    keyboard = [
        [
            InlineKeyboardButton(
                '🧾 Чек',
                callback_data=f'receipt|{ticket_id}',
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------

async def receipt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /receipt <ticket_id> command.

    Admin-only. Shows receipt card or help text if no argument provided.
    """
    reply_to_msg_id = update.effective_message.message_id

    if not context.args:
        text = 'Справка по команде<br>'
        text += '<code>/receipt &lt;номер билета&gt;</code><br><br>'
        text += 'Показать фискальный чек по номеру билета.'
        res_text = transform_html(text)
        await update.effective_message.reply_text(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_to_message_id=reply_to_msg_id,
        )
        return

    # Parse ticket ID
    try:
        ticket_id = int(context.args[0])
    except ValueError:
        text = f'Неверный номер билета: {context.args[0]}<br>'
        text += 'Используйте <code>/receipt &lt;номер&gt;</code>'
        res_text = transform_html(text)
        await update.effective_message.reply_text(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_to_message_id=reply_to_msg_id,
        )
        return

    # Fetch receipt info
    info = await get_ticket_receipt(context.session, ticket_id)

    # Format and send
    card_text = format_receipt_card(info)
    res_text = transform_html(card_text)
    keyboard = build_receipt_card_keyboard(info)

    await update.effective_message.reply_text(
        text=res_text.text,
        entities=res_text.entities,
        parse_mode=None,
        reply_to_message_id=reply_to_msg_id,
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# Callback handler
# ---------------------------------------------------------------------------

RECEIPT_CALLBACK_PATTERN = re.compile(r'^receipt\|(\d+)$')
RECEIPT_SEND_CALLBACK_PATTERN = re.compile(r'^receipt_send\|(\d+)$')


async def receipt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback from "🧾 Чек" button.

    Admin-only. Sends receipt card as a new message in the same thread.
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut:
        pass

    if not is_privileged_update(update):
        logger.warning('Non-admin callback receipt: %s', update.effective_user.id)
        return

    # Parse ticket ID from callback data
    match = RECEIPT_CALLBACK_PATTERN.match(query.data)
    if not match:
        return
    ticket_id = int(match.group(1))

    message_thread_id = update.effective_message.message_thread_id

    # Fetch receipt info
    info = await get_ticket_receipt(context.session, ticket_id)

    # Format and send as new message in the same thread
    card_text = format_receipt_card(info)
    res_text = transform_html(card_text)
    keyboard = build_receipt_card_keyboard(info)

    try:
        await update.effective_chat.send_message(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_to_message_id=query.message.message_id,
            message_thread_id=message_thread_id,
            reply_markup=keyboard,
        )
    except TimedOut:
        await update.effective_chat.send_message(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_to_message_id=query.message.message_id,
            reply_markup=keyboard,
        )


# ---------------------------------------------------------------------------
# Send-to-client callback handler
# ---------------------------------------------------------------------------

async def receipt_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback from "📤 Отправить клиенту" button.

    Admin-only. Sends the OFD link to the client and replaces the button
    with "✅ Отправлено клиенту".
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut:
        pass

    if not is_privileged_update(update):
        logger.warning('Non-admin callback receipt_send: %s', update.effective_user.id)
        try:
            await query.answer('Только для администраторов', show_alert=True)
        except TimedOut:
            pass
        return

    # Parse ticket ID from callback data
    match = RECEIPT_SEND_CALLBACK_PATTERN.match(query.data)
    if not match:
        return
    ticket_id = int(match.group(1))

    # Fetch receipt info
    info = await get_ticket_receipt(context.session, ticket_id)

    if info.status != ReceiptStatus.READY or not info.ofd_url or not info.client_chat_id:
        try:
            await query.answer('Чек не готов или клиент не найден', show_alert=True)
        except TimedOut:
            pass
        return

    # Send receipt link to client
    try:
        await context.bot.send_message(
            chat_id=info.client_chat_id,
            text=(
                f'Ваш фискальный чек по билету {info.ticket_id} готов.\n'
                f'Открыть чек: {info.ofd_url}'
            ),
        )
    except Forbidden:
        logger.warning('Client %s blocked the bot, cannot send receipt', info.client_chat_id)
        try:
            await query.answer('Клиент заблокировал бота', show_alert=True)
        except TimedOut:
            pass
        return
    except TimedOut:
        try:
            await query.answer('Ошибка отправки, попробуйте ещё раз', show_alert=True)
        except TimedOut:
            pass
        return

    # Edit the original message to replace keyboard with "sent" state
    sent_keyboard = build_receipt_card_keyboard_sent(info)
    try:
        await query.message.edit_reply_markup(reply_markup=sent_keyboard)
    except TimedOut:
        pass

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import TypeHandler, ContextTypes
from yookassa.domain.notification import WebhookNotification

from api.googlesheets import update_ticket_in_gspread
from api.gspread_pub import publish_update_ticket
from db import db_postgres
from db.enum import TicketStatus
from handlers.sub_hl import send_approve_reject_message_to_admin_in_webhook
from settings.settings import CHAT_ID_MIKIEREMIKI, ADMIN_CME_GROUP

webhook_hl_logger = logging.getLogger('bot.webhook')

INVOICE_NUMBER = {
    'Предоплата': '305862-32',
    'Оплата': '305862-36'
}


async def yookassa_hook_update(update: WebhookNotification,
                               context: 'ContextTypes.DEFAULT_TYPE'):
    text = 'Платеж\n'
    text = await parsing_metadata(update, text)
    try:
        await context.bot.send_message(CHAT_ID_MIKIEREMIKI, text)
    except BadRequest as e:
        webhook_hl_logger.error(e)
        webhook_hl_logger.info(text)

    if update.object.status == 'pending':
        await context.bot.send_message(CHAT_ID_MIKIEREMIKI,
                                       'Платеж ожидает оплаты')
    elif update.object.status == 'waiting_for_capture':
        pass  # Для двух стадийной оплаты
    elif update.object.status == 'succeeded':
        await processing_successful_payment(update, context)
    elif update.object.status == 'canceled':
        # TODO Сделать основную отмену билетов по этому уведомлению от yookassa
        pass


async def parsing_metadata(update: WebhookNotification, text: str) -> str:
    for k, v in dict(update).items():
        if k == 'object':
            for k1, v1 in v.items():
                text += f'{k1}: {v1}\n'
        else:
            text += f'{k}: {v}\n'
    return text


async def processing_ticket_paid(update, context: 'ContextTypes.DEFAULT_TYPE'):
    message_id = update.object.metadata['message_id']
    chat_id = update.object.metadata['chat_id']
    ticket_ids = update.object.metadata['ticket_ids'].split('|')
    ticket_ids = [int(ticket_id) for ticket_id in ticket_ids]
    choose_schedule_event_ids = update.object.metadata[
        'choose_schedule_event_ids'].split('|')
    command = update.object.metadata['command']
    webhook_hl_logger.info(
        f'webhook_update: '
        f'{ticket_ids=}, '
        f'{choose_schedule_event_ids=}, '
    )
    try:
        await context.bot.edit_message_reply_markup(chat_id, message_id)
    except BadRequest as e:
        webhook_hl_logger.error(e)
        webhook_hl_logger.error('Удаление кнопки для оплаты не произошло')
    text = f'<b>Номер вашего билета '
    ticket_status = TicketStatus.PAID
    sheet_id_domik = context.config.sheets.sheet_id_domik
    for ticket_id in ticket_ids:
        try:
            await publish_update_ticket(
                sheet_id_domik,
                ticket_id,
                str(ticket_status.value),
            )
        except Exception as e:
            webhook_hl_logger.exception(
                f"Failed to publish gspread task, fallback to direct call: {e}")
            await update_ticket_in_gspread(
                sheet_id_domik, ticket_id, ticket_status.value)
        await db_postgres.update_ticket(
            context.session, ticket_id, status=ticket_status)
        text += f'<code>{ticket_id}</code> '
    text += '</b>\n\n'
    refund = context.bot_data.get('settings', {}).get('REFUND_INFO', '')
    text += refund + '\n\n'
    text += (
        'Платеж успешно обработан\n\n'
        'Нажмите <b>«ДАЛЕЕ»</b> под сообщением для получения более '
        'подробной информации\n\n'
        '<i>Или отправьте квитанцию/чек об оплате</i>')
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton('ДАЛЕЕ', callback_data='Next')]])
    try:
        await context.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup)
    except BadRequest as e:
        webhook_hl_logger.error(e)
        webhook_hl_logger.error(
            'Отправка сообщения о обработке платежа не произошла')
    thread_id = None
    callback_name = None
    if command == 'reserve':
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Бронирования спектаклей', None))
        # TODO Переписать ключи словаря с топиками на использование enum
        if not thread_id:
            thread_id = (context.bot_data['dict_topics_name']
                         .get('Бронирование спектаклей', None))
        callback_name = 'reserve'
    if command == 'studio':
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Бронирования студия', None))
        callback_name = 'studio'
    try:
        await send_approve_reject_message_to_admin_in_webhook(context,
                                                              chat_id,
                                                              message_id,
                                                              ticket_ids,
                                                              thread_id,
                                                              callback_name)
    except (NameError, BadRequest) as e:
        webhook_hl_logger.error(e)
        error_text = 'Отправление в админский чат не произошло'
        webhook_hl_logger.error(error_text)
        text = f'{error_text} {ticket_ids=} {command=}'
        await context.bot.send_message(CHAT_ID_MIKIEREMIKI, text)


async def processing_successful_payment(update: WebhookNotification,
                                        context: 'ContextTypes.DEFAULT_TYPE'):
    invoice_original_number = update.object.metadata.get(
        'dashboardInvoiceOriginalNumber', False)
    if invoice_original_number in INVOICE_NUMBER.values():
        await processing_cme_prepaid(update, context)
    elif update.object.metadata.get('command', False):
        await processing_ticket_paid(update, context)


async def processing_cme_prepaid(update, context):
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Выездные мероприятия', None))
    try:
        invoice_original_number = update.object.metadata.get(
            'dashboardInvoiceOriginalNumber', False)
        status = 'Неизвестный_счет'
        for k, v in INVOICE_NUMBER.items():
            if v == invoice_original_number:
                status = k
                break
        text = f'#{status}\n'
        text += f'Платеж успешно обработан\n'
        customer_email = update.object.metadata['custEmail']
        customer_number = update.object.metadata['customerNumber']
        text += f'Покупатель: {customer_email}\n'
        text += f'Номер счета: {invoice_original_number}\n'
        if customer_number != customer_email:
            text += f' {customer_number}\n'

        text += 'Ждем сообщения от пользователя с квитанцией и номером заявки'

        await context.bot.send_message(
            chat_id=ADMIN_CME_GROUP,
            text=text,
            message_thread_id=thread_id,
        )
    except (NameError, BadRequest) as e:
        webhook_hl_logger.error(e)
        error_text = 'Отправление в админский чат не произошло'
        webhook_hl_logger.error(error_text)
        text = f'{error_text}'
        await context.bot.send_message(CHAT_ID_MIKIEREMIKI, text)


YookassaHookHandler = TypeHandler(WebhookNotification, yookassa_hook_update)

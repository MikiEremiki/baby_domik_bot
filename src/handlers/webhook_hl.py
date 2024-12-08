import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import TypeHandler, ContextTypes
from yookassa.domain.notification import WebhookNotification

from api.googlesheets import update_ticket_in_gspread
from db import db_postgres
from db.enum import TicketStatus
from handlers.sub_hl import send_approve_reject_message_to_admin_in_webhook
from settings.settings import CHAT_ID_MIKIEREMIKI, ADMIN_GROUP

webhook_hl_logger = logging.getLogger('bot.webhook')


async def webhook_update(update: WebhookNotification,
                         context: ContextTypes.DEFAULT_TYPE):
    text = 'Платеж\n'
    for k, v in dict(update).items():
        if k == 'object':
            for k1, v1 in v.items():
                text += f'{k1}: {v1}\n'
        else:
            text += f'{k}: {v}\n'
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
        prepaid_invoice_number = '305862-32'
        invoice_original_number = update.object.metadata.get(
            'dashboardInvoiceOriginalNumber', False)
        if invoice_original_number == prepaid_invoice_number:
           await processing_cme_prepaid(update, context)
        elif update.object.metadata.get('command', False):
            await processing_ticket_paid(update, context)
    elif update.object.status == 'canceled':
        pass


async def processing_ticket_paid(update, context):
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
    for ticket_id in ticket_ids:
        update_ticket_in_gspread(ticket_id, ticket_status.value)
        await db_postgres.update_ticket(context.session,
                                        ticket_id,
                                        status=ticket_status)
        text += f'<code>{ticket_id}</code> '
    text += '</b>\n\n'
    text += (
        'Платеж успешно обработан\n\n'
        'Нажмите <b>«ДАЛЕЕ»</b> под сообщением для получения более '
        'подробной информации\n\n'
        '<i>Или отправьте квитанцию/чек об оплате</i>')
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton('ДАЛЕЕ', callback_data='Next')]])
    try:
        await context.bot.send_message(chat_id=chat_id,
                                       text=text,
                                       reply_markup=reply_markup)
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


async def processing_cme_prepaid(update, context):
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Выездные мероприятия', None))
    try:
        text = f'#Предоплата\n'
        text += f'Платеж успешно обработан\n'
        customer_email = update.object.metadata['custEmail']
        customer_number = update.object.metadata['customerNumber']
        invoice_original_number = update.object.metadata['dashboardInvoiceOriginalNumber']
        text += f'Покупатель: {customer_email}'
        text += f'Номер счета: {invoice_original_number}'
        if customer_number != customer_email:
            text += f' {customer_number}'

        text += 'Ждем сообщения от пользователя с квитанцией и номером заявки'

        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=text,
            message_thread_id=thread_id,
        )
    except (NameError, BadRequest) as e:
        webhook_hl_logger.error(e)
        error_text = 'Отправление в админский чат не произошло'
        webhook_hl_logger.error(error_text)
        text = f'{error_text}'
        await context.bot.send_message(CHAT_ID_MIKIEREMIKI, text)


WebhookHandler = TypeHandler(WebhookNotification, webhook_update)

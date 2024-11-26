import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import TypeHandler, ContextTypes
from yookassa.domain.notification import WebhookNotification

from api.googlesheets import update_ticket_in_gspread
from db import db_postgres
from db.enum import TicketStatus
from handlers.sub_hl import send_approve_reject_message_to_admin_in_webhook
from settings.settings import CHAT_ID_MIKIEREMIKI

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
    await context.bot.send_message(CHAT_ID_MIKIEREMIKI, text)

    if update.object.status == 'pending':
        await context.bot.send_message(CHAT_ID_MIKIEREMIKI,
                                       'Платеж ожидает оплаты')
    if update.object.status == 'waiting_for_capture':
        pass  # Для двух стадийной оплаты
    if update.object.status == 'succeeded':
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

        await context.bot.edit_message_reply_markup(chat_id, message_id)

        text = f'<b>Номер вашего билета '
        ticket_status = TicketStatus.PAID
        for ticket_id in ticket_ids:
            update_ticket_in_gspread(ticket_id, ticket_status.value)
            await db_postgres.update_ticket(context.session,
                                            ticket_id,
                                            status=ticket_status)
            text += f'<code>{ticket_id}</code> '
        text += '</b>\n\n'
        refund = '❗️ВОЗВРАТ ДЕНЕЖНЫХ СРЕДСТВ ИЛИ ПЕРЕНОС ВОЗМОЖЕН НЕ МЕНЕЕ, ЧЕМ ЗА 24 ЧАСА❗\n\n'
        text += refund

        text += (
            'Платеж успешно обработан\n\n'
            'Нажмите <b>«ДАЛЕЕ»</b> под сообщением для получения более '
            'подробной информации\n\n'
            '<i>Или отправьте квитанцию/чек об оплате</i>')
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton('ДАЛЕЕ', callback_data='Next')]])
        await context.bot.send_message(chat_id=chat_id,
                                       text=text,
                                       reply_markup=reply_markup)

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
        except NameError as e:
            webhook_hl_logger.error(e)
            await context.bot.send_message(CHAT_ID_MIKIEREMIKI, f'{command=}')

        state = 'PAID'
        return state
    if update.object.status == 'canceled':
        pass


WebhookHandler = TypeHandler(WebhookNotification, webhook_update)

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, TimedOut, NetworkError
from telegram.ext import TypeHandler, ContextTypes
from yookassa.domain.notification import WebhookNotification

from api.googlesheets import update_ticket_in_gspread
from api.gspread_pub import publish_update_ticket
from db import db_postgres
from db.db_googlesheets import decrease_nonconfirm_seat
from db.enum import TicketStatus
from handlers.main_hl import send_approve_message
from handlers.sub_hl import (
    send_approve_reject_message_to_admin_in_webhook,
    get_booking_admin_text
)
from settings.settings import CHAT_ID_MIKIEREMIKI, ADMIN_CME_GROUP, ADMIN_GROUP

from utilities.utl_func import create_str_info_by_schedule_event_id
from utilities.utl_retry import retry_on_timeout

webhook_hl_logger = logging.getLogger('bot.webhook')

INVOICE_NUMBER = {
    'Предоплата': '305862-32',
    'Оплата': '305862-36'
}


@retry_on_timeout(retries=3, retry_delay=2.0)
async def _send_message(bot, *args, **kwargs):
    return await bot.send_message(*args, **kwargs)


@retry_on_timeout(retries=3, retry_delay=2.0)
async def _edit_message_reply_markup(bot, *args, **kwargs):
    return await bot.edit_message_reply_markup(*args, **kwargs)


async def yookassa_hook_update(update: WebhookNotification,
                               context: 'ContextTypes.DEFAULT_TYPE'):
    text = 'Платеж\n'
    text = await parsing_metadata(update, text)
    chat_dev = context.config.bot.developer_chat_id
    try:
        await _send_message(context.bot, chat_dev, text)
    except BadRequest as e:
        webhook_hl_logger.error(e)
        webhook_hl_logger.info(text)

    if update.object.status == 'pending':
        try:
            await _send_message(context.bot, chat_dev,
                                'Платеж ожидает оплаты')
        except (BadRequest, TimedOut, NetworkError) as e:
            webhook_hl_logger.error(f'Не удалось отправить уведомление pending: {e}')
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
    metadata = update.object.metadata
    source = metadata.get('source', 'bot')
    is_website = source == 'website'

    message_id = metadata['message_id']
    chat_id = metadata['chat_id']
    try:
        int_chat_id = int(chat_id)
    except (ValueError, TypeError):
        int_chat_id = 0

    ticket_ids = metadata['ticket_ids'].split('|')
    ticket_ids = [int(ticket_id) for ticket_id in ticket_ids]
    choose_schedule_event_ids = metadata[
        'choose_schedule_event_ids'].split('|')
    command = metadata['command']
    is_admin_booking = '_admin' in command
    webhook_hl_logger.info(
        f'webhook_update: '
        f'{ticket_ids=}, '
        f'{choose_schedule_event_ids=}, '
        f'{command=}, '
        f'{source=}, '
        f'{chat_id=}'
    )

    # Для заказов с сайта инициализируем user_data, чтобы работала кнопка "ДАЛЕЕ"
    if is_website and int_chat_id != 0:
        if int_chat_id not in context.application.user_data:
            if context.application.persistence:
                context.application.persistence.get_user_data().setdefault(
                    int_chat_id, {})

        user_data = context.application.user_data.get(int_chat_id)
        if user_data:
            user_data['command'] = command
            user_data['postfix_for_cancel'] = 'reserve' if 'reserve' in command else 'studio'
            if 'reserve_user_data' not in user_data:
                user_data['reserve_user_data'] = {}
            user_data['reserve_user_data']['ticket_ids'] = ticket_ids
            user_data['reserve_user_data']['flag_send_ticket_info'] = True
            # Очищаем client_data, чтобы get_booking_admin_text загрузил актуальные данные из БД
            user_data['reserve_user_data'].pop('client_data', None)
            user_data['reserve_user_data'].pop('original_child_text', None)
            if 'common_data' not in user_data:
                user_data['common_data'] = {}

            # Добавляем данные о мероприятии для уведомления, если их нет
            if not user_data['common_data'].get('text_for_notification_massage'):
                try:
                    schedule_event_id = int(choose_schedule_event_ids[0])
                    text_select_event = await create_str_info_by_schedule_event_id(
                        context, schedule_event_id)

                    ticket = await db_postgres.get_ticket(context.session, ticket_ids[0])
                    chose_base_ticket = await db_postgres.get_base_ticket(
                        context.session, ticket.base_ticket_id)

                    text_notification = (f'{text_select_event}<br>'
                                         f'Вариант бронирования:<br>'
                                         f'{chose_base_ticket.name} '
                                         f'{int(ticket.price)}руб<br>')
                    user_data['common_data']['text_for_notification_massage'] = text_notification
                except Exception as e:
                    webhook_hl_logger.error(f'Ошибка при формировании текста уведомления: {e}')

    if int_chat_id != 0 and message_id != 0:
        try:
            await _edit_message_reply_markup(context.bot, chat_id, message_id)
        except (BadRequest, TimedOut, NetworkError) as e:
            webhook_hl_logger.error(e)
            webhook_hl_logger.error('Удаление кнопки для оплаты не произошло')
    text = f'<b>Номер вашего билета '
    ticket_status = TicketStatus.APPROVED if is_admin_booking else TicketStatus.PAID
    sheet_id_domik = context.config.sheets.sheet_id_domik

    promo_id_raw = update.object.metadata.get('promo_id')
    promo_id = int(promo_id_raw) if promo_id_raw else None

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
            context.session, ticket_id, status=ticket_status,
            promo_id=promo_id)
        text += f'<code>{ticket_id}</code> '

    if promo_id:
        try:
            await db_postgres.increment_promotion_usage(
                context.session, promo_id)
        except Exception as e:
            text = f'Не удалось увеличить счетчик промо {promo_id}: {e}'
            webhook_hl_logger.exception(text)
    text += '</b>\n\n'
    refund = context.bot_data.get('settings', {}).get('REFUND_INFO', '')
    text += refund + '\n\n'
    text += 'Платеж успешно обработан\n\n'

    promo = None
    if promo_id:
        promo = await db_postgres.get_promotion(context.session, promo_id)

    thread_id = None
    callback_name = None
    base_command = command.replace('_admin', '')
    if base_command == 'reserve':
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Бронирования спектаклей', None))
        # TODO Переписать ключи словаря с топиками на использование enum
        if not thread_id:
            thread_id = (context.bot_data['dict_topics_name']
                         .get('Бронирование спектаклей', None))
        callback_name = 'reserve'
    if base_command == 'studio':
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Бронирования студия', None))
        callback_name = 'studio'

    user_data = None
    if int_chat_id != 0:
        user_data = context.application.user_data.get(int_chat_id)

        if user_data is not None:
            user_data['STATE'] = 'PAID'
            # Пытаемся принудительно установить состояние в разговоре
            key = (int_chat_id, int_chat_id)
            try:
                await context.application.persistence.update_conversation(
                    'reserve', key, 'PAID')
            except Exception as e:
                text = f'Не удалось обновить состояние в persistence: {e}'
                webhook_hl_logger.error(text)

    if is_admin_booking:
        # Для админских бронирований: списываем неподтвержденные места и отправляем сразу подтверждение пользователю
        for ticket_id in ticket_ids:
            try:
                t = await db_postgres.get_ticket(context.session, ticket_id)
                await decrease_nonconfirm_seat(
                    context, t.schedule_event_id, t.base_ticket_id)
            except Exception as e:
                text = f'Не удалось списать неподтвержденные места для {ticket_id}: {e}'
                webhook_hl_logger.exception(text)
        if int_chat_id != 0:
            try:
                await send_approve_message(int_chat_id, context, ticket_ids)
            except Exception as e:
                text = f'Не удалось отправить подтверждение пользователю для {ticket_ids}: {e}'
                webhook_hl_logger.exception(text)

        # Уведомление в админ-группу
        try:
            user = user_data['user'] if int_chat_id != 0 and user_data else None
            text_to_admin = f'#Бронирование #Админ_бронь\n'
            text_to_admin += f'Платеж по ссылке успешно обработан. Бронь подтверждена автоматически.\n'
            if user:
                booking_details = await get_booking_admin_text(
                    context, ticket_ids, user, user_data
                )
                text_to_admin += booking_details + '\n\n'

            for ticket_id in ticket_ids:
                text_to_admin += f'#ticket_id <code>{ticket_id}</code>\n'

            await _send_message(
                context.bot,
                chat_id=ADMIN_GROUP,
                text=text_to_admin,
                message_thread_id=thread_id,
                parse_mode='HTML'
            )
        except Exception as e:
            text = f'Не удалось отправить уведомление админу о платеже админ-брони: {e}'
            webhook_hl_logger.exception(text)
    else:
        if int_chat_id != 0:
            text += (
                'Нажмите <b>«ДАЛЕЕ»</b> под сообщением для получения более '
                'подробной информации\n\n'
                '<i>Или отправьте квитанцию/чек об оплате</i>'
            )

            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton('ДАЛЕЕ', callback_data='Next')]])
            try:
                message = await _send_message(
                    context.bot,
                    chat_id=int_chat_id, text=text, reply_markup=reply_markup)
                # Сохраняем ID сообщения для корректной работы кнопки "ДАЛЕЕ"
                if is_website and message:
                    user_data = context.application.user_data.get(int_chat_id)
                    if user_data:
                        user_data['common_data']['message_id_buy_info'] = message.message_id
            except (BadRequest, Forbidden) as e:
                webhook_hl_logger.error(e)
                webhook_hl_logger.error(
                    'Отправка сообщения о обработке платежа не произошла')

        try:
            await send_approve_reject_message_to_admin_in_webhook(context,
                                                                  int_chat_id,
                                                                  message_id,
                                                                  ticket_ids,
                                                                  thread_id,
                                                                  callback_name)
        except (NameError, BadRequest, TimedOut, NetworkError) as e:
            webhook_hl_logger.error(e)
            error_text = 'Отправление в админский чат не произошло'
            webhook_hl_logger.error(error_text)
            text = f'{error_text} {ticket_ids=} {command=}'
            if int_chat_id != 0:
                try:
                    await context.bot.send_message(CHAT_ID_MIKIEREMIKI, text)
                except (TimedOut, NetworkError) as fallback_err:
                    webhook_hl_logger.error(
                        f'Не удалось отправить fallback-сообщение: {fallback_err}')
            else:
                webhook_hl_logger.error(text)


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

        await _send_message(
            context.bot,
            chat_id=ADMIN_CME_GROUP,
            text=text,
            message_thread_id=thread_id,
        )
    except (NameError, BadRequest, TimedOut, NetworkError) as e:
        webhook_hl_logger.error(e)
        error_text = 'Отправление в админский чат не произошло'
        webhook_hl_logger.error(error_text)
        text = f'{error_text}'
        try:
            await context.bot.send_message(CHAT_ID_MIKIEREMIKI, text)
        except (TimedOut, NetworkError) as fallback_err:
            webhook_hl_logger.error(
                f'Не удалось отправить fallback-сообщение: {fallback_err}')


YookassaHookHandler = TypeHandler(WebhookNotification, yookassa_hook_update)

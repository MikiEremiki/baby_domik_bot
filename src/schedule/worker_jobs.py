import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from telegram.error import RetryAfter
from telegram.ext import ContextTypes

from db import db_postgres, Ticket
from db.enum import TicketStatus
from utilities.utl_db import open_session
from utilities.utl_func import (
    get_formatted_date_and_time_of_event, get_full_name_event)
from utilities.utl_googlesheets import cancel_ticket_and_return_seat_auto

worker_logger = logging.getLogger('bot.worker')


async def send_reminder(context: 'ContextTypes.DEFAULT_TYPE') -> None:
    worker_logger.info('Начало выполнения job send_reminder')
    job = context.job
    event_id = job.data['event_id']
    session = await open_session(context.config)
    try:
        event = await db_postgres.get_schedule_event(session, event_id)
        theater = await db_postgres.get_theater_event(
            session, event.theater_event_id)
        tickets: List[Ticket] = event.tickets

        date_event, time_event = await get_formatted_date_and_time_of_event(event)
        full_name = get_full_name_event(theater)

        for ticket in tickets:
            if (ticket.status in [TicketStatus.PAID, TicketStatus.APPROVED]
                    and not getattr(ticket, 'reminded_1d_at', None)):
                user_status = ticket.user.status
                if user_status and user_status.is_blocked_by_user:
                    worker_logger.info(
                        f"Пользователь {ticket.user.user_id} заблокировал бота. "
                        f"Пропуск отправки напоминания для билета {ticket.id}")
                    continue

                text = (f"Напоминаем о предстоящем мероприятии завтра!\n\n"
                        f'<b>{full_name}\n'
                        f'{date_event}\n'
                        f'{time_event}</b>\n'
                        f'<b>Номер вашего билета <code>{ticket.id}</code></b>\n')
                text += f'__________\n'
                refund = context.bot_data.get('settings', {}).get('REFUND_INFO', '')
                text += refund + '\n\n'
                text += ('Задать вопросы можно в сообщениях группы\n'
                         'https://vk.com/baby_theater_domik')
                try:
                    await send_remainder_msg(context, session, text, ticket)
                except RetryAfter as e:
                    worker_logger.error(
                        f"RetryAfter for ticket {ticket.id}: {e}")
                    delay = e.retry_after
                    if isinstance(e.retry_after, timedelta):
                        delay = e.retry_after.total_seconds()
                    await asyncio.sleep(delay)
                    await send_remainder_msg(context, session, text, ticket)
                except Exception as e:
                    worker_logger.error(
                        f"Failed to send reminder for ticket {ticket.id}: {e}")
                    worker_logger.info('Попытка повтора')
                    await send_remainder_msg(context, session, text, ticket)
            else:
                worker_logger.info(f"Ticket {ticket.id} already reminded")
    finally:
        await session.close()


async def cancel_old_created_tickets(context: 'ContextTypes.DEFAULT_TYPE') -> None:
    """
    Ежечасный обработчик: отменяет билеты в статусе CREATED, если им > 30 минут.
    Освобождает место и обновляет Google Sheets аналогично write_to_return_seats_for_sale.
    """
    worker_logger.info('Начало выполнения job cancel_old_created_tickets')
    session = await open_session(context.config)
    try:
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(minutes=30)
        tickets: List[Ticket] = await db_postgres.get_all_tickets_by_status(
            session, TicketStatus.CREATED)
        cnt_total = 0
        cnt_canceled = 0
        for t in tickets:
            cnt_total += 1
            created_at = getattr(t, 'created_at', None)
            if not created_at:
                continue
            if created_at <= threshold:
                context.session = session
                try:
                    text = await cancel_ticket_and_return_seat_auto(context, t.id)
                    await context.bot.send_message(
                        chat_id=context.config.bot.developer_chat_id,
                        text=f'AutoCancel: {text}')
                    cnt_canceled += 1
                except Exception as e:
                    worker_logger.exception(
                        f'Ошибка авто-отмены билета {t.id}: {e}')
        worker_logger.info(
            f'Отмена просроченных билетов завершена: всего={cnt_total}, отменено={cnt_canceled}')
    finally:
        await session.close()


async def send_remainder_msg(
        context: 'ContextTypes.DEFAULT_TYPE',
        session: AsyncSession,
        text: str,
        ticket: Ticket
):
    await context.bot.send_message(
        chat_id=ticket.user.chat_id,
        text=text
    )
    ticket.reminded_1d_at = datetime.now(timezone.utc)
    await session.commit()

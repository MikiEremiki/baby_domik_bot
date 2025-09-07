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

worker_logger = logging.getLogger('bot.worker')


async def send_reminder(context: "ContextTypes.DEFAULT_TYPE") -> None:
    worker_logger.info('Начало выполнения job send_reminder')
    job = context.job
    event_id = job.data['event_id']
    session = await open_session(context.config)
    event = await db_postgres.get_schedule_event(session, event_id)
    theater = await db_postgres.get_theater_event(
        session, event.theater_event_id)
    tickets: List[Ticket] = event.tickets

    date_event, time_event = await get_formatted_date_and_time_of_event(event)
    full_name = get_full_name_event(theater)

    for ticket in tickets:
        if (ticket.status in [TicketStatus.PAID, TicketStatus.APPROVED]
                and not getattr(ticket, 'reminded_1d_at', None)):
            text = (f"Напоминаем о предстоящем мероприятии завтра!\n\n"
                    f'<b>{full_name}\n'
                    f'{date_event}\n'
                    f'{time_event}</b>\n'
                    f'<b>Номер вашего билета <code>{ticket.id}</code></b>\n')
            text += f'__________\n'
            refund = '❗️ВОЗВРАТ ДЕНЕЖНЫХ СРЕДСТВ ИЛИ ПЕРЕНОС ВОЗМОЖЕН НЕ МЕНЕЕ, ЧЕМ ЗА 24 ЧАСА❗\n\n'
            text += refund
            text += ('Задать вопросы можно в сообщениях группы\n'
                     'https://vk.com/baby_theater_domik')
            try:
                await send_message(context, session, text, ticket)
            except RetryAfter as e:
                worker_logger.error(
                    f"RetryAfter for ticket {ticket.id}: {e}")
                delay = e.retry_after
                if isinstance(e.retry_after, timedelta):
                    delay = e.retry_after.total_seconds()
                await asyncio.sleep(delay)
                await send_message(context, session, text, ticket)
            except Exception as e:
                worker_logger.error(
                    f"Failed to send reminder for ticket {ticket.id}: {e}")
                worker_logger.info('Попытка повтора')
                await send_message(context, session, text, ticket)
        else:
            worker_logger.info(f"Ticket {ticket.id} already reminded")
    await session.close()


async def send_message(
        context: "ContextTypes.DEFAULT_TYPE",
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

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List

from telegram.ext import ContextTypes

from db import db_postgres, Ticket
from db.enum import AutoSendingTrigger, TicketStatus
from utilities.utl_db import open_session
from utilities.utl_func import get_formatted_date_and_time_of_event
from utilities.utl_googlesheets import cancel_ticket_and_return_seat_auto

worker_logger = logging.getLogger('bot.worker')


async def send_reminder(context: 'ContextTypes.DEFAULT_TYPE') -> None:
    """Legacy wrapper: delegates to the unified auto-sending dispatcher.

    Old scheduled jobs `reminder_event_{id}` stored in the job store still call
    this function. It loads the "Напоминание за день" auto-sending record,
    resolves recipients for the given schedule event, and dispatches through
    the unified pipeline. The delivery journal prevents duplicates if the tick
    already sent the message.

    Transitional check: ``reminded_1d_at`` on Ticket is still respected as
    "already sent" for backward compatibility.
    """
    worker_logger.info('Начало выполнения job send_reminder (wrapper)')
    job = context.job
    event_id = job.data['event_id']
    session = await open_session(context.config)
    try:
        from schedule.auto_sending import (
            resolve_auto_sending, dispatch_auto_sending,
            RECIPIENT_SELECTORS, Recipient, ticket_dedup_keys,
        )
        from db.models import ScheduleEvent, User, UserStatus
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select

        event = await db_postgres.get_schedule_event(session, event_id)
        if not event:
            worker_logger.warning(f"send_reminder: event {event_id} not found")
            return

        # Load the "Напоминание за день" auto-sending for this event.
        sendings = await resolve_auto_sending(
            session, AutoSendingTrigger.EVENT, event.theater_event_id)

        # Find the reminder sending (offset ≈ -1500 min).
        reminder_sending = None
        for s in sendings:
            if s.offset_minutes < 0:
                reminder_sending = s
                break

        if not reminder_sending:
            worker_logger.warning(
                f"send_reminder: no reminder sending found for event {event_id}")
            return

        # Load tickets with user info.
        tickets = (
            await session.execute(
                select(Ticket)
                .options(
                    selectinload(Ticket.user)
                    .selectinload(User.status),
                    selectinload(Ticket.people),
                )
                .where(
                    Ticket.schedule_event_id == event.id,
                    Ticket.status.in_([TicketStatus.PAID, TicketStatus.APPROVED]),
                )
            )
        ).scalars().all()

        # Filter out tickets already reminded via old legacy flag.
        tickets = [t for t in tickets if not getattr(t, 'reminded_1d_at', None)]

        # Group by user, build recipients.
        from schedule.auto_sending import group_tickets_by_user
        user_tickets, _ = group_tickets_by_user(tickets)

        if not user_tickets:
            worker_logger.info(f"send_reminder: no new recipients for event {event_id}")
            return

        date_event, time_event = await get_formatted_date_and_time_of_event(event)

        from schedule.auto_sending import build_recipient_ctx
        recipients = []
        for user_id, user_tix in user_tickets.items():
            ticket_ids = ", ".join(str(t.id) for t in user_tix)
            ctx = build_recipient_ctx(event, ticket_ids)
            ctx["date"] = date_event
            ctx["time"] = time_event
            recipients.append(Recipient(
                user=user_tix[0].user,
                ctx=ctx,
                dedup_keys=ticket_dedup_keys(user_tix),
                schedule_event_id=event.id,
            ))

        if recipients:
            await dispatch_auto_sending(
                context, session, reminder_sending, recipients)

    except Exception:
        worker_logger.exception(f"send_reminder wrapper failed for event {event_id}")
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
        session,
        text: str,
        ticket: Ticket
):
    """Legacy helper kept for backward compatibility, no longer called by send_reminder."""
    await context.bot.send_message(
        chat_id=ticket.user.chat_id,
        text=text
    )
    ticket.reminded_1d_at = datetime.now(timezone.utc)
    await session.commit()

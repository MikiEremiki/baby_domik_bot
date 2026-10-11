"""Auto-sending dispatcher: compute send time, render text, select recipients, dispatch, tick."""
import asyncio
import logging
import re
import time as time_module
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time as dt_time
from typing import Awaitable, Callable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from telegram.error import Forbidden, RetryAfter
from telegram.ext import ContextTypes
from sulguk import transform_html

from db import db_postgres
from db.enum import AutoSendingTrigger, TicketStatus
from db.models import (
    AutoSending, AutoSendingDelivery, ScheduleEvent,
    Ticket, User, UserStatus, UserTicket,
)
from utilities.utl_date import MOSCOW_TZ, to_moscow_dt
from utilities.utl_func import (
    get_full_name_event, get_formatted_date_and_time_of_event,
)
from utilities.utl_place import format_place_footnote

auto_sending_logger = logging.getLogger('bot.auto_sending')


# ─── Recipient dataclass ──────────────────────────────────────────────────────

@dataclass
class Recipient:
    user: User
    ctx: dict
    dedup_key: str
    schedule_event_id: int | None


RecipientSelector = Callable[
    [AsyncSession, AutoSending, datetime],
    Awaitable[list[Recipient]]
]


# ─── compute_send_time ────────────────────────────────────────────────────────

def compute_send_time(
    anchor: datetime,
    offset_minutes: int,
    window_start: dt_time | None = None,
    window_end: dt_time | None = None,
) -> datetime:
    """Compute the scheduled send datetime from an anchor + offset, optionally
    shifted into a daily window [window_start, window_end].

    - Negative offset  → before the anchor (e.g. reminder −1500 min).
    - Positive offset  → after the anchor (e.g. feedback +240 min).
    - If the raw time falls outside [window_start, window_end] the result is
      moved to the nearest boundary (start of the same day or start of the
      next day).
    """
    raw = anchor + timedelta(minutes=offset_minutes)

    if window_start is None and window_end is None:
        return raw

    win_start = window_start or dt_time.min
    win_end = window_end or dt_time.max

    raw_time = raw.time()

    # If raw time is within the window, return as-is.
    if win_start <= raw_time <= win_end:
        return raw

    # Before window start → shift to window_start on the same day.
    if raw_time < win_start:
        return raw.replace(hour=win_start.hour, minute=win_start.minute,
                           second=win_start.second, microsecond=0)

    # After window end → shift to window_start on the next day.
    next_day = raw.date() + timedelta(days=1)
    return datetime(
        year=next_day.year, month=next_day.month, day=next_day.day,
        hour=win_start.hour, minute=win_start.minute,
        second=win_start.second, tzinfo=raw.tzinfo,
    )


# ─── render_text ──────────────────────────────────────────────────────────────

def render_text(html_template: str, ctx: dict, sending_name: str = '') -> str:
    """Substitute ``{placeholder}`` tokens in *html_template* with values
    from *ctx*. Returns the rendered HTML string ready for ``transform_html``.

    Safety-net: if placeholder substitution fails, return the original template.

    Length guard: if the result exceeds 4096 characters, truncate with "…" and
    log a warning.
    """
    # Fill missing placeholders with empty string.
    safe_ctx = dict(ctx)
    for token in re.findall(r'\{(\w+)\}', html_template):
        if token not in safe_ctx:
            safe_ctx[token] = ''

    try:
        result = html_template.format(**safe_ctx)
    except (KeyError, ValueError) as exc:
        auto_sending_logger.warning(
            f"render_text placeholder error in '{sending_name}': {exc} | "
            f"ctx keys={list(ctx.keys())} | template_len={len(html_template)}")
        result = html_template

    if len(result) > 4096:
        auto_sending_logger.warning(
            f"render_text length {len(result)} > 4096 for '{sending_name}', "
            f"truncating.")
        result = result[:4093] + "…"

    return result


# ─── _send_and_record_delivery ────────────────────────────────────────────────

async def _send_and_record_delivery(
    bot: ContextTypes.DEFAULT_TYPE,
    user: User,
    transformed: object,
    auto_sending: AutoSending,
    session: AsyncSession,
    dedup_key: str,
    schedule_event_id: int | None,
    delivery_updated: bool,
    sent: int,
) -> int:
    """Send a message with transformed text and record the delivery.

    Returns the updated *sent* counter (incremented by 1).
    """
    await bot.send_message(
        chat_id=user.chat_id,
        text=transformed.text,
        entities=transformed.entities,
        parse_mode=None,
    )
    sent_at = datetime.now(tz=timezone.utc)
    if delivery_updated:
        await db_postgres.update_delivery(
            session, auto_sending.id, user.user_id, dedup_key, sent_at)
    else:
        await db_postgres.create_delivery(
            session,
            auto_sending_id=auto_sending.id,
            user_id=user.user_id,
            dedup_key=dedup_key,
            sent_at=sent_at,
            schedule_event_id=schedule_event_id,
            auto_commit=True,
        )
    return sent + 1


# ─── resolve_auto_sending ─────────────────────────────────────────────────────

async def resolve_auto_sending(
    session: AsyncSession,
    trigger: AutoSendingTrigger,
    theater_event_id: int | None = None,
) -> Sequence[AutoSending]:
    """Return active auto-sendings for the given trigger.

    Resolution order:
    1. First try to find a sending specific to *theater_event_id*.
    2. Fall back to general sendings (``theater_event_id IS NULL``).

    Returns all matching active sendings (there can be several with different
    names for the same trigger).
    """
    sendings = await db_postgres.get_all_active_auto_sendings(
        session, trigger=trigger)

    if not sendings:
        return []

    # Filter: prefer theater-specific, then general.
    specific = [s for s in sendings if s.theater_event_id == theater_event_id]
    if specific:
        return specific

    general = [s for s in sendings if s.theater_event_id is None]
    return general


# ─── Recipient selectors ──────────────────────────────────────────────────────

async def _selector_event(
    session: AsyncSession,
    auto_sending: AutoSending,
    now: datetime,
) -> list[Recipient]:
    """Select recipients for EVENT trigger: users with PAID/APPROVED tickets
    for the schedule event(s) associated with the auto_sending.

    Groups tickets by ``user_id``, builds ``dedup_key = se:{schedule_event_id}``.
    """
    # Filter out events that ended more than 3 days ago at the DB level.
    cutoff = now - timedelta(days=3)

    # Determine which schedule events to process.
    if auto_sending.theater_event_id is not None:
        # All schedule events for this theater event.
        stmt = (
            select(ScheduleEvent)
            .where(
                ScheduleEvent.theater_event_id == auto_sending.theater_event_id,
                ScheduleEvent.datetime_event >= cutoff,
            )
        )
    else:
        # All schedule events (general sending).
        stmt = (
            select(ScheduleEvent)
            .where(ScheduleEvent.datetime_event >= cutoff)
        )

    events = (await session.execute(stmt)).scalars().all()
    recipients: list[Recipient] = []

    for se in events:
        # Find PAID/APPROVED tickets for this schedule event.
        stmt = (
            select(Ticket)
            .options(
                selectinload(Ticket.user)
                .selectinload(User.status),
                selectinload(Ticket.people),
            )
            .where(
                Ticket.schedule_event_id == se.id,
                Ticket.status.in_([TicketStatus.PAID, TicketStatus.APPROVED]),
            )
        )
        tickets = (await session.execute(stmt)).scalars().all()

        # Group by user.
        user_tickets: dict[int, list[Ticket]] = {}
        for t in tickets:
            if t.user is None:
                auto_sending_logger.warning(
                    f"Ticket {t.id} has no user (user_id is NULL), skipping")
                continue
            user_tickets.setdefault(t.user.user_id, []).append(t)

        # Build context and recipients.
        date_event, time_event = await get_formatted_date_and_time_of_event(se)
        theater_event = se.theater_event
        full_name = get_full_name_event(theater_event)
        refund_info = ""  # Will be filled by caller if needed.

        place_str = format_place_footnote(se.place) if se.place else ""
        if not se.place:
            auto_sending_logger.warning(
                f"Schedule event {se.id} has no place (place_id is NULL)")

        for user_id, user_tix in user_tickets.items():
            ticket_ids = ", ".join(str(t.id) for t in user_tix)
            ctx = {
                "event_name": full_name,
                "date": date_event,
                "time": time_event,
                "place": place_str,
                "ticket_ids": ticket_ids,
                "refund_info": refund_info,
            }
            recipients.append(Recipient(
                user=user_tix[0].user,
                ctx=ctx,
                dedup_key=f"se:{se.id}",
                schedule_event_id=se.id,
            ))

    return recipients


async def _selector_payment(
    session: AsyncSession,
    auto_sending: AutoSending,
    now: datetime,
) -> list[Recipient]:
    """Select recipients for PAYMENT trigger.

    For payment-triggered sendings the caller passes the schedule event(s)
    through the auto_sending's ``theater_event_id`` or the caller is expected
    to have already filtered. This selector returns users with PAID tickets.

    In the initial implementation this mirrors EVENT selector because payment
    materials are also per-schedule-event. The dedup key is ``se:{schedule_event_id}``.
    """
    return await _selector_event(session, auto_sending, now)


async def select_payment_recipients(
    session: AsyncSession,
    ticket_ids: list[int],
) -> list[Recipient]:
    """Build Recipients for PAYMENT auto-sendings from just-paid tickets.

    Loads tickets by ID, groups by (user_id, schedule_event_id), and builds
    context with all standard placeholders including ``place``.

    Returns a list of Recipients ready for ``dispatch_auto_sending``.
    """
    from db import db_postgres

    # Load tickets with user info
    tickets = []
    for tid in ticket_ids:
        t = await db_postgres.get_ticket(session, tid)
        if t is not None:
            tickets.append(t)
    if not tickets:
        return []

    # Group tickets by (user_id, schedule_event_id)
    grouped: dict[tuple[int, int], list] = {}
    for t in tickets:
        if t.user is None:
            auto_sending_logger.warning(
                f"Ticket {t.id} has no user (user_id is NULL), skipping")
            continue
        key = (t.user.user_id, t.schedule_event_id)
        grouped.setdefault(key, []).append(t)

    if not grouped:
        return []

    # Build recipients
    recipients: list[Recipient] = []
    for (uid, se_id), user_tix in grouped.items():
        schedule_event = await db_postgres.get_schedule_event(session, se_id)
        if schedule_event is None:
            continue

        date_str, time_str = await get_formatted_date_and_time_of_event(
            schedule_event)
        theater_event = schedule_event.theater_event
        event_name = get_full_name_event(theater_event)
        ticket_id_str = ", ".join(str(t.id) for t in user_tix)

        place_str = format_place_footnote(schedule_event.place) if schedule_event.place else ""
        if not schedule_event.place:
            auto_sending_logger.warning(
                f"Schedule event {se_id} has no place (place_id is NULL)")

        ctx = {
            "event_name": event_name,
            "date": date_str,
            "time": time_str,
            "place": place_str,
            "ticket_ids": ticket_id_str,
            "refund_info": "",
        }

        user = user_tix[0].user
        recipients.append(Recipient(
            user=user,
            ctx=ctx,
            dedup_key=f"se:{se_id}",
            schedule_event_id=se_id,
        ))

    return recipients


RECIPIENT_SELECTORS: dict[AutoSendingTrigger, RecipientSelector] = {
    AutoSendingTrigger.EVENT: _selector_event,
    AutoSendingTrigger.PAYMENT: _selector_payment,
}


# ─── dispatch_auto_sending helpers ────────────────────────────────────────────

async def _check_dedup(
    session: AsyncSession,
    auto_sending: AutoSending,
    user_id: int,
    dedup_key: str,
    force_resend: bool,
) -> tuple[bool, bool]:
    """Check delivery dedup for a recipient.

    Returns (delivery_updated: bool, skip: bool).
    - ``skip=True``  → already delivered, do not resend (unless force_resend).
    - ``delivery_updated=True`` → force_resend mode; delivery row will be
      updated instead of created.
    """
    existing = await db_postgres.get_delivery(
        session, auto_sending.id, user_id, dedup_key)
    if existing:
        if force_resend:
            auto_sending_logger.info(
                f"Force resend: will update delivery for {user_id} "
                f"auto_sending {auto_sending.id} / {dedup_key}")
            return True, False
        auto_sending_logger.info(
            f"Skip {user_id}: already delivered "
            f"auto_sending {auto_sending.id} / {dedup_key}")
        return False, True
    return False, False


def _check_user_eligible(user: User) -> str | None:
    """Check whether a user is eligible to receive a message.

    Returns ``None`` when the user is eligible, or one of the skip reason
    strings: ``"no_chat"``, ``"blocked"``.
    """
    if user.chat_id == 0:
        return "no_chat"
    status = user.status
    if status and (
        status.is_blocked_by_user
        or status.is_blocked_by_admin
        or status.is_blacklisted
    ):
        return "blocked"
    return None


async def _send_with_retry(
    bot: ContextTypes.DEFAULT_TYPE,
    user: User,
    transformed: object,
    auto_sending: AutoSending,
    session: AsyncSession,
    dedup_key: str,
    schedule_event_id: int | None,
    delivery_updated: bool,
) -> tuple[int, int]:
    """Send a message to *user* with RetryAfter handling.

    Returns (sent_delta, error_delta) — each is 0 or 1.
    """
    try:
        await _send_and_record_delivery(
            bot, user, transformed, auto_sending, session,
            dedup_key, schedule_event_id, delivery_updated, 0)
        return 1, 0

    except Forbidden:
        auto_sending_logger.info(
            f"User {user.user_id} blocked the bot (Forbidden).")
        await db_postgres.update_user_status(
            session, user.user_id, is_blocked_by_user=True)
        return 0, 0

    except RetryAfter as e:
        delay = e.retry_after
        if isinstance(delay, timedelta):
            delay = delay.total_seconds()
        auto_sending_logger.warning(
            f"RetryAfter for {user.user_id}: sleeping {delay}s")
        await asyncio.sleep(delay)
        try:
            await _send_and_record_delivery(
                bot, user, transformed, auto_sending, session,
                dedup_key, schedule_event_id, delivery_updated, 0)
            return 1, 0
        except Exception as retry_err:
            error_type = type(retry_err).__name__
            auto_sending_logger.error(
                f"Critical send error for {user.user_id}: {error_type}: {retry_err}",
                extra={
                    'user_id': user.user_id,
                    'auto_sending_id': auto_sending.id,
                    'dedup_key': dedup_key,
                    'error_type': error_type,
                    'error_message': str(retry_err),
                },
            )
            return 0, 1

    except Exception as e:
        error_type = type(e).__name__
        auto_sending_logger.error(
            f"Critical send error for {user.user_id}: {error_type}: {e}",
            extra={
                'user_id': user.user_id,
                'auto_sending_id': auto_sending.id,
                'dedup_key': dedup_key,
                'error_type': error_type,
                'error_message': str(e),
            },
        )
        return 0, 1


async def _dispatch_single_recipient(
    bot: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    auto_sending: AutoSending,
    recipient: Recipient,
    refund_info: str,
    force_resend: bool,
) -> dict[str, int]:
    """Process a single recipient through the full dispatch pipeline.

    Returns a mini-stats dict with keys matching dispatch_auto_sending
    counters (each 0 or 1).
    """
    user = recipient.user
    ctx = recipient.ctx
    dedup_key = recipient.dedup_key
    schedule_event_id = recipient.schedule_event_id

    # Inject refund info if placeholder exists.
    if "refund_info" in ctx:
        ctx["refund_info"] = refund_info

    # 1. Dedup check.
    delivery_updated, skip = await _check_dedup(
        session, auto_sending, user.user_id, dedup_key, force_resend)
    if skip:
        return {'dedup_skipped': 1}

    # 2 & 3. Eligibility checks.
    skip_reason = _check_user_eligible(user)
    if skip_reason == "no_chat":
        auto_sending_logger.info(
            f"Skip {user.user_id}: chat_id == 0 (website order)")
        return {'no_chat_skipped': 1}
    if skip_reason == "blocked":
        status = user.status
        auto_sending_logger.info(
            f"Skip {user.user_id}: blocked "
            f"(user={status.is_blocked_by_user}, "
            f"admin={status.is_blocked_by_admin}, "
            f"blacklisted={status.is_blacklisted})")
        return {'blocked_skipped': 1}

    # 4. Render text and convert to Telegram entities.
    text = render_text(
        auto_sending.text, ctx, sending_name=auto_sending.name)
    transformed = transform_html(text)

    # 5. Send via bot guard.
    if not auto_sending.send_via_bot:
        auto_sending_logger.info(
            f"Skip {user.user_id}: send_via_bot is False")
        return {'not_sent_via_bot_skipped': 1}

    sent_delta, error_delta = await _send_with_retry(
        bot, user, transformed, auto_sending, session,
        dedup_key, schedule_event_id, delivery_updated)

    return {
        'sent': sent_delta,
        'errors': error_delta,
    }


# ─── dispatch_auto_sending ────────────────────────────────────────────────────

async def dispatch_auto_sending(
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    auto_sending: AutoSending,
    recipients: list[Recipient],
    force_resend: bool = False,
) -> dict:
    """Dispatch *auto_sending* to *recipients*.

    For each recipient:
    1. Skip if already in the delivery journal (dedup), unless force_resend.
    2. Skip if ``user.chat_id == 0`` (website orders without Telegram).
    3. Skip if ``is_blocked_by_user``.
    4. Render text, send via bot with HTML entities.
    5. Handle ``RetryAfter`` with sleep + retry.
    6. Record delivery in journal.

    Returns a dict with dispatch statistics:
    - sent: number of successfully sent messages
    - dedup_skipped: skipped because already delivered
    - no_chat_skipped: skipped because chat_id == 0
    - blocked_skipped: skipped because user is blocked
    - not_sent_via_bot_skipped: skipped because send_via_bot is False
    """
    bot = context.bot
    settings = context.bot_data.get("settings", {})
    refund_info = settings.get("REFUND_INFO", "")

    sent = 0
    dedup_skipped = 0
    no_chat_skipped = 0
    blocked_skipped = 0
    not_sent_via_bot_skipped = 0
    errors = 0

    for recipient in recipients:
        stats = await _dispatch_single_recipient(
            bot, session, auto_sending, recipient, refund_info, force_resend)
        sent += stats.get('sent', 0)
        dedup_skipped += stats.get('dedup_skipped', 0)
        no_chat_skipped += stats.get('no_chat_skipped', 0)
        blocked_skipped += stats.get('blocked_skipped', 0)
        not_sent_via_bot_skipped += stats.get('not_sent_via_bot_skipped', 0)
        errors += stats.get('errors', 0)

    return {
        'sent': sent,
        'dedup_skipped': dedup_skipped,
        'no_chat_skipped': no_chat_skipped,
        'blocked_skipped': blocked_skipped,
        'not_sent_via_bot_skipped': not_sent_via_bot_skipped,
        'errors': errors,
    }


# ─── Tick scheduler ───────────────────────────────────────────────────────────

TICK_INTERVAL_SECONDS = 180  # 3 minutes

_tick_lock = asyncio.Lock()


def _is_catch_up_allowed(
    auto_sending: AutoSending,
    send_time: datetime,
    event_datetime: datetime,
    now: datetime,
) -> bool:
    """Check if catch-up is allowed for this sending based on offset sign.

    Rules from the plan:
    - Negative offset (before event): don't send after the event has started.
    - Positive offset (after event): don't send later than 24h after the
      computed send time.
    """
    if auto_sending.offset_minutes < 0:
        # Negative offset: don't send if the event has already started.
        if now >= event_datetime:
            return False
    else:
        # Positive offset: don't catch up more than 24h after send_time.
        if now > send_time + timedelta(hours=24):
            return False
    return True


async def auto_sending_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic tick: process EVENT-triggered auto-sendings.

    Every 5 minutes (TICK_INTERVAL_SECONDS):
    1. For non-precise sendings — find schedule events whose computed send time
       falls in ``(now - catch_up_window, now]`` and dispatch immediately.
    2. For precise sendings — find events whose send time falls in
       ``(now, now + interval]`` and schedule a ``run_once`` job for the exact
       minute.

    Catch-up window equals the tick interval (5 min) — after a restart or
    pause the tick processes at most one interval of missed sendings.

    Concurrency guard: ``_tick_lock`` prevents overlapping executions.
    """
    auto_sending_logger.info("auto_sending_tick: starting")
    if _tick_lock.locked():
        auto_sending_logger.info("auto_sending_tick: previous tick still running, skipping")
        return

    async with _tick_lock:
        from utilities.utl_db import open_session

        tick_start = time_module.monotonic()
        total_sent = 0
        total_dedup = 0
        total_no_chat = 0
        total_blocked = 0
        total_errors = 0

        session = await open_session(context.config)
        try:
            now = datetime.now(tz=MOSCOW_TZ)
            catch_up_window = timedelta(seconds=TICK_INTERVAL_SECONDS)
            interval_end = now + catch_up_window

            # Load all active EVENT sendings.
            sendings = await db_postgres.get_all_active_auto_sendings(
                session, trigger=AutoSendingTrigger.EVENT)

            if not sendings:
                return

            # Load all schedule events in a wide date range that could possibly
            # have a send time in our window.  The widest offset determines the
            # range.  We load events from (now - max(|offset|) - 24h) to
            # (now + max(|offset|) + 24h) to be safe.
            # Also filter out events that ended more than 3 days ago at the DB level.
            max_offset_minutes = max(
                abs(s.offset_minutes) for s in sendings) if sendings else 0
            date_range_hours = max_offset_minutes / 60 + 24  # +24h safety margin for window shift
            date_from = now - timedelta(hours=date_range_hours)
            date_to = now + timedelta(hours=date_range_hours)
            
            # Cutoff: skip events that ended more than 3 days ago.
            cutoff = now - timedelta(days=3)
            
            auto_sending_logger.info(
                "Loading events from %s to %s (cutoff: %s)", date_from, date_to, cutoff)

            stmt = (
                select(ScheduleEvent)
                .where(
                    ScheduleEvent.datetime_event >= date_from,
                    ScheduleEvent.datetime_event <= date_to,
                    ScheduleEvent.datetime_event >= cutoff,
                )
            )
            relevant_events = (await session.execute(stmt)).scalars().all()
            auto_sending_logger.info("Loaded %d events from DB", len(relevant_events))

            if not relevant_events:
                return

            for auto_sending in sendings:
                for se in relevant_events:
                    # Compute the send time for this event + sending combination.
                    event_dt = to_moscow_dt(se.datetime_event)
                    send_time = compute_send_time(
                        event_dt,
                        auto_sending.offset_minutes,
                        auto_sending.window_start,
                        auto_sending.window_end,
                    )

                    # Ensure send_time is timezone-aware (MSK).
                    if send_time.tzinfo is None:
                        send_time = send_time.replace(tzinfo=MOSCOW_TZ)

                    if auto_sending.precise:
                        # Precise mode: schedule run_once if send_time is in
                        # (now, now + interval].
                        if now < send_time <= interval_end:
                            delta = (send_time - now).total_seconds()
                            auto_sending_logger.info(
                                f"Precise schedule: {auto_sending.name} "
                                f"for SE {se.id} in {delta:.0f}s")
                            context.job_queue.run_once(
                                _precise_dispatch_job,
                                when=send_time,
                                data={
                                    "auto_sending_id": auto_sending.id,
                                    "schedule_event_id": se.id,
                                },
                                name=f"auto_precise_{auto_sending.id}_{se.id}",
                                job_kwargs={
                                    "replace_existing": True,
                                    "id": f"auto_precise_{auto_sending.id}_{se.id}",
                                },
                            )
                    else:
                        # Non-precise: dispatch if send_time has passed.
                        # Dedup in the delivery journal ensures one-time delivery.
                        can_send = False
                        if auto_sending.window_start is not None \
                           and auto_sending.window_end is not None:
                            # Window-based: send when send_time <= now AND
                            # current time is inside the delivery window.
                            if send_time <= now and \
                               auto_sending.window_start <= now.time() <= \
                               auto_sending.window_end:
                                can_send = True
                        else:
                            # No window: send as soon as send_time has passed.
                            # _is_catch_up_allowed below prevents sending
                            # reminders after the event has started.
                            if send_time <= now:
                                can_send = True

                        if can_send:
                            # Additional catch-up guard.
                            if not _is_catch_up_allowed(
                                auto_sending, send_time, event_dt, now):
                                auto_sending_logger.info(
                                    f"Skip catch-up: {auto_sending.name} "
                                    f"SE {se.id} (guard)")
                                continue

                            # Skip if all recipients are already delivered.
                            has_undelivered = await _has_undelivered_recipients(
                                session, auto_sending, se.id)
                            if not has_undelivered:
                                auto_sending_logger.info(
                                    f"Skip all-delivered: {auto_sending.name} "
                                    f"SE {se.id}")
                                continue

                            auto_sending_logger.info(
                                f"Tick dispatch: {auto_sending.name} "
                                f"for SE {se.id}")
                            result = await _dispatch_for_event(
                                context, session, auto_sending, se)
                            if result:
                                total_sent += result.get('sent', 0)
                                total_dedup += result.get('dedup_skipped', 0)
                                total_no_chat += result.get('no_chat_skipped', 0)
                                total_blocked += result.get('blocked_skipped', 0)
                                total_errors += result.get('errors', 0)

            duration_ms = int((time_module.monotonic() - tick_start) * 1000)
            auto_sending_logger.info(
                "Tick completed",
                extra={
                    'tick_type': 'auto_sending',
                    'sent': total_sent,
                    'dedup_skipped': total_dedup,
                    'no_chat_skipped': total_no_chat,
                    'blocked_skipped': total_blocked,
                    'errors': total_errors,
                    'duration_ms': duration_ms,
                },
            )

        except Exception:
            auto_sending_logger.exception("auto_sending_tick failed")
        finally:
            await session.close()


async def _has_undelivered_recipients(
    session: AsyncSession,
    auto_sending: AutoSending,
    schedule_event_id: int,
) -> bool:
    """Check if there is at least one undelivered recipient.

    Returns True if there exists a user with a PAID/APPROVED ticket for the
    schedule event who does not yet have a delivery record for this auto_sending.
    Returns False if all ticket owners are already delivered (or no tickets exist).
    """
    from sqlalchemy import exists

    dedup_key = f"se:{schedule_event_id}"
    stmt = (
        select(Ticket)
        .join(UserTicket, UserTicket.ticket_id == Ticket.id)
        .where(
            Ticket.schedule_event_id == schedule_event_id,
            Ticket.status.in_([TicketStatus.PAID, TicketStatus.APPROVED]),
            ~exists(
                select(AutoSendingDelivery.id)
                .where(
                    AutoSendingDelivery.auto_sending_id == auto_sending.id,
                    AutoSendingDelivery.user_id == UserTicket.user_id,
                    AutoSendingDelivery.dedup_key == dedup_key,
                )
            ),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first() is not None


async def _dispatch_for_event(
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    auto_sending: AutoSending,
    schedule_event: ScheduleEvent,
) -> dict | None:
    """Resolve recipients for a single schedule event and dispatch.

    Returns the dispatch stats dict, or None if no recipients.
    """
    now = datetime.now(tz=MOSCOW_TZ)
    selector = RECIPIENT_SELECTORS.get(auto_sending.trigger)
    if not selector:
        auto_sending_logger.warning(
            f"No selector for trigger {auto_sending.trigger}")
        return None

    recipients = await selector(session, auto_sending, now)

    # Filter recipients to only those for this specific schedule event.
    recipients = [r for r in recipients if r.schedule_event_id == schedule_event.id]

    if recipients:
        return await dispatch_auto_sending(context, session, auto_sending, recipients)
    return None


async def _precise_dispatch_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback for precise run_once jobs — loads data and dispatches."""
    from utilities.utl_db import open_session

    auto_sending_id = context.job.data["auto_sending_id"]
    schedule_event_id = context.job.data["schedule_event_id"]

    session = await open_session(context.config)
    try:
        auto_sending = await db_postgres.get_auto_sending_by_id(
            session, auto_sending_id)
        if not auto_sending or not auto_sending.is_active:
            return

        schedule_event = await db_postgres.get_schedule_event(
            session, schedule_event_id)
        if not schedule_event:
            return

        await _dispatch_for_event(context, session, auto_sending, schedule_event)
    except Exception:
        auto_sending_logger.exception(
            f"_precise_dispatch_job failed for "
            f"auto_sending={auto_sending_id}, se={schedule_event_id}")
    finally:
        await session.close()

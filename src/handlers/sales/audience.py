"""SQL queries for audience selection in sales campaigns."""
from datetime import datetime, timezone, timedelta, date
from typing import Dict, List

import sqlalchemy as sa

from db import Ticket, ScheduleEvent, User, TheaterEvent
from db.enum import TicketStatus, AgeType
from db.models import UserTicket, Person, Child, PersonTicket

from .states import TZ, _round_half_to_even


async def _select_audience_rows(session, theater_event_ids: List[int]) -> List[tuple]:
    """Return the list of (user_id, chat_id) for users who attended in the current year
    for any of the given theater_event_ids.
    """
    if not theater_event_ids:
        return []
    now = datetime.now(timezone.utc)
    start_period = now - timedelta(days=365)

    t = Ticket.__table__
    ut = UserTicket.__table__
    u = User.__table__
    se = ScheduleEvent.__table__

    statuses = [TicketStatus.PAID, TicketStatus.APPROVED]

    stmt = (
        sa.select(u.c.user_id, u.c.chat_id)
        .select_from(ut
                     .join(t, ut.c.ticket_id == t.c.id)
                     .join(u, ut.c.user_id == u.c.user_id)
                     .join(se, t.c.schedule_event_id == se.c.id))
        .where(t.c.status.in_(statuses))
        .where(se.c.theater_event_id.in_(list(map(int, theater_event_ids))))
        .where(se.c.datetime_event >= start_period)
        .where(se.c.datetime_event < now)
        .where(u.c.chat_id.isnot(None))
    )
    rows = (await session.execute(stmt)).all()
    seen = set()
    result = []
    for user_id, chat_id in rows:
        if chat_id in seen:
            continue
        seen.add(chat_id)
        result.append((user_id, chat_id))
    return result


async def _select_ticket_holders_audience(session, sales_state: dict) -> tuple[List[tuple], List[int]]:
    """Return the list of (user_id, chat_id) and the list of ticket_ids."""
    filters = sales_state.get('filters', {})
    f_time = sales_state.get('f_schedule_time', 'future')
    f_show = sales_state.get('f_schedule_show', 'on')
    now = datetime.now(timezone.utc)

    t = Ticket.__table__
    ut = UserTicket.__table__
    u = User.__table__
    se = ScheduleEvent.__table__

    stmt = (
        sa.select(u.c.user_id, u.c.chat_id, t.c.id)
        .select_from(ut
                     .join(t, ut.c.ticket_id == t.c.id)
                     .join(u, ut.c.user_id == u.c.user_id)
                     .join(se, t.c.schedule_event_id == se.c.id))
        .where(u.c.chat_id.isnot(None))
    )

    if filters.get('ticket_ids'):
        stmt = stmt.where(t.c.id.in_(list(map(int, filters['ticket_ids']))))
    else:
        if filters.get('status'):
            status_members = []
            for val in filters['status']:
                for member in TicketStatus:
                    if member.value == val:
                        status_members.append(member)
                        break
            if status_members:
                stmt = stmt.where(t.c.status.in_(status_members))

        has_event_filter = False
        if filters.get('type_event_ids'):
            stmt = stmt.where(se.c.type_event_id.in_(list(map(int, filters['type_event_ids']))))
            has_event_filter = True

        if filters.get('theater_event_ids'):
            stmt = stmt.where(se.c.theater_event_id.in_(list(map(int, filters['theater_event_ids']))))
            has_event_filter = True

        if filters.get('schedule_event_ids'):
            stmt = stmt.where(t.c.schedule_event_id.in_(list(map(int, filters['schedule_event_ids']))))
            has_event_filter = True

        if not has_event_filter:
            if f_time == 'past':
                stmt = stmt.where(se.c.datetime_event < now)
            elif f_time == 'future':
                stmt = stmt.where(se.c.datetime_event >= now)
            if f_show == 'on':
                stmt = stmt.where(se.c.flag_turn_in_bot == True)
            elif f_show == 'off':
                stmt = stmt.where(se.c.flag_turn_in_bot == False)

        if filters.get('base_ticket_ids'):
            stmt = stmt.where(t.c.base_ticket_id.in_(list(map(int, filters['base_ticket_ids']))))

        child_age_min = filters.get('child_age_min')
        child_age_max = filters.get('child_age_max')
        if child_age_min is not None or child_age_max is not None:
            pt = PersonTicket.__table__
            p = Person.__table__
            c = Child.__table__
            computed_age = sa.case(
                (c.c.birthdate.isnot(None), sa.func.date_part('year', sa.func.age(c.c.birthdate))),
                else_=c.c.age
            )
            child_subq_stmt = (
                sa.select(sa.literal(1))
                .select_from(pt.join(p, pt.c.person_id == p.c.id).join(c, c.c.person_id == p.c.id))
                .where(pt.c.ticket_id == t.c.id)
                .where(p.c.age_type == AgeType.child)
            )
            if child_age_min is not None:
                child_subq_stmt = child_subq_stmt.where(computed_age >= child_age_min)
            if child_age_max is not None:
                child_subq_stmt = child_subq_stmt.where(computed_age <= child_age_max)
            stmt = stmt.where(child_subq_stmt.exists())

    rows = (await session.execute(stmt)).all()

    seen = set()
    result_rows = []
    found_ticket_ids = []

    for user_id, chat_id, ticket_id in rows:
        found_ticket_ids.append(ticket_id)
        if chat_id in seen:
            continue
        seen.add(chat_id)
        result_rows.append((user_id, chat_id))

    return result_rows, sorted(list(set(found_ticket_ids)))


async def _select_season_audience(session, sales_state: dict) -> List[tuple]:
    """Return list of (user_id, chat_id) for SEASON_TICKET_HOLDERS broadcast."""
    season_start: date | None = sales_state.get('season_start')
    season_end: date | None = sales_state.get('season_end')
    theater_ids = sales_state.get('season_theater_ids') or []
    child_age_min = sales_state.get('child_age_min')
    child_age_max = sales_state.get('child_age_max')
    status_values = sales_state.get('season_statuses') or []

    t = Ticket.__table__
    ut = UserTicket.__table__
    u = User.__table__
    se = ScheduleEvent.__table__

    if status_values:
        ticket_statuses = []
        for val in status_values:
            for member in TicketStatus:
                if member.value == val:
                    ticket_statuses.append(member)
                    break
    else:
        ticket_statuses = None

    stmt = (
        sa.select(u.c.user_id, u.c.chat_id)
        .select_from(ut
                     .join(t, ut.c.ticket_id == t.c.id)
                     .join(u, ut.c.user_id == u.c.user_id)
                     .join(se, t.c.schedule_event_id == se.c.id))
        .where(u.c.chat_id.isnot(None))
    )

    if season_start is not None and season_end is not None:
        period_start = datetime.combine(season_start, datetime.min.time(), tzinfo=timezone.utc)
        period_end = datetime.combine(season_end, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
        stmt = stmt.where(se.c.datetime_event >= period_start)
        stmt = stmt.where(se.c.datetime_event < period_end)

    if ticket_statuses:
        stmt = stmt.where(t.c.status.in_(ticket_statuses))

    if theater_ids:
        stmt = stmt.where(se.c.theater_event_id.in_(list(map(int, theater_ids))))

    age_filter_active = child_age_min is not None or child_age_max is not None
    if age_filter_active:
        pt = PersonTicket.__table__
        p = Person.__table__
        c = Child.__table__
        rounded_age = sa.func.round(c.c.age)
        child_subq = (
            sa.select(sa.literal(1))
            .select_from(pt.join(p, pt.c.person_id == p.c.id)
                        .join(c, c.c.person_id == p.c.id))
            .where(pt.c.ticket_id == t.c.id)
            .where(p.c.age_type == AgeType.child)
            .where(c.c.age.isnot(None))
        )
        if child_age_min is not None:
            child_subq = child_subq.where(rounded_age >= child_age_min)
        if child_age_max is not None:
            child_subq = child_subq.where(rounded_age <= child_age_max)
        stmt = stmt.where(child_subq.exists())

    rows = (await session.execute(stmt)).all()
    seen = set()
    result = []
    for user_id, chat_id in rows:
        if chat_id in seen:
            continue
        seen.add(chat_id)
        result.append((user_id, chat_id))
    return result


async def _get_available_schedules(session, theater_id: int):
    now = datetime.now(timezone.utc)
    se = ScheduleEvent.__table__
    te = TheaterEvent.__table__
    stmt = (
        sa.select(se)
        .join(te, se.c.theater_event_id == te.c.id)
        .where(se.c.theater_event_id == int(theater_id))
        .where(se.c.flag_turn_in_bot == True)
        .where(te.c.flag_active_repertoire == True)
        .where(se.c.datetime_event > now)
        .order_by(se.c.datetime_event.asc())
    )
    return (await session.execute(stmt)).mappings().all()


async def _availability_block(session, schedule_ids: List[int]) -> str:
    from db.sales_crud import get_free_places
    from settings.settings import DICT_CONVERT_WEEKDAY_NUMBER_TO_STR

    if not schedule_ids:
        return ''
    free = await get_free_places(session, schedule_ids)
    if not free:
        return ''

    now = datetime.now(timezone.utc)
    rows = (await session.execute(
        sa.select(ScheduleEvent.id, ScheduleEvent.datetime_event)
        .where(ScheduleEvent.id.in_(list(map(int, schedule_ids))))
        .where(ScheduleEvent.datetime_event > now)
        .order_by(ScheduleEvent.datetime_event)
    )).all()

    # Only show sessions with at least 1 free children's seat.
    # The campaign is for children, so adult-only seats are irrelevant.
    valid_rows = []
    for sid, dt in rows:
        fc, fa = free.get(int(sid), (0, 0))
        if fc >= 1:
            valid_rows.append((sid, dt))

    if not valid_rows:
        return ''

    lines = ['Кол-во свободных мест:', '⬇️Дата Время — Детских | Взрослых⬇️']
    for sid, dt in valid_rows:
        dt_local = dt.astimezone(TZ)
        weekday = int(dt_local.strftime('%w'))
        date_txt = dt_local.strftime('%d.%m ')
        time_txt = dt_local.strftime('%H:%M')
        fc, fa = free.get(int(sid), (0, 0))
        lines.append(
            f"{date_txt}({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]}) {time_txt} — {fc} дет | {fa} взр")
    # Use <br> for HTML storage so sulguk.transform_html() converts them
    # back to \n in the final Telegram text. Bare \n are ignored in HTML.
    return '<br>'.join(lines)

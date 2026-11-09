"""CRUD stubs for sales feature (no migrations yet).
Actual implementations will be filled in subsequent steps.
"""
from __future__ import annotations
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.enum import TicketStatus
from db.models import SalesCampaign, SalesCampaignSchedule, SalesRecipient, ScheduleEvent, Ticket, BaseTicket


async def create_campaign(session: AsyncSession, *,
                          created_by_admin_id: int,
                          campaign_type: str,
                          theater_event_id: Optional[int],
                          title: str,
                          status: str = 'draft') -> SalesCampaign:
    campaign = SalesCampaign(
        created_by_admin_id=created_by_admin_id,
        type=campaign_type,
        theater_event_id=theater_event_id,
        title=title,
        status=status,
    )
    session.add(campaign)
    await session.flush()
    return campaign


async def set_campaign_schedules(session: AsyncSession, campaign_id: int, schedule_ids: Iterable[int]) -> None:
    # Clear existing
    await session.execute(delete(SalesCampaignSchedule).where(SalesCampaignSchedule.campaign_id == campaign_id))
    # Insert unique
    uniq = set(int(sid) for sid in schedule_ids)
    for sid in uniq:
        session.add(SalesCampaignSchedule(campaign_id=campaign_id, schedule_event_id=sid))
    await session.flush()


async def set_campaign_status(session: AsyncSession, campaign_id: int, status: str) -> None:
    campaign = await session.get(SalesCampaign, campaign_id)
    if campaign:
        campaign.status = status
        await session.flush()


async def update_campaign_message(session: AsyncSession, campaign_id: int, **fields) -> None:
    campaign = await session.get(SalesCampaign, campaign_id)
    if not campaign:
        return
    for k, v in fields.items():
        if hasattr(campaign, k):
            setattr(campaign, k, v)
    await session.flush()


async def snapshot_recipients(session: AsyncSession, campaign_id: int, rows: Iterable[Tuple[Optional[int], int]]) -> int:
    """Insert recipients snapshot.
    rows: iterable of tuples (user_id, chat_id)
    Returns count inserted.
    """
    uniq = set()
    count = 0
    for user_id, chat_id in rows:
        key = int(chat_id)
        if key in uniq:
            continue
        uniq.add(key)
        session.add(SalesRecipient(campaign_id=campaign_id,
                                   user_id=user_id,
                                   chat_id=chat_id,
                                   status='pending'))
        count += 1
    await session.flush()
    return count


async def iter_recipients_for_send(session: AsyncSession, campaign_id: int, batch_size: int = 200) -> List[SalesRecipient]:
    q = select(SalesRecipient).where(SalesRecipient.campaign_id == campaign_id, SalesRecipient.status == 'pending').limit(batch_size)
    res = (await session.execute(q)).scalars().all()
    return res


async def mark_recipient_status(session: AsyncSession, recipient_id: int, status: str, last_error: Optional[str] = None) -> None:
    r = await session.get(SalesRecipient, recipient_id)
    if r:
        r.status = status
        r.last_error = last_error
        await session.flush()


async def get_recent_campaigns(session: AsyncSession, limit: int = 10) -> List[SalesCampaign]:
    """Get recent campaigns that can be resumed (draft, running, canceled)."""
    stmt = (
        select(SalesCampaign)
        .where(SalesCampaign.status.in_(['draft', 'running', 'canceled']))
        .order_by(SalesCampaign.id.desc())
        .limit(limit)
    )
    result = (await session.execute(stmt)).scalars().all()
    return list(result)


async def get_campaign_with_schedules(session: AsyncSession, campaign_id: int):
    """Get campaign with its schedules loaded."""
    from sqlalchemy.orm import selectinload
    stmt = (
        select(SalesCampaign)
        .options(selectinload(SalesCampaign.schedules))
        .where(SalesCampaign.id == campaign_id)
    )
    result = (await session.execute(stmt)).scalars().first()
    return result


async def delete_campaign(session: AsyncSession, campaign_id: int) -> bool:
    """Delete a campaign and all related schedules and recipients (CASCADE)."""
    campaign = await session.get(SalesCampaign, campaign_id)
    if campaign:
        await session.delete(campaign)
        await session.flush()
        return True
    return False


async def get_recipient_counts(session: AsyncSession, campaign_id: int) -> Tuple[int, int]:
    """Return (total_recipients, pending_recipients) for a campaign."""
    total = (await session.execute(
        select(func.count()).select_from(SalesRecipient).where(
            SalesRecipient.campaign_id == campaign_id
        )
    )).scalar() or 0
    pending = (await session.execute(
        select(func.count()).select_from(SalesRecipient).where(
            SalesRecipient.campaign_id == campaign_id,
            SalesRecipient.status == 'pending'
        )
    )).scalar() or 0
    return total, pending


async def get_free_places(session: AsyncSession, schedule_ids: List[int]):
    """Return mapping schedule_id -> (free_child, free_adult).
    Accurate calculation based on tickets: free = total - taken, clamped to 0.
    taken_child = SUM(BaseTicket.quality_of_children) over PAID/APPROVED tickets
    taken_adult = SUM(BaseTicket.quality_of_adult + BaseTicket.quality_of_add_adult)
    """
    if not schedule_ids:
        return {}

    ids = list({int(s) for s in schedule_ids})

    # Aggregate taken seats per schedule from tickets joined to base tickets
    agg = (
        select(
            Ticket.schedule_event_id.label('sid'),
            func.coalesce(func.sum(BaseTicket.quality_of_children), 0).label('taken_child'),
            func.coalesce(func.sum(BaseTicket.quality_of_adult + BaseTicket.quality_of_add_adult), 0).label('taken_adult'),
        )
        .join(BaseTicket, BaseTicket.base_ticket_id == Ticket.base_ticket_id)
        .where(Ticket.schedule_event_id.in_(ids))
        .where(Ticket.status.in_([TicketStatus.PAID, TicketStatus.APPROVED]))
        .group_by(Ticket.schedule_event_id)
        .subquery()
    )

    q = (
        select(
            ScheduleEvent.id,
            func.greatest(
                ScheduleEvent.qty_child - func.coalesce(agg.c.taken_child, 0), 0
            ).label('free_child'),
            func.greatest(
                ScheduleEvent.qty_adult - func.coalesce(agg.c.taken_adult, 0), 0
            ).label('free_adult'),
        )
        .outerjoin(agg, agg.c.sid == ScheduleEvent.id)
        .where(ScheduleEvent.id.in_(ids))
    )

    rows = (await session.execute(q)).all()
    result = {}
    for sid, free_child, free_adult in rows:
        fc = max(int(free_child or 0), 0)
        fa = max(int(free_adult or 0), 0)
        result[int(sid)] = (fc, fa)
    return result

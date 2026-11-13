"""Tests for cascade deletion of SalesCampaign (schedules and recipients)."""
import asyncio
from datetime import datetime

from sqlalchemy import select, func

from db.models import (
    SalesCampaign,
    SalesCampaignSchedule,
    SalesRecipient,
    ScheduleEvent,
    TheaterEvent,
    TypeEvent,
    Place,
)
from db import sales_crud
from conftest import AsyncSessionWrapper, _run_with_db


def test_delete_campaign_cascades_to_schedules_and_recipients():
    """Deleting a campaign must cascade-delete all related schedules and recipients."""

    async def run(session: AsyncSessionWrapper):
        # --- Setup: create supporting records ---
        te = TheaterEvent(id=1, name="Колобок", flag_active_bd=True)
        tpe = TypeEvent(id=1, name="Репертуарные", name_alias="repertoire")
        pl = Place(id=1, name="Основная сцена", address="ул. Примерная, 1")
        session.add_all([te, tpe, pl])
        await session.flush()

        se = ScheduleEvent(
            id=1, type_event_id=1, theater_event_id=1, place_id=1,
            datetime_event=datetime.now(),
            qty_child=10, qty_adult=10,
        )
        session.add(se)
        await session.flush()

        # --- Create campaign with schedules and recipients ---
        campaign = SalesCampaign(
            id=1,
            created_by_admin_id=100,
            type="promo",
            theater_event_id=1,
            title="Test campaign",
        )
        session.add(campaign)
        await session.flush()

        session.add(SalesCampaignSchedule(
            id=1, campaign_id=campaign.id, schedule_event_id=1
        ))
        session.add_all([
            SalesRecipient(id=1, campaign_id=campaign.id, user_id=1001, chat_id=2001, status="pending"),
            SalesRecipient(id=2, campaign_id=campaign.id, user_id=1002, chat_id=2002, status="pending"),
            SalesRecipient(id=3, campaign_id=campaign.id, user_id=1003, chat_id=2003, status="pending"),
        ])
        await session.commit()

        # --- Verify data exists ---
        total, _ = await sales_crud.get_recipient_counts(session, campaign.id)
        assert total == 3

        sched_count = (await session.execute(
            select(func.count()).select_from(SalesCampaignSchedule)
            .where(SalesCampaignSchedule.campaign_id == campaign.id)
        )).scalar()
        assert sched_count == 1

        # --- Delete campaign ---
        deleted = await sales_crud.delete_campaign(session, campaign.id)
        assert deleted is True

        # --- Verify cascade: schedules and recipients are gone ---
        remaining_campaign = await session.get(SalesCampaign, campaign.id)
        assert remaining_campaign is None

        remaining_schedules = (await session.execute(
            select(func.count()).select_from(SalesCampaignSchedule)
            .where(SalesCampaignSchedule.campaign_id == campaign.id)
        )).scalar()
        assert remaining_schedules == 0

        remaining_recipients = (await session.execute(
            select(func.count()).select_from(SalesRecipient)
            .where(SalesRecipient.campaign_id == campaign.id)
        )).scalar()
        assert remaining_recipients == 0

    asyncio.run(_run_with_db(run))


def test_delete_nonexistent_campaign_returns_false():
    """Deleting a campaign that does not exist should return False."""

    async def run(session: AsyncSessionWrapper):
        deleted = await sales_crud.delete_campaign(session, 99999)
        assert deleted is False

    asyncio.run(_run_with_db(run))


def test_delete_campaign_only_deletes_its_own_related_records():
    """Deleting one campaign should not affect another campaign's data."""

    async def run(session: AsyncSessionWrapper):
        # --- Setup shared schedule event ---
        te = TheaterEvent(id=1, name="Колобок", flag_active_bd=True)
        tpe = TypeEvent(id=1, name="Репертуарные", name_alias="repertoire")
        pl = Place(id=1, name="Основная сцена", address="ул. Примерная, 1")
        session.add_all([te, tpe, pl])
        await session.flush()

        se = ScheduleEvent(
            id=1, type_event_id=1, theater_event_id=1, place_id=1,
            datetime_event=datetime.now(),
            qty_child=10, qty_adult=10,
        )
        session.add(se)
        await session.flush()

        # --- Create two campaigns ---
        campaign_a = SalesCampaign(
            id=1, created_by_admin_id=100, type="promo",
            theater_event_id=1, title="Campaign A",
        )
        campaign_b = SalesCampaign(
            id=2, created_by_admin_id=100, type="promo",
            theater_event_id=1, title="Campaign B",
        )
        session.add_all([campaign_a, campaign_b])
        await session.flush()

        session.add_all([
            SalesCampaignSchedule(id=1, campaign_id=campaign_a.id, schedule_event_id=1),
            SalesCampaignSchedule(id=2, campaign_id=campaign_b.id, schedule_event_id=1),
            SalesRecipient(id=1, campaign_id=campaign_a.id, user_id=1001, chat_id=2001, status="pending"),
            SalesRecipient(id=2, campaign_id=campaign_b.id, user_id=1002, chat_id=2002, status="pending"),
            SalesRecipient(id=3, campaign_id=campaign_b.id, user_id=1003, chat_id=2003, status="pending"),
        ])
        await session.commit()

        # --- Delete campaign A ---
        await sales_crud.delete_campaign(session, campaign_a.id)

        # --- Campaign B and its data must remain intact ---
        remaining_b = await session.get(SalesCampaign, campaign_b.id)
        assert remaining_b is not None

        total_b, _ = await sales_crud.get_recipient_counts(session, campaign_b.id)
        assert total_b == 2

        sched_b = (await session.execute(
            select(func.count()).select_from(SalesCampaignSchedule)
            .where(SalesCampaignSchedule.campaign_id == campaign_b.id)
        )).scalar()
        assert sched_b == 1

    asyncio.run(_run_with_db(run))

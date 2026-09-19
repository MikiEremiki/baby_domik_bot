import asyncio
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from db import db_postgres
from db.models import BaseModel, ScheduleEvent, ScheduleChange, BaseTicket, TypeEvent, TheaterEvent, Place
from db.enum import TicketPriceType
from utilities.utl_schedule_changes import (
    normalize_schedule_snapshot,
    compute_schedule_diff,
    TRACKED_SCHEDULE_FIELDS,
    EXPORTABLE_SCHEDULE_FIELDS,
)


class AsyncSessionWrapper:
    def __init__(self, sync_session: Session):
        self._session = sync_session

    async def execute(self, statement, *args, **kwargs):
        return self._session.execute(statement, *args, **kwargs)

    async def get(self, entity, ident, *args, **kwargs):
        return self._session.get(entity, ident, *args, **kwargs)

    async def merge(self, instance, *args, **kwargs):
        return self._session.merge(instance, *args, **kwargs)

    async def commit(self):
        return self._session.commit()

    async def flush(self):
        return self._session.flush()

    async def refresh(self, instance):
        return self._session.refresh(instance)

    async def rollback(self):
        return self._session.rollback()

    def add(self, instance):
        self._session.add(instance)

    def add_all(self, instances):
        self._session.add_all(instances)


async def _run_with_db(test_coro):
    engine = create_engine("sqlite:///:memory:", echo=False)
    BaseModel.metadata.create_all(engine)

    sync_maker = sessionmaker(bind=engine, expire_on_commit=False)
    with sync_maker() as session:
        wrapped = AsyncSessionWrapper(session)
        await test_coro(wrapped)

    engine.dispose()


def test_snapshot_and_diff_normalization():
    before = {
        'id': 1,
        'type_event_id': 1,
        'theater_event_id': 2,
        'place_id': None,
        'flag_turn_in_bot': False,
        'datetime_event': '2026-10-15T11:00:00',
        'qty_child': 5,
        'qty_adult': 5,
        'flag_gift': False,
        'flag_christmas_tree': False,
        'flag_santa': False,
        'ticket_price_type': 'none',
        'base_ticket_ids': [10, 20],
    }

    after = {
        'id': 1,
        'type_event_id': 1,
        'theater_event_id': 2,
        'place_id': 2,
        'flag_turn_in_bot': True,
        'datetime_event': '2026-10-15T12:00:00',
        'qty_child': 6,
        'qty_adult': 5,
        'flag_gift': True,
        'flag_christmas_tree': False,
        'flag_santa': False,
        'ticket_price_type': 'indiv',
        'base_ticket_ids': [10, 20, 30],
    }

    norm_before = normalize_schedule_snapshot(before)
    norm_after = normalize_schedule_snapshot(after)

    changed_fields, diff = compute_schedule_diff(norm_before, norm_after)
    assert set(changed_fields) == {
        'place_id', 'flag_turn_in_bot', 'datetime_event', 'qty_child',
        'flag_gift', 'ticket_price_type', 'base_ticket_ids'
    }
    assert diff['place_id'] == {'before': None, 'after': 2}
    assert diff['flag_turn_in_bot'] == {'before': False, 'after': True}
    assert diff['qty_child'] == {'before': 5, 'after': 6}
    assert diff['flag_gift'] == {'before': False, 'after': True}
    assert diff['base_ticket_ids'] == {'before': [10, 20], 'after': [10, 20, 30]}


def test_create_schedule_event_records_change():
    async def run(session: AsyncSessionWrapper):
        # Create base entities
        te = TypeEvent(id=1, name='Спектакль', name_alias='show')
        th = TheaterEvent(id=10, name='Колобок', flag_active_repertoire=True)
        session.add_all([te, th])
        await session.flush()

        event = await db_postgres.create_schedule_event(
            session,
            schedule_event_id=1,
            type_event_id=1,
            theater_event_id=10,
            flag_turn_in_bot=True,
            datetime_event=datetime(2026, 11, 1, 11, 0),
            qty_child=8,
            qty_adult=8,
            flag_gift=True,
            author_id=12345,
            author_name='admin_test',
            source='schedule_hl',
            operation_key='op_create_1',
            auto_commit=True
        )

        assert event.id is not None
        assert event.qty_child_free_seat == 8

        # Check ScheduleChange
        changes = (await session.execute(
            db_postgres.select(ScheduleChange).where(ScheduleChange.schedule_event_id == event.id)
        )).scalars().all()

        assert len(changes) == 1
        ch = changes[0]
        assert ch.operation_type == 'create'
        assert ch.author_id == 12345
        assert ch.author_name == 'admin_test'
        assert ch.source == 'schedule_hl'
        assert ch.operation_key == 'op_create_1'
        assert ch.snapshot_before is None
        assert ch.snapshot_after['qty_child'] == 8
        assert ch.snapshot_after['flag_gift'] is True
        assert ch.report_status == 'pending'
        assert ch.sync_status == 'pending'

    asyncio.run(_run_with_db(run))


def test_create_schedule_event_idempotency_via_operation_key():
    async def run(session: AsyncSessionWrapper):
        te = TypeEvent(id=1, name='Спектакль', name_alias='show')
        th = TheaterEvent(id=10, name='Колобок', flag_active_repertoire=True)
        session.add_all([te, th])
        await session.flush()

        ev1 = await db_postgres.create_schedule_event(
            session,
            schedule_event_id=1,
            type_event_id=1,
            theater_event_id=10,
            flag_turn_in_bot=True,
            datetime_event=datetime(2026, 11, 1, 11, 0),
            operation_key='idempotent_key_123',
            auto_commit=True
        )

        # Calling again with same key returns existing event
        ev2 = await db_postgres.create_schedule_event(
            session,
            schedule_event_id=1,
            type_event_id=1,
            theater_event_id=10,
            flag_turn_in_bot=True,
            datetime_event=datetime(2026, 11, 1, 11, 0),
            operation_key='idempotent_key_123',
            auto_commit=True
        )

        assert ev1.id == ev2.id

        changes = (await session.execute(
            db_postgres.select(ScheduleChange).where(ScheduleChange.operation_key == 'idempotent_key_123')
        )).scalars().all()
        assert len(changes) == 1

    asyncio.run(_run_with_db(run))


def test_update_schedule_event_records_diff_and_ignores_noop():
    async def run(session: AsyncSessionWrapper):
        te = TypeEvent(id=1, name='Спектакль', name_alias='show')
        th = TheaterEvent(id=10, name='Колобок', flag_active_repertoire=True)
        p = Place(id=2, name='Новая сцена', address='ул. Пушкина')
        bt1 = BaseTicket(base_ticket_id=100, name='1+1', cost_main=1000, cost_privilege=1000, cost_main_in_period=1000, cost_privilege_in_period=1000, quality_of_children=1, quality_of_adult=1, quality_of_add_adult=0, quality_visits=1)
        bt2 = BaseTicket(base_ticket_id=200, name='2+2', cost_main=2000, cost_privilege=2000, cost_main_in_period=2000, cost_privilege_in_period=2000, quality_of_children=2, quality_of_adult=2, quality_of_add_adult=0, quality_visits=1)
        session.add_all([te, th, p, bt1, bt2])
        await session.flush()

        event = await db_postgres.create_schedule_event(
            session,
            schedule_event_id=1,
            type_event_id=1,
            theater_event_id=10,
            flag_turn_in_bot=False,
            datetime_event=datetime(2026, 11, 1, 11, 0),
            qty_child=5,
            qty_adult=5,
            base_ticket_ids=[100],
            record_change=True,
            auto_commit=True
        )

        # 1. Update event
        updated_event = await db_postgres.update_schedule_event(
            session,
            schedule_event_id=event.id,
            qty_child=10,
            flag_turn_in_bot=True,
            place_id=2,
            base_ticket_ids=[100, 200],
            author_id=999,
            author_name='editor',
            source='schedule_hl',
            auto_commit=True
        )
        assert updated_event.qty_child == 10
        assert updated_event.place_id == 2

        changes = (await session.execute(
            db_postgres.select(ScheduleChange)
            .where(ScheduleChange.schedule_event_id == event.id)
            .order_by(ScheduleChange.id.asc())
        )).scalars().all()

        assert len(changes) == 2
        update_ch = changes[1]
        assert update_ch.operation_type == 'update'
        assert set(update_ch.changed_fields) == {'qty_child', 'flag_turn_in_bot', 'place_id', 'base_ticket_ids'}
        assert update_ch.snapshot_before['qty_child'] == 5
        assert update_ch.snapshot_after['qty_child'] == 10
        assert update_ch.snapshot_before['base_ticket_ids'] == [100]
        assert update_ch.snapshot_after['base_ticket_ids'] == [100, 200]

        # 2. No-op update (saving same data again) -> should not produce another change record
        await db_postgres.update_schedule_event(
            session,
            schedule_event_id=event.id,
            qty_child=10,
            flag_turn_in_bot=True,
            place_id=2,
            base_ticket_ids=[100, 200],
            author_id=999,
            author_name='editor',
            source='schedule_hl',
            auto_commit=True
        )

        changes_after_noop = (await session.execute(
            db_postgres.select(ScheduleChange)
            .where(ScheduleChange.schedule_event_id == event.id)
        )).scalars().all()
        assert len(changes_after_noop) == 2

    asyncio.run(_run_with_db(run))

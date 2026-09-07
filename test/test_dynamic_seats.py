import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from db.models import (
    BaseModel,
    ScheduleEvent,
    BaseTicket,
    Ticket,
)
from db.enum import TicketStatus
from db.db_postgres import (
    get_schedule_event_available_seats,
    get_schedule_events_with_seats,
    populate_schedule_events_seats,
)
from api.googlesheets import _write_data_to_batch_update


class AsyncSessionWrapper:
    def __init__(self, sync_session: Session):
        self._session = sync_session

    async def execute(self, statement, *args, **kwargs):
        return self._session.execute(statement, *args, **kwargs)

    async def get(self, entity, ident, *args, **kwargs):
        return self._session.get(entity, ident, *args, **kwargs)

    async def commit(self):
        return self._session.commit()

    async def flush(self):
        return self._session.flush()

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


def test_dynamic_seats_empty_schedule():
    async def run(session: AsyncSessionWrapper):
        se = ScheduleEvent(
            id=1,
            type_event_id=1,
            theater_event_id=1,
            datetime_event=datetime(2030, 5, 1, 12, 0, tzinfo=timezone.utc),
            qty_child=10,
            qty_adult=8,
            flag_turn_in_bot=True,
        )
        session.add(se)
        await session.commit()

        seats = await get_schedule_event_available_seats(session, 1)
        assert seats['total_child'] == 10
        assert seats['total_adult'] == 8
        assert seats['occupied_child'] == 0
        assert seats['occupied_adult'] == 0
        assert seats['free_child'] == 10
        assert seats['free_adult'] == 8
        assert seats['nonconfirm_child'] == 0
        assert seats['nonconfirm_adult'] == 0

    asyncio.run(_run_with_db(run))


def test_dynamic_seats_with_paid_and_created_tickets():
    async def run(session: AsyncSessionWrapper):
        now = datetime.now(timezone.utc)

        se = ScheduleEvent(
            id=2,
            type_event_id=1,
            theater_event_id=1,
            datetime_event=datetime(2030, 5, 1, 12, 0, tzinfo=timezone.utc),
            qty_child=10,
            qty_adult=10,
            flag_turn_in_bot=True,
        )
        bt = BaseTicket(
            base_ticket_id=1,
            name="1+1+1",
            quality_of_children=1,
            quality_of_adult=1,
            quality_of_add_adult=1,
            quality_visits=1,
            cost_main=1000,
            cost_privilege=1000,
            cost_main_in_period=1000,
            cost_privilege_in_period=1000,
        )
        session.add_all([se, bt])
        await session.commit()

        # 1) Оплаченный билет (1 ребенок, 2 взрослых)
        t1 = Ticket(
            id=101,
            base_ticket_id=1,
            schedule_event_id=2,
            price=1000,
            status=TicketStatus.PAID,
            created_at=now - timedelta(minutes=30),
        )
        # 2) Свежесозданный билет (1 ребено��, 2 взрослых) - удерживает места
        t2 = Ticket(
            id=102,
            base_ticket_id=1,
            schedule_event_id=2,
            price=1000,
            status=TicketStatus.CREATED,
            created_at=now - timedelta(minutes=3),
        )
        # 3) Просроченный CREATED билет (> 10 минут) - НЕ должен удерживать места
        t3 = Ticket(
            id=103,
            base_ticket_id=1,
            schedule_event_id=2,
            price=1000,
            status=TicketStatus.CREATED,
            created_at=now - timedelta(minutes=15),
        )
        # 4) Отмененный билет - НЕ должен удерживать места
        t4 = Ticket(
            id=104,
            base_ticket_id=1,
            schedule_event_id=2,
            price=1000,
            status=TicketStatus.CANCELED,
            created_at=now - timedelta(minutes=2),
        )
        # 5) Возвращенный билет - НЕ должен удерживать места
        t5 = Ticket(
            id=105,
            base_ticket_id=1,
            schedule_event_id=2,
            price=1000,
            status=TicketStatus.REFUNDED,
            created_at=now - timedelta(minutes=2),
        )
        session.add_all([t1, t2, t3, t4, t5])
        await session.commit()

        seats = await get_schedule_event_available_seats(session, 2)
        # Активны t1 (PAID) и t2 (CREATED <= 10m):
        # t1: 1 ребенок, 2 взрослых
        # t2: 1 ребенок, 2 взрослых
        # Итого занято: 2 ребенка, 4 взрослых
        assert seats['total_child'] == 10
        assert seats['total_adult'] == 10
        assert seats['occupied_child'] == 2
        assert seats['occupied_adult'] == 4
        assert seats['free_child'] == 8
        assert seats['free_adult'] == 6
        assert seats['nonconfirm_child'] == 1
        assert seats['nonconfirm_adult'] == 2

    asyncio.run(_run_with_db(run))


def test_dynamic_seats_batch_and_populate():
    async def run(session: AsyncSessionWrapper):
        now = datetime.now(timezone.utc)

        se1 = ScheduleEvent(
            id=10,
            type_event_id=1,
            theater_event_id=1,
            datetime_event=datetime(2030, 5, 1, 10, 0, tzinfo=timezone.utc),
            qty_child=5,
            qty_adult=5,
            flag_turn_in_bot=True,
        )
        se2 = ScheduleEvent(
            id=11,
            type_event_id=1,
            theater_event_id=1,
            datetime_event=datetime(2030, 5, 1, 14, 0, tzinfo=timezone.utc),
            qty_child=8,
            qty_adult=8,
            flag_turn_in_bot=True,
        )
        bt = BaseTicket(
            base_ticket_id=2,
            name="2+1",
            quality_of_children=2,
            quality_of_adult=1,
            quality_of_add_adult=0,
            quality_visits=1,
            cost_main=1000,
            cost_privilege=1000,
            cost_main_in_period=1000,
            cost_privilege_in_period=1000,
        )
        session.add_all([se1, se2, bt])
        await session.commit()

        t1 = Ticket(
            id=201,
            base_ticket_id=2,
            schedule_event_id=10,
            price=1000,
            status=TicketStatus.APPROVED,
            created_at=now,
        )
        session.add(t1)
        await session.commit()

        seats_map = await get_schedule_events_with_seats(session, [10, 11])
        assert 10 in seats_map
        assert 11 in seats_map

        assert seats_map[10]['free_child'] == 3  # 5 - 2
        assert seats_map[10]['free_adult'] == 4  # 5 - 1
        assert seats_map[11]['free_child'] == 8
        assert seats_map[11]['free_adult'] == 8

        # Проверяем populate_schedule_events_seats
        events = [se1, se2]
        await populate_schedule_events_seats(session, events)
        assert se1.qty_child_free_seat == 3
        assert se1.qty_adult_free_seat == 4
        assert se2.qty_child_free_seat == 8
        assert se2.qty_adult_free_seat == 8

    asyncio.run(_run_with_db(run))


def test_dynamic_seats_overbooking_bounds():
    async def run(session: AsyncSessionWrapper):
        now = datetime.now(timezone.utc)
        se = ScheduleEvent(
            id=20,
            type_event_id=1,
            theater_event_id=1,
            datetime_event=datetime(2030, 5, 1, 10, 0, tzinfo=timezone.utc),
            qty_child=1,
            qty_adult=1,
            flag_turn_in_bot=True,
        )
        bt = BaseTicket(
            base_ticket_id=3,
            name="2+2",
            quality_of_children=2,
            quality_of_adult=2,
            quality_of_add_adult=0,
            quality_visits=1,
            cost_main=1000,
            cost_privilege=1000,
            cost_main_in_period=1000,
            cost_privilege_in_period=1000,
        )
        session.add_all([se, bt])
        await session.commit()

        t = Ticket(
            id=301,
            base_ticket_id=3,
            schedule_event_id=20,
            price=1000,
            status=TicketStatus.PAID,
            created_at=now,
        )
        session.add(t)
        await session.commit()

        seats = await get_schedule_event_available_seats(session, 20)
        assert seats['occupied_child'] == 2
        assert seats['occupied_adult'] == 2
        # Не должно быть отрицательным
        assert seats['free_child'] == 0
        assert seats['free_adult'] == 0

    asyncio.run(_run_with_db(run))


def test_gspread_batch_update_calls_agcm():
    async def run():
        mock_ss = MagicMock()
        mock_ss.ss.values_batch_update = MagicMock()

        with patch("api.googlesheets._open_spreadsheet", AsyncMock(return_value=mock_ss)), \
             patch("api.googlesheets._agcm._call", AsyncMock(return_value={'spreadsheetId': 'test_id', 'responses': []})) as mock_call:
            await _write_data_to_batch_update(
                data=[{'range': 'A1:B2', 'values': [[1, 2]]}],
                spreadsheet_id='test_sheet_id',
                value_input_option='USER_ENTERED'
            )

            assert mock_call.called
            assert mock_call.call_args[0][0] == mock_ss.ss.values_batch_update

    asyncio.run(run())

import asyncio
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from db.models import (
    BaseModel,
    ScheduleEvent,
    BaseTicket,
    Ticket,
    Person,
    Adult,
    Child,
    User,
    PersonTicket,
)
from db.enum import TicketStatus, AgeType, UserRole
from db.db_postgres import (
    get_schedule_event_available_seats,
    get_children_by_phone,
    search_children,
    get_or_create_custom_base_ticket,
    create_people,
    get_expired_tickets,
)
from utilities.utl_kbd import create_kbd_edit_children


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


def test_get_children_by_phone_website_and_bot():
    async def run(session: AsyncSessionWrapper):
        # 1. Adult from website (no user_id)
        p_adult_web = Person(id=1, name="Мама с сайта", age_type=AgeType.adult)
        a_web = Adult(id=1, person_id=1, phone="9991112233")
        session.add_all([p_adult_web, a_web])

        # Child with parent_id = 1 (created via website, no user_id)
        p_child_web = Person(id=2, name="Саша", age_type=AgeType.child, parent_id=1)
        c_web = Child(id=2, person_id=2, age=4)
        session.add_all([p_child_web, c_web])

        # 2. Adult & child from Telegram bot (with user_id)
        user_bot = User(user_id=100500, chat_id=100500)
        p_adult_bot = Person(id=3, name="Папа из бота", age_type=AgeType.adult, user_id=100500)
        a_bot = Adult(id=3, person_id=3, phone="9992223344")
        session.add_all([user_bot, p_adult_bot, a_bot])

        # Child created with user_id = 100500
        p_child_bot = Person(id=4, name="Миша", age_type=AgeType.child, user_id=100500)
        c_bot = Child(id=4, person_id=4, age=6)
        session.add_all([p_child_bot, c_bot])

        await session.commit()

        # Query children for website adult phone
        children_web = await get_children_by_phone(session, "9991112233")
        assert len(children_web) == 1
        assert children_web[0][0] == "Саша"
        assert children_web[0][1] == 4

        # Query children for bot adult phone
        children_bot = await get_children_by_phone(session, "9992223344")
        assert len(children_bot) == 1
        assert children_bot[0][0] == "Миша"
        assert children_bot[0][1] == 6

        # Query non-existent phone
        children_empty = await get_children_by_phone(session, "0000000000")
        assert len(children_empty) == 0

    asyncio.run(_run_with_db(run))


def test_search_children_name_and_age():
    async def run(session: AsyncSessionWrapper):
        p1 = Person(id=10, name="Анна Смирнова", age_type=AgeType.child)
        c1 = Child(id=10, person_id=10, age=3)

        p2 = Person(id=11, name="Анечка Иванова", age_type=AgeType.child)
        c2 = Child(id=11, person_id=11, age=5)

        p3 = Person(id=12, name="Борис Петров", age_type=AgeType.child)
        c3 = Child(id=12, person_id=12, age=3)

        session.add_all([p1, c1, p2, c2, p3, c3])
        await session.commit()

        # Search by name substring
        res_name = await search_children(session, name_query="Ан")
        names = [r[0] for r in res_name]
        assert "Анна Смирнова" in names
        assert "Анечка Иванова" in names
        assert "Борис Петров" not in names

        # Search by age
        res_age = await search_children(session, age_query=3)
        names_age = [r[0] for r in res_age]
        assert "Анна Смирнова" in names_age
        assert "Борис Петров" in names_age
        assert "Анечка Иванова" not in names_age

    asyncio.run(_run_with_db(run))


def test_get_or_create_custom_base_ticket():
    async def run(session: AsyncSessionWrapper):
        # Create standard ticket with ID 1
        bt_std = BaseTicket(
            base_ticket_id=1,
            name="Стандарт",
            cost_main=1000,
            cost_privilege=1000,
            cost_main_in_period=1000,
            cost_privilege_in_period=1000,
            quality_of_children=1,
            quality_of_adult=1,
            quality_of_add_adult=0,
            quality_visits=1,
            flag_individual=False,
        )
        session.add(bt_std)
        await session.commit()

        # First custom ticket
        custom1 = await get_or_create_custom_base_ticket(
            session, quality_of_children=8, quality_of_adult=1, cost=15000
        )
        assert custom1.base_ticket_id == 1000
        assert custom1.flag_individual is True
        assert custom1.quality_of_children == 8
        assert custom1.quality_of_adult == 1
        assert custom1.cost_main == 15000

        # Request same custom ticket -> should return existing
        custom1_again = await get_or_create_custom_base_ticket(
            session, quality_of_children=8, quality_of_adult=1, cost=15000
        )
        assert custom1_again.base_ticket_id == 1000

        # Second different custom ticket -> ID 1001
        custom2 = await get_or_create_custom_base_ticket(
            session, quality_of_children=5, quality_of_adult=2, cost=10000
        )
        assert custom2.base_ticket_id == 1001
        assert custom2.quality_of_children == 5
        assert custom2.quality_of_adult == 2

    asyncio.run(_run_with_db(run))


def test_create_people_with_stub_children():
    async def run(session: AsyncSessionWrapper):
        user = User(user_id=999, chat_id=999)
        session.add(user)
        await session.commit()

        client_data = {
            'name_adult': 'Иван Иванов',
            'phone': '9998887766',
            'data_children': [['Ребенок 1', '0'], ['Ребенок 2', '0']],
            'flag_stub_children': True
        }
        people_ids = await create_people(session, user_id=999, client_data=client_data)
        assert len(people_ids) == 1  # Only adult person ID returned

        # Check people in database
        adult_res = (await session.execute(select(Adult).where(Adult.phone == '9998887766'))).scalar_one_or_none()
        assert adult_res is not None
        assert adult_res.person_id == people_ids[0]

        # Ensure no children were inserted into Person or Child table
        children_in_db = (await session.execute(select(Child))).scalars().all()
        assert len(children_in_db) == 0

    asyncio.run(_run_with_db(run))


def test_reserved_status_seats_and_expiration():
    async def run(session: AsyncSessionWrapper):
        se = ScheduleEvent(
            id=10,
            type_event_id=1,
            theater_event_id=1,
            datetime_event=datetime(2030, 5, 1, 12, 0, tzinfo=timezone.utc),
            qty_child=10,
            qty_adult=10,
            flag_turn_in_bot=True,
        )
        bt = BaseTicket(
            base_ticket_id=1000,
            name="Кастом 8+1",
            quality_of_children=8,
            quality_of_adult=1,
            quality_of_add_adult=0,
            quality_visits=1,
            cost_main=15000,
            cost_privilege=15000,
            cost_main_in_period=15000,
            cost_privilege_in_period=15000,
            flag_individual=True,
        )
        session.add_all([se, bt])
        await session.commit()

        # Check initial seats
        seats_init = await get_schedule_event_available_seats(session, 10)
        assert seats_init['free_child'] == 10
        assert seats_init['free_adult'] == 10

        # Create ticket with RESERVED status created 30 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        t_reserved = Ticket(
            id=100,
            base_ticket_id=1000,
            price=15000,
            schedule_event_id=10,
            status=TicketStatus.RESERVED,
            created_at=old_time,
        )
        session.add(t_reserved)
        await session.commit()

        # Check seats: RESERVED should hold seats indefinitely
        seats_reserved = await get_schedule_event_available_seats(session, 10)
        assert seats_reserved['free_child'] == 2  # 10 - 8
        assert seats_reserved['free_adult'] == 9  # 10 - 1

        # Check get_expired_tickets: RESERVED must NOT be returned as expired
        expired = await get_expired_tickets(session, minutes=10)
        expired_ids = [t.id for t in expired]
        assert 100 not in expired_ids

        # If ticket is cancelled by admin, seats return immediately
        t_reserved.status = TicketStatus.CANCELED
        await session.commit()

        seats_after_cancel = await get_schedule_event_available_seats(session, 10)
        assert seats_after_cancel['free_child'] == 10
        assert seats_after_cancel['free_adult'] == 10

    asyncio.run(_run_with_db(run))


def test_kbd_edit_children_buttons_order():
    children = [
        ["Алиса", "4", 101],
        ["Боря", "6", 102],
    ]
    # Admin view
    kbd_admin = create_kbd_edit_children(
        children, page=0, selected_children=[], limit=2, current_filter='PHONE', is_admin=True
    )
    # 1st row: ➕ Добавить ребенка
    assert len(kbd_admin[0]) == 1
    assert kbd_admin[0][0].text == "➕ Добавить ребенка"
    assert kbd_admin[0][0].callback_data == "CHLD_ADD"

    # 2nd row: Filters
    assert len(kbd_admin[1]) == 3
    assert "По имени" in kbd_admin[1][0].text
    assert "По возрасту" in kbd_admin[1][1].text
    assert "Сбросить" in kbd_admin[1][2].text

    # 3rd row: Skip button
    assert len(kbd_admin[2]) == 1
    assert "Пропустить" in kbd_admin[2][0].text
    assert kbd_admin[2][0].callback_data == "CHLD_SKIP"

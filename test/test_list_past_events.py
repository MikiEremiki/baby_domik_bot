import asyncio
from datetime import datetime, date, time, timedelta
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from db.models import (
    BaseModel,
    ScheduleEvent,
    TheaterEvent,
    TypeEvent,
    Place,
)
from db import db_postgres
from utilities.utl_func import get_actual_from_by_command
from handlers.reserve.choice import (
    choice_month,
    choice_show_by_repertoire,
    choice_date,
    choice_time,
    choice_place,
)
from handlers.reserve.input import send_clients_data


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


# ---------------------------------------------------------------------------
# 1. Tests for get_actual_from_by_command
# ---------------------------------------------------------------------------

def test_get_actual_from_by_command_list():
    expected = datetime.combine(date.today() - timedelta(days=1), time.min)
    res = get_actual_from_by_command('list')
    assert res == expected


def test_get_actual_from_by_command_reserve_and_others():
    now_before = datetime.now()
    res_reserve = get_actual_from_by_command('reserve')
    res_studio = get_actual_from_by_command('studio')
    res_list_wait = get_actual_from_by_command('list_wait')
    res_none = get_actual_from_by_command(None)
    now_after = datetime.now()

    for res in [res_reserve, res_studio, res_list_wait, res_none]:
        assert now_before <= res <= now_after


# ---------------------------------------------------------------------------
# 2. Database query functions with custom from_datetime
# ---------------------------------------------------------------------------

def test_db_queries_filter_with_from_datetime():
    async def run(session: AsyncSessionWrapper):
        # Create type event, theater event, place
        te = TheaterEvent(id=1, name="Колобок", flag_active_bd=True)
        session.add(te)
        tpe = TypeEvent(id=1, name="Репертуарные", name_alias="repertoire")
        session.add(tpe)
        pl = Place(id=1, name="Основная сцена", address="ул. Примерная, 1")
        session.add(pl)

        now = datetime.now()
        dt_two_days_ago = now - timedelta(days=2)
        dt_yesterday_morning = datetime.combine(date.today() - timedelta(days=1), time(11, 0))
        dt_yesterday_evening = datetime.combine(date.today() - timedelta(days=1), time(18, 0))
        dt_tomorrow = now + timedelta(days=1)

        ev_old = ScheduleEvent(
            id=1, type_event_id=1, theater_event_id=1, place_id=1,
            datetime_event=dt_two_days_ago, qty_child=10, qty_adult=10,
            flag_turn_in_bot=True
        )
        ev_yesterday1 = ScheduleEvent(
            id=2, type_event_id=1, theater_event_id=1, place_id=1,
            datetime_event=dt_yesterday_morning, qty_child=10, qty_adult=10,
            flag_turn_in_bot=True
        )
        ev_yesterday2 = ScheduleEvent(
            id=3, type_event_id=1, theater_event_id=1, place_id=1,
            datetime_event=dt_yesterday_evening, qty_child=10, qty_adult=10,
            flag_turn_in_bot=True
        )
        ev_future = ScheduleEvent(
            id=4, type_event_id=1, theater_event_id=1, place_id=1,
            datetime_event=dt_tomorrow, qty_child=10, qty_adult=10,
            flag_turn_in_bot=True
        )

        session.add_all([ev_old, ev_yesterday1, ev_yesterday2, ev_future])
        await session.commit()

        # Test get_schedule_events_by_type_actual for /list (from yesterday 00:00:00)
        from_list = get_actual_from_by_command('list')
        events_list = await db_postgres.get_schedule_events_by_type_actual(
            session, [1], from_datetime=from_list
        )
        event_ids_list = [e.id for e in events_list]
        assert event_ids_list == [2, 3, 4]  # 2 days ago (id=1) excluded, yesterday (2, 3) and tomorrow (4) included

        # Test get_schedule_events_by_type_actual for /reserve (default / from_datetime=now)
        from_reserve = get_actual_from_by_command('reserve')
        events_reserve = await db_postgres.get_schedule_events_by_type_actual(
            session, [1], from_datetime=from_reserve
        )
        event_ids_reserve = [e.id for e in events_reserve]
        assert event_ids_reserve == [4]  # only future event

        # Test get_schedule_events_by_ids with actual_only=True and from_datetime
        all_ids = [1, 2, 3, 4]
        events_ids_list = await db_postgres.get_schedule_events_by_ids(
            session, all_ids, actual_only=True, from_datetime=from_list
        )
        assert [e.id for e in events_ids_list] == [2, 3, 4]

        events_ids_reserve = await db_postgres.get_schedule_events_by_ids(
            session, all_ids, actual_only=True, from_datetime=from_reserve
        )
        assert [e.id for e in events_ids_reserve] == [4]

        # Test get_schedule_events_by_ids_and_theater with actual_only=True and from_datetime
        events_ids_th_list = await db_postgres.get_schedule_events_by_ids_and_theater(
            session, all_ids, [1], actual_only=True, from_datetime=from_list
        )
        assert [e.id for e in events_ids_th_list] == [2, 3, 4]

        events_ids_th_reserve = await db_postgres.get_schedule_events_by_ids_and_theater(
            session, all_ids, [1], actual_only=True, from_datetime=from_reserve
        )
        assert [e.id for e in events_ids_th_reserve] == [4]

    asyncio.run(_run_with_db(run))


# ---------------------------------------------------------------------------
# 3. Handlers pass from_datetime for /list vs /reserve
# ---------------------------------------------------------------------------

def test_choice_month_passes_from_datetime(monkeypatch):
    async def run():
        mock_get_events = AsyncMock(return_value=[])
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_schedule_events_by_type_actual', mock_get_events)
        monkeypatch.setattr('handlers.reserve.choice.clean_replay_kb_and_send_typing_action', AsyncMock(return_value=MagicMock(message_id=1)))
        monkeypatch.setattr('handlers.reserve.choice.set_back_context', AsyncMock())

        update = MagicMock()
        update.effective_message.text = '/list'
        update.effective_message.is_topic_message = False
        update.callback_query = None
        update.effective_chat.id = 123
        update.effective_chat.send_message = AsyncMock()

        context = MagicMock()
        context.user_data = {
            'command': 'list',
            'reserve_user_data': {},
        }
        context.bot.delete_message = AsyncMock()

        await choice_month(update, context)

        assert mock_get_events.call_count == 1
        call_kwargs = mock_get_events.call_args.kwargs
        expected_from = datetime.combine(date.today() - timedelta(days=1), time.min)
        assert call_kwargs.get('from_datetime') == expected_from

    asyncio.run(run())


def test_choice_show_by_repertoire_passes_from_datetime(monkeypatch):
    async def run():
        mock_get_events = AsyncMock(return_value=[])
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_schedule_events_by_type_actual', mock_get_events)
        monkeypatch.setattr('handlers.reserve.choice.set_back_context', AsyncMock())

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = 'MODE|REPERTOIRE'
        update.callback_query.answer = AsyncMock()
        update.callback_query.delete_message = AsyncMock()
        update.effective_chat.send_message = AsyncMock()

        context = MagicMock()
        context.user_data = {
            'command': 'list',
            'reserve_user_data': {},
        }

        await choice_show_by_repertoire(update, context)

        assert mock_get_events.call_count >= 1
        for call in mock_get_events.call_args_list:
            expected_from = datetime.combine(date.today() - timedelta(days=1), time.min)
            assert call.kwargs.get('from_datetime') == expected_from

    asyncio.run(run())


def test_choice_date_passes_from_datetime(monkeypatch):
    async def run():
        mock_get_events = AsyncMock(return_value=[])
        mock_theater = MagicMock(
            name="Тест",
            min_age_child=0,
            max_age_child=0,
            flag_active_bd=True,
            flag_premiere=False,
            flag_compact=False,
            note=None,
        )
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_schedule_events_by_ids_and_theater', mock_get_events)
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_theater_event', AsyncMock(return_value=mock_theater))
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_default_place', AsyncMock(return_value=MagicMock(id=1, name="Зал")))
        monkeypatch.setattr('handlers.reserve.choice.set_back_context', AsyncMock())

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = 'SHOW|10'
        update.callback_query.answer = AsyncMock()
        update.callback_query.delete_message = AsyncMock()
        update.effective_chat.send_message = AsyncMock()

        context = MagicMock()
        context.user_data = {
            'command': 'list',
            'STATE': 'SHOW',
            'select_mode': 'DATE',
            'postfix_for_cancel': 'list',
            'reserve_user_data': {
                'SHOW': {'schedule_event_ids': [101, 102]}
            },
        }

        await choice_date(update, context)

        assert mock_get_events.call_count == 1
        call_kwargs = mock_get_events.call_args.kwargs
        expected_from = datetime.combine(date.today() - timedelta(days=1), time.min)
        assert call_kwargs.get('from_datetime') == expected_from
        assert call_kwargs.get('actual_only') is True

    asyncio.run(run())


def test_choice_time_passes_from_datetime(monkeypatch):
    async def run():
        mock_get_events = AsyncMock(return_value=[])
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_schedule_events_by_ids', mock_get_events)
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_default_place', AsyncMock(return_value=MagicMock(id=1, name="Зал")))
        monkeypatch.setattr('handlers.reserve.choice._render_time_for_date', AsyncMock(return_value='TIME'))

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = f'DATE|{date.today().isoformat()}'
        update.callback_query.answer = AsyncMock()
        update.callback_query.delete_message = AsyncMock()

        context = MagicMock()
        context.user_data = {
            'command': 'list',
            'STATE': 'DATE',
            'reserve_user_data': {
                'DATE': {'schedule_event_ids': [201, 202]}
            },
        }

        res = await choice_time(update, context)
        assert res == 'TIME'

        assert mock_get_events.call_count == 1
        call_kwargs = mock_get_events.call_args.kwargs
        expected_from = datetime.combine(date.today() - timedelta(days=1), time.min)
        assert call_kwargs.get('from_datetime') == expected_from
        assert call_kwargs.get('actual_only') is True

    asyncio.run(run())


def test_choice_place_passes_from_datetime(monkeypatch):
    async def run():
        mock_get_events = AsyncMock(return_value=[])
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_schedule_events_by_ids', mock_get_events)
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_default_place', AsyncMock(return_value=MagicMock(id=1, name="Зал")))
        monkeypatch.setattr('handlers.reserve.choice.db_postgres.get_place', AsyncMock(return_value=MagicMock(id=2, name="Площадка 2")))

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = 'PLACE|2'
        update.callback_query.answer = AsyncMock()
        update.callback_query.delete_message = AsyncMock()

        context = MagicMock()
        context.user_data = {
            'command': 'list',
            'STATE': 'PLACE',
            'reserve_user_data': {
                'PLACE': {
                    'branch': 'DATE',
                    'schedule_event_ids': [301, 302],
                }
            },
        }

        await choice_place(update, context)

        assert mock_get_events.call_count == 1
        call_kwargs = mock_get_events.call_args.kwargs
        expected_from = datetime.combine(date.today() - timedelta(days=1), time.min)
        assert call_kwargs.get('from_datetime') == expected_from
        assert call_kwargs.get('actual_only') is True

    asyncio.run(run())


# ---------------------------------------------------------------------------
# 4. send_clients_data works with past events
# ---------------------------------------------------------------------------

def test_send_clients_data_with_past_event(monkeypatch):
    async def run():
        past_event = ScheduleEvent(
            id=999,
            type_event_id=1,
            theater_event_id=1,
            datetime_event=datetime.now() - timedelta(days=1),
            qty_child=10,
            qty_adult=10,
            flag_turn_in_bot=True,
        )
        past_event.tickets = []

        theater_event = TheaterEvent(id=1, name="Прошедший спектакль")

        monkeypatch.setattr('handlers.reserve.input.db_postgres.get_schedule_event', AsyncMock(return_value=past_event))
        monkeypatch.setattr('handlers.reserve.input.db_postgres.get_theater_event', AsyncMock(return_value=theater_event))

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = 'TIME|999'
        update.effective_chat.send_action = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.answer = AsyncMock()

        context = MagicMock()
        context.user_data = {'command': 'list'}

        state = await send_clients_data(update, context)
        assert state == -1  # ConversationHandler.END

        # Verify message was edited to show event info
        assert update.callback_query.edit_message_text.call_count >= 1

    asyncio.run(run())

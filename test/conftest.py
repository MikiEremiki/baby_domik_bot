"""Shared pytest fixtures and utilities for all tests."""
from collections import defaultdict
from datetime import datetime, timezone
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from api.web import main as web_main
from api.web.config import broker
from api.web.deps import get_session
from api.web.routes import pages, booking
from api.web.services import booking_service
from db.models import BaseModel


# ─── DB fixtures ───────────────────────────────────────────────────────────────


class AsyncSessionWrapper:
    """Wraps a synchronous SQLAlchemy Session so it can be used where an
    async session is expected (e.g. by application code that awaits
    ``session.execute(...)``).

    Provides the full set of methods used across all test files.
    """

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

    async def delete(self, instance):
        self._session.delete(instance)


async def _run_with_db(test_coro):
    """Create an in-memory SQLite DB, run *test_coro(session)*, then dispose.

    *test_coro* receives an :class:`AsyncSessionWrapper` instance.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    BaseModel.metadata.create_all(engine)

    sync_maker = sessionmaker(bind=engine, expire_on_commit=False)
    with sync_maker() as session:
        wrapped = AsyncSessionWrapper(session)
        await test_coro(wrapped)

    engine.dispose()


# ─── Telegram mock fixtures ───────────────────────────────────────────────────


@pytest.fixture
def mock_context():
    """A minimal ``context`` mock with ``session``, ``bot``, and ``config``."""
    context = MagicMock()
    context.session = AsyncMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.config = MagicMock()
    context.config.bot.developer_chat_id = 123456789
    return context


@pytest.fixture
def mock_seats():
    """A typical seats-dictionary returned by ``get_schedule_event_available_seats``."""
    return {
        'total_child': 10,
        'total_adult': 8,
        'occupied_child': 2,
        'occupied_adult': 2,
        'free_child': 6,
        'free_adult': 5,
        'nonconfirm_child': 2,
        'nonconfirm_adult': 1,
    }


def _create_mock_update(
    source='WEBSITE',
    chat_id='5473664345',
    message_id=123,
    ticket_ids='4915',
    choose_schedule_event_ids='101',
    command='reserve',
    promo_id=None,
):
    """Build a mock Telegram ``Update`` with NATS metadata."""
    update = MagicMock()
    metadata = {
        'source': source,
        'chat_id': str(chat_id) if chat_id is not None else '',
        'message_id': message_id,
        'ticket_ids': ticket_ids,
        'choose_schedule_event_ids': choose_schedule_event_ids,
        'command': command,
    }
    if promo_id:
        metadata['promo_id'] = str(promo_id)
    update.object.metadata = metadata
    return update


def _create_mock_context(has_persistence=True):
    """Build a mock ``context`` resembling a real PTB ``ContextTypes.DEFAULT``."""
    context = MagicMock()
    raw_user_data = defaultdict(dict)
    context.application.user_data = MappingProxyType(raw_user_data)

    if has_persistence:
        context.application.persistence = MagicMock()
        context.application.persistence.get_user_data = AsyncMock(return_value={})
        context.application.persistence.update_conversation = AsyncMock()
        context.application.mark_data_for_update_persistence = MagicMock()
    else:
        context.application.persistence = None
        context.application.mark_data_for_update_persistence = MagicMock()

    context.config.sheets.sheet_id_domik = 'test_sheet_id'
    context.config.bot.developer_chat_id = 111
    context.bot_data = {
        'settings': {'REFUND_INFO': 'Правила возврата'},
        'dict_topics_name': {
            'Бронирования спектаклей': 42,
            'Бронирования студия': 43,
        },
    }
    context.session = AsyncMock()

    mock_sent_msg = MagicMock()
    mock_sent_msg.message_id = 777
    context.bot.send_message = AsyncMock(return_value=mock_sent_msg)
    context.bot.edit_message_reply_markup = AsyncMock()

    return context


# ─── FastAPI web mock utilities ────────────────────────────────────────────────


def _create_mock_theater_event(
    free_seats_child=10,
    free_seats_adult=5,
    event_id=1,
    event_name="Test Event",
    note="Test Description",
    min_age_child=3,
    flag_active_repertoire=True,
    link="http://test.com/image.jpg",
    session_id=101,
    session_datetime=None,
    flag_turn_in_bot=True,
    type_event_name='Репертуарный',
    qty_child_nonconfirm=0,
    qty_adult_nonconfirm=0,
):
    """Create a mock TheaterEvent with one ScheduleEvent.

    Returns ``(theater_event, schedule_event)`` tuple.
    """
    if session_datetime is None:
        session_datetime = datetime(2030, 1, 1, tzinfo=timezone.utc)

    event = MagicMock()
    event.id = event_id
    event.name = event_name
    event.note = note
    event.duration = None
    event.min_age_child = min_age_child
    event.flag_active_repertoire = flag_active_repertoire
    event.link = link

    s_event = MagicMock()
    s_event.id = session_id
    s_event.datetime_event = session_datetime
    s_event.qty_child_free_seat = free_seats_child
    s_event.qty_adult_free_seat = free_seats_adult
    s_event.qty_child_nonconfirm_seat = qty_child_nonconfirm
    s_event.qty_adult_nonconfirm_seat = qty_adult_nonconfirm
    s_event.flag_turn_in_bot = flag_turn_in_bot
    s_event.theater_event = event
    s_event.type_event_id = 1
    type_event_mock = MagicMock()
    type_event_mock.name = type_event_name
    s_event.type_event = type_event_mock

    event.schedule_events = [s_event]
    return event, s_event


def _create_mock_schedule_event(
    free_seats_child=10,
    free_seats_adult=5,
    event_id=1,
    event_name="Test Event",
    note="Test Description",
    min_age_child=3,
    flag_active_repertoire=True,
    link="http://test.com/image.jpg",
    session_id=101,
    session_datetime=None,
    flag_turn_in_bot=True,
    type_event_name='Репертуарный',
    qty_child_nonconfirm=0,
    qty_adult_nonconfirm=0,
    base_tickets=None,
):
    """Create a mock ScheduleEvent (with attached TheaterEvent).

    Returns ``(schedule_event, theater_event)`` tuple.
    """
    event, s_event = _create_mock_theater_event(
        free_seats_child=free_seats_child,
        free_seats_adult=free_seats_adult,
        event_id=event_id,
        event_name=event_name,
        note=note,
        min_age_child=min_age_child,
        flag_active_repertoire=flag_active_repertoire,
        link=link,
        session_id=session_id,
        session_datetime=session_datetime,
        flag_turn_in_bot=flag_turn_in_bot,
        type_event_name=type_event_name,
        qty_child_nonconfirm=qty_child_nonconfirm,
        qty_adult_nonconfirm=qty_adult_nonconfirm,
    )
    s_event.type_event.base_tickets = base_tickets if base_tickets is not None else []
    return s_event, event


def _create_web_client(monkeypatch, mock_default_place=True):
    """Create a FastAPI TestClient with all common mocks applied.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        mock_default_place: If True, also mock ``get_default_place`` on
            ``pages``, ``booking``, and ``booking_service`` modules.
    """
    # Infrastructure mocks — prevent real NATS/DB connections
    monkeypatch.setattr(broker, 'connect', AsyncMock(return_value=None), raising=False)
    monkeypatch.setattr(broker, 'close', AsyncMock(return_value=None), raising=False)
    monkeypatch.setattr(broker, 'stop', AsyncMock(return_value=None), raising=False)
    monkeypatch.setattr(broker, 'publish', AsyncMock(return_value=None), raising=False)
    monkeypatch.setattr(booking_service, 'cleanup_expired_bookings', AsyncMock())
    monkeypatch.setattr(booking_service, 'publish_update_ticket', AsyncMock(), raising=False)
    monkeypatch.setattr(booking, 'publish_update_ticket', AsyncMock(), raising=False)
    monkeypatch.setattr(pages, 'get_afishas', AsyncMock(return_value=[]))

    if mock_default_place:
        default_place = MagicMock(id=1, name='Домик', address='ул. Пушкина, 1')
        monkeypatch.setattr(pages, 'get_default_place', AsyncMock(return_value=default_place), raising=False)
        monkeypatch.setattr(booking, 'get_default_place', AsyncMock(return_value=default_place), raising=False)
        monkeypatch.setattr(booking_service, 'get_default_place', AsyncMock(return_value=default_place), raising=False)

    # Session dependency override
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.first.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.rollback = AsyncMock()

    web_main.app.dependency_overrides[get_session] = lambda: mock_session

    return TestClient(web_main.app)

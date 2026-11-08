"""Shared pytest fixtures and utilities for all tests."""
from collections import defaultdict
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

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
    source='website',
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

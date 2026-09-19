import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from db import db_postgres
from db.models import BaseModel, ScheduleChange, ScheduleEvent, TheaterEvent, TypeEvent
from handlers.schedule_sync_hl import (
    format_schedule_change_report,
    send_schedule_change_report,
    send_pending_schedule_reports,
)
from settings.settings import ADMIN_GROUP


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


def test_format_schedule_change_report_create():
    change = ScheduleChange(
        id=1,
        schedule_event_id=10,
        author_id=123,
        author_name='<admin>&co',
        operation_type='create',
        created_at=datetime(2026, 9, 20, 10, 0, 0),
        snapshot_after={
            'type_event_id': 1,
            'theater_event_id': 2,
            'place_id': None,
            'flag_turn_in_bot': True,
            'datetime_event': '2026-10-01T11:00:00',
            'qty_child': 5,
            'qty_adult': 5,
            'flag_gift': True,
            'flag_christmas_tree': False,
            'flag_santa': False,
            'ticket_price_type': 'none',
            'base_ticket_ids': [100],
        },
        changed_fields=['type_event_id', 'theater_event_id', 'qty_child']
    )

    text = format_schedule_change_report(
        change,
        theater_name='Театр <Сказка>',
        type_name='Премьера & показ',
        place_name='Домик'
    )

    assert '#change_1' in text
    assert '#10' in text
    assert '&lt;admin&gt;&amp;co' in text
    assert 'Театр &lt;Сказка&gt;' in text
    assert 'Премьера &amp; показ' in text
    assert 'Вкл' in text
    assert '🎁 ✅' in text


def test_format_schedule_change_report_update():
    change = ScheduleChange(
        id=2,
        schedule_event_id=10,
        author_id=123,
        author_name='admin',
        operation_type='update',
        created_at=datetime(2026, 9, 20, 10, 0, 0),
        snapshot_before={
            'qty_child': 5,
            'flag_turn_in_bot': False,
        },
        snapshot_after={
            'qty_child': 10,
            'flag_turn_in_bot': True,
        },
        changed_fields=['qty_child', 'flag_turn_in_bot']
    )

    text = format_schedule_change_report(change)
    assert 'Редактирование' in text
    assert 'Кол-во детских мест:</b> 5 ➡️ <b>10</b>' in text
    assert 'Вкл/Выкл в боте:</b> Выкл ➡️ <b>Вкл</b>' in text


def test_format_schedule_change_report_datetime_update():
    # Test reproduction for changing date/time to 21.09.2026 18:00
    change = ScheduleChange(
        id=3,
        schedule_event_id=10,
        author_id=123,
        author_name='admin',
        operation_type='update',
        created_at=datetime(2026, 9, 20, 10, 0, 0),
        snapshot_before={
            'datetime_event': '2026-09-21T21:00:00+03:00',
        },
        snapshot_after={
            'datetime_event': '2026-09-21T18:00:00+03:00',
        },
        changed_fields=['datetime_event']
    )

    text = format_schedule_change_report(change)
    assert 'Дата и время:</b> 21.09.2026 21:00 ➡️ <b>21.09.2026 18:00</b>' in text

    # Also test legacy format without timezone
    change_legacy = ScheduleChange(
        id=4,
        schedule_event_id=10,
        author_id=123,
        author_name='admin',
        operation_type='update',
        created_at=datetime(2026, 9, 20, 10, 0, 0),
        snapshot_before={
            'datetime_event': '2026-09-21T21:00:00',
        },
        snapshot_after={
            'datetime_event': '2026-09-21T18:00:00',
        },
        changed_fields=['datetime_event']
    )

    text_legacy = format_schedule_change_report(change_legacy)
    assert 'Дата и время:</b> 21.09.2026 21:00 ➡️ <b>21.09.2026 18:00</b>' in text_legacy


def test_send_schedule_change_report_flow():
    async def run(session: AsyncSessionWrapper):
        te = TypeEvent(id=1, name='Спектакль', name_alias='show')
        th = TheaterEvent(id=2, name='Теремок', flag_active_repertoire=True)
        se = ScheduleEvent(
            id=10,
            type_event_id=1,
            theater_event_id=2,
            datetime_event=datetime(2026, 10, 1, 11, 0),
            qty_child=5,
            qty_adult=5
        )
        ch = ScheduleChange(
            id=1,
            schedule_event_id=10,
            author_id=123,
            author_name='admin',
            operation_type='create',
            snapshot_after={'qty_child': 5, 'theater_event_id': 2, 'type_event_id': 1},
            changed_fields=['qty_child'],
            report_status='pending',
            sync_status='pending',
        )
        session.add_all([te, th, se, ch])
        await session.commit()

        context = MagicMock()
        context.session = session
        context.bot_data = {'dict_topics_name': {'Изменения расписания': 555}}
        sent_msg = MagicMock()
        sent_msg.message_id = 9999
        context.bot.send_message = AsyncMock(return_value=sent_msg)

        ok = await send_schedule_change_report(context, 1)
        assert ok is True

        context.bot.send_message.assert_awaited_once()
        call_kwargs = context.bot.send_message.call_args.kwargs
        assert call_kwargs['chat_id'] == ADMIN_GROUP
        assert call_kwargs['message_thread_id'] == 555
        assert 'Теремок' in call_kwargs['text']

        # Verify DB updated
        updated_ch = await db_postgres.get_schedule_change(session, 1)
        assert updated_ch.report_status == 'sent'
        assert updated_ch.telegram_message_id == 9999
        assert updated_ch.telegram_thread_id == 555

    asyncio.run(_run_with_db(run))


def test_send_schedule_change_report_missing_topic():
    async def run(session: AsyncSessionWrapper):
        ch = ScheduleChange(
            id=2,
            schedule_event_id=10,
            operation_type='create',
            snapshot_after={'qty_child': 5},
            changed_fields=['qty_child'],
            report_status='pending',
            sync_status='pending',
        )
        session.add(ch)
        await session.commit()

        context = MagicMock()
        context.session = session
        context.bot_data = {'dict_topics_name': {}}  # No topic configured
        context.bot.send_message = AsyncMock()

        ok = await send_schedule_change_report(context, 2)
        assert ok is False
        context.bot.send_message.assert_not_called()

        updated_ch = await db_postgres.get_schedule_change(session, 2)
        assert updated_ch.report_status == 'failed'
        assert 'не настроена' in updated_ch.report_error

    asyncio.run(_run_with_db(run))

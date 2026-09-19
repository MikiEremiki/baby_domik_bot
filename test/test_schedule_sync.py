import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from db import db_postgres
from db.models import BaseModel, ScheduleChange, ScheduleSyncRun, ScheduleEvent, TheaterEvent, TypeEvent
from utilities.utl_date import datetime_to_sheets_date_time, convert_sheets_datetime
from utilities.schemas.schedule_event import ScheduleEventDTO
from api.googlesheets import sync_schedule_events_to_gspread
from handlers.schedule_sync_hl import (
    sync_schedule_command,
    handle_sync_schedule_confirm,
    handle_sync_schedule_cancel,
)
from handlers.hooks.schedule_sync_hl import (
    format_sync_run_summary,
    schedule_sync_hook_update,
)
from api.broker_nats import ScheduleSyncResultData
from settings.settings import ADMIN_GROUP


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


def test_datetime_to_sheets_conversion_roundtrip():
    # Regular daytime
    dt_utc = datetime.datetime(2026, 10, 15, 8, 30, 0)  # 11:30 MSK
    sheets_date, sheets_time = datetime_to_sheets_date_time(dt_utc, utc_offset=3)
    restored_dt = convert_sheets_datetime(sheets_date, sheets_time, utc_offset=-3)
    assert restored_dt.year == 2026
    assert restored_dt.month == 10
    assert restored_dt.day == 15
    assert restored_dt.hour == 8
    assert restored_dt.minute == 30

    # Midnight / day transition: 21:00 UTC on 2026-10-15 = 00:00 MSK on 2026-10-16
    dt_utc_midnight = datetime.datetime(2026, 10, 15, 21, 0, 0)
    sheets_date_m, sheets_time_m = datetime_to_sheets_date_time(dt_utc_midnight, utc_offset=3)
    restored_dt_m = convert_sheets_datetime(sheets_date_m, sheets_time_m, utc_offset=-3)
    assert restored_dt_m.year == 2026
    assert restored_dt_m.month == 10
    assert restored_dt_m.day == 15
    assert restored_dt_m.hour == 21
    assert restored_dt_m.minute == 0


def test_sync_schedule_events_to_gspread_create_and_update():
    async def run():
        headers = [
            'event_id', 'event_type', 'theater_event_id', 'place_id',
            'flag_turn_on_off', 'date_show', 'time_show', 'qty_child',
            'qty_child_free_seat', 'qty_child_nonconfirm_seat',
            'qty_adult', 'qty_adult_free_seat', 'qty_adult_nonconfirm_seat',
            'flag_gift', 'flag_christmas_tree', 'flag_santa', 'ticket_price_type'
        ]
        dict_col = {name: i for i, name in enumerate(headers)}

        # Sheet rows (row 1 empty, row 2 headers, row 3 event 100)
        existing_rows = [
            ['' for _ in headers],
            headers,
            [100, 1, 10, None, True, 46285, 0.5, 5, 5, 0, 5, 5, 0, False, False, False, ''],
        ]

        mock_write_batch = AsyncMock()
        mock_append = AsyncMock()

        with patch('api.googlesheets._get_column_info', AsyncMock(return_value=(dict_col, len(headers)))), \
             patch('api.googlesheets._get_values', AsyncMock(return_value=existing_rows)), \
             patch('api.googlesheets._write_data_to_batch_update', mock_write_batch), \
             patch('api.googlesheets._execute_append_googlesheet', mock_append):

            items = [
                # 1. Update existing event (100) from qty_child=5 to qty_child=8
                {
                    'item_id': 'run1_100',
                    'event_id': 100,
                    'change_ids': [1],
                    'operation': 'update',
                    'expected': {
                        'id': 100, 'type_event_id': 1, 'theater_event_id': 10,
                        'datetime_event': '2026-09-20T09:00:00', 'qty_child': 5, 'qty_adult': 5,
                        'flag_turn_in_bot': True, 'flag_gift': False, 'ticket_price_type': None
                    },
                    'desired': {
                        'id': 100, 'type_event_id': 1, 'theater_event_id': 10,
                        'datetime_event': '2026-09-20T09:00:00', 'qty_child': 8, 'qty_adult': 5,
                        'flag_turn_in_bot': True, 'flag_gift': False, 'ticket_price_type': None
                    },
                    'fields': ['qty_child', 'base_ticket_ids']
                },
                # 2. Create new event (200)
                {
                    'item_id': 'run1_200',
                    'event_id': 200,
                    'change_ids': [2],
                    'operation': 'create',
                    'expected': None,
                    'desired': {
                        'id': 200, 'type_event_id': 1, 'theater_event_id': 10,
                        'datetime_event': '2026-09-20T09:00:00', 'qty_child': 10, 'qty_adult': 10,
                        'flag_turn_in_bot': True, 'flag_gift': True, 'ticket_price_type': None
                    },
                    'fields': ['type_event_id', 'theater_event_id', 'qty_child', 'qty_adult', 'flag_turn_in_bot', 'flag_gift', 'ticket_price_type']
                }
            ]

            results = await sync_schedule_events_to_gspread('sheet123', 'run1', items)

            assert len(results) == 2
            assert results[0]['status'] == 'updated'
            assert results[0]['unsupported_fields'] == ['base_ticket_ids']
            assert results[1]['status'] == 'created'

            mock_write_batch.assert_awaited_once()
            mock_append.assert_awaited_once()

    asyncio.run(run())


def test_sync_schedule_conflict_detection():
    async def run():
        headers = [
            'event_id', 'event_type', 'theater_event_id', 'place_id',
            'flag_turn_on_off', 'date_show', 'time_show', 'qty_child',
            'qty_child_free_seat', 'qty_child_nonconfirm_seat',
            'qty_adult', 'qty_adult_free_seat', 'qty_adult_nonconfirm_seat',
            'flag_gift', 'flag_christmas_tree', 'flag_santa', 'ticket_price_type'
        ]
        dict_col = {name: i for i, name in enumerate(headers)}

        # Sheet row has qty_child = 12 (someone manually changed it in sheet!)
        existing_rows = [
            ['' for _ in headers],
            headers,
            [100, 1, 10, None, True, 46285, 0.5, 12, 12, 0, 5, 5, 0, False, False, False, ''],
        ]

        mock_write_batch = AsyncMock()

        with patch('api.googlesheets._get_column_info', AsyncMock(return_value=(dict_col, len(headers)))), \
             patch('api.googlesheets._get_values', AsyncMock(return_value=existing_rows)), \
             patch('api.googlesheets._write_data_to_batch_update', mock_write_batch):

            items = [
                {
                    'item_id': 'run1_100',
                    'event_id': 100,
                    'change_ids': [1],
                    'operation': 'update',
                    # We expected 5, bot wants 8, but sheet currently has 12 -> CONFLICT!
                    'expected': {
                        'id': 100, 'type_event_id': 1, 'theater_event_id': 10,
                        'datetime_event': '2026-09-20T09:00:00', 'qty_child': 5, 'qty_adult': 5,
                        'flag_turn_in_bot': True, 'flag_gift': False, 'ticket_price_type': None
                    },
                    'desired': {
                        'id': 100, 'type_event_id': 1, 'theater_event_id': 10,
                        'datetime_event': '2026-09-20T09:00:00', 'qty_child': 8, 'qty_adult': 5,
                        'flag_turn_in_bot': True, 'flag_gift': False, 'ticket_price_type': None
                    },
                    'fields': ['qty_child']
                }
            ]

            results = await sync_schedule_events_to_gspread('sheet123', 'run1', items)

            assert len(results) == 1
            assert results[0]['status'] == 'conflict'
            assert 'qty_child' in results[0]['details']['conflicts']
            mock_write_batch.assert_not_called()

    asyncio.run(run())


def test_format_sync_run_summary_text():
    results = [
        {'item_id': '1', 'event_id': 10, 'change_ids': [1], 'status': 'created', 'unsupported_fields': ['base_ticket_ids']},
        {'item_id': '2', 'event_id': 20, 'change_ids': [2], 'status': 'updated'},
        {'item_id': '3', 'event_id': 30, 'change_ids': [3], 'status': 'already_equal'},
        {
            'item_id': '4', 'event_id': 40, 'change_ids': [4], 'status': 'conflict',
            'details': {
                'conflicts': {
                    'qty_child': {'expected': 5, 'actual_in_sheet': 12, 'desired': 8}
                }
            }
        },
        {'item_id': '5', 'event_id': 50, 'change_ids': [5], 'status': 'failed', 'details': {'error': 'Строка не найдена'}}
    ]

    text = format_sync_run_summary('run-uuid-123', results)
    assert 'Создано: <b>1</b>' in text
    assert 'Обновлено: <b>1</b>' in text
    assert 'Уже совпадает: <b>1</b>' in text
    assert 'Конфликты: <b>1</b>' in text
    assert 'Ошибки: <b>1</b>' in text
    assert 'Сеанс <code>#40</code>' in text
    assert 'Кол-во детских мест' in text
    assert 'ожидалось [<code>5</code>]' in text
    assert 'в таблице [<code>12</code>]' in text
    assert 'в боте [<code>8</code>]' in text
    assert 'base_ticket_ids' in text


def test_schedule_sync_hook_handler_updates_db_and_reports():
    async def run(session: AsyncSessionWrapper):
        run_obj = ScheduleSyncRun(
            id='test-run-1',
            spreadsheet_id='sheet_test',
            status='running',
            change_ids=[1, 2],
            payload={'items': []},
            report_status='pending',
        )
        ch1 = ScheduleChange(id=1, schedule_event_id=10, operation_type='create', snapshot_after={}, changed_fields=[], sync_status='in_progress')
        ch2 = ScheduleChange(id=2, schedule_event_id=20, operation_type='update', snapshot_after={}, changed_fields=[], sync_status='in_progress')
        session.add_all([run_obj, ch1, ch2])
        await session.commit()

        context = MagicMock()
        context.session = session
        context.bot_data = {'dict_topics_name': {'Изменения расписания': 777}}
        sent_msg = MagicMock()
        sent_msg.message_id = 8888
        context.bot.send_message = AsyncMock(return_value=sent_msg)

        result_data = ScheduleSyncResultData({
            'run_id': 'test-run-1',
            'sheet_id': 'sheet_test',
            'item_results': [
                {'item_id': 'test-run-1_10', 'event_id': 10, 'change_ids': [1], 'status': 'created'},
                {'item_id': 'test-run-1_20', 'event_id': 20, 'change_ids': [2], 'status': 'conflict', 'details': {'conflicts': {}}},
            ]
        })

        await schedule_sync_hook_update(result_data, context)

        # Check DB
        updated_run = await db_postgres.get_schedule_sync_run(session, 'test-run-1')
        assert updated_run.status == 'completed'
        assert updated_run.report_status == 'sent'
        assert updated_run.telegram_message_id == 8888

        updated_ch1 = await db_postgres.get_schedule_change(session, 1)
        assert updated_ch1.sync_status == 'synced'

        updated_ch2 = await db_postgres.get_schedule_change(session, 2)
        assert updated_ch2.sync_status == 'conflict'

        context.bot.send_message.assert_awaited_once()

    asyncio.run(_run_with_db(run))


def test_update_schedule_events_from_googlesheets_skips_unsynced():
    async def run(session: AsyncSessionWrapper):
        te = TypeEvent(id=1, name='Спектакль', name_alias='show')
        th = TheaterEvent(id=10, name='Колобок', flag_active_repertoire=True)
        se1 = ScheduleEvent(id=100, type_event_id=1, theater_event_id=10, datetime_event=datetime.datetime(2026, 10, 1, 11, 0), qty_child=5, qty_adult=5)
        se2 = ScheduleEvent(id=200, type_event_id=1, theater_event_id=10, datetime_event=datetime.datetime(2026, 10, 1, 11, 0), qty_child=5, qty_adult=5)
        ch = ScheduleChange(id=1, schedule_event_id=100, operation_type='update', snapshot_after={}, changed_fields=['qty_child'], sync_status='pending')
        session.add_all([te, th, se1, se2, ch])
        await session.commit()

        # DTO models from Google Sheets trying to update both se1 and se2 to qty_child=20
        dto1 = ScheduleEventDTO(
            event_id=100, event_type=1, theater_event_id=10, flag_turn_on_off=True,
            date_show=46285, time_show=0.5, qty_child=20, qty_child_free_seat=20, qty_child_nonconfirm_seat=0,
            qty_adult=5, qty_adult_free_seat=5, qty_adult_nonconfirm_seat=0,
            flag_gift=False, flag_christmas_tree=False, flag_santa=False, ticket_price_type='None'
        )
        dto2 = ScheduleEventDTO(
            event_id=200, event_type=1, theater_event_id=10, flag_turn_on_off=True,
            date_show=46285, time_show=0.5, qty_child=20, qty_child_free_seat=20, qty_child_nonconfirm_seat=0,
            qty_adult=5, qty_adult_free_seat=5, qty_adult_nonconfirm_seat=0,
            flag_gift=False, flag_christmas_tree=False, flag_santa=False, ticket_price_type='None'
        )

        skipped_ids = await db_postgres.update_schedule_events_from_googlesheets(
            session, [dto1, dto2], auto_commit=True
        )

        assert skipped_ids == {100}

        # Event 100 should NOT be overwritten (remains qty_child=5)
        check_se1 = await session.get(ScheduleEvent, 100)
        assert check_se1.qty_child == 5

        # Event 200 SHOULD be updated (qty_child=20)
        check_se2 = await session.get(ScheduleEvent, 200)
        assert check_se2.qty_child == 20

    asyncio.run(_run_with_db(run))

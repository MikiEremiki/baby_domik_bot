import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from db.db_googlesheets import (
    increase_free_and_decrease_nonconfirm_seat,
    decrease_free_and_increase_nonconfirm_seat,
    increase_free_seat,
    decrease_free_seat,
    decrease_nonconfirm_seat,
    update_free_seat,
)


@pytest.fixture
def mock_context():
    context = MagicMock()
    context.session = AsyncMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.config = MagicMock()
    context.config.bot.developer_chat_id = 123456789
    return context


@pytest.fixture
def mock_seats():
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


def test_increase_free_and_decrease_nonconfirm_seat(mock_context, mock_seats):
    with patch('db.db_postgres.get_schedule_event_available_seats', AsyncMock(return_value=mock_seats)) as mock_db, \
         patch('db.db_googlesheets._publish_write_data_reserve', AsyncMock()) as mock_pub:
        res = asyncio.run(increase_free_and_decrease_nonconfirm_seat(mock_context, 42))

        assert res == 1
        mock_db.assert_awaited_once_with(mock_context.session, 42)
        mock_pub.assert_awaited_once_with(42, [6, 2, 5, 1], 1)


def test_decrease_free_and_increase_nonconfirm_seat(mock_context, mock_seats):
    with patch('db.db_postgres.get_schedule_event_available_seats', AsyncMock(return_value=mock_seats)) as mock_db, \
         patch('db.db_googlesheets._publish_write_data_reserve', AsyncMock()) as mock_pub:
        res = asyncio.run(decrease_free_and_increase_nonconfirm_seat(mock_context, "42"))

        assert res == 1
        mock_db.assert_awaited_once_with(mock_context.session, 42)
        mock_pub.assert_awaited_once_with(42, [6, 2, 5, 1], 1)


def test_decrease_nonconfirm_seat(mock_context, mock_seats):
    with patch('db.db_postgres.get_schedule_event_available_seats', AsyncMock(return_value=mock_seats)) as mock_db, \
         patch('db.db_googlesheets._publish_write_data_reserve', AsyncMock()) as mock_pub:
        res = asyncio.run(decrease_nonconfirm_seat(mock_context, 100))

        assert res == 1
        mock_db.assert_awaited_once_with(mock_context.session, 100)
        mock_pub.assert_awaited_once_with(100, [2, 1], 2)


def test_increase_free_seat(mock_context, mock_seats):
    with patch('db.db_postgres.get_schedule_event_available_seats', AsyncMock(return_value=mock_seats)) as mock_db, \
         patch('db.db_googlesheets._publish_write_data_reserve', AsyncMock()) as mock_pub:
        res = asyncio.run(increase_free_seat(mock_context, 100))

        assert res == 1
        mock_db.assert_awaited_once_with(mock_context.session, 100)
        mock_pub.assert_awaited_once_with(100, [6, 5], 3)


def test_decrease_free_seat(mock_context, mock_seats):
    with patch('db.db_postgres.get_schedule_event_available_seats', AsyncMock(return_value=mock_seats)) as mock_db, \
         patch('db.db_googlesheets._publish_write_data_reserve', AsyncMock()) as mock_pub:
        res = asyncio.run(decrease_free_seat(mock_context, 100))

        assert res == 1
        mock_db.assert_awaited_once_with(mock_context.session, 100)
        mock_pub.assert_awaited_once_with(100, [6, 5], 3)


def test_update_free_seat(mock_context, mock_seats):
    with patch('db.db_postgres.get_schedule_event_available_seats', AsyncMock(return_value=mock_seats)) as mock_db, \
         patch('db.db_googlesheets._publish_write_data_reserve', AsyncMock()) as mock_pub:
        res = asyncio.run(update_free_seat(mock_context, 100))

        assert res == 1
        mock_db.assert_awaited_once_with(mock_context.session, 100)
        mock_pub.assert_awaited_once_with(100, [6, 5], 3)


def test_sync_seats_error_handling(mock_context):
    with patch('db.db_postgres.get_schedule_event_available_seats', AsyncMock(side_effect=RuntimeError("DB Connection Error"))), \
         patch('db.db_googlesheets._publish_write_data_reserve', AsyncMock()) as mock_pub:
        res = asyncio.run(increase_free_seat(mock_context, 99))

        assert res == 0
        mock_pub.assert_not_called()
        mock_context.bot.send_message.assert_awaited_once()
        sent_text = mock_context.bot.send_message.call_args.kwargs['text']
        assert 'event_id=99' in sent_text
        assert 'Не увеличились свободные места' in sent_text

"""Tests for _availability_block() — filtering sessions with 0 free seats.

These tests verify that sessions without children's seats (fc == 0) are
excluded from the availability block, and the block returns empty string
when no valid sessions remain.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytz

from handlers.sales.audience import _availability_block


TZ = pytz.timezone('Europe/Moscow')


def _make_schedule_row(schedule_id: int, year: int = 2030, month: int = 1, day: int = 1, hour: int = 18):
    """Create a mock ScheduleEvent row (id, datetime_event)."""
    dt = datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)
    return (schedule_id, dt)


class TestAvailabilityBlockFiltering:
    """Test that _availability_block filters out sessions with 0 children's seats."""

    def test_all_sessions_have_seats(self):
        """When all sessions have children's seats, all are shown."""
        schedule_ids = [1, 2]
        free = {1: (5, 3), 2: (2, 1)}  # (child, adult)
        rows = [_make_schedule_row(1, day=10), _make_schedule_row(2, day=11)]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        with patch('db.sales_crud.get_free_places', AsyncMock(return_value=free)):
            result = asyncio.run(_availability_block(mock_session, schedule_ids))

        assert 'Кол-во свободных мест:' in result
        assert '5 дет' in result
        assert '2 дет' in result

    def test_session_with_zero_child_seats_filtered(self):
        """A session with 0 children's seats but adult seats is excluded."""
        schedule_ids = [1, 2]
        free = {1: (5, 3), 2: (0, 10)}  # session 2 has 0 child seats
        rows = [_make_schedule_row(1, day=10), _make_schedule_row(2, day=11)]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        with patch('db.sales_crud.get_free_places', AsyncMock(return_value=free)):
            result = asyncio.run(_availability_block(mock_session, schedule_ids))

        assert 'Кол-во свободных мест:' in result
        assert '5 дет' in result
        # Session 2 should NOT appear
        assert '10 взр' not in result

    def test_all_sessions_zero_child_seats_returns_empty(self):
        """When all sessions have 0 children's seats, return empty string."""
        schedule_ids = [1, 2]
        free = {1: (0, 5), 2: (0, 3)}  # all have 0 child seats
        rows = [_make_schedule_row(1, day=10), _make_schedule_row(2, day=11)]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        with patch('db.sales_crud.get_free_places', AsyncMock(return_value=free)):
            result = asyncio.run(_availability_block(mock_session, schedule_ids))

        assert result == ''

    def test_session_with_zero_seats_at_all(self):
        """A session with 0 child and 0 adult seats is excluded."""
        schedule_ids = [1, 2]
        free = {1: (5, 3), 2: (0, 0)}
        rows = [_make_schedule_row(1, day=10), _make_schedule_row(2, day=11)]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        with patch('db.sales_crud.get_free_places', AsyncMock(return_value=free)):
            result = asyncio.run(_availability_block(mock_session, schedule_ids))

        assert 'Кол-во свободных мест:' in result
        assert '5 дет' in result

    def test_empty_schedule_ids_returns_empty(self):
        """Empty schedule_ids should return empty string."""
        mock_session = AsyncMock()

        result = asyncio.run(_availability_block(mock_session, []))
        assert result == ''

    def test_no_free_places_data_returns_empty(self):
        """When get_free_places returns empty dict, return empty string."""
        schedule_ids = [1]
        rows = [_make_schedule_row(1, day=10)]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        with patch('db.sales_crud.get_free_places', AsyncMock(return_value={})):
            result = asyncio.run(_availability_block(mock_session, schedule_ids))

        assert result == ''

    def test_mixed_sessions_only_valid_shown(self):
        """With 3 sessions (valid, zero child, zero all), only valid appears."""
        schedule_ids = [1, 2, 3]
        free = {1: (3, 2), 2: (0, 5), 3: (0, 0)}
        rows = [
            _make_schedule_row(1, day=10),
            _make_schedule_row(2, day=11),
            _make_schedule_row(3, day=12),
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        with patch('db.sales_crud.get_free_places', AsyncMock(return_value=free)):
            result = asyncio.run(_availability_block(mock_session, schedule_ids))

        assert 'Кол-во свободных мест:' in result
        assert '3 дет' in result
        assert '5 взр' not in result  # session 2 excluded
        # Only 1 session line should appear (plus 2 header lines)
        parts = result.split('<br>')
        assert len(parts) == 3  # header1, header2, one session

    def test_uses_br_not_newline(self):
        """Availability block uses <br> for HTML storage, not bare \\n."""
        schedule_ids = [1]
        free = {1: (5, 3)}
        rows = [_make_schedule_row(1, day=10)]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        with patch('db.sales_crud.get_free_places', AsyncMock(return_value=free)):
            result = asyncio.run(_availability_block(mock_session, schedule_ids))

        assert '\n' not in result
        assert '<br>' in result

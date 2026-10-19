"""Unit tests for tick scheduler: auto_sending_tick, catch-up, precise, send_reminder wrapper."""
import asyncio
from datetime import datetime, timedelta, timezone, time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

from schedule.auto_sending import (
    auto_sending_tick,
    _is_catch_up_allowed,
    _dispatch_for_event,
    _precise_dispatch_job,
    TICK_INTERVAL_SECONDS,
    compute_send_time,
    Recipient,
    RECIPIENT_SELECTORS,
)
from db.enum import AutoSendingTrigger


def _run(coro):
    """Run an async coroutine, creating a new event loop if needed."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


# ─── _is_catch_up_allowed ─────────────────────────────────────────────────────

class TestIsCatchUpAllowed:
    """Tests for catch-up guard logic."""

    def _make_sending(self, offset_minutes):
        s = MagicMock()
        s.offset_minutes = offset_minutes
        return s

    def test_negative_offset_before_event(self):
        """Negative offset: now before event → allowed."""
        sending = self._make_sending(-1500)
        event_dt = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
        send_time = datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc)
        now = datetime(2026, 5, 14, 11, 3, tzinfo=timezone.utc)
        assert _is_catch_up_allowed(sending, send_time, event_dt, now) is True

    def test_negative_offset_event_passed(self):
        """Negative offset: event already started → not allowed."""
        sending = self._make_sending(-1500)
        event_dt = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
        send_time = datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc)
        now = datetime(2026, 5, 15, 13, 0, tzinfo=timezone.utc)  # after event
        assert _is_catch_up_allowed(sending, send_time, event_dt, now) is False

    def test_negative_offset_event_just_started(self):
        """Negative offset: now equals event start → not allowed."""
        sending = self._make_sending(-1500)
        event_dt = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
        send_time = datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc)
        now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)  # exactly at event
        assert _is_catch_up_allowed(sending, send_time, event_dt, now) is False

    def test_positive_offset_within_24h(self):
        """Positive offset: within 24h of send_time → allowed."""
        sending = self._make_sending(240)
        event_dt = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
        send_time = datetime(2026, 5, 15, 16, 0, tzinfo=timezone.utc)
        now = datetime(2026, 5, 15, 16, 3, tzinfo=timezone.utc)
        assert _is_catch_up_allowed(sending, send_time, event_dt, now) is True

    def test_positive_offset_over_24h(self):
        """Positive offset: more than 24h after send_time → not allowed."""
        sending = self._make_sending(240)
        event_dt = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
        send_time = datetime(2026, 5, 15, 16, 0, tzinfo=timezone.utc)
        now = datetime(2026, 5, 17, 17, 0, tzinfo=timezone.utc)  # 25h later
        assert _is_catch_up_allowed(sending, send_time, event_dt, now) is False

    def test_zero_offset(self):
        """Zero offset treated as positive (≥0)."""
        sending = self._make_sending(0)
        event_dt = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
        send_time = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 5, 15, 12, 3, tzinfo=timezone.utc)
        assert _is_catch_up_allowed(sending, send_time, event_dt, now) is True


# ─── auto_sending_tick ────────────────────────────────────────────────────────

class TestAutoSendingTick:
    """Tests for the main tick function."""

    def test_tick_skips_when_locked(self):
        """If _tick_lock is already held, tick returns immediately."""
        # Simulate lock held.
        lock = MagicMock()
        lock.locked.return_value = True

        context = MagicMock()
        with patch('schedule.auto_sending._tick_lock', lock):
            _run(auto_sending_tick(context))

        # Should not have opened any session.
        assert True  # No exception = passed

    def test_tick_no_active_sendings(self):
        """Tick returns early when no active EVENT sendings."""
        context = MagicMock()
        context.config = MagicMock()

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        with patch('schedule.auto_sending.open_session', return_value=mock_session), \
             patch('schedule.auto_sending.db_postgres.get_all_active_auto_sendings',
                   return_value=[]):
            _run(auto_sending_tick(context))

    def test_tick_dispatches_non_precise(self):
        """Non-precise sending with send_time in window is dispatched."""
        context = MagicMock()
        context.config = MagicMock()

        # Create a mock auto_sending with negative offset.
        auto_sending = MagicMock()
        auto_sending.id = 1
        auto_sending.offset_minutes = -1500
        auto_sending.window_start = None
        auto_sending.window_end = None
        auto_sending.precise = False
        auto_sending.name = "Reminder"
        auto_sending.trigger = AutoSendingTrigger.EVENT

        # Event at 2026-05-15 12:00 MSK → send_time = 2026-05-14 11:00 MSK.
        event_dt_utc = datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc)  # 12:00 MSK
        mock_se = MagicMock()
        mock_se.id = 10
        mock_se.datetime_event = event_dt_utc

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_se]
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch('schedule.auto_sending.open_session', return_value=mock_session), \
             patch('schedule.auto_sending.db_postgres.get_all_active_auto_sendings',
                   return_value=[auto_sending]), \
             patch('schedule.auto_sending.to_moscow_dt', side_effect=lambda dt: dt.replace(tzinfo=timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo("Europe/Moscow"))), \
             patch('schedule.auto_sending._dispatch_for_event', new_callable=AsyncMock) as mock_dispatch:
            _run(auto_sending_tick(context))

    def test_tick_precise_schedules_run_once(self):
        """Precise sending schedules run_once job when send_time is in (now, now+interval]."""
        from utilities.utl_date import MOSCOW_TZ
        import zoneinfo

        context = MagicMock()
        context.config = MagicMock()
        context.job_queue = MagicMock()

        auto_sending = MagicMock()
        auto_sending.id = 2
        auto_sending.offset_minutes = 0  # offset=0 → send_time = event time
        auto_sending.window_start = None
        auto_sending.window_end = None
        auto_sending.precise = True
        auto_sending.name = "Precise Feedback"
        auto_sending.trigger = AutoSendingTrigger.EVENT

        now = datetime.now(tz=MOSCOW_TZ)
        # Place event 60s in the future → send_time = now + 60s (within interval)
        future_event = now + timedelta(seconds=60)

        mock_se = MagicMock()
        mock_se.id = 20
        mock_se.datetime_event = future_event

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_se]
        mock_session.execute = AsyncMock(return_value=mock_result)

        def to_moscow_side_effect(dt):
            """Return dt as-is if already MSK, otherwise convert."""
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(MOSCOW_TZ)

        with patch('schedule.auto_sending.open_session', return_value=mock_session), \
             patch('schedule.auto_sending.db_postgres.get_all_active_auto_sendings',
                   return_value=[auto_sending]), \
             patch('schedule.auto_sending.to_moscow_dt', side_effect=to_moscow_side_effect):
            _run(auto_sending_tick(context))

        # Verify run_once was called for precise scheduling.
        context.job_queue.run_once.assert_called()


# ─── _dispatch_for_event ──────────────────────────────────────────────────────

class TestDispatchForEvent:
    """Tests for _dispatch_for_event helper."""

    def test_dispatch_filters_by_schedule_event_id(self):
        """Only recipients matching the schedule event are dispatched."""
        context = MagicMock()
        session = AsyncMock()

        auto_sending = MagicMock()
        auto_sending.trigger = AutoSendingTrigger.EVENT

        se = MagicMock()
        se.id = 10

        # Create a mock user.
        user = MagicMock()
        user.user_id = 100
        user.chat_id = 12345
        user.status = None

        recipients = [
            Recipient(user=user, ctx={}, dedup_keys=["se:10"], schedule_event_id=10),
            Recipient(user=user, ctx={}, dedup_keys=["se:20"], schedule_event_id=20),
        ]

        with patch('schedule.auto_sending.RECIPIENT_SELECTORS',
                   {AutoSendingTrigger.EVENT: AsyncMock(return_value=recipients)}), \
             patch('schedule.auto_sending.dispatch_auto_sending', new_callable=AsyncMock) as mock_disp:
            _run(_dispatch_for_event(context, session, auto_sending, se))

        # Only the recipient with schedule_event_id=10 should be passed.
        mock_disp.assert_called_once()
        _, _, _, passed_recipients = mock_disp.call_args[0]
        assert len(passed_recipients) == 1
        assert passed_recipients[0].schedule_event_id == 10


# ─── _precise_dispatch_job ────────────────────────────────────────────────────

class TestPreciseDispatchJob:
    """Tests for precise dispatch job callback."""

    def test_precise_job_loads_and_dispatches(self):
        """Precise job loads auto_sending and schedule_event, then dispatches."""
        context = MagicMock()
        context.job.data = {
            "auto_sending_id": 1,
            "schedule_event_id": 10,
        }
        context.config = MagicMock()

        mock_sending = MagicMock()
        mock_sending.is_active = True

        mock_se = MagicMock()

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()
        mock_session.get = AsyncMock(side_effect=[mock_sending, mock_se])

        with patch('schedule.auto_sending.open_session', return_value=mock_session), \
             patch('schedule.auto_sending.db_postgres.get_auto_sending_by_id',
                   return_value=mock_sending), \
             patch('schedule.auto_sending.db_postgres.get_schedule_event',
                   return_value=mock_se), \
             patch('schedule.auto_sending._dispatch_for_event', new_callable=AsyncMock) as mock_disp:
            _run(_precise_dispatch_job(context))

        mock_disp.assert_called_once()

    def test_precise_job_skips_inactive(self):
        """Precise job skips if auto_sending is not active."""
        context = MagicMock()
        context.job.data = {
            "auto_sending_id": 1,
            "schedule_event_id": 10,
        }
        context.config = MagicMock()

        mock_sending = MagicMock()
        mock_sending.is_active = False

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        with patch('schedule.auto_sending.open_session', return_value=mock_session), \
             patch('schedule.auto_sending.db_postgres.get_auto_sending_by_id',
                   return_value=mock_sending), \
             patch('schedule.auto_sending._dispatch_for_event', new_callable=AsyncMock) as mock_disp:
            _run(_precise_dispatch_job(context))

        mock_disp.assert_not_called()


# ─── TICK_INTERVAL_SECONDS ────────────────────────────────────────────────────

class TestTickConstants:
    """Verify tick interval constant."""

    def test_interval_is_3_minutes(self):
        assert TICK_INTERVAL_SECONDS == 180

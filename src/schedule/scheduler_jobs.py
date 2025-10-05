import logging
from datetime import timedelta, datetime

from telegram.ext import ContextTypes

from schedule.worker_jobs import send_reminder
from utilities.schemas import ScheduleEventDTO

scheduler_logger = logging.getLogger('bot.scheduler_jobs')


def _compute_notification_times(datetime_event: datetime) -> tuple[datetime, datetime]:
    """
    Возвращает времена, используемые для планирования напоминания:
    - check_datetime: время, не позднее которого можно планировать (min 4 часа до начала)
    - notification_datetime: момент отправки напоминания за 1 день и 1 час до события
    """
    check_datetime = datetime_event - timedelta(hours=4)
    notification_datetime = datetime_event - timedelta(days=1, hours=1)
    return check_datetime, notification_datetime


def _remove_existing_reminders(
        context: 'ContextTypes.DEFAULT_TYPE',
        event_id: int
) -> bool:
    """
    Удаляет существующие напоминания для данного события.
    Возвращает True, если была удалена хотя бы одна работа, иначе False.
    """
    job = context.job_queue.get_jobs_by_name(f'reminder_event_{event_id}')
    if not job:
        return False
    for j in job:
        j.schedule_removal()
        scheduler_logger.info(f'job removed: {j}')
    return True


async def schedule_notification_job(
        context: 'ContextTypes.DEFAULT_TYPE',
        event: ScheduleEventDTO
) -> None:
    datetime_event = event.get_datetime_event()
    check_datetime, notification_datetime = _compute_notification_times(datetime_event)

    event_id = event.event_id
    now = datetime.now()

    if not event.flag_turn_on_off:
        _remove_existing_reminders(context, event_id)
        return

    if check_datetime > now:
        if notification_datetime < now:
            notification_datetime = now + timedelta(seconds=10)
        job = context.job_queue.run_once(
            send_reminder,
            notification_datetime,
            data={'event_id': event_id},
            name=f'reminder_event_{event_id}',
            job_kwargs={'replace_existing': True,
                        'id': f'reminder_event_{event_id}'}
        )
        scheduler_logger.info(f'job created: {job}')
    else:
        scheduler_logger.info(f'job skipped: {event.event_id} {datetime_event}')

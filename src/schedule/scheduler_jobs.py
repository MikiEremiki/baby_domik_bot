import logging

from telegram.ext import ContextTypes

from utilities.schemas import ScheduleEventDTO

scheduler_logger = logging.getLogger('bot.scheduler_jobs')


def _remove_existing_reminders(
        context: 'ContextTypes.DEFAULT_TYPE',
        event_id: int
) -> bool:
    """
    Удаляет существующие legacy напоминания для данного события.
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
    """Schedule notification job — no longer creates reminder tasks.

    Auto-sendings are now handled by the unified tick scheduler
    (`auto_sending_tick`). This function only cleans up any remaining
    legacy `reminder_event_{id}` jobs when an event is turned off.
    """
    event_id = event.event_id

    if not event.flag_turn_on_off:
        _remove_existing_reminders(context, event_id)

    scheduler_logger.debug(
        f"schedule_notification_job: event {event_id} — "
        f"delegated to auto_sending_tick")

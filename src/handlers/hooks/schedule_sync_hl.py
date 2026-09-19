import html
import logging
from typing import Any, Dict, List

from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes, TypeHandler

from api.broker_nats import ScheduleSyncResultData
from db import db_postgres
from settings.settings import ADMIN_GROUP
from utilities.schemas import kv_name_attr_schedule_event
from utilities.utl_date import format_cell_value_for_report

logger = logging.getLogger('bot.hooks.schedule_sync')


def format_sync_run_summary(
        run_id: str,
        item_results: List[Dict[str, Any]],
        error: str = None
) -> str:
    created = [it for it in item_results if it.get('status') == 'created']
    updated = [it for it in item_results if it.get('status') == 'updated']
    already_equal = [it for it in item_results if it.get('status') == 'already_equal']
    conflicts = [it for it in item_results if it.get('status') == 'conflict']
    failed = [it for it in item_results if it.get('status') == 'failed']

    text = (
        f"📊 <b>Итоги выгрузки расписания в Google Таблицу</b>\n"
        f"ID запуска: <code>{run_id}</code>\n\n"
        f"• Создано: <b>{len(created)}</b>\n"
        f"• Обновлено: <b>{len(updated)}</b>\n"
        f"• Уже совпадает: <b>{len(already_equal)}</b>\n"
        f"• Конфликты: <b>{len(conflicts)}</b>\n"
        f"• Ошибки: <b>{len(failed)}</b>\n"
    )

    if error:
        text += f"\n❌ <b>Общая ошибка запуска:</b> {html.escape(error)}\n"

    if conflicts:
        text += "\n⚠️ <b>Детали конфликтов (сеанс не перезаписан):</b>\n"
        for it in conflicts:
            eid = it.get('event_id')
            details = it.get('details', {}) or {}
            c_map = details.get('conflicts', {})
            text += f"• Сеанс <code>#{eid}</code>:\n"
            for col, c_info in c_map.items():
                f_name = kv_name_attr_schedule_event.get(col, col)
                exp = html.escape(
                    format_cell_value_for_report(col, c_info.get('expected')))
                act = html.escape(
                    format_cell_value_for_report(col, c_info.get('actual_in_sheet')))
                des = html.escape(
                    format_cell_value_for_report(col, c_info.get('desired')))
                text += (
                    f"  - <b>{html.escape(f_name)}</b>: ожидалось [<code>{exp}</code>], "
                    f"в таблице [<code>{act}</code>], в боте [<code>{des}</code>]\n"
                )

    if failed:
        text += "\n❌ <b>Ошибки по сеансам:</b>\n"
        for it in failed:
            eid = it.get('event_id')
            details = it.get('details', {}) or {}
            err_msg = details.get('error', 'Неизвестная ошибка')
            text += f"• Сеанс <code>#{eid}</code>: {html.escape(str(err_msg))}\n"

    # Неподдерживаемые поля
    unsupported_map: Dict[str, List[int]] = {}
    for it in item_results:
        eid = it.get('event_id')
        for f in it.get('unsupported_fields', []):
            unsupported_map.setdefault(f, []).append(eid)

    if unsupported_map:
        text += "\nℹ️ <b>Неподдерживаемые поля:</b>\n"
        for f, eids in unsupported_map.items():
            f_name = kv_name_attr_schedule_event.get(f, f)
            eids_str = ', '.join(f"#{e}" for e in eids)
            text += f"• <b>{html.escape(f_name)}</b> (сеансы: {eids_str}) — зафиксированы в боте, но не экспортируются в текущую структуру таблицы.\n"

    return text


async def schedule_sync_hook_update(
        update: ScheduleSyncResultData,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Обрабатывает результат выгрузки расписания из NATS топика 'schedule_sync_result'.
    """
    data = update.data
    run_id = data.get('run_id')
    item_results = data.get('item_results', [])
    error = data.get('error')

    session = context.session
    sync_run = await db_postgres.get_schedule_sync_run(session, run_id)
    if not sync_run:
        logger.warning(f"ScheduleSyncRun #{run_id} not found in DB.")
        return

    has_failures = bool(error or any(it.get('status') in ('failed', 'conflict') for it in item_results))
    run_status = 'failed' if error else ('completed' if not has_failures else 'completed')

    # Идемпотентно обновляем статус изменений
    for it in item_results:
        st = it.get('status')
        c_ids = it.get('change_ids', [])
        if st in ('created', 'updated', 'already_equal'):
            new_sync_st = 'synced'
        elif st == 'conflict':
            new_sync_st = 'conflict'
        else:
            new_sync_st = 'failed'

        await db_postgres.update_schedule_changes_sync_status(
            session,
            change_ids=c_ids,
            sync_status=new_sync_st,
            sync_run_id=run_id,
            auto_commit=False
        )

    await db_postgres.update_schedule_sync_run(
        session,
        run_id=run_id,
        status=run_status,
        results=data,
        report_status='pending',
        auto_commit=True
    )

    # Формируем и отправляем итоговый отчет в тему «Изменения расписания»
    report_text = format_sync_run_summary(run_id, item_results, error=error)

    dict_topics_name = context.bot_data.get('dict_topics_name', {})
    thread_id = dict_topics_name.get('Изменения расписания')

    kwargs = {}
    if thread_id:
        kwargs['message_thread_id'] = thread_id

    try:
        sent_msg = await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=report_text,
            parse_mode=ParseMode.HTML,
            **kwargs
        )
        await db_postgres.update_schedule_sync_run(
            session,
            run_id=run_id,
            report_status='sent',
            telegram_message_id=sent_msg.message_id,
            telegram_chat_id=ADMIN_GROUP,
            telegram_thread_id=thread_id,
            auto_commit=True
        )
    except BadRequest as e:
        logger.error(f"Failed to send schedule sync summary to Telegram: {e}")
        await db_postgres.update_schedule_sync_run(
            session,
            run_id=run_id,
            report_status='failed',
            report_error=str(e),
            auto_commit=True
        )
    except Exception as e:
        logger.exception(f"Unexpected error sending schedule sync summary: {e}")
        await db_postgres.update_schedule_sync_run(
            session,
            run_id=run_id,
            report_status='failed',
            report_error=str(e),
            auto_commit=True
        )


ScheduleSyncHookHandler = TypeHandler(ScheduleSyncResultData, schedule_sync_hook_update)

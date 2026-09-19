import html
import logging
import uuid
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from db import db_postgres
from db.models import ScheduleChange, ScheduleSyncRun, ScheduleEvent, TheaterEvent, TypeEvent, Place
from db.enum import TicketPriceType
from api.gspread_pub import publish_sync_schedule
from settings.settings import ADMIN_GROUP, ADMIN_GROUP_ID, ADMIN_ID
from utilities.schemas import kv_name_attr_schedule_event
from utilities.utl_func import to_moscow_dt, MOSCOW_TZ, _bot_is_admin, split_message
from utilities.utl_schedule_changes import EXPORTABLE_SCHEDULE_FIELDS

logger = logging.getLogger('bot.schedule_sync_hl')


def _format_value_for_report(field: str, val: Any) -> str:
    if val is None:
        return '—'
    if field == 'flag_turn_in_bot':
        return 'Вкл' if val else 'Выкл'
    if field in ('flag_gift', 'flag_christmas_tree', 'flag_santa'):
        return '✅' if val else '❌'
    if field == 'datetime_event':
        try:
            import datetime
            if isinstance(val, str):
                dt = datetime.datetime.fromisoformat(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=MOSCOW_TZ)
                else:
                    dt = to_moscow_dt(dt)
            elif isinstance(val, datetime.datetime):
                dt = to_moscow_dt(val)
            else:
                return str(val)
            return dt.strftime('%d.%m.%Y %H:%M')
        except Exception:
            return str(val)
    if field == 'ticket_price_type':
        try:
            if isinstance(val, TicketPriceType):
                return val.name
            tpt = TicketPriceType(val)
            return tpt.name
        except Exception:
            return str(val)
    if field == 'base_ticket_ids':
        if isinstance(val, list):
            return f"{len(val)} шт. ({', '.join(str(x) for x in val)})" if val else 'наследовать'
        return str(val)
    return str(val)


def format_schedule_change_report(
        change: ScheduleChange,
        theater_name: Optional[str] = None,
        type_name: Optional[str] = None,
        place_name: Optional[str] = None
) -> str:
    created_dt_str = to_moscow_dt(change.created_at).strftime('%d.%m.%Y %H:%M:%S')
    op_label = 'Создание' if change.operation_type == 'create' else 'Редактирование'
    author_str = html.escape(change.author_name or 'Неизвестно')
    if change.author_id:
        author_str += f" (ID: {change.author_id})"

    text = (
        f"<b>Изменение расписания</b> <code>#change_{change.id}</code>\n"
        f"<b>Сеанс:</b> <code>#{change.schedule_event_id}</code>\n"
        f"<b>Операция:</b> {op_label}\n"
        f"<b>Автор:</b> {author_str}\n"
        f"<b>Время (МСК):</b> {created_dt_str}\n"
    )

    if change.operation_type == 'create':
        after = change.snapshot_after or {}
        text += "\n<b>Параметры сеанса:</b>\n"
        text += f"• <b>Спектакль:</b> {html.escape(theater_name or str(after.get('theater_event_id', '—')))}\n"
        text += f"• <b>Тип мероприятия:</b> {html.escape(type_name or str(after.get('type_event_id', '—')))}\n"
        text += f"• <b>Локация:</b> {html.escape(place_name or 'Домик')}\n"
        text += f"• <b>Дата/время:</b> {_format_value_for_report('datetime_event', after.get('datetime_event'))}\n"
        text += f"• <b>Места:</b> {after.get('qty_child', 0)} дет / {after.get('qty_adult', 0)} взр\n"
        text += f"• <b>В боте:</b> {_format_value_for_report('flag_turn_in_bot', after.get('flag_turn_in_bot'))}\n"
        text += f"• <b>Стоимость:</b> {_format_value_for_report('ticket_price_type', after.get('ticket_price_type'))}\n"
        text += (
            f"• <b>Флаги:</b> 🎁 {_format_value_for_report('flag_gift', after.get('flag_gift'))} | "
            f"🎄 {_format_value_for_report('flag_christmas_tree', after.get('flag_christmas_tree'))} | "
            f"🎅🏻 {_format_value_for_report('flag_santa', after.get('flag_santa'))}\n"
        )
        text += f"• <b>Базовые билеты:</b> {_format_value_for_report('base_ticket_ids', after.get('base_ticket_ids'))}\n"
    else:
        before = change.snapshot_before or {}
        after = change.snapshot_after or {}
        changed = change.changed_fields or []
        text += "\n<b>Измененные поля:</b>\n"
        for f in changed:
            f_name = kv_name_attr_schedule_event.get(f, f)
            v_before = _format_value_for_report(f, before.get(f))
            v_after = _format_value_for_report(f, after.get(f))
            if f == 'theater_event_id' and theater_name:
                v_after = f"{html.escape(theater_name)} ({v_after})"
            elif f == 'place_id' and place_name:
                v_after = f"{html.escape(place_name)} ({v_after})"
            elif f == 'type_event_id' and type_name:
                v_after = f"{html.escape(type_name)} ({v_after})"
            text += f"• <b>{html.escape(f_name)}:</b> {html.escape(v_before)} ➡️ <b>{html.escape(v_after)}</b>\n"

    return text


async def send_schedule_change_report(
        context: ContextTypes.DEFAULT_TYPE,
        change_id: int
) -> bool:
    """
    Отправляет отчёт об изменении расписания в отдельную тему админ-группы.
    """
    session = context.session
    change = await db_postgres.get_schedule_change(session, change_id)
    if not change:
        return False

    dict_topics_name = context.bot_data.get('dict_topics_name', {})
    thread_id = dict_topics_name.get('Изменения расписания')
    if not thread_id:
        logger.warning(
            f"Тема «Изменения расписания» не найдена в dict_topics_name. Отчёт #{change_id} отложен."
        )
        await db_postgres.update_schedule_change_report_status(
            session, change_id, report_status='failed',
            report_error='Тема «Изменения расписания» не настроена'
        )
        return False

    theater_name = None
    type_name = None
    place_name = None
    try:
        after = change.snapshot_after or {}
        th_id = after.get('theater_event_id')
        if th_id:
            th = await db_postgres.get_theater_event(session, th_id)
            if th:
                theater_name = th.name
        tp_id = after.get('type_event_id')
        if tp_id:
            tp = await db_postgres.get_type_event(session, tp_id)
            if tp:
                type_name = tp.name
        pl_id = after.get('place_id')
        if pl_id:
            pl = await db_postgres.get_place(session, pl_id)
            if pl:
                place_name = pl.name
    except Exception as e:
        logger.warning(f"Error resolving related names for report #{change_id}: {e}")

    report_text = format_schedule_change_report(
        change, theater_name=theater_name, type_name=type_name, place_name=place_name
    )

    try:
        sent_msg = await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            message_thread_id=thread_id,
            text=report_text,
            parse_mode=ParseMode.HTML
        )
        await db_postgres.update_schedule_change_report_status(
            session,
            change_id=change_id,
            report_status='sent',
            telegram_message_id=sent_msg.message_id,
            telegram_chat_id=ADMIN_GROUP,
            telegram_thread_id=thread_id,
            report_error=None
        )
        return True
    except Exception as e:
        logger.exception(f"Failed to send schedule change report #{change_id}: {e}")
        await db_postgres.update_schedule_change_report_status(
            session,
            change_id=change_id,
            report_status='failed',
            report_error=str(e)
        )
        return False


async def send_pending_schedule_reports(context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Фоновая задача отправки ожидающих и неотправленных отчетов.
    """
    session = context.session
    pending_changes = await db_postgres.get_pending_schedule_changes_for_report(session, limit=50)
    sent_count = 0
    for ch in pending_changes:
        ok = await send_schedule_change_report(context, ch.id)
        if ok:
            sent_count += 1
    return sent_count


async def sync_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /sync_schedule [event_id] для инициализации выгрузки в Google Sheets.
    """
    if not await _bot_is_admin(update, context):
        return

    session = context.session
    from settings.config_loader import parse_settings
    cfg = parse_settings()
    sheet_id = cfg.sheets.sheet_id_domik

    # Проверяем, нет ли уже активного запуска
    active_run = await db_postgres.get_active_schedule_sync_run(session, sheet_id)
    if active_run:
        msg = (
            f"⚠️ <b>Выгрузка уже выполняется</b>\n\n"
            f"Активный запуск: <code>{active_run.id}</code> (статус: {active_run.status}).\n"
            f"Дождитесь завершения текущего запуска."
        )
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    target_event_id: Optional[int] = None
    if context.args:
        try:
            target_event_id = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("ID сеанса должен быть числом: <code>/sync_schedule [event_id]</code>", parse_mode=ParseMode.HTML)
            return

    pending_changes = await db_postgres.get_pending_schedule_changes_for_sync(
        session, event_id=target_event_id
    )
    if not pending_changes:
        text = "Нет сеансов с изменениями, ожидающих выгрузки."
        if target_event_id:
            text = f"Для сеанса #{target_event_id} нет изменений, ожидающих выгрузки."
        await update.effective_message.reply_text(text)
        return

    # Агрегируем изменения по сеансам
    grouped_changes: Dict[int, List[ScheduleChange]] = {}
    for ch in pending_changes:
        grouped_changes.setdefault(ch.schedule_event_id, []).append(ch)

    run_id = str(uuid.uuid4())
    sync_items = []
    change_ids_all = []

    for eid, ch_list in grouped_changes.items():
        # Сортируем изменения по времени/id
        ch_list.sort(key=lambda x: x.id)
        c_ids = [c.id for c in ch_list]
        change_ids_all.extend(c_ids)

        first_change = ch_list[0]
        last_change = ch_list[-1]

        is_create = any(c.operation_type == 'create' for c in ch_list)
        operation = 'create' if is_create else 'update'
        expected = first_change.snapshot_before
        desired = last_change.snapshot_after

        # Объединяем все затронутые поля
        all_changed_fields = set()
        for c in ch_list:
            all_changed_fields.update(c.changed_fields or [])

        export_fields = [f for f in all_changed_fields if f in EXPORTABLE_SCHEDULE_FIELDS or f == 'base_ticket_ids']

        sync_items.append({
            'item_id': f"{run_id}_{eid}",
            'event_id': eid,
            'change_ids': c_ids,
            'operation': operation,
            'expected': expected,
            'desired': desired,
            'fields': export_fields,
        })

    user = update.effective_user
    initiator_id = user.id if user else None
    initiator_name = (f"@{user.username}" if user and user.username else (user.full_name if user else None))

    payload = {
        'run_id': run_id,
        'sheet_id': sheet_id,
        'items': sync_items,
    }

    await db_postgres.create_schedule_sync_run(
        session,
        run_id=run_id,
        initiator_id=initiator_id,
        initiator_name=initiator_name,
        spreadsheet_id=sheet_id,
        change_ids=change_ids_all,
        payload=payload,
        auto_commit=True
    )

    text = (
        f"<b>Выгрузка изменений расписания в Google Таблицу</b>\n\n"
        f"Сеансов к выгрузке: <b>{len(sync_items)}</b>\n"
        f"Всего изменений: <b>{len(change_ids_all)}</b>\n"
        f"ID запуска: <code>{run_id}</code>\n\n"
        f"Подтвердите запуск выгрузки:"
    )

    keyboard = [
        [
            InlineKeyboardButton('✅ Подтвердить выгрузку', callback_data=f'sch_sync_confirm_{run_id}'),
            InlineKeyboardButton('❌ Отмена', callback_data=f'sch_sync_cancel_{run_id}')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.effective_message.reply_text(
        text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
    )


async def handle_sync_schedule_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await _bot_is_admin(update, context):
        await query.edit_message_text("Недостаточно прав для выполнения операции.")
        return

    session = context.session
    cb_data = query.data
    run_id = cb_data.replace('sch_sync_confirm_', '')

    sync_run = await db_postgres.get_schedule_sync_run(session, run_id)
    if not sync_run or sync_run.status != 'created':
        await query.edit_message_text("⚠️ Запуск не найден или уже был обработан.")
        return

    await db_postgres.update_schedule_sync_run(session, run_id, status='running', auto_commit=True)
    await db_postgres.update_schedule_changes_sync_status(
        session,
        change_ids=sync_run.change_ids,
        sync_status='in_progress',
        sync_run_id=run_id,
        auto_commit=True
    )

    try:
        await publish_sync_schedule(
            sheet_id=sync_run.spreadsheet_id,
            run_id=run_id,
            items=sync_run.payload.get('items', [])
        )
        await query.edit_message_text(
            f"⏳ <b>Выгрузка запущена</b>\n\n"
            f"ID запуска: <code>{run_id}</code>\n"
            f"Результат будет опубликован в теме «Изменения расписания».",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception(f"Failed to publish sync_schedule task: {e}")
        await db_postgres.update_schedule_sync_run(session, run_id, status='failed', report_error=str(e), auto_commit=True)
        await query.edit_message_text(f"❌ Ошибка отправки задания в очередь: {e}")


async def handle_sync_schedule_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await _bot_is_admin(update, context):
        return

    session = context.session
    cb_data = query.data
    run_id = cb_data.replace('sch_sync_cancel_', '')

    sync_run = await db_postgres.get_schedule_sync_run(session, run_id)
    if sync_run and sync_run.status == 'created':
        await db_postgres.update_schedule_sync_run(session, run_id, status='cancelled', auto_commit=True)

    await query.edit_message_text("❌ Выгрузка отменена.")

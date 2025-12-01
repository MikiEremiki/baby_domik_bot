import logging
from datetime import datetime, timezone
from typing import Dict, List

import sqlalchemy as sa
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest

from db import (
    TheaterEvent, ScheduleEvent, User, Ticket, SalesRecipient, SalesCampaign)
from db.enum import TicketStatus
from db.models import UserTicket
from db.sales_crud import (
    create_campaign, set_campaign_schedules, snapshot_recipients,
    update_campaign_message, set_campaign_status, get_free_places
)
from api.sales_pub import publish_sales
from handlers import init_conv_hl_dialog
from utilities.utl_func import set_back_context
from utilities.utl_kbd import (
    create_replay_markup, remove_intent_id, add_intent_id, adjust_kbd,
    add_btn_back_and_cancel)
from settings.settings import DICT_CONVERT_WEEKDAY_NUMBER_TO_STR, URL_BOT

sales_logger = logging.getLogger('bot.sales')

PAGE_SIZE = 8
TZ = pytz.timezone('Europe/Moscow')

# States (conversation will import these)
MENU = 'MENU'
PICK_TYPE = 'PICK_TYPE'
PICK_THEATER = 'PICK_THEATER'
PICK_SCOPE = 'PICK_SCOPE'
PICK_SCHEDULES = 'PICK_SCHEDULES'
PICK_AUDIENCE_THEATER = 'PICK_AUDIENCE_THEATER'
BUILD_AUDIENCE = 'BUILD_AUDIENCE'
GET_MESSAGE = 'GET_MESSAGE'
PREVIEW = 'PREVIEW'

# Sales types registry
SALES_TYPES: Dict[str, Dict] = {
    "WAS_THIS_YEAR_ON_PLAY": {
        "title": ("Рассылка о свободных местах на выбранный спектакль."
                  " По людям, которые посещали спектакль/спектакли"),
        "enabled": True,
        "start_state": PICK_THEATER,
    },
    # "ATTENDED_SCHEDULE": {
    #     "title": "Были на конкретном сеансе…",
    #     "enabled": False,
    #     "start_state": None,
    # },
    # "WAITLIST_BY_PLAY": {
    #     "title": "Лист ожидания по спектаклю…",
    #     "enabled": False,
    #     "start_state": None,
    # },
    # "STUDIO_BUYERS": {
    #     "title": "Покупали студию…",
    #     "enabled": False,
    #     "start_state": None,
    # },
    # "SEGMENT_RULES": {
    #     "title": "По сегментам (возраст/скидки)…",
    #     "enabled": False,
    #     "start_state": None,
    # },
}


def _get_usage_text_for_type(type_code: str) -> str:
    """Return a short contextual instruction shown right after type selection."""
    if type_code == "WAS_THIS_YEAR_ON_PLAY":
        return (
            '<b>Как пользоваться этим типом рассылки:</b>\n'
            '1) Выберите спектакль.\n'
            '2) Выберите охват сеансов: все доступные или вручную по датам.\n'
            '3) Выберите спектакль(и), по которым отберём аудиторию — тех, кто уже был в этом году.\n'
            '4) Пришлите текст или одно медиа с подписью, проверьте предпросмотр и запустите.'
        )
    # Default hint for future types
    return (
        '<b>Как пользоваться:</b>\n'
        '1) Следуйте шагам мастера: выберите объект, задайте охват, подготовьте сообщение.\n'
        '2) Проверьте предпросмотр и запустите рассылку.'
    )


async def _ensure_campaign_and_schedules(update: Update,
                                         context: ContextTypes.DEFAULT_TYPE):
    """Create a SalesCampaign if needed and persist selected schedules."""
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
    theater_id = int(sales_state['theater_event_id'])
    schedule_ids: List[int] = list(
        map(int, sales_state.get('schedule_ids', [])))
    if not schedule_ids:
        return None

    # Load theater name for title
    te_row = (await session.execute(
        TheaterEvent.__table__.select().where(
            TheaterEvent.__table__.c.id == theater_id)
    )).mappings().first()
    theater_name = te_row['name'] if te_row else f"#{theater_id}"

    title = f"Продажи: {theater_name} ({len(schedule_ids)} сеансов)"
    campaign = await create_campaign(
        session,
        created_by_admin_id=update.effective_user.id,
        type=sales_state.get('type', 'WAS_THIS_YEAR_ON_PLAY'),
        theater_event_id=theater_id,
        title=title,
        status='draft',
    )
    campaign_id = campaign.id
    sales_state['campaign_id'] = campaign_id
    # Persist schedules set (idempotent with UniqueConstraint)
    await set_campaign_schedules(session, campaign_id, schedule_ids)
    await session.flush()
    await session.commit()
    return campaign_id


async def _select_audience_rows(session, theater_event_ids: List[int]) -> List[
    tuple]:
    """Return the list of (user_id, chat_id) for users who attended in the current year
    for any of the given theater_event_ids.
    """
    if not theater_event_ids:
        return []
    now = datetime.now(timezone.utc)
    year_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    next_year_start = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)

    t = Ticket.__table__
    ut = UserTicket.__table__
    u = User.__table__
    se = ScheduleEvent.__table__

    statuses = [TicketStatus.PAID, TicketStatus.APPROVED]

    stmt = (
        sa.select(u.c.user_id, u.c.chat_id)
        .select_from(ut
                     .join(t, ut.c.ticket_id == t.c.id)
                     .join(u, ut.c.user_id == u.c.user_id)
                     .join(se, t.c.schedule_event_id == se.c.id))
        .where(t.c.status.in_(statuses))
        .where(se.c.theater_event_id.in_(list(map(int, theater_event_ids))))
        .where(se.c.datetime_event >= year_start)
        .where(se.c.datetime_event < next_year_start)
        .where(u.c.chat_id.isnot(None))
    )
    rows = (await session.execute(stmt)).all()
    # Dedup by chat_id while preserving user_id (first occurrence)
    seen = set()
    result = []
    for user_id, chat_id in rows:
        if chat_id in seen:
            continue
        seen.add(chat_id)
        result.append((user_id, chat_id))
    return result


async def show_build_audience(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Build audience snapshot and show summary. In dev mode prompt to enter chat_id list; otherwise proceed to GET_MESSAGE."""
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
    # Determine which theater_event(s) to use for audience filter
    theater_ids: List[int] = list(
        map(int, sales_state.get('audience_theater_ids') or []))
    if not theater_ids:
        # fallback to main selected theater
        theater_ids = [int(sales_state['theater_event_id'])]
    campaign_id = await _ensure_campaign_and_schedules(update, context)

    # Take a snapshot from DB
    rows = await _select_audience_rows(session, theater_ids)
    inserted = await snapshot_recipients(session, campaign_id, rows)
    await session.flush()
    await session.commit()

    # Get counts for reporting
    total_found = len(rows)
    total_pending = inserted

    # Build info about selected audience theaters
    audience_info = ''
    try:
        if theater_ids:
            names = (await session.execute(sa.select(TheaterEvent.name).where(
                TheaterEvent.id.in_(theater_ids)))).scalars().all()
            if names:
                audience_info = f"\nФильтр по спектаклям для аудитории: {', '.join(names)}"
    except Exception:
        pass

    text_lines = [
        'Отбор аудитории завершён.',
        f'Всего найдено уникальных пользователей: {total_found}',
        f'Добавлено получателей (pending): {total_pending}',
        audience_info,
    ]
    if sales_state.get('dev_mode'):
        text_lines.append(
            '\nDev-режим: отправьте одним сообщением список chat_id через пробелы или переносы строк.\nПример: 123 456 789')

    await update.effective_chat.send_message(
        text='\n'.join([t for t in text_lines if t is not None and t != '']),
        message_thread_id=getattr(update.effective_message, 'message_thread_id',
                                  None)
    )
    if sales_state.get('dev_mode'):
        return BUILD_AUDIENCE
    # Prompt for a message right away in normal mode
    return await ask_message(update, context)


async def input_dev_chat_ids(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """Parse admin-provided chat_ids in dev mode and replace recipients' snapshot, then ask for a message."""
    sales_state = context.user_data.setdefault('sales', {})
    if not sales_state.get('dev_mode'):
        await update.effective_chat.send_message(
            'Этот шаг доступен только в dev-режиме. Используйте /sales dev')
        return BUILD_AUDIENCE

    text = (update.effective_message.text or '').strip()
    raw = text.replace(',', ' ').replace('\n', ' ').split()
    chat_ids = []
    for token in raw:
        try:
            cid = int(token)
            chat_ids.append(cid)
        except ValueError:
            continue
    uniq = sorted(set(chat_ids))
    if not uniq:
        await update.effective_chat.send_message(
            'Не найдено ни одного корректного chat_id. Повторите ввод.')
        return BUILD_AUDIENCE

    session = context.session
    campaign_id = sales_state.get('campaign_id')
    # Replace recipients' snapshot
    await session.execute(sa.delete(SalesRecipient.__table__).where(
        SalesRecipient.__table__.c.campaign_id == campaign_id))
    await snapshot_recipients(session, campaign_id,
                              [(cid, cid) for cid in uniq])
    await session.flush()
    await session.commit()

    await update.effective_chat.send_message(
        f'Dev-режим: список получателей заменён. Всего chat_id: {len(uniq)}')
    # Proceed to message capture
    return await ask_message(update, context)


async def _show_pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Build numbered short list and numeric buttons (usage hint will be shown after selection)
    lines = [
        '<b>Рассылки/Продажи</b>\n',
        'Выберите тип рассылки, нажав на цифру под списком.',
        '\nДоступные типы:'
    ]
    # Map numbers to type codes and prepare buttons 1..N
    number_to_code: Dict[int, str] = {}
    i = 0
    for code, meta in SALES_TYPES.items():
        if not meta.get('enabled'):
            continue
        i += 1
        number_to_code[i] = code
        title = meta['title']
        lines.append(f"{i}. {title}")
    if i == 0:
        await update.effective_chat.send_message(
            'Нет доступных типов рассылок. Пожалуйста, попробуйте позже.')
        return MENU

    # Save mapping in user_data for this step
    context.user_data.setdefault('sales', {})['type_map'] = number_to_code

    text = '\n'.join(lines)
    kb: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(n), callback_data=str(n)) for n in
        range(1, i + 1)
    ]
    reply_markup = await create_replay_markup(
        kb,
        intent_id='sales:type',
        postfix_for_cancel='sales',
        add_back_btn=False,
        size_row=5
    )
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=getattr(update.effective_message, 'message_thread_id',
                                  None)
    )
    state = PICK_TYPE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return PICK_TYPE


async def start_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: /sales [dev]"""
    # Parse optional argument 'dev'
    args = context.args or []
    await init_conv_hl_dialog(update, context)
    context.user_data.setdefault('sales', {})
    context.user_data['sales']['dev_mode'] = False
    if args and args[0].lower() == 'dev':
        context.user_data['sales']['dev_mode'] = True
    sales_logger.info("/sales started by %s dev_mode=%s",
                      update.effective_user.id,
                      context.user_data['sales']['dev_mode'])

    # Show type selection
    return await _show_pick_type(update, context)


async def pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    _, type_code = remove_intent_id(data)

    # Support numeric selection mapped in user_data, fallback to legacy type_code
    sales_state = context.user_data.setdefault('sales', {})
    if type_code.isdigit():
        mapping = sales_state.get('type_map') or {}
        type_code = mapping.get(int(type_code))
    else:
        type_code = type_code

    meta = SALES_TYPES.get(type_code) if type_code else None
    if not meta:
        await query.edit_message_text("Неизвестный тип. Попробуйте ещё раз.")
        return await _show_pick_type(update, context)

    if not meta.get('enabled'):
        await query.answer("Скоро", show_alert=False)
        return PICK_TYPE

    context.user_data['sales']['type'] = type_code

    # Remove menu message
    await query.delete_message()

    # Show contextual usage hint after type selection
    try:
        text = _get_usage_text_for_type(type_code)
        if text:
            await update.effective_chat.send_message(
                text=text,
                message_thread_id=getattr(update.effective_message,
                                          'message_thread_id', None)
            )
    except Exception:
        pass

    # Go to pick theater
    return await show_pick_theater(update, context)


async def show_pick_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = context.session
    # Active repertoire only
    theaters = (await session.execute(
        TheaterEvent.__table__.select().where(
            TheaterEvent.flag_active_repertoire == True)
    )).mappings().all()

    if not theaters:
        await update.effective_chat.send_message(
            "Нет активных спектаклей в репертуаре.")
        return MENU

    # Build numbered list text and numeric buttons
    number_to_theater: Dict[int, int] = {}
    lines: List[str] = [
        '<b>Выберите спектакль по которому показывать доступные места</b>',
        'Нажмите на цифру под списком.'
    ]
    for idx, t in enumerate(theaters, start=1):
        number_to_theater[idx] = int(t['id'])
        name = t['name']
        lines.append(f"{idx}. {name}")

    # Save mapping for pick_theater
    context.user_data.setdefault('sales', {})['theater_map'] = number_to_theater

    kb: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(i), callback_data=str(i)) for i in
        range(1, len(number_to_theater) + 1)
    ]

    text = '\n'.join(lines)
    reply_markup = await create_replay_markup(
        kb,
        intent_id='sales:theater',
        postfix_for_cancel='sales',
        add_back_btn=True,
        postfix_for_back=PICK_TYPE,
        size_row=5
    )
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=getattr(update.effective_message, 'message_thread_id',
                                  None)
    )
    state = PICK_THEATER
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return PICK_THEATER


async def pick_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, payload = remove_intent_id(query.data)
    sales_state = context.user_data.setdefault('sales', {})

    # Support numeric selection via mapping, fallback to legacy theater id in payload
    theater_id_val = None
    if payload and payload.isdigit():
        mapping = sales_state.get('theater_map') or {}
        theater_id_val = mapping.get(int(payload))
    else:
        # Legacy behavior: payload contains theater_id directly
        try:
            theater_id_val = int(payload)
        except (TypeError, ValueError):
            theater_id_val = None

    if not theater_id_val:
        await query.edit_message_text(
            'Не удалось определить спектакль. Вернитесь и выберите снова.')
        return PICK_THEATER

    sales_state['theater_event_id'] = str(theater_id_val)

    await query.delete_message()

    # Show scope choice
    kb = [
        InlineKeyboardButton('Все доступные спектакли', callback_data='all'),
        InlineKeyboardButton('Выбрать даты/сеансы вручную',
                             callback_data='manual'),
    ]
    reply_markup = await create_replay_markup(
        kb,
        intent_id='sales:scope',
        postfix_for_cancel='sales',
        add_back_btn=True,
        postfix_for_back=PICK_THEATER,
        size_row=1
    )
    text = 'Выберите охват спектаклей для показа свободных мест'
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=getattr(update.effective_message, 'message_thread_id',
                                  None)
    )
    state = PICK_SCOPE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return PICK_SCOPE


async def pick_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, scope = remove_intent_id(query.data)

    if scope == 'manual':
        # Go to manual schedules selection
        await query.delete_message()
        return await show_pick_schedules(update, context, page=1)

    # scope == 'all' -> collect schedules by availability rules
    theater_id = context.user_data['sales'].get('theater_event_id')
    if not theater_id:
        await query.edit_message_text(
            'Спектакль не выбран. Вернитесь на шаг назад.')
        return PICK_THEATER

    session = context.session
    now = datetime.now(timezone.utc)

    # Build query: schedule.flag_turn_in_bot = true AND theater.flag_active_repertoire = true AND schedule.datetime_event > now
    se = ScheduleEvent.__table__
    te = TheaterEvent.__table__
    stmt = (
        sa.select(se)
        .join(te, se.c.theater_event_id == te.c.id)
        .where(se.c.theater_event_id == int(theater_id))
        .where(se.c.flag_turn_in_bot == True)
        .where(te.c.flag_active_repertoire == True)
        .where(se.c.datetime_event > now)
        .order_by(se.c.datetime_event.asc())
    )
    rows = (await session.execute(stmt)).mappings().all()
    schedule_ids = [r['id'] for r in rows]
    context.user_data['sales']['schedule_ids'] = schedule_ids

    # Ensure a campaign exists and persist schedules
    await _ensure_campaign_and_schedules(update, context)

    # Proceed to choose theater(s) for audience filter
    return await show_pick_audience_theater(update, context)


# --- Audience theaters selection (PICK_AUDIENCE_THEATER) ---
async def show_pick_audience_theater(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE):
    """Let admin choose theater_event(s) to filter audience 'already attended this year'.
    Text shows a numbered list, buttons are numeric (1..N), selection is multi-select with Done.
    """
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
    # Initialize selection with the primary chosen theater if empty
    selected: set = set(sales_state.get('audience_theater_ids') or [])
    if not selected and sales_state.get('theater_event_id'):
        try:
            selected.add(int(sales_state['theater_event_id']))
        except Exception:
            pass
    sales_state['audience_theater_ids'] = list(selected)

    # Load active repertoire
    rows = (await session.execute(
        TheaterEvent.__table__.select().where(
            TheaterEvent.flag_active_repertoire == True)
    )).mappings().all()

    if not rows:
        await update.effective_chat.send_message(
            "Нет активных спектаклей в репертуаре.")
        return MENU

    # Build numbered text and numeric buttons
    number_to_tid: Dict[int, int] = {}
    lines: List[str] = [
        '<b>Выберите спектакль(и) для фильтра аудитории</b>',
        'Отметьте цифрами под списком, затем нажмите «Готово».',
        'По этим спектаклям будут выбраны пользователи, которые уже были в текущем году.',
    ]
    for idx, r in enumerate(rows, start=1):
        t_id = int(r['id'])
        number_to_tid[idx] = t_id
        mark = '✅' if t_id in selected else '▫️'
        lines.append(f"{idx}. {mark} {r['name']}")

    # Save mapping for numeric callbacks
    sales_state['aud_theater_map'] = number_to_tid

    num_buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(i), callback_data=str(i)) for i in
        range(1, len(number_to_tid) + 1)
    ]
    btn_rows = adjust_kbd(num_buttons, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:aud_theater')
    done_row = add_intent_id(
        [[InlineKeyboardButton('Готово', callback_data='done')]],
        'sales:aud_theater')
    kb = btn_rows + done_row
    kb.append(
        add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                postfix_for_back=PICK_SCOPE))
    reply_markup = InlineKeyboardMarkup(kb)

    text = '\n'.join(lines)

    await update.effective_message.delete()
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=getattr(update.effective_message, 'message_thread_id',
                                  None)
    )
    state = PICK_AUDIENCE_THEATER
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return PICK_AUDIENCE_THEATER


async def pick_audience_theater(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sales_state = context.user_data.setdefault('sales', {})
    intent_id, payload = remove_intent_id(query.data)

    selected: set = set(map(int, sales_state.get('audience_theater_ids') or []))

    # Toggle selection by numeric button or legacy toggle:<id>
    t_id: int | None = None
    if payload.isdigit():
        mapping = sales_state.get('aud_theater_map') or {}
        t_id = mapping.get(int(payload))
    elif payload.startswith('toggle:'):
        try:
            t_id = int(payload.split(':', 1)[1])
        except ValueError:
            t_id = None

    if t_id is not None:
        if t_id in selected:
            selected.remove(t_id)
        else:
            selected.add(t_id)
        sales_state['audience_theater_ids'] = list(selected)

    if payload == 'done':
        if not selected:
            await query.answer('Выберите хотя бы один спектакль',
                               show_alert=True)
            return PICK_AUDIENCE_THEATER
        # proceed to build audience
        await query.edit_message_reply_markup()
        return await show_build_audience(update, context)

    # re-render message with numbered list + numeric buttons
    session = context.session
    rows = (await session.execute(
        TheaterEvent.__table__.select().where(
            TheaterEvent.flag_active_repertoire == True)
    )).mappings().all()

    number_to_tid: Dict[int, int] = {}
    lines: List[str] = [
        '<b>Выберите спектакль(и) для фильтра аудитории</b>',
        'Отметьте цифрами под списком, затем нажмите «Готово».',
        'По этим спектаклям будут выбраны пользователи, которые уже были в текущем году.',
    ]
    for idx, r in enumerate(rows, start=1):
        t_id = int(r['id'])
        number_to_tid[idx] = t_id
        mark = '✅' if t_id in selected else '▫️'
        lines.append(f"{idx}. {mark} {r['name']}")

    # Save mapping for numeric callbacks
    sales_state['aud_theater_map'] = number_to_tid

    num_buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(i), callback_data=str(i)) for i in
        range(1, len(number_to_tid) + 1)
    ]
    btn_rows = adjust_kbd(num_buttons, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:aud_theater')
    done_row = add_intent_id(
        [[InlineKeyboardButton('Готово', callback_data='done')]],
        'sales:aud_theater')
    kb = btn_rows + done_row
    kb.append(
        add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                postfix_for_back=PICK_SCOPE))
    reply_markup = InlineKeyboardMarkup(kb)

    text = '\n'.join(lines)
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup)
    except BadRequest as e:
        if 'Message is not modified' in str(e):
            sales_logger.info('Игнорируем клик без изменений')
        else:
            sales_logger.error(e)

    state = PICK_AUDIENCE_THEATER
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return PICK_AUDIENCE_THEATER


# --- Manual schedules selection (PICK_SCHEDULES) ---
async def _get_available_schedules(session, theater_id: int):
    now = datetime.now(timezone.utc)
    se = ScheduleEvent.__table__
    te = TheaterEvent.__table__
    stmt = (
        sa.select(se)
        .join(te, se.c.theater_event_id == te.c.id)
        .where(se.c.theater_event_id == int(theater_id))
        .where(se.c.flag_turn_in_bot == True)
        .where(te.c.flag_active_repertoire == True)
        .where(se.c.datetime_event > now)
        .order_by(se.c.datetime_event.asc())
    )
    return (await session.execute(stmt)).mappings().all()


def _format_label(dt_utc, selected: bool) -> str:
    dt_local = dt_utc.astimezone(TZ)
    weekday = int(dt_local.strftime('%w'))
    date_txt = dt_local.strftime('%d.%m ')
    time_txt = dt_local.strftime('%H:%M')
    pref = '✅' if selected else '▫️'
    return f"{pref} {date_txt}({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]}) {time_txt}"


async def show_pick_schedules(update: Update,
                              context: ContextTypes.DEFAULT_TYPE,
                              page: int = 1):
    sales_state = context.user_data.setdefault('sales', {})
    theater_id = sales_state.get('theater_event_id')
    if not theater_id:
        await update.effective_chat.send_message(
            'Спектакль не выбран. Вернитесь на шаг назад.')
        return PICK_THEATER

    session = context.session
    # Fetch available schedules for manual selection (no caching in user_data)
    rows = await _get_available_schedules(session, int(theater_id))

    # Ensure a selected set exists
    sales_state.setdefault('manual_selected_ids', set())

    # Store the current page as 1-based for UI
    page1 = max(1, int(page))
    sales_state['page1'] = page1

    # Build event buttons for the current page (mixed intents like reserve.choice_show)
    total = len(rows)
    pages_total = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start_idx = (page1 - 1) * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total)

    event_buttons: List[InlineKeyboardButton] = []
    for r in rows[start_idx:end_idx]:
        sid = r['id']
        selected = sid in sales_state['manual_selected_ids']
        label = _format_label(r['datetime_event'], selected)
        event_buttons.append(
            InlineKeyboardButton(label, callback_data=f"toggle:{sid}"))

    # Apply intent to event rows and done row
    event_rows = adjust_kbd(event_buttons, 2)
    event_rows = add_intent_id(event_rows, 'sales:schedule')

    # Pagination row with separate intent
    nav_row = []
    if page1 > 1:
        nav_row.append(
            InlineKeyboardButton('« Пред', callback_data=str(page1 - 1)))
    nav_row.append(InlineKeyboardButton(f'{page1}/{pages_total}',
                                        callback_data=str(page1)))
    if page1 < pages_total:
        nav_row.append(
            InlineKeyboardButton('След »', callback_data=str(page1 + 1)))
    nav_rows = add_intent_id([nav_row], 'sales:schedule_page')

    # Add a separate row for Done
    done_row = [InlineKeyboardButton('Готово', callback_data='done')]
    done_row = add_intent_id([done_row], 'sales:schedule')

    # Combine and add back/cancel
    kb = event_rows + nav_rows + done_row
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales',
                                      add_back_btn=True,
                                      postfix_for_back=PICK_SCOPE))
    reply_markup = InlineKeyboardMarkup(kb)

    hdr = 'Выберите даты/сеансы вручную (нажимайте, чтобы отметить/снять).\n'
    pager = f"Стр. {page1}/{pages_total}\n"
    info = f"Всего доступно: {total}. Выбрано: {len(sales_state['manual_selected_ids'])}"
    await update.effective_chat.send_message(
        text=hdr + pager + info,
        reply_markup=reply_markup,
        message_thread_id=getattr(update.effective_message,
                                  'message_thread_id',
                                  None)
    )
    return PICK_SCHEDULES


async def pick_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sales_state = context.user_data.setdefault('sales', {})
    intent_id, payload = remove_intent_id(query.data)

    # Ensure cache exists
    if 'all_schedules' not in sales_state:
        theater_id = sales_state.get('theater_event_id')
        if not theater_id:
            await query.answer(
                'Спектакль не выбран. Вернитесь на шаг назад.', show_alert=True)
            return PICK_THEATER
        sales_state['all_schedules'] = await _get_available_schedules(
            context.session, int(theater_id))
        sales_state.setdefault('manual_selected_ids', set())
        sales_state.setdefault('page1', 1)

    if intent_id == 'sales:schedule_page':
        # Payload is a page number (1-based)
        try:
            page1_new = max(1, int(payload))
        except (TypeError, ValueError):
            page1_new = sales_state.get('page1', 1)
        total = len(sales_state['all_schedules'])
        pages_total = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if page1_new > pages_total:
            page1_new = pages_total
        sales_state['page1'] = page1_new
    elif intent_id == 'sales:schedule':
        # toggle/done callbacks
        if payload.startswith('toggle:'):
            try:
                sid = int(payload.split(':', 1)[1])
            except ValueError:
                sid = None
            if sid is not None:
                sel: set = sales_state.setdefault('manual_selected_ids', set())
                if sid in sel:
                    sel.remove(sid)
                else:
                    sel.add(sid)
        elif payload == 'done':
            selected_ids = list(sales_state.get('manual_selected_ids', set()))
            if not selected_ids:
                await query.answer('Выберите хотя бы один сеанс',
                                   show_alert=True)
                return PICK_SCHEDULES

            await query.edit_message_reply_markup()
            # Save final selection into common field
            context.user_data['sales']['schedule_ids'] = selected_ids
            # Proceed to choose theater(s) for audience filter
            return await show_pick_audience_theater(update, context)

    # Re-render current page using mixed-intent keyboard
    page1 = int(sales_state.get('page1', 1))
    all_rows = sales_state.get('all_schedules', [])
    total = len(all_rows)
    pages_total = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start_idx = (page1 - 1) * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total)

    event_buttons: List[InlineKeyboardButton] = []
    for r in all_rows[start_idx:end_idx]:
        sid = r['id']
        selected = sid in sales_state.get('manual_selected_ids', set())
        label = _format_label(r['datetime_event'], selected)
        event_buttons.append(
            InlineKeyboardButton(label, callback_data=f"toggle:{sid}"))

    # Apply intent to event rows and done row
    event_rows = adjust_kbd(event_buttons, 2)
    event_rows = add_intent_id(event_rows, 'sales:schedule')

    # Pagination row with separate intent
    nav_row = []
    if page1 > 1:
        nav_row.append(
            InlineKeyboardButton('« Пред', callback_data=str(page1 - 1)))
    nav_row.append(InlineKeyboardButton(f'{page1}/{pages_total}',
                                        callback_data=str(page1)))
    if page1 < pages_total:
        nav_row.append(
            InlineKeyboardButton('След »', callback_data=str(page1 + 1)))
    nav_rows = add_intent_id([nav_row], 'sales:schedule_page')

    # Add a separate row for Done
    done_row = [InlineKeyboardButton('Готово', callback_data='done')]
    done_row = add_intent_id([done_row], 'sales:schedule')

    # Combine and add back/cancel
    kb = event_rows + nav_rows + done_row
    kb.append(
        add_btn_back_and_cancel(postfix_for_cancel='sales',
                                add_back_btn=True,
                                postfix_for_back=PICK_SCOPE))
    reply_markup = InlineKeyboardMarkup(kb)

    hdr = 'Выберите даты/сеансы вручную (нажимайте, чтобы отметить/снять).\n'
    pager = f"Стр. {page1}/{pages_total}\n"
    info = f"Всего доступно: {total}. Выбрано: {len(sales_state.get('manual_selected_ids', set()))}"

    text = hdr + pager + info
    try:
        await query.edit_message_text(text,
                                      reply_markup=reply_markup)
    except BadRequest as e:
        if 'Message is not modified' in str(e):
            sales_logger.info(
                'Игнорируем клик по текущей странице (без изменений)')
        else:
            sales_logger.error(e)
    state = PICK_SCHEDULES
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return PICK_SCHEDULES


# --- Step 5–6: admin message capture and preview ---
async def ask_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END
    text = (
        'Шаг 5 — отправьте сообщение для рассылки.\n\n'
        'Допустимые варианты:\n'
        '• Текстовое сообщение\n'
        ' ИЛИ\n'
        '• Одно фото/видео/анимация с подписью\n\n'
        'Медиа-группы (альбомы) пока не поддерживаются.'
    )

    reply_markup = InlineKeyboardMarkup([
        add_btn_back_and_cancel(postfix_for_cancel='sales',
                                add_back_btn=True,
                                postfix_for_back=PICK_SCOPE)])
    await update.effective_chat.send_message(text, reply_markup=reply_markup)
    state = GET_MESSAGE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return GET_MESSAGE


def _serialize_entities(entities):
    try:
        return [e.to_dict() for e in (entities or [])]
    except Exception:
        return None


async def handle_admin_message(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Store admin message payload into SalesCampaign and proceed to preview."""
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END

    msg = update.effective_message
    fields = {
        'message_kind': None,
        'message_text': None,
        'message_entities': None,
        'caption_text': None,
        'caption_entities': None,
        'photo_file_id': None,
        'video_file_id': None,
        'animation_file_id': None,
    }

    # Media group is not supported: PTB exposes media_group_id
    if getattr(msg, 'media_group_id', None):
        await update.effective_chat.send_message(
            'Альбомы пока не поддерживаются. Отправьте один медиафайл с подписью или просто текст.')
        return GET_MESSAGE

    if msg.photo:
        fields['message_kind'] = 'photo'
        fields['caption_text'] = msg.caption_html or ''
        fields['caption_entities'] = _serialize_entities(msg.caption_entities)
        fields['photo_file_id'] = msg.photo[-1].file_id
    elif msg.video:
        fields['message_kind'] = 'video'
        fields['caption_text'] = msg.caption_html or ''
        fields['caption_entities'] = _serialize_entities(msg.caption_entities)
        fields['video_file_id'] = msg.video.file_id
    elif msg.animation:
        fields['message_kind'] = 'animation'
        fields['caption_text'] = msg.caption_html or ''
        fields['caption_entities'] = _serialize_entities(msg.caption_entities)
        fields['animation_file_id'] = msg.animation.file_id
    elif msg.text:
        fields['message_kind'] = 'text'
        fields['message_text'] = msg.text_html or ''
        fields['message_entities'] = _serialize_entities(msg.entities)
    else:
        await update.effective_chat.send_message(
            'Поддерживаются только текст, фото, видео, анимация.')
        return GET_MESSAGE

    # Persist
    await update_campaign_message(context.session, campaign_id, **fields)
    await context.session.commit()

    # Go to preview
    return await show_preview(update, context)


async def _format_availability_block(session, schedule_ids: List[int]) -> str:
    if not schedule_ids:
        return 'Внимание: не выбраны сеансы.'
    free = await get_free_places(session, schedule_ids)
    if not free:
        return 'Кол-во свободных мест: нет данных.'
    # need datetime
    rows = (await session.execute(
        sa.select(ScheduleEvent.id, ScheduleEvent.datetime_event)
        .where(ScheduleEvent.id.in_(list(map(int, schedule_ids))))
        .order_by(ScheduleEvent.datetime_event)
    )).all()
    lines = ['Кол-во свободных мест:', '⬇️Дата Время — Детских | Взрослых⬇️']
    for sid, dt in rows:
        dt_local = dt.astimezone(TZ)
        weekday = int(dt_local.strftime('%w'))
        date_txt = dt_local.strftime('%d.%m ')
        time_txt = dt_local.strftime('%H:%M')
        fc, fa = free.get(int(sid), (0, 0))
        lines.append(
            f"{date_txt}({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]}) {time_txt} — {fc} дет | {fa} взр")
    return '\n'.join(lines)


async def show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END

    session = context.session
    campaign: SalesCampaign = await session.get(SalesCampaign, campaign_id)
    schedule_ids: List[int] = context.user_data['sales'].get('schedule_ids', [])

    # Availability block
    availability_block = await _format_availability_block(session, schedule_ids)

    # Recipients' count
    pending_cnt = (await session.execute(
        sa.select(sa.func.count()).select_from(SalesRecipient).where(
            SalesRecipient.campaign_id == campaign_id)
    )).scalar() or 0

    reserve_text = (f"👉 /reserve команда для покупки билетов\n"
                    f"Выбирайте подходящий спектакль и следуйте инструкциям")

    # Build keyboard: first row with the DeepLink URL button, next rows with actions under intent
    action_rows = [
        [InlineKeyboardButton('Запустить', callback_data='run')],
        [InlineKeyboardButton('Изменить текст', callback_data='edit_text')],
        [InlineKeyboardButton('Изменить сеансы',
                              callback_data='edit_schedules')],
        [InlineKeyboardButton('Отмена', callback_data='cancel')],
    ]
    action_rows = add_intent_id(action_rows, 'sales:preview')
    reply_markup = InlineKeyboardMarkup(action_rows)

    # Compose message
    kind = campaign.message_kind
    if kind == 'text':
        text = (campaign.message_text or '')
        text = text + '\n\n' + availability_block + f"\n\n{reserve_text}"
        await update.effective_chat.send_message(text=text,
                                                 reply_markup=reply_markup,
                                                 disable_web_page_preview=True)
    elif kind == 'photo' and campaign.photo_file_id:
        caption = (campaign.caption_text or '')
        caption = caption + '\n\n' + availability_block + f"\n\n{reserve_text}"
        await update.effective_chat.send_photo(photo=campaign.photo_file_id,
                                               caption=caption,
                                               reply_markup=reply_markup)
    elif kind == 'video' and campaign.video_file_id:
        caption = (campaign.caption_text or '')
        caption = caption + '\n\n' + availability_block + f"\n\n{reserve_text}"
        await update.effective_chat.send_video(video=campaign.video_file_id,
                                               caption=caption,
                                               reply_markup=reply_markup)
    elif kind == 'animation' and campaign.animation_file_id:
        caption = (campaign.caption_text or '')
        caption = caption + '\n\n' + availability_block + f"\n\n{reserve_text}"
        await update.effective_chat.send_animation(
            animation=campaign.animation_file_id,
            caption=caption,
            reply_markup=reply_markup)
    else:
        text = 'Сообщение кампании не задано. Отправьте текст/медиа.'
        await update.effective_chat.send_message(text)
        return await ask_message(update, context)

    await update.effective_chat.send_message(
        f'Предпросмотр. Получателей: {pending_cnt}. Показов: {len(schedule_ids)}')

    return PREVIEW


async def _safe_edit_message(query, text: str):
    try:
        msg = getattr(query, 'message', None)
        # If original message was media with caption, edit caption; else edit text
        if msg is not None and (
                getattr(msg, 'photo', None) or getattr(msg, 'video',
                                                       None) or getattr(msg,
                                                                        'animation',
                                                                        None)):
            await query.edit_message_caption(caption=text)
        else:
            await query.edit_message_text(text=text)
    except BadRequest as e:
        if 'Message is not modified' in str(e):
            sales_logger.info('Игнорируем редактирование без изменений')
        else:
            sales_logger.error('Failed to edit preview message: %s', e)


async def preview_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    if action == 'edit_text':
        await query.delete_message()
        return await ask_message(update, context)
    if action == 'edit_schedules':
        await query.delete_message()
        return await show_pick_schedules(update, context, page=1)
    if action == 'cancel':
        # mark canceled
        campaign_id = sales_state.get('campaign_id')
        await set_campaign_status(context.session, campaign_id, 'canceled')
        await context.session.commit()
        await _safe_edit_message(query, 'Кампания отменена.')
        return ConversationHandler.END
    if action == 'run':
        # Validate prerequisites
        session = context.session
        campaign_id = sales_state.get('campaign_id')
        if not campaign_id:
            await query.answer(
                'Внутренняя ошибка: нет кампании. Начните заново /sales',
                show_alert=True)
            return PREVIEW
        # Check message exists
        campaign: SalesCampaign = await session.get(SalesCampaign, campaign_id)
        if not campaign or not campaign.message_kind:
            await query.answer('Сначала задайте текст/медиа сообщения.',
                               show_alert=True)
            return PREVIEW
        # Check schedules
        schedule_ids: List[int] = context.user_data['sales'].get('schedule_ids',
                                                                 [])
        if not schedule_ids:
            await query.answer(
                'Не выбраны сеансы. Вернитесь и выберите даты/сеансы.',
                show_alert=True)
            return PREVIEW
        # Check recipients pending
        pending_cnt = (await session.execute(
            sa.select(sa.func.count()).select_from(SalesRecipient).where(
                (SalesRecipient.campaign_id == campaign_id) & (
                        SalesRecipient.status == 'pending')
            )
        )).scalar() or 0
        if pending_cnt <= 0:
            await query.answer('Аудитория пуста или уже отправлена.',
                               show_alert=True)
            return PREVIEW
        # Set running and publish task
        try:
            await set_campaign_status(session, campaign_id, 'running')
            await session.commit()
            await publish_sales(campaign_id)
        except Exception as e:
            sales_logger.exception('Failed to publish sales task: %s', e)
            try:
                await set_campaign_status(session, campaign_id, 'failed')
                await session.commit()
            except Exception:
                pass
            text = ('Не удалось запустить рассылку: ошибка публикации задачи.\n'
                    'Попробуйте позже.')
            await _safe_edit_message(query, text)
            return PREVIEW
        text = (f'Задача на рассылку опубликована.\nКампания #{campaign_id}\n'
                f'Статус кампании: running. Ожидайте отчёт по завершении.')
        await _safe_edit_message(query, text)
        return ConversationHandler.END
    # default
    return ConversationHandler.END

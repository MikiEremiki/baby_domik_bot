import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List

import sqlalchemy as sa
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest

from db import (
    TheaterEvent, ScheduleEvent, User, Ticket, SalesRecipient, SalesCampaign,
    TypeEvent, BaseTicket, db_postgres)
from db.enum import TicketStatus, AgeType
from db.models import UserTicket, Person, Child, PersonTicket
from db.sales_crud import (
    create_campaign, set_campaign_schedules, snapshot_recipients,
    update_campaign_message, set_campaign_status, get_free_places
)
from api.sales_pub import publish_sales
from handlers import init_conv_hl_dialog
from utilities.utl_func import set_back_context, get_full_name_event
from utilities.utl_kbd import (
    create_replay_markup, remove_intent_id, add_intent_id, adjust_kbd,
    add_btn_back_and_cancel)
from settings.settings import DICT_CONVERT_WEEKDAY_NUMBER_TO_STR

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

# New states for TICKET_HOLDERS filters
PICK_FILTERS = 'PICK_FILTERS'
PICK_FILTER_STATUS = 'PICK_FILTER_STATUS'
PICK_FILTER_TYPE_EVENT = 'PICK_FILTER_TYPE_EVENT'
PICK_FILTER_THEATER_EVENT = 'PICK_FILTER_THEATER_EVENT'
PICK_FILTER_SCHEDULE_EVENT = 'PICK_FILTER_SCHEDULE_EVENT'
PICK_FILTER_BASE_TICKET = 'PICK_FILTER_BASE_TICKET'
PICK_TICKET_IDS = 'PICK_TICKET_IDS'
PICK_FILTER_CHILD_AGE_MIN = 'PICK_FILTER_CHILD_AGE_MIN'
PICK_FILTER_CHILD_AGE_MAX = 'PICK_FILTER_CHILD_AGE_MAX'

# Sales types registry
SALES_TYPES: Dict[str, Dict] = {
    "WAS_THIS_YEAR_ON_PLAY": {
        "title": ("Рассылка о свободных местах на выбранный спектакль."
                  " По людям, которые посещали спектакль/спектакли"),
        "enabled": True,
        "start_state": PICK_THEATER,
    },
    "TICKET_HOLDERS": {
        "title": "Рассылка по обладателям билетов (с фильтрами)",
        "enabled": True,
        "start_state": PICK_FILTERS,
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
    if type_code == "TICKET_HOLDERS":
        return (
            '<b>Как пользоваться этим типом рассылки:</b>\n'
            '1) Задайте фильтры для отбора аудитории (статус билетов, спектакли, типы, сеансы, возраст детей или конкретные билеты).\n'
            '2) Событийные фильтры (спектакль/тип/сеанс) отключают фильтрацию по времени — вы получите всех, у кого есть билет на любой из выбранных объектов.\n'
            '3) Если фильтры не заданы, рассылка пойдёт по всем, у кого Оплаченные/Подтверждённые билеты на будущие сеансы.\n'
            '4) Пришлите текст или медиа, проверьте и запустите.'
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
    campaign_type = sales_state.get('type')

    theater_id_raw = sales_state.get('theater_event_id')
    theater_id = int(theater_id_raw) if theater_id_raw else None

    schedule_ids: List[int] = list(
        map(int, sales_state.get('schedule_ids', [])))

    if not schedule_ids and campaign_type != 'TICKET_HOLDERS':
        return None

    # Load theater name for title
    theater_name = "Без спектакля"
    if theater_id:
        te_row = (await session.execute(
            TheaterEvent.__table__.select().where(
                TheaterEvent.__table__.c.id == theater_id)
        )).mappings().first()
        theater_name = te_row['name'] if te_row else f"#{theater_id}"

    if campaign_type == 'TICKET_HOLDERS':
        title = f"Рассылка: Обладатели билетов ({datetime.now().strftime('%d.%m %H:%M')})"
    else:
        title = f"Продажи: {theater_name} ({len(schedule_ids)} сеансов)"

    campaign = await create_campaign(
        session,
        created_by_admin_id=update.effective_user.id,
        campaign_type=campaign_type,
        theater_event_id=theater_id,
        title=title,
        status='draft',
    )
    campaign_id = campaign.id
    sales_state['campaign_id'] = campaign_id

    if schedule_ids:
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
    start_period = now - timedelta(days=365)

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
        .where(se.c.datetime_event >= start_period)
        .where(se.c.datetime_event < now)
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


async def _select_ticket_holders_audience(session, sales_state: dict) -> tuple[List[tuple], List[int]]:
    """Return the list of (user_id, chat_id) and the list of ticket_ids."""
    filters = sales_state.get('filters', {})
    f_time = sales_state.get('f_schedule_time', 'future')
    f_show = sales_state.get('f_schedule_show', 'on')
    now = datetime.now(timezone.utc)

    t = Ticket.__table__
    ut = UserTicket.__table__
    u = User.__table__
    se = ScheduleEvent.__table__

    stmt = (
        sa.select(u.c.user_id, u.c.chat_id, t.c.id)
        .select_from(ut
                     .join(t, ut.c.ticket_id == t.c.id)
                     .join(u, ut.c.user_id == u.c.user_id)
                     .join(se, t.c.schedule_event_id == se.c.id))
        .where(u.c.chat_id.isnot(None))
    )

    if filters.get('ticket_ids'):
        # Manual IDs bypass other filters
        stmt = stmt.where(t.c.id.in_(list(map(int, filters['ticket_ids']))))
    else:
        if filters.get('status'):
            status_members = []
            for val in filters['status']:
                for member in TicketStatus:
                    if member.value == val:
                        status_members.append(member)
                        break
            if status_members:
                stmt = stmt.where(t.c.status.in_(status_members))

        has_event_filter = False
        if filters.get('type_event_ids'):
            stmt = stmt.where(se.c.type_event_id.in_(list(map(int, filters['type_event_ids']))))
            has_event_filter = True

        if filters.get('theater_event_ids'):
            stmt = stmt.where(se.c.theater_event_id.in_(list(map(int, filters['theater_event_ids']))))
            has_event_filter = True

        if filters.get('schedule_event_ids'):
            stmt = stmt.where(t.c.schedule_event_id.in_(list(map(int, filters['schedule_event_ids']))))
            has_event_filter = True

        if not has_event_filter:
            if f_time == 'past':
                stmt = stmt.where(se.c.datetime_event < now)
            elif f_time == 'future':
                stmt = stmt.where(se.c.datetime_event >= now)
            if f_show == 'on':
                stmt = stmt.where(se.c.flag_turn_in_bot == True)
            elif f_show == 'off':
                stmt = stmt.where(se.c.flag_turn_in_bot == False)

        if filters.get('base_ticket_ids'):
            stmt = stmt.where(t.c.base_ticket_id.in_(list(map(int, filters['base_ticket_ids']))))

        child_age_min = filters.get('child_age_min')
        child_age_max = filters.get('child_age_max')
        if child_age_min is not None or child_age_max is not None:
            pt = PersonTicket.__table__
            p = Person.__table__
            c = Child.__table__
            computed_age = sa.case(
                (c.c.birthdate.isnot(None), sa.func.date_part('year', sa.func.age(c.c.birthdate))),
                else_=c.c.age
            )
            child_subq_stmt = (
                sa.select(sa.literal(1))
                .select_from(pt.join(p, pt.c.person_id == p.c.id).join(c, c.c.person_id == p.c.id))
                .where(pt.c.ticket_id == t.c.id)
                .where(p.c.age_type == AgeType.child)
            )
            if child_age_min is not None:
                child_subq_stmt = child_subq_stmt.where(computed_age >= child_age_min)
            if child_age_max is not None:
                child_subq_stmt = child_subq_stmt.where(computed_age <= child_age_max)
            stmt = stmt.where(child_subq_stmt.exists())

    rows = (await session.execute(stmt)).all()
    
    # Dedup by chat_id while preserving user_id (first occurrence)
    seen = set()
    result_rows = []
    found_ticket_ids = []
    
    for user_id, chat_id, ticket_id in rows:
        found_ticket_ids.append(ticket_id)
        if chat_id in seen:
            continue
        seen.add(chat_id)
        result_rows.append((user_id, chat_id))
        
    return result_rows, sorted(list(set(found_ticket_ids)))


def _compress_ids(ids: List[int], max_chars: int = 200) -> str:
    """Convert sorted list of ints to range notation, e.g. [1,2,3,5,7,8] → '1–3, 5, 7–8'."""
    if not ids:
        return ''
    ranges = []
    start = prev = ids[0]
    for n in ids[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append(f"{start}–{prev}" if prev != start else str(start))
            start = prev = n
    ranges.append(f"{start}–{prev}" if prev != start else str(start))
    result = ', '.join(ranges)
    if len(result) > max_chars:
        result = result[:max_chars].rsplit(',', 1)[0] + ', …'
    return result


async def show_build_audience(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Build audience snapshot and show summary. In dev mode prompt to enter chat_id list; otherwise proceed to GET_MESSAGE."""
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
    campaign_type = sales_state.get('type')

    # Determine audience rows
    if campaign_type == 'TICKET_HOLDERS':
        rows, ticket_ids = await _select_ticket_holders_audience(session, sales_state)
        filters = sales_state.get('filters', {})
        f_time = sales_state.get('f_schedule_time', 'all')
        f_show = sales_state.get('f_schedule_show', 'all')
        filter_lines = []
        if filters.get('ticket_ids'):
            filter_lines.append("• ID билетов вручную")
        else:
            if filters.get('status'):
                filter_lines.append("• Статус билета")
            if filters.get('type_event_ids'):
                filter_lines.append("• Тип мероприятия")
            if filters.get('theater_event_ids'):
                filter_lines.append("• Спектакль")
            if filters.get('schedule_event_ids'):
                filter_lines.append("• Сеанс")
            if filters.get('base_ticket_ids'):
                filter_lines.append("• Базовый билет")
            if filters.get('child_age_min') is not None or filters.get('child_age_max') is not None:
                filter_lines.append("• Возраст детей")
            has_event = any([filters.get('type_event_ids'), filters.get('theater_event_ids'), filters.get('schedule_event_ids')])
            if not has_event:
                time_label = {'all': 'все', 'past': 'прошедшие', 'future': 'будущие'}.get(f_time, f_time)
                show_label = {'all': 'любая', 'on': 'вкл в боте', 'off': 'выкл в боте'}.get(f_show, f_show)
                filter_lines.append(f"• Время сеансов: {time_label}, видимость: {show_label}")
        filters_text = "\n<b>Применённые фильтры:</b>\n" + "\n".join(filter_lines) if filter_lines else "\n<b>Фильтры не заданы</b> (выбраны все билеты)"
        audience_info = "Аудитория: обладатели билетов." + filters_text
        if ticket_ids:
            audience_info += f"\n<b>ID билетов ({len(ticket_ids)}):</b> {_compress_ids(ticket_ids)}"
        postfix_for_back = PICK_FILTERS
    else:
        # Determine which theater_event(s) to use for audience filter
        theater_ids: List[int] = list(
            map(int, sales_state.get('audience_theater_ids') or []))
        if not theater_ids:
            # fallback to main selected theater
            theater_ids = [int(sales_state['theater_event_id'])]
        rows = await _select_audience_rows(session, theater_ids)

        audience_info = ''
        try:
            if theater_ids:
                names = (await session.execute(sa.select(TheaterEvent.name).where(
                    TheaterEvent.id.in_(theater_ids)))).scalars().all()
                if names:
                    audience_info = f"\nФильтр по спектаклям для аудитории: {', '.join(names)}"
        except Exception:
            pass
        postfix_for_back = PICK_AUDIENCE_THEATER

    campaign_id = await _ensure_campaign_and_schedules(update, context)

    # Take a snapshot from DB
    inserted = await snapshot_recipients(session, campaign_id, rows)
    await session.flush()
    await session.commit()

    # Get counts for reporting
    total_found = len(rows)
    total_pending = inserted

    text_lines = [
        '<b>Отбор аудитории завершён.</b>',
        f'Всего найдено уникальных пользователей: {total_found}',
        f'Добавлено получателей (pending): {total_pending}',
        audience_info,
    ]

    text = '\n'.join([t for t in text_lines if t is not None and t != ''])

    if sales_state.get('dev_mode'):
        text += '\n\nDev-режим: отправьте одним сообщением список chat_id через пробелы или переносы строк.\nПример: 123 456 789'
        kb = [InlineKeyboardButton("Далее (сообщение)", callback_data="next_message")]
        reply_markup = await create_replay_markup(
            kb,
            intent_id='sales',
            postfix_for_cancel='sales',
            add_back_btn=True,
            postfix_for_back=postfix_for_back,
            size_row=1
        )
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        state = BUILD_AUDIENCE
        await set_back_context(context, state, text, reply_markup)
        context.user_data['STATE'] = state
        return BUILD_AUDIENCE

    # Prompt for a message right away in normal mode; pass audience summary
    sales_state['audience_summary'] = text
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

    # Completely reset sales state to avoid leaking data from previous sessions
    context.user_data['sales'] = {
        'dev_mode': False,
        'type': None,
        'campaign_id': None,
        'theater_event_id': None,
        'schedule_ids': [],
        'filters': {},
        'audience_theater_ids': [],
        'f_schedule_time': 'all',
        'f_schedule_show': 'all',
    }

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

    # Go to next state based on type
    start_state = meta.get('start_state', PICK_THEATER)
    if start_state == PICK_FILTERS:
        return await show_pick_filters(update, context)

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


async def _proceed_to_audience_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper to route to the correct audience selection step based on campaign type."""
    sales_state = context.user_data.get('sales', {})
    campaign_type = sales_state.get('type')

    if campaign_type == 'TICKET_HOLDERS':
        return await show_pick_filters(update, context)

    # Default for WAS_THIS_YEAR_ON_PLAY
    return await show_pick_audience_theater(update, context)


# --- Filters for TICKET_HOLDERS type ---

async def show_pick_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    f_time = sales_state.get('f_schedule_time', 'future')
    f_show = sales_state.get('f_schedule_show', 'on')

    text = "<b>Настройка фильтров аудитории (Обладатели билетов)</b>\n\n"
    text += "Выберите критерии для отбора пользователей. Если фильтр не задан, он не учитывается.\n\n"

    # Show summary of selected filters
    status_list = filters.get('status', [])
    if status_list:
        text += f"✅ Статусы: {', '.join(status_list)}\n"
    if filters.get('type_event_ids'):
        text += f"✅ Типы событий: {len(filters['type_event_ids'])}\n"
    if filters.get('theater_event_ids'):
        text += f"✅ Спектакли: {len(filters['theater_event_ids'])}\n"
    if filters.get('schedule_event_ids'):
        text += f"✅ Сеансы: {len(filters['schedule_event_ids'])}\n"
    if filters.get('base_ticket_ids'):
        text += f"✅ Билеты: {len(filters['base_ticket_ids'])}\n"
    if filters.get('ticket_ids'):
        text += f"✅ ID билетов (вручную): {len(filters['ticket_ids'])}\n"
    child_age_min = filters.get('child_age_min')
    child_age_max = filters.get('child_age_max')
    if child_age_min is not None or child_age_max is not None:
        if child_age_min is not None and child_age_max is not None:
            text += f"✅ Возраст детей: от {child_age_min} до {child_age_max}\n"
        elif child_age_min is not None:
            text += f"✅ Возраст детей: {child_age_min}+\n"
        else:
            text += f"✅ Возраст детей: до {child_age_max}\n"

    # Time/show sub-filters (applied when no event filter is set)
    time_label = {'all': 'Все', 'past': 'Прошедшие', 'future': 'Будущие'}.get(f_time, f_time)
    show_label = {'all': 'Все', 'on': 'Вкл в боте', 'off': 'Выкл в боте'}.get(f_show, f_show)
    text += f"\n📅 Без событийного фильтра: <b>{time_label}</b>, видимость <b>{show_label}</b>"

    time_kb = add_intent_id([[
        InlineKeyboardButton(f"{'✅' if f_time == 'all' else '▫️'} Все", callback_data="time:all"),
        InlineKeyboardButton(f"{'✅' if f_time == 'past' else '▫️'} Прош.", callback_data="time:past"),
        InlineKeyboardButton(f"{'✅' if f_time == 'future' else '▫️'} Буд.", callback_data="time:future"),
    ]], 'sales:filters')
    show_kb = add_intent_id([[
        InlineKeyboardButton(f"{'✅' if f_show == 'all' else '▫️'} Любая", callback_data="show:all"),
        InlineKeyboardButton(f"{'✅' if f_show == 'on' else '▫️'} Вкл", callback_data="show:on"),
        InlineKeyboardButton(f"{'✅' if f_show == 'off' else '▫️'} Выкл", callback_data="show:off"),
    ]], 'sales:filters')

    has_filters = any([
        filters.get('status'), filters.get('type_event_ids'), filters.get('theater_event_ids'),
        filters.get('schedule_event_ids'), filters.get('base_ticket_ids'), filters.get('ticket_ids'),
        filters.get('child_age_min') is not None, filters.get('child_age_max') is not None,
    ])
    action_btns = [
        InlineKeyboardButton("Статус билета", callback_data="status"),
        InlineKeyboardButton("Тип мероприятия", callback_data="type_event"),
        InlineKeyboardButton("Спектакль", callback_data="theater_event"),
        InlineKeyboardButton("Сеанс", callback_data="schedule_event"),
        InlineKeyboardButton("Базовый билет", callback_data="base_ticket"),
        InlineKeyboardButton("Возраст детей", callback_data="child_age"),
        InlineKeyboardButton("Ввести ID билетов вручную", callback_data="manual_ids"),
    ]
    if has_filters:
        action_btns.append(InlineKeyboardButton("🗑 Сбросить фильтры", callback_data="reset"))
    action_btns.append(InlineKeyboardButton("ГОТОВО - Перейти к отбору", callback_data="done"))
    action_rows = adjust_kbd(action_btns, 1)
    action_rows = add_intent_id(action_rows, 'sales:filters')

    kb = time_kb + show_kb + action_rows
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=PICK_TYPE))
    reply_markup = InlineKeyboardMarkup(kb)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
        except BadRequest:
            await update.effective_chat.send_message(text=text, reply_markup=reply_markup)
    else:
        await update.effective_chat.send_message(text=text, reply_markup=reply_markup)

    state = PICK_FILTERS
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return PICK_FILTERS


async def back_to_pick_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live re-render of pick_filters screen (used instead of snapshot-based back)."""
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_filters(update, context)


async def pick_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    if action.startswith('time:'):
        sales_state['f_schedule_time'] = action.split(':')[1]
        return await show_pick_filters(update, context)
    if action.startswith('show:'):
        sales_state['f_schedule_show'] = action.split(':')[1]
        return await show_pick_filters(update, context)

    if action == "reset":
        sales_state = context.user_data.setdefault('sales', {})
        sales_state['filters'] = {}
        return await show_pick_filters(update, context)

    if action == "status":
        return await show_pick_filter_status(update, context)
    if action == "type_event":
        return await show_pick_filter_type_event(update, context)
    if action == "theater_event":
        return await show_pick_filter_theater_event(update, context)
    if action == "schedule_event":
        return await show_pick_filter_schedule_event(update, context)
    if action == "base_ticket":
        return await show_pick_filter_base_ticket(update, context)
    if action == "child_age":
        return await show_pick_filter_child_age_min(update, context)
    if action == "manual_ids":
        return await show_pick_ticket_ids(update, context)
    if action == "done":
        await query.delete_message()
        return await show_build_audience(update, context)

    return PICK_FILTERS


async def show_pick_filter_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.get('sales', {})
    filters = sales_state.get('filters', {})
    selected: set = set(filters.get('status') or [])

    number_to_status: Dict[int, str] = {}
    lines: List[str] = [
        "<b>Выберите статусы билетов</b>",
        "Отметьте цифрами под списком, затем нажмите «Готово»."
    ]

    for idx, s in enumerate(TicketStatus, start=1):
        number_to_status[idx] = s.value
        mark = '✅' if s.value in selected else '▫️'
        lines.append(f"{idx}. {mark} {s.value}")

    sales_state['filter_status_map'] = number_to_status

    num_buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(i), callback_data=str(i)) for i in
        range(1, len(TicketStatus) + 1)
    ]
    btn_rows = adjust_kbd(num_buttons, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:f_status')

    done_row = add_intent_id(
        [[InlineKeyboardButton("Готово", callback_data="done")]],
        'sales:f_status'
    )

    kb = btn_rows + done_row
    kb.append(
        add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                postfix_for_back=PICK_FILTERS))

    reply_markup = InlineKeyboardMarkup(kb)
    text = "\n".join(lines)

    await update.callback_query.edit_message_text(text=text,
                                                 reply_markup=reply_markup)
    return PICK_FILTER_STATUS


async def pick_filter_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    selected: set = set(filters.get('status') or [])

    if payload == "done":
        return await show_pick_filters(update, context)

    # Check for numeric selection
    if payload.isdigit():
        mapping = sales_state.get('filter_status_map') or {}
        status_val = mapping.get(int(payload))
        if status_val:
            if status_val in selected:
                selected.remove(status_val)
            else:
                selected.add(status_val)
            filters['status'] = list(selected)

    return await show_pick_filter_status(update, context)


async def show_pick_filter_type_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = context.session
    sales_state = context.user_data.get('sales', {})
    filters = sales_state.get('filters', {})
    selected: set = set(filters.get('type_event_ids') or [])

    # Fetch all type events
    rows = (await session.execute(sa.select(TypeEvent))).scalars().all()

    if not rows:
        await update.callback_query.answer("Нет типов мероприятий.", show_alert=True)
        return PICK_FILTERS

    number_to_tid: Dict[int, int] = {}
    lines: List[str] = [
        "<b>Выберите типы мероприятий</b>",
        "Отметьте цифрами под списком, затем нажмите «Готово»."
    ]

    for idx, r in enumerate(rows, start=1):
        number_to_tid[idx] = r.id
        mark = '✅' if r.id in selected else '▫️'
        lines.append(f"{idx}. {mark} {r.name}")

    sales_state['filter_type_event_map'] = number_to_tid

    num_buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(i), callback_data=str(i)) for i in
        range(1, len(rows) + 1)
    ]
    btn_rows = adjust_kbd(num_buttons, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:f_type_event')

    done_row = add_intent_id(
        [[InlineKeyboardButton("Готово", callback_data="done")]],
        'sales:f_type_event'
    )

    kb = btn_rows + done_row
    kb.append(
        add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                postfix_for_back=PICK_FILTERS))

    reply_markup = InlineKeyboardMarkup(kb)
    text = "\n".join(lines)

    await update.callback_query.edit_message_text(text=text,
                                                 reply_markup=reply_markup)
    return PICK_FILTER_TYPE_EVENT


async def pick_filter_type_event(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    selected: set = set(filters.get('type_event_ids') or [])

    if payload == "done":
        return await show_pick_filters(update, context)

    # Check for numeric selection
    if payload.isdigit():
        mapping = sales_state.get('filter_type_event_map') or {}
        tid = mapping.get(int(payload))
        if tid is not None:
            if tid in selected:
                selected.remove(tid)
            else:
                selected.add(tid)
            filters['type_event_ids'] = list(selected)

    return await show_pick_filter_type_event(update, context)


async def show_pick_filter_theater_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = context.session
    sales_state = context.user_data.get('sales', {})
    filters = sales_state.get('filters', {})
    selected: set = set(filters.get('theater_event_ids') or [])

    # Fetch active repertoire
    rows = (await session.execute(
        sa.select(TheaterEvent).where(TheaterEvent.flag_active_repertoire == True)
    )).scalars().all()

    if not rows:
        await update.callback_query.answer("Нет активных спектаклей.", show_alert=True)
        return PICK_FILTERS

    # Build numbered list and mapping
    number_to_tid: Dict[int, int] = {}
    lines: List[str] = [
        "<b>Выберите спектакли</b>",
        "Отметьте цифрами под списком, затем нажмите «Готово»."
    ]

    for idx, r in enumerate(rows, start=1):
        number_to_tid[idx] = r.id
        mark = '✅' if r.id in selected else '▫️'
        lines.append(f"{idx}. {mark} {r.name}")

    # Save mapping for numeric callbacks
    sales_state['filter_theater_map'] = number_to_tid

    num_buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(i), callback_data=str(i)) for i in
        range(1, len(rows) + 1)
    ]
    btn_rows = adjust_kbd(num_buttons, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:f_theater_event')

    done_row = add_intent_id(
        [[InlineKeyboardButton("Готово", callback_data="done")]],
        'sales:f_theater_event'
    )

    kb = btn_rows + done_row
    kb.append(
        add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                postfix_for_back=PICK_FILTERS))

    reply_markup = InlineKeyboardMarkup(kb)
    text = "\n".join(lines)

    await update.callback_query.edit_message_text(text=text,
                                                 reply_markup=reply_markup)
    return PICK_FILTER_THEATER_EVENT


async def pick_filter_theater_event(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    selected: set = set(filters.get('theater_event_ids') or [])

    if payload == "done":
        return await show_pick_filters(update, context)

    # Check for numeric selection
    if payload.isdigit():
        mapping = sales_state.get('filter_theater_map') or {}
        tid = mapping.get(int(payload))
        if tid is not None:
            if tid in selected:
                selected.remove(tid)
            else:
                selected.add(tid)
            filters['theater_event_ids'] = list(selected)

    return await show_pick_filter_theater_event(update, context)


async def show_pick_filter_schedule_event(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE,
                                        page: int = 1):
    session = context.session
    sales_state = context.user_data.get('sales', {})
    filters = sales_state.get('filters', {})
    selected: set = set(filters.get('schedule_event_ids') or [])

    # Get sub-filters
    f_time = sales_state.get('f_schedule_time', 'future')
    f_show = sales_state.get('f_schedule_show', 'on')

    # Fetch schedules
    now = datetime.now(timezone.utc)
    stmt = sa.select(ScheduleEvent)

    theater_event_ids = filters.get('theater_event_ids', [])
    if theater_event_ids:
        stmt = stmt.where(ScheduleEvent.theater_event_id.in_(theater_event_ids))

    if f_time == 'past':
        stmt = stmt.where(ScheduleEvent.datetime_event < now)
    elif f_time == 'future':
        stmt = stmt.where(ScheduleEvent.datetime_event >= now)
    # if 'all', no time filter

    if f_show == 'on':
        stmt = stmt.where(ScheduleEvent.flag_turn_in_bot == True)
    elif f_show == 'off':
        stmt = stmt.where(ScheduleEvent.flag_turn_in_bot == False)
    # if 'all', no show filter

    stmt = stmt.order_by(ScheduleEvent.datetime_event.desc())
    all_rows = (await session.execute(stmt)).scalars().all()

    total = len(all_rows)
    pages_total = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page1 = max(1, min(page, pages_total))
    start_idx = (page1 - 1) * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total)

    lines = [
        f"<b>Выберите сеансы</b>",
        f"Стр. {page1}/{pages_total}. Отметьте цифрами под списком, затем нажмите «Готово»."
    ]
    if total == 0:
        lines.append("\n⚠️ <b>Сеансов не найдено. Попробуйте изменить фильтры (Время / Статус).</b>")

    # Sub-filters keyboards
    time_kb = [
        InlineKeyboardButton(f"{'✅' if f_time == 'all' else '▫️'} Все", callback_data="time:all"),
        InlineKeyboardButton(f"{'✅' if f_time == 'past' else '▫️'} Прош.", callback_data="time:past"),
        InlineKeyboardButton(f"{'✅' if f_time == 'future' else '▫️'} Буд.", callback_data="time:future"),
    ]
    show_kb = [
        InlineKeyboardButton(f"{'✅' if f_show == 'all' else '▫️'} Любая", callback_data="show:all"),
        InlineKeyboardButton(f"{'✅' if f_show == 'on' else '▫️'} Вкл", callback_data="show:on"),
        InlineKeyboardButton(f"{'✅' if f_show == 'off' else '▫️'} Выкл", callback_data="show:off"),
    ]

    kb_sub = add_intent_id([time_kb, show_kb], 'sales:f_schedule_sub')

    kb = []
    for r in all_rows[start_idx:end_idx]:
        mark = '✅' if r.id in selected else '▫️'
        label_dt = _format_label(r.datetime_event, False).strip('▫️ ')
        if not r.flag_turn_in_bot:
            label_dt = "🚫 " + label_dt
        lines.append(f"ID: {r.id}. {mark} {label_dt}")
        kb.append(InlineKeyboardButton(str(r.id), callback_data=str(r.id)))

    # Pagination
    nav_row = []
    if page1 > 1:
        nav_row.append(
            InlineKeyboardButton('« Пред', callback_data=f"page:{page1 - 1}"))
    nav_row.append(
        InlineKeyboardButton(f'{page1}/{pages_total}', callback_data=f"page:{page1}"))
    if page1 < pages_total:
        nav_row.append(
            InlineKeyboardButton('След »', callback_data=f"page:{page1 + 1}"))

    kb_nav = add_intent_id([nav_row], 'sales:f_schedule_page')

    event_rows = adjust_kbd(kb, 5)
    event_rows = add_intent_id(event_rows, 'sales:f_schedule')

    done_row = [InlineKeyboardButton("Готово", callback_data="done")]
    done_row = add_intent_id([done_row], 'sales:f_schedule')

    kb_final = kb_sub + event_rows + kb_nav + done_row
    kb_final.append(add_btn_back_and_cancel(postfix_for_cancel='sales',
                                            add_back_btn=True,
                                            postfix_for_back=PICK_FILTERS))

    reply_markup = InlineKeyboardMarkup(kb_final)
    text = "\n".join(lines)

    if update.callback_query:
        await update.callback_query.edit_message_text(text=text,
                                                     reply_markup=reply_markup)
    return PICK_FILTER_SCHEDULE_EVENT


async def pick_filter_schedule_event(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    intent_id, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    selected: set = set(filters.get('schedule_event_ids') or [])

    if intent_id == 'sales:f_schedule_sub':
        if payload.startswith('time:'):
            sales_state['f_schedule_time'] = payload.split(':')[1]
            return await show_pick_filter_schedule_event(update, context, page=1)
        if payload.startswith('show:'):
            sales_state['f_schedule_show'] = payload.split(':')[1]
            return await show_pick_filter_schedule_event(update, context, page=1)

    if intent_id == 'sales:f_schedule_page':
        if payload.startswith('page:'):
            page = int(payload.split(':')[1])
            return await show_pick_filter_schedule_event(update, context, page=page)

    if payload == "done":
        return await show_pick_filters(update, context)

    if payload.isdigit():
        sid = int(payload)
        if sid in selected:
            selected.remove(sid)
        else:
            selected.add(sid)
        filters['schedule_event_ids'] = list(selected)

    # Find current page from text if we can
    match = re.search(r"Стр\. (\d+)/", query.message.text)
    page = int(match.group(1)) if match else 1

    return await show_pick_filter_schedule_event(update, context, page=page)


async def show_pick_filter_base_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = context.session
    sales_state = context.user_data.get('sales', {})
    filters = sales_state.get('filters', {})
    selected: set = set(filters.get('base_ticket_ids') or [])

    # Fetch active base tickets
    rows = (await session.execute(
        sa.select(BaseTicket).where(BaseTicket.flag_active == True)
    )).scalars().all()

    if not rows:
        await update.callback_query.answer("Нет активных билетов.", show_alert=True)
        return PICK_FILTERS

    number_to_tid: Dict[int, int] = {}
    lines: List[str] = [
        "<b>Выберите типы билетов (BaseTicket)</b>",
        "Отметьте цифрами под списком, затем нажмите «Готово»."
    ]

    for idx, r in enumerate(rows, start=1):
        number_to_tid[idx] = r.base_ticket_id
        mark = '✅' if r.base_ticket_id in selected else '▫️'
        lines.append(f"{idx}. {mark} {r.name}")

    sales_state['filter_base_ticket_map'] = number_to_tid

    num_buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(i), callback_data=str(i)) for i in
        range(1, len(rows) + 1)
    ]
    btn_rows = adjust_kbd(num_buttons, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:f_base_ticket')

    done_row = add_intent_id(
        [[InlineKeyboardButton("Готово", callback_data="done")]],
        'sales:f_base_ticket'
    )

    kb = btn_rows + done_row
    kb.append(
        add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                postfix_for_back=PICK_FILTERS))

    reply_markup = InlineKeyboardMarkup(kb)
    text = "\n".join(lines)

    await update.callback_query.edit_message_text(text=text,
                                                 reply_markup=reply_markup)
    return PICK_FILTER_BASE_TICKET


async def pick_filter_base_ticket(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    selected: set = set(filters.get('base_ticket_ids') or [])

    if payload == "done":
        return await show_pick_filters(update, context)

    # Check for numeric selection
    if payload.isdigit():
        mapping = sales_state.get('filter_base_ticket_map') or {}
        tid = mapping.get(int(payload))
        if tid is not None:
            if tid in selected:
                selected.remove(tid)
            else:
                selected.add(tid)
            filters['base_ticket_ids'] = list(selected)

    return await show_pick_filter_base_ticket(update, context)


async def show_pick_filter_child_age_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "<b>Возраст детей — минимум</b>",
        "Выберите минимальный возраст ребёнка (включительно).",
        "«12+» означает от 12 лет без верхней границы.",
    ]
    kb_btns = [InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(0, 13)]
    kb_btns.append(InlineKeyboardButton("12+", callback_data="12plus"))
    btn_rows = adjust_kbd(kb_btns, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:f_child_age_min')
    kb = btn_rows
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=PICK_FILTERS))
    reply_markup = InlineKeyboardMarkup(kb)
    text = "\n".join(lines)
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await update.effective_chat.send_message(text=text, reply_markup=reply_markup)
    return PICK_FILTER_CHILD_AGE_MIN


async def pick_filter_child_age_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})

    if payload == "12plus":
        filters['child_age_min'] = 12
        filters['child_age_max'] = None
        return await show_pick_filters(update, context)

    if payload.isdigit():
        filters['child_age_min'] = int(payload)
        filters.pop('child_age_max', None)
        return await show_pick_filter_child_age_max(update, context)

    return PICK_FILTER_CHILD_AGE_MIN


async def show_pick_filter_child_age_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.get('sales', {})
    filters = sales_state.get('filters', {})
    age_min = filters.get('child_age_min', 0)

    lines = [
        "<b>Возраст детей — максимум</b>",
        f"Минимум: {age_min}. Выберите максимальный возраст или «Пропустить» для без ограничения.",
    ]
    kb_btns = [InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(age_min + 1, 13)]
    kb_btns.append(InlineKeyboardButton("Пропустить", callback_data="skip"))
    btn_rows = adjust_kbd(kb_btns, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:f_child_age_max')
    kb = btn_rows
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=PICK_FILTER_CHILD_AGE_MIN))
    reply_markup = InlineKeyboardMarkup(kb)
    text = "\n".join(lines)
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await update.effective_chat.send_message(text=text, reply_markup=reply_markup)
    return PICK_FILTER_CHILD_AGE_MAX


async def pick_filter_child_age_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})

    if payload == "skip":
        filters['child_age_max'] = None
    elif payload.isdigit():
        filters['child_age_max'] = int(payload)
    else:
        return PICK_FILTER_CHILD_AGE_MAX

    return await show_pick_filters(update, context)


async def show_pick_ticket_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>Ввод ID билетов вручную</b>\n\n"
        "Пришлите список ID билетов через запятую, пробел или с новой строки.\n"
        "Пример: 1024, 1025, 1026\n\n"
        "<i>Другие фильтры будут проигнорированы.</i>"
    )
    kb = []
    reply_markup = await create_replay_markup(
        kb,
        intent_id='sales:f_manual_ids',
        postfix_for_cancel='sales',
        add_back_btn=True,
        postfix_for_back=PICK_FILTERS
    )

    sales_state = context.user_data.setdefault('sales', {})
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
        sales_state['ticket_ids_prompt_msg_id'] = update.callback_query.message.message_id
    else:
        sent = await update.effective_chat.send_message(text=text, reply_markup=reply_markup)
        sales_state['ticket_ids_prompt_msg_id'] = sent.message_id

    state = PICK_TICKET_IDS
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def pick_ticket_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    ids = re.findall(r'\d+', text)
    if not ids:
        await update.effective_chat.send_message("ID не найдены. Попробуйте ещё раз или нажмите Назад.")
        return PICK_TICKET_IDS

    sales_state = context.user_data.setdefault('sales', {})
    prompt_msg_id = sales_state.pop('ticket_ids_prompt_msg_id', None)
    if prompt_msg_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=prompt_msg_id,
                reply_markup=None
            )
        except Exception:
            pass

    filters = sales_state.setdefault('filters', {})
    filters['ticket_ids'] = list(map(int, ids))

    # Clear other filters to avoid confusion as manual IDs bypass them
    for key in ['status', 'type_event_ids', 'theater_event_ids', 'schedule_event_ids', 'base_ticket_ids']:
        filters.pop(key, None)

    return await show_build_audience(update, context)


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

    # Proceed to choose audience
    return await _proceed_to_audience_selection(update, context)


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
    lines = []
    for r in rows[start_idx:end_idx]:
        sid = r['id']
        selected = sid in sales_state['manual_selected_ids']
        mark = '✅' if selected else '▫️'
        label_dt = _format_label(r['datetime_event'], False).strip('▫️ ')
        lines.append(f"ID: {sid}. {mark} {label_dt}")
        event_buttons.append(InlineKeyboardButton(str(sid), callback_data=str(sid)))

    # Apply intent to event rows and done row
    event_rows = adjust_kbd(event_buttons, 5)
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

    hdr = '<b>Выберите даты/сеансы вручную</b>\nОтметьте цифрами под списком, затем нажмите «Готово».\n'
    pager = f"Стр. {page1}/{pages_total}\n"
    info = f"Всего доступно: {total}. Выбрано: {len(sales_state['manual_selected_ids'])}\n\n"
    text = hdr + pager + info + "\n".join(lines)
    await update.effective_chat.send_message(
        text=text,
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
        # toggle/done/numeric callbacks
        if payload.isdigit():
            sid = int(payload)
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
            # Proceed to choose audience
            return await _proceed_to_audience_selection(update, context)

    # Re-render current page using mixed-intent keyboard
    page1 = int(sales_state.get('page1', 1))
    all_rows = sales_state.get('all_schedules', [])
    total = len(all_rows)
    pages_total = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start_idx = (page1 - 1) * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total)

    event_buttons: List[InlineKeyboardButton] = []
    lines = []
    for r in all_rows[start_idx:end_idx]:
        sid = r['id']
        selected = sid in sales_state.get('manual_selected_ids', set())
        mark = '✅' if selected else '▫️'
        label_dt = _format_label(r['datetime_event'], False).strip('▫️ ')
        lines.append(f"ID: {sid}. {mark} {label_dt}")
        event_buttons.append(InlineKeyboardButton(str(sid), callback_data=str(sid)))

    # Apply intent to event rows and done row
    event_rows = adjust_kbd(event_buttons, 5)
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

    hdr = '<b>Выберите даты/сеансы вручную</b>\nОтметьте цифрами под списком, затем нажмите «Готово».\n'
    pager = f"Стр. {page1}/{pages_total}\n"
    info = f"Всего доступно: {total}. Выбрано: {len(sales_state.get('manual_selected_ids', set()))}\n\n"

    text = hdr + pager + info + "\n".join(lines)
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
    audience_summary = sales_state.pop('audience_summary', None)
    step_text = (
        'Шаг 5 — отправьте сообщение для рассылки.\n\n'
        'Допустимые варианты:\n'
        '• Текстовое сообщение\n'
        ' ИЛИ\n'
        '• Одно фото/видео/анимация с подписью\n\n'
        'Медиа-группы (альбомы) пока не поддерживаются.'
    )
    text = (audience_summary + '\n\n' + step_text) if audience_summary else step_text

    back_target = BUILD_AUDIENCE if sales_state.get('dev_mode') else PICK_FILTERS
    reply_markup = InlineKeyboardMarkup([
        add_btn_back_and_cancel(postfix_for_cancel='sales',
                                add_back_btn=True,
                                postfix_for_back=back_target)])
    sent = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    sales_state['ask_message_msg_id'] = sent.message_id
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

    prompt_msg_id = sales_state.pop('ask_message_msg_id', None)
    if prompt_msg_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=prompt_msg_id,
                reply_markup=None
            )
        except Exception:
            pass

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


async def _availability_block(session, schedule_ids: List[int]) -> str:
    if not schedule_ids:
        return 'Внимание: не выбраны сеансы.'
    free = await get_free_places(session, schedule_ids)
    if not free:
        return 'Кол-во свободных мест: нет данных.'

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

    full_name = ""
    availability_block = ""
    reserve_text = (f"👉 /reserve команда для покупки билетов\n"
                    f"Выбирайте подходящий спектакль и следуйте инструкциям")

    if campaign.type == 'WAS_THIS_YEAR_ON_PLAY' and campaign.theater_event_id:
        theater_event = await db_postgres.get_theater_event(
            session, campaign.theater_event_id)
        if theater_event:
            full_name = get_full_name_event(theater_event)
        availability_block = await _availability_block(session, schedule_ids)

    # Recipients' count
    pending_cnt = (await session.execute(
        sa.select(sa.func.count()).select_from(SalesRecipient).where(
            SalesRecipient.campaign_id == campaign_id)
    )).scalar() or 0

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
    extra = ''
    if campaign.type == 'WAS_THIS_YEAR_ON_PLAY':
        extra += f"\n\n{full_name}" if full_name else ""
        extra += f"\n\n{availability_block}" if availability_block else ""
        extra += f"\n\n{reserve_text}"

    if kind == 'text':
        text = (campaign.message_text or '') + extra
        await update.effective_chat.send_message(text=text,
                                                 reply_markup=reply_markup,
                                                 disable_web_page_preview=True)
    elif kind == 'photo' and campaign.photo_file_id:
        caption = (campaign.caption_text or '') + extra
        await update.effective_chat.send_photo(photo=campaign.photo_file_id,
                                               caption=caption,
                                               reply_markup=reply_markup)
    elif kind == 'video' and campaign.video_file_id:
        caption = (campaign.caption_text or '') + extra
        await update.effective_chat.send_video(video=campaign.video_file_id,
                                               caption=caption,
                                               reply_markup=reply_markup)
    elif kind == 'animation' and campaign.animation_file_id:
        caption = (campaign.caption_text or '') + extra
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
                getattr(msg, 'photo', None) or
                getattr(msg, 'video', None) or
                getattr(msg, 'animation', None)
        ):
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
        # Check schedules (only for WAS_THIS_YEAR_ON_PLAY)
        campaign_type = campaign.type
        schedule_ids: List[int] = context.user_data['sales'].get('schedule_ids', [])
        if not schedule_ids and campaign_type == 'WAS_THIS_YEAR_ON_PLAY':
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

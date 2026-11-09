import decimal
import logging
import re
from datetime import datetime, timezone, timedelta, date
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
    update_campaign_message, set_campaign_status, get_free_places,
    get_recent_campaigns, get_campaign_with_schedules,
    delete_campaign, get_recipient_counts
)
from api.sales_pub import publish_sales
from handlers import init_conv_hl_dialog
from utilities.utl_func import set_back_context, get_full_name_event
from utilities.utl_kbd import (
    create_replay_markup, remove_intent_id, add_intent_id, adjust_kbd,
    add_btn_back_and_cancel)
from utilities.utl_tg import is_not_modified, safe_edit_text, safe_edit_caption
from utilities.utl_sales_message import (
    send_campaign_message, analyze_length, format_length_report, build_extra,
)
from settings.settings import DICT_CONVERT_WEEKDAY_NUMBER_TO_STR

sales_logger = logging.getLogger('bot.sales')

PAGE_SIZE = 8
SALES_PAGE_SIZE = 30
TZ = pytz.timezone('Europe/Moscow')


# ─── Shared theater selection helpers ─────────────────────────────────────────

async def fetch_active_theaters(session) -> List[TheaterEvent]:
    """Fetch all active repertoire theater events ordered by ID."""
    rows = (await session.execute(
        sa.select(TheaterEvent)
        .where(TheaterEvent.flag_active_repertoire == True)
        .order_by(TheaterEvent.id)
    )).scalars().all()
    return rows


def paginate_list(items: list, page: int, page_size: int):
    """Return (page_items, page1, pages_total) for a paginated list."""
    total = len(items)
    pages_total = max(1, (total + page_size - 1) // page_size)
    page1 = max(1, min(page, pages_total))
    start_idx = (page1 - 1) * page_size
    end_idx = min(start_idx + page_size, total)
    return items[start_idx:end_idx], page1, pages_total


def build_theater_selection_text(
    page_theaters: list,
    selected_ids: set,
    title: str,
    hint: str,
    page: int,
    pages_total: int,
    use_real_id: bool = True,
) -> str:
    """Build numbered list text with ✅/▫️ markers for theater selection.

    Args:
        page_theaters: List of theater objects (dict or model) for current page.
        selected_ids: Set of selected theater IDs.
        title: Bold title line (e.g. "Шаг 1/4: Выберите спектакль").
        hint: Hint line shown below the title.
        page: Current 1-based page number.
        pages_total: Total number of pages.
        use_real_id: If True, use theater.id; if False, use ordinal number.
    """
    lines: List[str] = [f'<b>{title}</b>']
    if pages_total > 1:
        lines.append(f'Стр. {page}/{pages_total}. {hint}')
    else:
        lines.append(hint)

    for idx, t in enumerate(page_theaters, start=1):
        tid = int(t['id']) if isinstance(t, dict) else int(t.id)
        name = t['name'] if isinstance(t, dict) else t.name
        mark = '✅' if tid in selected_ids else '▫️'
        if use_real_id:
            lines.append(f"{tid}. {mark} {name}")
        else:
            lines.append(f"{idx}. {mark} {name}")
    lines.append('')
    lines.append('')
    return '\n'.join(lines)


def build_theater_keyboard(
    page_theaters: list,
    intent_id: str,
    page: int,
    pages_total: int,
    rows_per_row: int = 6,
    *,
    use_real_id: bool = True,
    done_label: str = None,
    done_callback_data: str = 'done',
    back_postfix: str = None,
    page_callback_prefix: str = 'page',
) -> InlineKeyboardMarkup:
    """Build inline keyboard for theater selection with pagination.

    Args:
        page_theaters: List of theater objects for current page.
        intent_id: Intent ID prefix for callbacks.
        page: Current 1-based page number.
        pages_total: Total number of pages.
        rows_per_row: Number of buttons per row.
        use_real_id: If True, callback_data uses theater.id.
        done_label: If set, adds a "Done" button with this label.
        done_callback_data: Callback data for the done button (default: "done").
        back_postfix: Postfix for the Back button (passed to add_btn_back_and_cancel).
        page_callback_prefix: Prefix for page navigation callbacks (e.g. "page" or "theater_page").
    """
    kb_btns: List[InlineKeyboardButton] = []
    for t in page_theaters:
        tid = int(t['id']) if isinstance(t, dict) else int(t.id)
        kb_btns.append(InlineKeyboardButton(str(tid), callback_data=str(tid)))

    btn_rows = adjust_kbd(kb_btns, rows_per_row)
    btn_rows = add_intent_id(btn_rows, intent_id)

    final_kb: List[List[InlineKeyboardButton]] = list(btn_rows)

    # Pagination nav
    if pages_total > 1:
        nav_row: List[InlineKeyboardButton] = []
        if page > 1:
            nav_row.append(InlineKeyboardButton('« Пред', callback_data=f"{page_callback_prefix}:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f'{page}/{pages_total}', callback_data=f"{page_callback_prefix}:{page}"))
        if page < pages_total:
            nav_row.append(InlineKeyboardButton('След »', callback_data=f"{page_callback_prefix}:{page + 1}"))
        final_kb.extend(add_intent_id([nav_row], intent_id))

    # Done button
    if done_label:
        done_row = add_intent_id(
            [[InlineKeyboardButton(done_label, callback_data=done_callback_data)]],
            intent_id
        )
        final_kb.extend(done_row)

    # Back + Cancel
    final_kb.append(add_btn_back_and_cancel(
        postfix_for_cancel='sales',
        add_back_btn=True,
        postfix_for_back=back_postfix,
    ))

    return InlineKeyboardMarkup(final_kb)


async def _show_step(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    state: str,
) -> str:
    """Render a wizard step by editing the current step message.

    If editing fails with 'Message to edit not found', falls back to sending
    a new message and remembering its ID for the next edit.
    Returns the conversation state.
    """
    sales_state = context.user_data.setdefault('sales', {})
    chat_id = update.effective_chat.id
    step_msg_id = sales_state.get('step_msg_id')

    # Try to edit the existing step message
    edited = False
    if step_msg_id is not None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=step_msg_id,
                text=text,
                reply_markup=reply_markup,
            )
            edited = True
        except BadRequest as e:
            if "Message to edit not found" in str(e) or is_not_modified(e):
                # Content unchanged — treat as successfully "edited"
                if is_not_modified(e):
                    edited = True
            else:
                raise

    if not edited:
        # Fallback: send a new message
        sent = await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None),
        )
        sales_state['step_msg_id'] = sent.message_id

        # Answer pending callback to remove loading indicator
        if update.callback_query:
            try:
                await update.callback_query.answer()
            except BadRequest:
                pass

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


# States (conversation will import these)
MENU = 'MENU'
PICK_EXISTING_CAMPAIGN = 'PICK_EXISTING_CAMPAIGN'
CAMPAIGN_ACTION_MENU = 'CAMPAIGN_ACTION_MENU'
PICK_TYPE = 'PICK_TYPE'
PICK_THEATER = 'PICK_THEATER'
PICK_SCOPE = 'PICK_SCOPE'
PICK_SCHEDULES = 'PICK_SCHEDULES'
PICK_AUDIENCE_THEATER = 'PICK_AUDIENCE_THEATER'
BUILD_AUDIENCE = 'BUILD_AUDIENCE'
GET_MESSAGE = 'GET_MESSAGE'
PREVIEW = 'PREVIEW'

# New states for media collection and length fix
GET_MEDIA = 'GET_MEDIA'
LENGTH_FIX = 'LENGTH_FIX'

PICK_ATTACH_THEATER = 'PICK_ATTACH_THEATER'

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

# States for SEASON_TICKET_HOLDERS type
PICK_SEASON_START = 'PICK_SEASON_START'
PICK_SEASON_END = 'PICK_SEASON_END'
PICK_SEASON_THEATERS = 'PICK_SEASON_THEATERS'
PICK_SEASON_AGE_MIN = 'PICK_SEASON_AGE_MIN'
PICK_SEASON_AGE_MAX = 'PICK_SEASON_AGE_MAX'
PICK_SEASON_STATUSES = 'PICK_SEASON_STATUSES'

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
    "SEASON_TICKET_HOLDERS": {
        "title": "Рассылка посетителям сезона (билеты за период)",
        "enabled": True,
        "start_state": PICK_SEASON_START,
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
            '4) При необходимости выберите сеансы вручную.\n'
            '5) Проверьте сводку аудитории.\n'
            '6) Пришлите медиа (необязательно).\n'
            '7) Отправьте текст сообщения.'
        )
    if type_code == "TICKET_HOLDERS":
        return (
            '<b>Как пользоваться этим типом рассылки:</b>\n'
            '1) Задайте фильтры для отбора аудитории (статус билетов, спектакли, типы, сеансы, возраст детей или конкретные билеты).\n'
            '2) При необходимости прикрепите спектакль со свободными местами.\n'
            '3) Проверьте сводку аудитории.\n'
            '4) Пришлите медиа (необязательно).\n'
            '5) Отправьте текст сообщения.'
        )
    if type_code == "SEASON_TICKET_HOLDERS":
        return (
            '<b>Как пользоваться этим типом рассылки:</b>\n'
            '1) Введите дату начала периода прошедших сеансов (формат ДД.ММ.ГГГГ) или пропустите.\n'
            '2) Введите дату конца периода (формат ДД.ММ.ГГГГ) или пропустите.\n'
            '3) При необходимости выберите конкретные спектакли (только активные).\n'
            '4) При необходимости задайте минимальный возраст ребёнка в билете кнопками.\n'
            '5) При необходимости задайте максимальный возраст ребёнка в билете кнопками.\n'
            '6) При необходимости выберите статусы билетов.\n'
            '7) При необходимости прикрепите спектакль со свободными местами.\n'
            '8) Проверьте сводку аудитории.\n'
            '9) Пришлите медиа (необязательно).\n'
            '10) Отправьте текст сообщения.'
        )
    # Default hint for future types
    return (
        '<b>Как пользоваться:</b>\n'
        '1) Следуйте шагам мастера: выберите объект, задайте охват, подготовьте сообщение.\n'
        '2) Проверьте предпросмотр и запустите рассылку.'
    )


def _get_step_info(type_code: str, step_name: str) -> tuple:
    """Return (current_step, total_steps) for a given type and step name.
    
    step_name is one of: 'filters', 'attach_theater', 'build_audience', 'media', 'text',
    'theater', 'scope', 'audience_theater', 'schedules',
    'season_start', 'season_end', 'season_theaters', 'season_age_min', 'season_age_max', 'season_statuses'
    """
    if type_code == 'TICKET_HOLDERS':
        # 1: filters, 2: attach_theater (theater, scope, schedules are sub-steps),
        # 3: build_audience, 4: media, 5: text
        _map = {
            'filters': (1, 5),
            'attach_theater': (2, 5),
            'theater': (2, 5),
            'scope': (2, 5),
            'schedules': (2, 5),
            'build_audience': (3, 5),
            'media': (4, 5),
            'text': (5, 5),
        }
    elif type_code == 'WAS_THIS_YEAR_ON_PLAY':
        # 1: theater, 2: scope, 3: audience_theater, 4: schedules (optional),
        # 5: build_audience, 6: media, 7: text
        _map = {
            'theater': (1, 7),
            'scope': (2, 7),
            'audience_theater': (3, 7),
            'schedules': (4, 7),
            'build_audience': (5, 7),
            'media': (6, 7),
            'text': (7, 7),
        }
    elif type_code == 'SEASON_TICKET_HOLDERS':
        # 1: season_start, 2: season_end, 3: season_theaters, 4: season_age_min,
        # 5: season_age_max, 6: season_statuses, 7: attach_theater (theater, scope, schedules are sub-steps),
        # 8: build_audience, 9: media, 10: text
        _map = {
            'season_start': (1, 10),
            'season_end': (2, 10),
            'season_theaters': (3, 10),
            'season_age_min': (4, 10),
            'season_age_max': (5, 10),
            'season_statuses': (6, 10),
            'attach_theater': (7, 10),
            'theater': (7, 10),
            'scope': (7, 10),
            'schedules': (7, 10),
            'build_audience': (8, 10),
            'media': (9, 10),
            'text': (10, 10),
        }
    else:
        _map = {step_name: (1, 1) for step_name in ['filters', 'attach_theater', 'build_audience', 'media', 'text']}
    return _map.get(step_name, (1, 1))






def _get_usage_text_with_highlight(type_code: str, current_step: int) -> str:
    """Return usage text with the current step highlighted in bold.
    
    Wraps the step matching `current_step` in <b> tags for all types.
    """
    if type_code == "TICKET_HOLDERS":
        steps = [
            'Задайте фильтры для отбора аудитории (статус билетов, спектакли, типы, сеансы, возраст детей или конкретные билеты).',
            'При необходимости прикрепите спектакль со свободными местами.',
            'Проверьте сводку аудитории.',
            'Пришлите медиа (необязательно).',
            'Отправьте текст сообщения.',
        ]
    elif type_code == "WAS_THIS_YEAR_ON_PLAY":
        steps = [
            'Выберите спектакль.',
            'Выберите охват сеансов: все доступные или вручную по датам.',
            'Выберите спектакль(и), по которым отберём аудиторию — тех, кто уже был в этом году.',
            'При необходимости выберите сеансы вручную.',
            'Проверьте сводку аудитории.',
            'Пришлите медиа (необязательно).',
            'Отправьте текст сообщения.',
        ]
    elif type_code == "SEASON_TICKET_HOLDERS":
        steps = [
            'Введите дату начала периода прошедших сеансов (формат ДД.ММ.ГГГГ) или пропустите.',
            'Введите дату конца периода (формат ДД.ММ.ГГГГ) или пропустите.',
            'При необходимости выберите конкретные спектакли (только активные).',
            'При необходимости задайте минимальный возраст ребёнка в билете кнопками.',
            'При необходимости задайте максимальный возраст ребёнка в билете кнопками.',
            'При необходимости выберите статусы билетов.',
            'При необходимости прикрепите спектакль со свободными местами.',
            'Проверьте сводку аудитории.',
            'Пришлите медиа (необязательно).',
            'Отправьте текст сообщения.',
        ]
    else:
        return _get_usage_text_for_type(type_code)
    
    lines: List[str] = ['<b>Как пользоваться этим типом рассылки:</b>']
    for i, step_text in enumerate(steps, start=1):
        if i == current_step:
            lines.append(f'<b>{i}) {step_text}</b>')
        else:
            lines.append(f'{i}) {step_text}')
    
    return '\n'.join(lines)


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

    if not schedule_ids and campaign_type not in ('TICKET_HOLDERS', 'SEASON_TICKET_HOLDERS'):
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
    elif campaign_type == 'SEASON_TICKET_HOLDERS':
        season_start = sales_state.get('season_start')
        season_end = sales_state.get('season_end')
        if season_start and season_end:
            title = f"Рассылка: Сезон {season_start.strftime('%d.%m.%Y')}–{season_end.strftime('%d.%m.%Y')}"
        else:
            title = f"Рассылка: Посетители сезона ({datetime.now().strftime('%d.%m %H:%M')})"
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
    elif campaign_type == 'SEASON_TICKET_HOLDERS':
        rows = await _select_season_audience(session, sales_state)
        season_start = sales_state.get('season_start')
        season_end = sales_state.get('season_end')
        theater_ids = sales_state.get('season_theater_ids') or []
        c_min = sales_state.get('child_age_min')
        c_max = sales_state.get('child_age_max')
        status_values = sales_state.get('season_statuses') or []

        period_label = ""
        if season_start and season_end:
            period_label = f"\nПериод: {season_start.strftime('%d.%m.%Y')} – {season_end.strftime('%d.%m.%Y')}"

        theater_label = ""
        if theater_ids:
            names = (await session.execute(sa.select(TheaterEvent.name).where(
                TheaterEvent.id.in_(theater_ids)))).scalars().all()
            if names:
                theater_label = f"\nСпектакли ({len(names)}): {', '.join(names)}"
        else:
            theater_label = "\nСпектакли: все"

        age_label = ""
        if c_min is not None and c_max is not None:
            age_label = f"\nВозраст ребёнка: от {c_min} до {c_max} лет"
        elif c_min is not None:
            age_label = f"\nВозраст ребёнка: от {c_min}+ лет"
        elif c_max is not None:
            age_label = f"\nВозраст ребёнка: до {c_max} лет"
        else:
            age_label = "\nВозраст ребёнка: без ограничения"

        status_label = ""
        if status_values:
            status_label = f"\nСтатусы билетов: {', '.join(status_values)}"
        else:
            status_label = "\nСтатусы билетов: все"

        audience_info = (
            f"\nАудитория: посетители сезона.{period_label}{theater_label}{age_label}{status_label}"
        )
        if sales_state.get('attach_theater'):
            postfix_for_back = PICK_SCOPE
        else:
            postfix_for_back = PICK_ATTACH_THEATER
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

    # Handle empty audience for all types before creating campaign
    if not rows:
        text = (
            '<b>Аудитория пуста</b>\n\n'
            'По заданным условиям не найдено получателей.\n'
            'Создание рассылки завершено.\n\n'
            'Чтобы запустить рассылку заново, используйте команду /sales.'
        )
        await update.effective_chat.send_message(
            text=text,
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return MENU

    campaign_id = await _ensure_campaign_and_schedules(update, context)

    # Safe snapshot replacement: clear old recipients for draft campaign before inserting new ones
    if campaign_id:
        await session.execute(
            sa.delete(SalesRecipient.__table__).where(
                SalesRecipient.__table__.c.campaign_id == campaign_id
            )
        )

    # Take a snapshot from DB
    inserted = await snapshot_recipients(session, campaign_id, rows)
    await session.flush()
    await session.commit()

    # Get counts for reporting
    total_found = len(rows)
    total_pending = inserted

    # Add step header based on campaign type
    if campaign_type == 'SEASON_TICKET_HOLDERS':
        step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'build_audience')
        step_header = f'<b>Шаг {step_n}/{step_total}: Проверьте сводку аудитории</b>'
        usage_block = _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)
    elif campaign_type == 'TICKET_HOLDERS':
        step_n, step_total = _get_step_info('TICKET_HOLDERS', 'build_audience')
        step_header = f'<b>Шаг {step_n}/{step_total}: Проверьте сводку аудитории</b>'
        usage_block = _get_usage_text_with_highlight('TICKET_HOLDERS', step_n)
    elif campaign_type == 'WAS_THIS_YEAR_ON_PLAY':
        step_n, step_total = _get_step_info('WAS_THIS_YEAR_ON_PLAY', 'build_audience')
        step_header = f'<b>Шаг {step_n}/{step_total}: Проверьте сводку аудитории</b>'
        usage_block = _get_usage_text_with_highlight('WAS_THIS_YEAR_ON_PLAY', step_n)
    else:
        step_header = '<b>Отбор аудитории завершён.</b>'
        usage_block = None

    text_lines = [
        step_header,
        f'Всего найдено уникальных пользователей: {total_found}',
        f'Добавлено получателей (pending): {total_pending}',
        audience_info,
    ]

    # Compact summary for subsequent steps (without step header and usage block)
    summary_lines = [
        f'Всего найдено уникальных пользователей: {total_found}',
        f'Добавлено получателей (pending): {total_pending}',
        audience_info,
    ]
    audience_summary = '\n'.join([t for t in summary_lines if t is not None and t != ''])

    # Full text with step header for dev mode
    text = '\n'.join([t for t in text_lines if t is not None and t != ''])
    if usage_block:
        text += '\n\n' + usage_block

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

    # Prompt for media step first, then text
    sales_state['audience_summary'] = audience_summary
    return await show_get_media(update, context)


# --- Media collection step ---

MAX_MEDIA_COUNT = 10


def _extract_media_info(msg) -> 'dict | None':
    """Extract media type and file_id from a message."""
    if msg.photo:
        return {'type': 'photo', 'file_id': msg.photo[-1].file_id}
    elif msg.video:
        return {'type': 'video', 'file_id': msg.video.file_id}
    elif msg.animation:
        return {'type': 'animation', 'file_id': msg.animation.file_id}
    return None


async def show_get_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step: collect media files (up to 10). Admin can skip to go straight to text."""
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END

    audience_summary = sales_state.pop('audience_summary', None)
    media = sales_state.get('media', [])
    campaign_type = sales_state.get('type')
    step_n, step_total = _get_step_info(campaign_type, 'media')
    step_text = (
        f'<b>Шаг {step_n}/{step_total}: Пришлите медиа (необязательно)</b>\n\n'
        f'Текущих медиа: {len(media)}/{MAX_MEDIA_COUNT}\n\n'
        'Отправьте фото, видео или анимацию (до 10 файлов).\n'
        'GIF-анимации считаются отдельно — только одна GIF в альбоме.\n\n'
        'После отправки медиа можно сразу написать текст —\n'
        'это завершит выбор медиа и покажет предпросмотр.\n\n'
        'Нажмите «Пропустить», чтобы перейти к вводу текста.'
    )
    text = step_text
    if audience_summary:
        text = audience_summary + '\n\n' + step_text

    if sales_state.get('dev_mode'):
        back_target = BUILD_AUDIENCE
    elif campaign_type == 'TICKET_HOLDERS':
        back_target = PICK_ATTACH_THEATER
    elif campaign_type == 'SEASON_TICKET_HOLDERS':
        back_target = PICK_ATTACH_THEATER
    else:
        back_target = PICK_AUDIENCE_THEATER

    kb = [
        [InlineKeyboardButton('⏭ Пропустить', callback_data='skip')],
    ]
    if media:
        kb.append([InlineKeyboardButton('🗑 Очистить медиа', callback_data='clear')])
    kb = add_intent_id(kb, 'sales:media')
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales',
                                       add_back_btn=True,
                                       postfix_for_back=back_target))
    reply_markup = InlineKeyboardMarkup(kb)

    state = await _show_step(update, context, text, reply_markup, GET_MEDIA)
    # Remember the prompt message ID so handle_media_text can clear its markup later
    sales_state['get_media_msg_id'] = sales_state.get('step_msg_id')
    return state


async def handle_media_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Accumulate media files in sales_state['media']."""
    sales_state = context.user_data.setdefault('sales', {})
    msg = update.effective_message

    # Reject media groups
    if getattr(msg, 'media_group_id', None):
        await update.effective_chat.send_message(
            'Альбомы напрямую не поддерживаются. Отправляйте по одному файлу.')
        return GET_MEDIA

    media_info = _extract_media_info(msg)
    if not media_info:
        await update.effective_chat.send_message(
            'Поддерживаются только фото, видео и анимация (GIF).')
        return GET_MEDIA

    # GIF limit: only one animation allowed
    if media_info['type'] == 'animation':
        existing = sales_state.get('media', [])
        if any(m['type'] == 'animation' for m in existing):
            await update.effective_chat.send_message(
                'GIF-анимация уже добавлена. Только одна GIF допускается.')
            return GET_MEDIA

    # Accumulate
    media = sales_state.get('media', [])
    if len(media) >= MAX_MEDIA_COUNT:
        await update.effective_chat.send_message(
            f'Лимит {MAX_MEDIA_COUNT} медиа достигнут. Нажмите «Далее» или очистите список.')
        return GET_MEDIA

    media.append(media_info)
    sales_state['media'] = media

    # Update extra_payload
    extra_payload = sales_state.get('extra_payload', {})
    extra_payload['media'] = media
    sales_state['extra_payload'] = extra_payload

    await update.effective_chat.send_message(
        f'✅ Медиа добавлено ({len(media)}/{MAX_MEDIA_COUNT}). '
        f'Отправьте ещё, напишите текст для предпросмотра, '
        f'или нажмите «Пропустить».'
    )
    return GET_MEDIA


async def handle_media_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text message in GET_MEDIA state: store text and proceed to preview."""
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END

    msg = update.effective_message
    plain_text = msg.text_html or ''
    entities = _serialize_entities(msg.entities)

    # Clear prompt message
    prompt_msg_id = sales_state.pop('get_media_msg_id', None)
    if prompt_msg_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=prompt_msg_id,
                reply_markup=None
            )
        except Exception:
            pass

    # Store text in extra_payload
    extra_payload = sales_state.get('extra_payload', {})
    extra_payload['text'] = plain_text
    extra_payload['text_entities'] = entities
    
    # Determine text_mode: with media → caption, without → separate
    media = sales_state.get('media', [])
    if media:
        extra_payload['text_mode'] = 'caption'
    else:
        extra_payload['text_mode'] = 'separate'
    
    sales_state['extra_payload'] = extra_payload

    # Also update campaign DB fields for backward compatibility
    fields = {
        'message_kind': 'text',
        'message_text': plain_text,
        'message_entities': entities,
    }
    await update_campaign_message(context.session, campaign_id, **fields)
    await context.session.commit()

    # Proceed to preview
    return await show_preview(update, context)


async def handle_media_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle skip/clear actions in GET_MEDIA state."""
    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})

    if action == 'skip':
        # Clear prompt message
        prompt_msg_id = sales_state.pop('get_media_msg_id', None)
        if prompt_msg_id:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=update.effective_chat.id,
                    message_id=prompt_msg_id,
                    reply_markup=None
                )
            except Exception:
                pass
        return await ask_message(update, context)

    if action == 'clear':
        sales_state['media'] = []
        extra_payload = sales_state.get('extra_payload', {})
        extra_payload.pop('media', None)
        sales_state['extra_payload'] = extra_payload
        return await show_get_media(update, context)

    return GET_MEDIA


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
    # Proceed to media step
    return await show_get_media(update, context)


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
    return await _show_step(update, context, text, reply_markup, PICK_TYPE)


def _status_label(status: str) -> str:
    """Return a short emoji label for campaign status."""
    return {'draft': '📝', 'running': '🔄', 'canceled': '❌', 'done': '✅'}.get(status, status)


async def show_pick_existing_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of recent campaigns that can be resumed, plus 'Create new' button."""
    session = context.session
    campaigns = await get_recent_campaigns(session, limit=10)

    type_labels = {
        'WAS_THIS_YEAR_ON_PLAY': 'Свободные места',
        'TICKET_HOLDERS': 'Обладатели билетов',
        'SEASON_TICKET_HOLDERS': 'Посетители сезона',
    }

    lines = ['<b>Выберите кампанию или создайте новую:</b>\n']
    kb = []

    for c in campaigns:
        label = type_labels.get(c.type, c.type)
        status_emoji = _status_label(c.status)
        title = (c.title or f'Кампания #{c.id}')
        lines.append(f'{status_emoji} <b>#{c.id}</b> — {title}\n<i>{label} · {c.status}</i>')

    kb.append([InlineKeyboardButton(
        '➕ Создать новую', callback_data='new'
    )])

    # Build campaign buttons as a flat list, then reshape with adjust_kbd
    campaign_buttons = []
    for c in campaigns:
        status_emoji = _status_label(c.status)
        campaign_buttons.append(InlineKeyboardButton(
            f'{status_emoji} #{c.id}',
            callback_data=f'campaign:{c.id}'
        ))
    kb.extend(adjust_kbd(campaign_buttons, 4))
    kb = add_intent_id(kb, 'sales:existing')
    kb.append([InlineKeyboardButton('Отмена', callback_data='Отменить')])
    reply_markup = InlineKeyboardMarkup(kb)

    text = '\n\n'.join(lines) if campaigns else '<b>Нет доступных кампаний.</b>\n\nСоздайте новую.'
    return await _show_step(update, context, text, reply_markup, PICK_EXISTING_CAMPAIGN)


async def pick_existing_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle selection: show action menu for existing campaign or create a new one."""
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    if payload == 'new':
        # Reset state and go to type selection
        context.user_data['sales'] = {
            'dev_mode': context.user_data['sales'].get('dev_mode', False),
            'type': None,
            'campaign_id': None,
            'theater_event_id': None,
            'schedule_ids': [],
            'filters': {},
            'audience_theater_ids': [],
            'f_schedule_time': 'all',
            'f_schedule_show': 'all',
            'child_age_min': None,
            'child_age_max': None,
            'attach_theater': False,
        }
        return await _show_pick_type(update, context)

    if payload.startswith('campaign:'):
        campaign_id = int(payload.split(':', 1)[1])
        return await show_campaign_action_menu(update, context, campaign_id)

    # Fallback
    return await show_pick_existing_campaign(update, context)


async def show_campaign_action_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, campaign_id: int):
    """Show action menu for a selected campaign: resume, continue, edit, cancel, delete."""
    session = context.session
    campaign = await get_campaign_with_schedules(session, campaign_id)

    if not campaign:
        return await show_pick_existing_campaign(update, context)

    # Store campaign_id in state for action handlers
    context.user_data['sales']['campaign_id'] = campaign.id

    type_labels = {
        'WAS_THIS_YEAR_ON_PLAY': 'Свободные места',
        'TICKET_HOLDERS': 'Обладатели билетов',
        'SEASON_TICKET_HOLDERS': 'Посетители сезона',
    }
    label = type_labels.get(campaign.type, campaign.type)
    status_emoji = _status_label(campaign.status)
    title = campaign.title or f'Кампания #{campaign.id}'

    total, pending = await get_recipient_counts(session, campaign_id)

    has_content = (
        campaign.extra_payload or
        campaign.message_text or
        campaign.caption_text or
        campaign.message_kind
    )

    text = (
        f'{status_emoji} <b>{title}</b> (#{campaign.id})\n\n'
        f'Тип: {label}\n'
        f'Статус: {campaign.status}\n'
        f'Получатели: {total} (ожидает: {pending})\n'
        f'Сообщение: {"есть" if has_content else "не задано"}'
    )

    kb = []
    # Resume — re-publish to NATS (only if has content and pending recipients)
    if has_content and pending > 0 and campaign.status != 'done':
        kb.append([InlineKeyboardButton(
            '🔄 Перезапустить', callback_data='action:resume'
        )])
    # Continue — go to wizard to finish setup
    if not has_content or campaign.status in ('draft', 'running'):
        kb.append([InlineKeyboardButton(
            '▶️ Продолжить настройку', callback_data='action:continue'
        )])
    # Edit — go to preview to edit media/text
    if has_content:
        kb.append([InlineKeyboardButton(
            '✏️ Изменить сообщение', callback_data='action:edit'
        )])
    # Cancel — set status to canceled
    if campaign.status in ('draft', 'running'):
        kb.append([InlineKeyboardButton(
            '❌ Отменить', callback_data='action:cancel'
        )])
    # Delete — remove campaign
    if campaign.status in ('draft', 'canceled'):
        kb.append([InlineKeyboardButton(
            '🗑 Удалить', callback_data='action:delete'
        )])

    kb.append([InlineKeyboardButton('← Назад', callback_data='back')])
    kb = add_intent_id(kb, 'sales:action')
    reply_markup = InlineKeyboardMarkup(kb)

    return await _show_step(update, context, text, reply_markup, CAMPAIGN_ACTION_MENU)


async def handle_campaign_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle action selection for a campaign."""
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    campaign_id = context.user_data['sales'].get('campaign_id')
    if not campaign_id:
        await query.answer('Сначала выберите кампанию.', show_alert=True)
        return await show_pick_existing_campaign(update, context)

    if payload == 'action:resume':
        # Re-publish campaign to NATS — go to preview for confirmation
        return await show_preview(update, context)

    if payload == 'action:continue':
        # Restore campaign state and go to appropriate wizard step
        session = context.session
        campaign = await get_campaign_with_schedules(session, campaign_id)
        if not campaign:
            await query.answer('Кампания не найдена.', show_alert=True)
            return await show_pick_existing_campaign(update, context)

        sales_state = context.user_data['sales']
        sales_state['campaign_id'] = campaign.id
        sales_state['type'] = campaign.type
        sales_state['theater_event_id'] = campaign.theater_event_id
        sales_state['schedule_ids'] = [s.schedule_event_id for s in campaign.schedules]
        if campaign.extra_payload:
            sales_state['extra_payload'] = campaign.extra_payload

        has_content = (
            campaign.extra_payload or
            campaign.message_text or
            campaign.caption_text or
            campaign.message_kind
        )

        if has_content:
            # Has message — go to media/text step to potentially modify
            return await show_preview(update, context)
        else:
            # No message — go to audience step based on type
            start_state = SALES_TYPES.get(campaign.type, {}).get('start_state', PICK_THEATER)
            if start_state == PICK_FILTERS:
                return await show_pick_filters(update, context)
            if start_state == PICK_SEASON_START:
                return await show_pick_season_start(update, context)
            return await show_pick_theater(update, context)

    if payload == 'action:edit':
        # Go to preview to edit media/text
        return await show_preview(update, context)

    if payload == 'action:cancel':
        session = context.session
        await set_campaign_status(session, campaign_id, 'canceled')
        await session.commit()
        sales_logger.info(f'Кампания #{campaign_id} отменена')
        await query.answer('Кампания отменена.', show_alert=True)
        return await show_pick_existing_campaign(update, context)

    if payload == 'action:delete':
        session = context.session
        deleted = await delete_campaign(session, campaign_id)
        if deleted:
            await session.commit()
            sales_logger.info(f'Кампания #{campaign_id} удалена')
            await query.answer('Кампания удалена.', show_alert=True)
        else:
            await query.answer('Кампания не найдена.', show_alert=True)
        return await show_pick_existing_campaign(update, context)

    if payload == 'back':
        return await show_pick_existing_campaign(update, context)

    # Fallback
    return await show_campaign_action_menu(update, context, campaign_id)


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
        'child_age_min': None,
        'child_age_max': None,
        'attach_theater': False,
    }

    if args and args[0].lower() == 'dev':
        context.user_data['sales']['dev_mode'] = True
    sales_logger.info("/sales started by %s dev_mode=%s",
                      update.effective_user.id,
                      context.user_data['sales']['dev_mode'])

    # Show existing campaigns or create new
    return await show_pick_existing_campaign(update, context)


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

    # Usage hint is now inline in each screen, no separate message needed

    # Go to next state based on type
    start_state = meta.get('start_state', PICK_THEATER)
    if start_state == PICK_FILTERS:
        return await show_pick_filters(update, context)
    if start_state == PICK_SEASON_START:
        return await show_pick_season_start(update, context)

    return await show_pick_theater(update, context)


# --- SEASON_TICKET_HOLDERS: date input helpers ---

def _parse_date(text: str) -> 'date | None':
    """Parse DD.MM.YYYY date string, return None on failure."""
    m = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})$', text.strip())
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


# --- SEASON_TICKET_HOLDERS: Period date input (optional) ---

async def show_pick_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1/8: Optional period start date. Admin can skip to use all history."""
    context.user_data.setdefault('sales', {})
    step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'season_start')
    usage_block = _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)
    text = (
        f'<b>Шаг {step_n}/{step_total} (необязательно): Дата начала периода</b>\n\n'
        'Введите дату начала периода прошедших сеансов в формате ДД.ММ.ГГГГ\n'
        'или нажмите «Вся история», чтобы не ограничивать по дате.\n\n'
        'Дата должна быть раньше сегодняшнего дня.\n\n'
        + usage_block
    )
    kb = [
        [InlineKeyboardButton('📅 Вся история (без периода)', callback_data='all_history')],
        [InlineKeyboardButton('⏭ Пропустить', callback_data='skip')],
    ]
    kb = add_intent_id(kb, 'sales:season_start')
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=PICK_TYPE))
    reply_markup = InlineKeyboardMarkup(kb)
    return await _show_step(update, context, text, reply_markup, PICK_SEASON_START)


async def pick_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle period start: text date input or callback (all_history)."""
    sales_state = context.user_data.setdefault('sales', {})

    # Callback: skip period entirely or skip just start date
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        _, payload = remove_intent_id(query.data)
        if payload == 'all_history':
            sales_state['season_start'] = None
            sales_state['season_end'] = None
            return await show_pick_season_theaters(update, context)
        if payload == 'skip':
            sales_state['season_start'] = None
            return await show_pick_season_end(update, context)
        return PICK_SEASON_START

    # Text: parse date
    text = update.effective_message.text.strip()
    d = _parse_date(text)
    if d is None:
        await update.effective_chat.send_message(
            'Неверный формат. Пожалуйста, введите дату как ДД.ММ.ГГГГ.\nПример: 01.02.2025',
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return PICK_SEASON_START
    today = datetime.now(timezone.utc).date()
    if d >= today:
        await update.effective_chat.send_message(
            f'Дата должна быть раньше сегодняшнего дня ({today.strftime("%d.%m.%Y")}).',
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return PICK_SEASON_START
    sales_state['season_start'] = d
    await update.effective_message.delete()
    return await show_pick_season_end(update, context)


async def show_pick_season_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2/8: Optional period end date. Admin can skip to use today."""
    sales_state = context.user_data.setdefault('sales', {})
    season_start = sales_state.get('season_start')
    step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'season_end')
    usage_block = _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)

    # Get max available date from DB for "skip" hint
    session = context.session
    try:
        max_dt_row = (await session.execute(
            sa.select(sa.func.max(ScheduleEvent.datetime_event))
        )).scalar()
        max_date = max_dt_row.date() if max_dt_row else datetime.now(timezone.utc).date()
        max_date_hint = f' (будет использовано: {max_date.strftime("%d.%m.%Y")})'
    except Exception:
        max_date_hint = ''

    season_start_text = season_start.strftime("%d.%m.%Y") if season_start else "не задана (весь период)"
    step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'season_end')
    text = (
        f'<b>Шаг {step_n}/{step_total} (необязательно): Дата конца периода</b>\n\n'
        f'Дата начала: {season_start_text}\n\n'
        'Введите дату конца периода в формате ДД.ММ.ГГГГ\n'
        'или нажмите «Пропустить»' + max_date_hint + '.\n\n'
        'Дата должна быть раньше сегодняшнего дня'
        + (f' и не раньше даты начала ({season_start.strftime("%d.%m.%Y")}).\n\n' if season_start else '.\n\n')
        + usage_block
    )
    kb = [
        [InlineKeyboardButton('⏭ Пропустить', callback_data='skip')],
    ]
    kb = add_intent_id(kb, 'sales:season_end')
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=PICK_SEASON_START))
    reply_markup = InlineKeyboardMarkup(kb)
    return await _show_step(update, context, text, reply_markup, PICK_SEASON_END)


async def pick_season_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle period end: text date input or callback (skip)."""
    sales_state = context.user_data.setdefault('sales', {})

    # Callback: skip and use max available date
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        _, payload = remove_intent_id(query.data)
        if payload == 'skip':
            # Set end to max available date in DB
            session = context.session
            try:
                max_dt_row = (await session.execute(
                    sa.select(sa.func.max(ScheduleEvent.datetime_event))
                )).scalar()
                sales_state['season_end'] = max_dt_row.date() if max_dt_row else datetime.now(timezone.utc).date()
            except Exception:
                sales_state['season_end'] = datetime.now(timezone.utc).date()
            return await show_pick_season_theaters(update, context)
        return PICK_SEASON_END

    # Text: parse date
    text = update.effective_message.text.strip()
    d = _parse_date(text)
    if d is None:
        await update.effective_chat.send_message(
            'Неверный формат. Пожалуйста, введите дату как ДД.ММ.ГГГГ.\nПример: 31.01.2026',
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return PICK_SEASON_END
    today = datetime.now(timezone.utc).date()
    if d >= today:
        await update.effective_chat.send_message(
            f'Дата должна быть раньше сегодняшнего дня ({today.strftime("%d.%m.%Y")}).',
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return PICK_SEASON_END
    season_start = sales_state.get('season_start')
    if season_start and d < season_start:
        await update.effective_chat.send_message(
            f'Дата конца ({d.strftime("%d.%m.%Y")}) не может быть раньше даты начала ({season_start.strftime("%d.%m.%Y")}).',
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return PICK_SEASON_END
    sales_state['season_end'] = d
    await update.effective_message.delete()
    return await show_pick_season_theaters(update, context)


# --- SEASON_TICKET_HOLDERS: Theater event multi-select with pagination ---

async def show_pick_season_theaters(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
    selected: set = set(sales_state.get('season_theater_ids') or [])

    rows = await fetch_active_theaters(session)
    if not rows:
        await update.effective_chat.send_message(
            'Нет активных спектаклей в репертуаре.',
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return PICK_SEASON_START

    page_rows, page1, pages_total = paginate_list(rows, page, SALES_PAGE_SIZE)
    sales_state['season_theater_page'] = page1

    step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'season_theaters')
    title = f'Шаг {step_n}/{step_total}: Выберите спектакли'
    hint = 'Отметьте цифрами (ID спектакля), затем «Далее».\n(Только активные спектакли)'
    text = build_theater_selection_text(page_rows, selected, title, hint, page1, pages_total)
    text += _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)

    reply_markup = build_theater_keyboard(
        page_rows, 'sales:season_theater', page1, pages_total,
        done_label='Далее', done_callback_data='next', back_postfix=PICK_SEASON_END,
        page_callback_prefix='page',
    )

    return await _show_step(update, context, text, reply_markup, PICK_SEASON_THEATERS)


async def pick_season_theaters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    intent_id, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    selected: set = set(sales_state.get('season_theater_ids') or [])

    if intent_id == 'sales:season_theater' and payload.startswith('page:'):
        page = int(payload.split(':')[1])
        return await show_pick_season_theaters(update, context, page=page)

    if intent_id == 'sales:season_theater':
        if payload == "next":
            return await show_pick_season_age_min(update, context)
        if payload.isdigit():
            tid = int(payload)
            if tid in selected:
                selected.remove(tid)
            else:
                selected.add(tid)
            sales_state['season_theater_ids'] = list(selected)
    return await show_pick_season_theaters(update, context,
                                           page=sales_state.get('season_theater_page', 1))


# --- SEASON_TICKET_HOLDERS: Optional child age range (buttons) ---

async def show_pick_season_age_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 4/8: Minimum child age selection via buttons (0–10 + Skip)."""
    context.user_data.setdefault('sales', {})
    step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'season_age_min')
    usage_block = _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)
    text = (
        f'<b>Шаг {step_n}/{step_total}: Минимальный возраст ребёнка в билете (необязательно)</b>\n\n'
        'Этот фильтр отбирает только тех, у кого в билете указан ребёнок подходящего возраста.\n\n'
        'Выберите минимальный возраст или нажмите «Пропустить».\n\n'
        + usage_block
    )
    kb_btns = [InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(0, 11)]
    kb_btns.append(InlineKeyboardButton("Пропустить", callback_data="skip"))
    btn_rows = adjust_kbd(kb_btns, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:season_age_min')
    kb = btn_rows
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=PICK_SEASON_THEATERS))
    reply_markup = InlineKeyboardMarkup(kb)
    return await _show_step(update, context, text, reply_markup, PICK_SEASON_AGE_MIN)


async def pick_season_age_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle age min button press."""
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})

    if payload == "skip":
        sales_state['child_age_min'] = None
        return await show_pick_season_age_max(update, context)

    try:
        age = int(payload)
        if 0 <= age <= 10:
            sales_state['child_age_min'] = age
            return await show_pick_season_age_max(update, context)
    except (ValueError, TypeError):
        pass

    return PICK_SEASON_AGE_MIN


async def show_pick_season_age_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 5/8: Maximum child age selection via buttons (min–10 + Skip)."""
    sales_state = context.user_data.setdefault('sales', {})
    c_min = sales_state.get('child_age_min')
    step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'season_age_max')
    usage_block = _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)
    if c_min is not None:
        text = (
            f'<b>Шаг {step_n}/{step_total}: Максимальный возраст ребёнка</b>\n\n'
            f'Минимальный возраст: {c_min} лет.\n\n'
            'Выберите максимальный возраст или нажмите «Пропустить».\n\n'
            + usage_block
        )
    else:
        text = (
            f'<b>Шаг {step_n}/{step_total}: Максимальный возраст ребёнка</b>\n\n'
            'Выберите максимальный возраст или нажмите «Пропустить».\n\n'
            + usage_block
        )
        kb_btns = [InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(0, 11)]

    kb_btns.append(InlineKeyboardButton("Пропустить", callback_data="skip"))
    btn_rows = adjust_kbd(kb_btns, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:season_age_max')
    kb = btn_rows
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=PICK_SEASON_AGE_MIN))
    reply_markup = InlineKeyboardMarkup(kb)
    return await _show_step(update, context, text, reply_markup, PICK_SEASON_AGE_MAX)


async def pick_season_age_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle age max button press."""
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})

    if payload == "skip":
        sales_state['child_age_max'] = None
        return await show_pick_season_statuses(update, context)

    try:
        age = int(payload)
        if 0 <= age <= 10:
            c_min = sales_state.get('child_age_min')
            if c_min is not None and age < c_min:
                return PICK_SEASON_AGE_MAX
            sales_state['child_age_max'] = age
            return await show_pick_season_statuses(update, context)
    except (ValueError, TypeError):
        pass

    return PICK_SEASON_AGE_MAX


# --- SEASON_TICKET_HOLDERS: Ticket status multi-select ---

async def show_pick_season_statuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    selected: set = set(sales_state.get('season_statuses') or
                        [TicketStatus.PAID.value, TicketStatus.APPROVED.value])

    step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'season_statuses')
    lines: List[str] = [
        f'<b>Шаг {step_n}/{step_total}: Статусы билетов</b>',
        'Отметьте цифрами, затем «Далее».',
        '(Если ничего не отмечено — все статусы)'
    ]
    number_to_status: Dict[int, str] = {}
    for idx, s in enumerate(TicketStatus, start=1):
        number_to_status[idx] = s.value
        mark = '✅' if s.value in selected else '▫️'
        lines.append(f"{idx}. {mark} {s.value}")
    lines.append('')
    sn, _ = _get_step_info('SEASON_TICKET_HOLDERS', 'season_statuses')
    lines.append(_get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', sn))

    sales_state['season_status_map'] = number_to_status

    num_buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(i), callback_data=str(i)) for i in
        range(1, len(TicketStatus) + 1)
    ]
    btn_rows = adjust_kbd(num_buttons, 5)
    btn_rows = add_intent_id(btn_rows, 'sales:season_status')

    next_row = add_intent_id(
        [[InlineKeyboardButton("Далее (сводка)", callback_data="next")]],
        'sales:season_status'
    )

    kb = btn_rows + next_row
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=PICK_SEASON_AGE_MAX))

    reply_markup = InlineKeyboardMarkup(kb)
    text = "\n".join(lines)

    return await _show_step(update, context, text, reply_markup, PICK_SEASON_STATUSES)


async def pick_season_statuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    selected: set = set(sales_state.get('season_statuses') or
                        [TicketStatus.PAID.value, TicketStatus.APPROVED.value])

    if payload == "next":
        # Save empty selection as "all statuses"
        if not selected:
            sales_state['season_statuses'] = []
        return await show_pick_attach_theater(update, context)

    if payload.isdigit():
        mapping = sales_state.get('season_status_map') or {}
        status_val = mapping.get(int(payload))
        if status_val:
            if status_val in selected:
                selected.remove(status_val)
            else:
                selected.add(status_val)
            sales_state['season_statuses'] = list(selected)
    return await show_pick_season_statuses(update, context)


# --- SEASON_TICKET_HOLDERS: SQL audience query ---

def _round_half_to_even(value: float) -> int:
    """Round float to nearest even integer on tie (banker's rounding)."""
    d = decimal.Decimal(str(value))
    return int(d.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_EVEN))


async def _select_season_audience(session, sales_state: dict) -> List[tuple]:
    """Return list of (user_id, chat_id) for SEASON_TICKET_HOLDERS broadcast."""
    season_start: date | None = sales_state.get('season_start')
    season_end: date | None = sales_state.get('season_end')
    theater_ids = sales_state.get('season_theater_ids') or []
    child_age_min = sales_state.get('child_age_min')
    child_age_max = sales_state.get('child_age_max')
    status_values = sales_state.get('season_statuses') or []

    t = Ticket.__table__
    ut = UserTicket.__table__
    u = User.__table__
    se = ScheduleEvent.__table__

    # Build ticket status filter
    if status_values:
        ticket_statuses = []
        for val in status_values:
            for member in TicketStatus:
                if member.value == val:
                    ticket_statuses.append(member)
                    break
    else:
        # Empty selection means all statuses — no filter
        ticket_statuses = None

    stmt = (
        sa.select(u.c.user_id, u.c.chat_id)
        .select_from(ut
                     .join(t, ut.c.ticket_id == t.c.id)
                     .join(u, ut.c.user_id == u.c.user_id)
                     .join(se, t.c.schedule_event_id == se.c.id))
        .where(u.c.chat_id.isnot(None))
    )

    # Period filter: only apply if both dates are set
    if season_start is not None and season_end is not None:
        period_start = datetime.combine(season_start, datetime.min.time(), tzinfo=timezone.utc)
        period_end = datetime.combine(season_end, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
        stmt = stmt.where(se.c.datetime_event >= period_start)
        stmt = stmt.where(se.c.datetime_event < period_end)

    if ticket_statuses:
        stmt = stmt.where(t.c.status.in_(ticket_statuses))

    if theater_ids:
        stmt = stmt.where(se.c.theater_event_id.in_(list(map(int, theater_ids))))

    # Child age filter (optional)
    age_filter_active = child_age_min is not None or child_age_max is not None
    if age_filter_active:
        pt = PersonTicket.__table__
        p = Person.__table__
        c = Child.__table__
        # Round child.age to nearest even on tie
        rounded_age = sa.func.round(c.c.age)
        child_subq = (
            sa.select(sa.literal(1))
            .select_from(pt.join(p, pt.c.person_id == p.c.id)
                        .join(c, c.c.person_id == p.c.id))
            .where(pt.c.ticket_id == t.c.id)
            .where(p.c.age_type == AgeType.child)
            .where(c.c.age.isnot(None))
        )
        if child_age_min is not None:
            child_subq = child_subq.where(rounded_age >= child_age_min)
        if child_age_max is not None:
            child_subq = child_subq.where(rounded_age <= child_age_max)
        stmt = stmt.where(child_subq.exists())

    rows = (await session.execute(stmt)).all()
    # Dedup by chat_id
    seen = set()
    result = []
    for user_id, chat_id in rows:
        if chat_id in seen:
            continue
        seen.add(chat_id)
        result.append((user_id, chat_id))
    return result


# --- SEASON_TICKET_HOLDERS: Back navigation ---

async def back_to_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live re-render of season start screen."""
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_start(update, context)


async def back_to_season_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live re-render of season end screen."""
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_end(update, context)


async def back_to_season_theaters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live re-render of season theaters screen."""
    if update.callback_query:
        await update.callback_query.answer()
    sales_state = context.user_data.setdefault('sales', {})
    page = sales_state.get('season_theater_page', 1)
    return await show_pick_season_theaters(update, context, page=page)


async def back_to_season_age_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live re-render of season age min screen."""
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_age_min(update, context)


async def back_to_season_age_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live re-render of season age max screen."""
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_age_max(update, context)


async def back_to_season_statuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live re-render of season statuses screen."""
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_statuses(update, context)


async def back_to_attach_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live re-render of attach theater screen (used by SEASON_TICKET_HOLDERS from GET_MESSAGE)."""
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_attach_theater(update, context)


async def show_pick_theater(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
    campaign_type = sales_state.get('type')

    rows = await fetch_active_theaters(session)
    if not rows:
        await update.effective_chat.send_message(
            "Нет активных спектаклей в репертуаре.")
        return MENU

    page_theaters, page1, pages_total = paginate_list(rows, page, SALES_PAGE_SIZE)
    sales_state['theater_page'] = page1

    step_n, step_total = _get_step_info(campaign_type, 'theater')
    title = f'Шаг {step_n}/{step_total}: Выберите спектакль'
    hint = 'Нажмите на цифру под списком (ID спектакля).'
    text = build_theater_selection_text(page_theaters, set(), title, hint, page1, pages_total)

    if campaign_type == 'WAS_THIS_YEAR_ON_PLAY':
        text += _get_usage_text_with_highlight('WAS_THIS_YEAR_ON_PLAY', step_n)

    if campaign_type in ('SEASON_TICKET_HOLDERS', 'TICKET_HOLDERS'):
        postfix_for_back = PICK_ATTACH_THEATER
    else:
        postfix_for_back = PICK_TYPE

    reply_markup = build_theater_keyboard(
        page_theaters, 'sales:theater', page1, pages_total,
        back_postfix=postfix_for_back,
        page_callback_prefix='theater_page',
    )
    return await _show_step(update, context, text, reply_markup, PICK_THEATER)


async def pick_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    intent_id, payload = remove_intent_id(query.data)
    sales_state = context.user_data.setdefault('sales', {})

    # Handle pagination navigation
    if intent_id == 'sales:theater' and payload.startswith('theater_page:'):
        try:
            page = int(payload.split(':')[1])
        except (TypeError, ValueError):
            page = 1
        return await show_pick_theater(update, context, page=page)

    # Payload contains theater_event.id directly
    try:
        theater_id_val = int(payload)
    except (TypeError, ValueError):
        theater_id_val = None

    if not theater_id_val:
        await query.edit_message_text(
            'Не удалось определить спектакль. Вернитесь и выберите снова.')
        return PICK_THEATER

    sales_state['theater_event_id'] = str(theater_id_val)

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
    sales_state = context.user_data.get('sales', {})
    campaign_type = sales_state.get('type')
    step_n, step_total = _get_step_info(campaign_type, 'scope')
    text = f'<b>Шаг {step_n}/{step_total}: Выберите охват спектаклей</b>\n\nВыберите охват спектаклей для показа свободных мест'
    if campaign_type == 'WAS_THIS_YEAR_ON_PLAY':
        usage_block = _get_usage_text_with_highlight('WAS_THIS_YEAR_ON_PLAY', step_n)
        text += '\n\n' + usage_block
    return await _show_step(update, context, text, reply_markup, PICK_SCOPE)


async def _proceed_to_audience_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper to route to the correct audience selection step based on campaign type."""
    sales_state = context.user_data.get('sales', {})
    campaign_type = sales_state.get('type')

    if campaign_type == 'TICKET_HOLDERS':
        return await show_build_audience(update, context)

    if campaign_type == 'SEASON_TICKET_HOLDERS':
        return await show_build_audience(update, context)

    # Default for WAS_THIS_YEAR_ON_PLAY
    return await show_pick_audience_theater(update, context)


async def show_pick_attach_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    campaign_type = sales_state.get('type')

    # Build summary text based on campaign type
    if campaign_type == 'SEASON_TICKET_HOLDERS':
        season_start = sales_state.get('season_start')
        season_end = sales_state.get('season_end')
        period_str = ""
        if season_start and season_end:
            period_str = f"{season_start.strftime('%d.%m.%Y')} – {season_end.strftime('%d.%m.%Y')}"
        theater_ids = sales_state.get('season_theater_ids') or []
        theater_str = f"{len(theater_ids)} спектаклей" if theater_ids else "все спектакли"
        c_min = sales_state.get('child_age_min')
        c_max = sales_state.get('child_age_max')
        age_str = "без ограничения"
        if c_min is not None and c_max is not None:
            age_str = f"от {c_min} до {c_max} лет"
        elif c_min is not None:
            age_str = f"от {c_min}+ лет"
        elif c_max is not None:
            age_str = f"до {c_max} лет"
        status_values = sales_state.get('season_statuses') or []
        status_str = ", ".join(status_values) if status_values else "все"
        summary_lines = [
            "<b>Параметры рассылки посетителям сезона:</b>",
            f"Период: {period_str}",
            f"Спектакли: {theater_str}",
            f"Возраст ребёнка: {age_str}",
            f"Статусы билетов: {status_str}",
            "",
        ]
        back_target = PICK_SEASON_STATUSES
    elif campaign_type == 'TICKET_HOLDERS':
        filters = sales_state.get('filters', {})
        filter_lines = []
        if filters.get('status'):
            filter_lines.append(f"Статусы: {', '.join(filters['status'])}")
        if filters.get('type_event_ids'):
            filter_lines.append(f"Типы: {len(filters['type_event_ids'])} выбрано")
        if filters.get('theater_event_ids'):
            filter_lines.append(f"Спектакли: {len(filters['theater_event_ids'])} выбрано")
        if filters.get('schedule_event_ids'):
            filter_lines.append(f"Сеансы: {len(filters['schedule_event_ids'])} выбрано")
        if filters.get('ticket_ids'):
            filter_lines.append(f"Билеты (по ID): {len(filters['ticket_ids'])} выбрано")
        if filters.get('base_ticket_ids'):
            filter_lines.append(f"Базовые билеты: {len(filters['base_ticket_ids'])} выбрано")
        if filters.get('child_age_min') is not None or filters.get('child_age_max') is not None:
            c_min = filters.get('child_age_min')
            c_max = filters.get('child_age_max')
            if c_min is not None and c_max is not None:
                filter_lines.append(f"Возраст: от {c_min} до {c_max} лет")
            elif c_min is not None:
                filter_lines.append(f"Возраст: от {c_min}+ лет")
            elif c_max is not None:
                filter_lines.append(f"Возраст: до {c_max} лет")
        if filter_lines:
            summary_lines = [
                "<b>Параметры рассылки обладателям билетов:</b>",
            ] + filter_lines + [""]
        else:
            summary_lines = [
                "<b>Параметры рассылки обладателям билетов:</b>",
                "Фильтры не заданы (будут отобраны все с Оплаченными/Подтверждёнными билетами на будущие сеансы)",
                "",
            ]
        back_target = PICK_FILTERS
    # Add usage hint with highlighted current step
    if campaign_type == 'SEASON_TICKET_HOLDERS':
        step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'attach_theater')
        usage_block = _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)
        attach_header = f"<b>Шаг {step_n}/{step_total}: Прикрепить спектакль со свободными местами?</b>\n"
    elif campaign_type == 'TICKET_HOLDERS':
        step_n, step_total = _get_step_info('TICKET_HOLDERS', 'attach_theater')
        usage_block = _get_usage_text_with_highlight('TICKET_HOLDERS', step_n)
        attach_header = f"<b>Шаг {step_n}/{step_total}: Прикрепить спектакль со свободными местами?</b>\n"
    else:
        usage_block = None
        attach_header = "<b>Прикрепить спектакль со свободными местами?</b>\n"

    text = (
        "\n".join(summary_lines)
        + "\n"
        + attach_header
        + ("Вы можете прикрепить спектакль и сеансы "
           "(в сообщение добавится блок со свободными местами и кнопка покупки)"
           " или отправить простое информационное сообщение.")
    )
    if usage_block:
        text += "\n\n" + usage_block
    kb = [
        [InlineKeyboardButton("🎭 Прикрепить спектакль", callback_data="yes")],
        [InlineKeyboardButton("✉️ Без спектакля (только сообщение)", callback_data="no")],
    ]
    kb = add_intent_id(kb, 'sales:attach_theater')
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=back_target))
    reply_markup = InlineKeyboardMarkup(kb)

    return await _show_step(update, context, text, reply_markup, PICK_ATTACH_THEATER)


async def pick_attach_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})

    if payload == "yes":
        sales_state['attach_theater'] = True
        return await show_pick_theater(update, context)

    if payload == "no":
        sales_state['attach_theater'] = False
        sales_state['theater_event_id'] = None
        sales_state['schedule_ids'] = []
        return await show_build_audience(update, context)

    return PICK_ATTACH_THEATER


# --- Filters for TICKET_HOLDERS type ---

async def show_pick_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    f_time = sales_state.get('f_schedule_time', 'future')
    f_show = sales_state.get('f_schedule_show', 'on')

    step_n, step_total = _get_step_info('TICKET_HOLDERS', 'filters')
    usage_block = _get_usage_text_with_highlight('TICKET_HOLDERS', step_n)
    text = f"<b>Шаг {step_n}/{step_total}: Настройка фильтров аудитории (Обладатели билетов)</b>\n\n"
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
    # Main filter buttons in 2 columns (2 per row)
    main_filter_btns = [
        InlineKeyboardButton("Статус билета", callback_data="status"),
        InlineKeyboardButton("Тип мероприятия", callback_data="type_event"),
        InlineKeyboardButton("Спектакль", callback_data="theater_event"),
        InlineKeyboardButton("Сеанс", callback_data="schedule_event"),
        InlineKeyboardButton("Базовый билет", callback_data="base_ticket"),
        InlineKeyboardButton("Возраст детей", callback_data="child_age"),
    ]
    main_filter_rows = adjust_kbd(main_filter_btns, 2)
    main_filter_rows = add_intent_id(main_filter_rows, 'sales:filters')

    # Additional action buttons (1 per row)
    extra_btns = [
        InlineKeyboardButton("Ввести ID билетов вручную", callback_data="manual_ids"),
    ]
    if has_filters:
        extra_btns.append(InlineKeyboardButton("🗑 Сбросить фильтры", callback_data="reset"))
    extra_btns.append(InlineKeyboardButton("ГОТОВО - Перейти к отбору", callback_data="done"))
    extra_rows = adjust_kbd(extra_btns, 1)
    extra_rows = add_intent_id(extra_rows, 'sales:filters')

    text += "\n\n" + usage_block

    kb = time_kb + show_kb + main_filter_rows + extra_rows
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=PICK_TYPE))
    reply_markup = InlineKeyboardMarkup(kb)

    return await _show_step(update, context, text, reply_markup, PICK_FILTERS)


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
        return await show_pick_attach_theater(update, context)

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

    return await _show_step(update, context, text, reply_markup, PICK_FILTER_STATUS)


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

    lines: List[str] = [
        "<b>Выберите типы мероприятий</b>",
        "Отметьте цифрами (ID типа), затем нажмите «Готово»."
    ]

    for r in rows:
        mark = '✅' if r.id in selected else '▫️'
        lines.append(f"{r.id}. {mark} {r.name}")

    num_buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(r.id), callback_data=str(r.id)) for r in rows
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

    return await _show_step(update, context, text, reply_markup, PICK_FILTER_TYPE_EVENT)


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

    # Check for numeric selection (payload is the type_event_id)
    if payload.isdigit():
        tid = int(payload)
        if tid in selected:
            selected.remove(tid)
        else:
            selected.add(tid)
        filters['type_event_ids'] = list(selected)

    return await show_pick_filter_type_event(update, context)


async def show_pick_filter_theater_event(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    selected: set = set(filters.get('theater_event_ids') or [])

    rows = await fetch_active_theaters(session)
    if not rows:
        await update.callback_query.answer("Нет активных спектаклей.", show_alert=True)
        return PICK_FILTERS

    page_theaters, page1, pages_total = paginate_list(rows, page, SALES_PAGE_SIZE)
    sales_state['filter_theater_page'] = page1

    title = 'Выберите спектакли'
    hint = 'Отметьте цифрами (ID спектакля), затем нажмите «Готово».'
    text = build_theater_selection_text(page_theaters, selected, title, hint, page1, pages_total)

    reply_markup = build_theater_keyboard(
        page_theaters, 'sales:f_theater_event', page1, pages_total,
        rows_per_row=5, done_label='Готово', back_postfix=PICK_FILTERS,
    )
    return await _show_step(update, context, text, reply_markup, PICK_FILTER_THEATER_EVENT)


async def pick_filter_theater_event(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    intent_id, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    selected: set = set(filters.get('theater_event_ids') or [])

    if intent_id == 'sales:f_theater_event' and payload.startswith('page:'):
        page = int(payload.split(':')[1])
        return await show_pick_filter_theater_event(update, context, page=page)

    if payload == "done":
        return await show_pick_filters(update, context)

    if payload.isdigit():
        tid = int(payload)
        if tid in selected:
            selected.remove(tid)
        else:
            selected.add(tid)
        filters['theater_event_ids'] = list(selected)

    return await show_pick_filter_theater_event(update, context,
                                                page=sales_state.get('filter_theater_page', 1))


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

    return await _show_step(update, context, text, reply_markup, PICK_FILTER_SCHEDULE_EVENT)


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

    lines: List[str] = [
        "<b>Выберите типы билетов (BaseTicket)</b>",
        "Отметьте цифрами (ID билета), затем нажмите «Готово»."
    ]

    for r in rows:
        mark = '✅' if r.base_ticket_id in selected else '▫️'
        lines.append(f"{r.base_ticket_id}. {mark} {r.name}")

    num_buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(r.base_ticket_id), callback_data=str(r.base_ticket_id)) for r in rows
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

    return await _show_step(update, context, text, reply_markup, PICK_FILTER_BASE_TICKET)


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

    # Check for numeric selection (payload is the base_ticket_id)
    if payload.isdigit():
        tid = int(payload)
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
    return await _show_step(update, context, text, reply_markup, PICK_FILTER_CHILD_AGE_MIN)


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
    return await _show_step(update, context, text, reply_markup, PICK_FILTER_CHILD_AGE_MAX)


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

    state = await _show_step(update, context, text, reply_markup, PICK_TICKET_IDS)
    # Remember the prompt message ID so pick_ticket_ids can clear its markup later
    context.user_data.setdefault('sales', {})['ticket_ids_prompt_msg_id'] = context.user_data['sales'].get('step_msg_id')
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

    return await show_pick_attach_theater(update, context)


async def pick_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, scope = remove_intent_id(query.data)

    if scope == 'manual':
        # Go to manual schedules selection
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
                                     context: ContextTypes.DEFAULT_TYPE,
                                     page: int = 1):
    """Let admin choose theater_event(s) to filter audience 'already attended this year'.
    Multi-select with Done, uses real theater_event.id, paginated.
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

    rows = await fetch_active_theaters(session)
    if not rows:
        await update.effective_chat.send_message(
            "Нет активных спектаклей в репертуаре.")
        return MENU

    page_theaters, page1, pages_total = paginate_list(rows, page, SALES_PAGE_SIZE)
    sales_state['aud_theater_page'] = page1

    step_n, step_total = _get_step_info('WAS_THIS_YEAR_ON_PLAY', 'audience_theater')
    title = f'Шаг {step_n}/{step_total}: Выберите спектакль(и) для фильтра аудитории'
    hint = 'Отметьте цифрами (ID спектакля), затем нажмите «Готово».\nПо этим спектаклям будут выбраны пользователи, которые уже были в текущем году.'
    text = build_theater_selection_text(page_theaters, selected, title, hint, page1, pages_total)
    text += _get_usage_text_with_highlight('WAS_THIS_YEAR_ON_PLAY', step_n)

    reply_markup = build_theater_keyboard(
        page_theaters, 'sales:aud_theater', page1, pages_total,
        rows_per_row=5, done_label='Готово', back_postfix=PICK_SCOPE,
    )
    return await _show_step(update, context, text, reply_markup, PICK_AUDIENCE_THEATER)


async def pick_audience_theater(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sales_state = context.user_data.setdefault('sales', {})
    intent_id, payload = remove_intent_id(query.data)

    selected: set = set(map(int, sales_state.get('audience_theater_ids') or []))

    # Handle pagination navigation
    if intent_id == 'sales:aud_theater' and payload.startswith('page:'):
        page = int(payload.split(':')[1])
        return await show_pick_audience_theater(update, context, page=page)

    # Toggle selection (payload is theater_event.id directly)
    if payload.isdigit():
        t_id = int(payload)
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
        return await show_build_audience(update, context)

    return await show_pick_audience_theater(update, context,
                                            page=sales_state.get('aud_theater_page', 1))


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
    return await _show_step(update, context, text, reply_markup, PICK_SCHEDULES)


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
    return await _show_step(update, context, text, reply_markup, PICK_SCHEDULES)


# --- Step 6: admin text input ---
async def ask_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END
    audience_summary = sales_state.pop('audience_summary', None)
    media = sales_state.get('media', [])
    media_hint = f'Медиа прикреплено: {len(media)}' if media else 'Медиа не прикреплено.'
    campaign_type = sales_state.get('type')
    step_n, step_total = _get_step_info(campaign_type, 'text')
    step_text = (
        f'<b>Шаг {step_n}/{step_total}: Отправьте текст сообщения</b>\n\n'
        f'{media_hint}\n\n'
        'Отправьте текстовое сообщение.\n'
        'Текст будет добавлен к медиа как подпись (до 1024 символов)\n'
        'или отправлен отдельным сообщением, если не помещается.\n\n'
        'После отправки вы увидите предпросмотр.'
    )
    text = step_text
    if audience_summary:
        text = audience_summary + '\n\n' + step_text

    if sales_state.get('dev_mode'):
        back_target = BUILD_AUDIENCE
    elif campaign_type == 'TICKET_HOLDERS':
        back_target = PICK_ATTACH_THEATER
    elif campaign_type == 'SEASON_TICKET_HOLDERS':
        back_target = PICK_ATTACH_THEATER
    else:
        back_target = PICK_AUDIENCE_THEATER
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
    """Store admin text message into extra_payload and proceed to preview.
    
    In the new flow, media is collected in GET_MEDIA state.
    This handler now accepts only text messages.
    """
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

    # Only accept text messages; media handled in GET_MEDIA
    if not msg.text:
        await update.effective_chat.send_message(
            'На этом шаге принимается только текст. Медиа отправлялось на предыдущем шаге.\n'
            'Если вы хотели отправить медиа, нажмите «Назад».'
        )
        return GET_MESSAGE

    plain_text = msg.text_html or ''
    entities = _serialize_entities(msg.entities)

    # Store in extra_payload
    extra_payload = sales_state.get('extra_payload', {})
    extra_payload['text'] = plain_text
    extra_payload['text_entities'] = entities
    
    # Determine text_mode based on media and length
    media = sales_state.get('media', [])
    if media:
        # Will check length in preview
        extra_payload['text_mode'] = 'caption'
    else:
        # No media — text only, no caption limit
        extra_payload['text_mode'] = 'separate'
    
    sales_state['extra_payload'] = extra_payload

    # Also update campaign DB fields for backward compatibility
    fields = {
        'message_kind': 'text',
        'message_text': plain_text,
        'message_entities': entities,
    }
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

    if campaign.type in ('WAS_THIS_YEAR_ON_PLAY', 'TICKET_HOLDERS', 'SEASON_TICKET_HOLDERS') and campaign.theater_event_id:
        theater_event = await db_postgres.get_theater_event(
            session, campaign.theater_event_id)
        if theater_event:
            full_name = get_full_name_event(theater_event)
        availability_block = await _availability_block(session, schedule_ids)

    # Build extra block
    extra = build_extra(full_name, availability_block, reserve_text)

    # Get media and text from extra_payload (new format)
    extra_payload = sales_state.get('extra_payload', {})
    media = extra_payload.get('media', [])
    plain_text = extra_payload.get('text', '')
    text_mode = extra_payload.get('text_mode', 'caption')

    # Fallback to old campaign fields if no extra_payload
    if not media and not plain_text:
        plain_text = campaign.message_text or campaign.caption_text or ''
        kind = campaign.message_kind
        if kind == 'photo' and campaign.photo_file_id:
            media = [{'type': 'photo', 'file_id': campaign.photo_file_id}]
        elif kind == 'video' and campaign.video_file_id:
            media = [{'type': 'video', 'file_id': campaign.video_file_id}]
        elif kind == 'animation' and campaign.animation_file_id:
            media = [{'type': 'animation', 'file_id': campaign.animation_file_id}]
        if not media:
            text_mode = 'separate'

    # Check length before sending preview
    has_media = bool(media)
    report = analyze_length(plain_text, extra, has_media, text_mode)
    if report:
        # Show length fix screen
        sales_state['length_report'] = report
        text_report = format_length_report(report)
        kb = [
            [InlineKeyboardButton('✂️ Сократить текст', callback_data='shorten')],
            [InlineKeyboardButton('📤 Отправить текст отдельно', callback_data='send_separate')],
        ]
        kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales',
                                          add_back_btn=True,
                                          postfix_for_back=GET_MESSAGE))
        reply_markup = InlineKeyboardMarkup(add_intent_id(kb, 'sales:length'))
        await update.effective_chat.send_message(
            text=text_report,
            reply_markup=reply_markup,
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        state = LENGTH_FIX
        await set_back_context(context, state, text_report, reply_markup)
        context.user_data['STATE'] = state
        return LENGTH_FIX

    # Recipients' count
    pending_cnt = (await session.execute(
        sa.select(sa.func.count()).select_from(SalesRecipient).where(
            SalesRecipient.campaign_id == campaign_id)
    )).scalar() or 0

    # Build keyboard for preview actions
    action_rows = [
        [InlineKeyboardButton('Запустить', callback_data='run')],
        [InlineKeyboardButton('Изменить текст', callback_data='edit_text')],
        [InlineKeyboardButton('Изменить медиа', callback_data='edit_media')],
    ]
    if campaign.theater_event_id or schedule_ids:
        action_rows.append([InlineKeyboardButton('Изменить сеансы',
                              callback_data='edit_schedules')])
    action_rows = add_intent_id(action_rows, 'sales:preview')
    action_rows.append([InlineKeyboardButton('Отмена', callback_data='Отменить')])
    reply_markup = InlineKeyboardMarkup(action_rows)

    # Send preview using unified send_campaign_message
    chat = update.effective_chat
    thread_id = getattr(update.effective_message, 'message_thread_id', None)

    sent_messages = await send_campaign_message(
        context.bot,
        chat.id,
        media=media,
        text=plain_text,
        extra=extra,
        text_mode=text_mode,
        reply_markup=reply_markup,
        message_thread_id=thread_id,
    )

    # Store preview message IDs for editing
    sales_state['preview_message_ids'] = [m.message_id for m in sent_messages]

    # Send info message separately
    await chat.send_message(
        f'👁 Предпросмотр. Получателей: {pending_cnt}. Показов: {len(schedule_ids)}',
        message_thread_id=thread_id,
    )

    return PREVIEW


async def _safe_edit_message(query, text: str):
    msg = getattr(query, 'message', None)
    if msg is not None and (
            getattr(msg, 'photo', None) or
            getattr(msg, 'video', None) or
            getattr(msg, 'animation', None)
    ):
        await safe_edit_caption(query, caption=text, logger=sales_logger)
    else:
        await safe_edit_text(query, text=text, logger=sales_logger)


async def preview_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    if action == 'edit_text':
        # Clean up preview messages
        for mid in sales_state.pop('preview_message_ids', []):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=mid)
            except Exception:
                pass
        return await ask_message(update, context)
    if action == 'edit_media':
        # Clean up preview messages
        for mid in sales_state.pop('preview_message_ids', []):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=mid)
            except Exception:
                pass
        return await show_get_media(update, context)
    if action == 'edit_schedules':
        return await show_pick_schedules(update, context, page=1)
    if action == 'cancel':
        # mark canceled
        campaign_id = sales_state.get('campaign_id')
        await set_campaign_status(context.session, campaign_id, 'canceled')
        await context.session.commit()
        # Delete preview messages
        for mid in sales_state.pop('preview_message_ids', []):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=mid)
            except Exception:
                pass
        await update.effective_chat.send_message(
            'Кампания отменена.\n\nЧтобы запустить рассылку заново, используйте команду /sales.',
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
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
        # Check campaign status — prevent re-running
        campaign: SalesCampaign = await session.get(SalesCampaign, campaign_id)
        if not campaign:
            await query.answer('Кампания не найдена.', show_alert=True)
            return PREVIEW
        if campaign.status == 'done':
            await query.answer(
                'Кампания уже завершена.',
                show_alert=True)
            return PREVIEW
        if campaign.status == 'canceled':
            await query.answer(
                'Кампания отменена. Создайте новую через /sales.',
                show_alert=True)
            return PREVIEW
        if campaign.status == 'running':
            # Campaign was interrupted — reset and re-publish
            sales_logger.info(
                f'Кампания #{campaign_id} в running, перезапуск: recipients в pending')
        # Check message exists
        extra_payload = sales_state.get('extra_payload', {})
        has_text = bool(extra_payload.get('text'))
        has_media = bool(extra_payload.get('media'))
        has_old_message = campaign.message_kind is not None
        if not has_text and not has_media and not has_old_message:
            await query.answer('Сначала задайте текст сообщения.',
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
        # Save extra_payload to campaign before publishing
        if extra_payload:
            await session.execute(
                sa.update(SalesCampaign)
                .where(SalesCampaign.id == campaign_id)
                .values(extra_payload=extra_payload)
            )
            await session.commit()
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


async def handle_length_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle LENGTH_FIX state actions: shorten or send_separate."""
    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})

    if action == 'send_separate':
        # Change text_mode to 'separate' and re-preview
        extra_payload = sales_state.get('extra_payload', {})
        extra_payload['text_mode'] = 'separate'
        sales_state['extra_payload'] = extra_payload
        sales_state.pop('length_report', None)
        return await show_preview(update, context)

    if action == 'shorten':
        # Go back to text input
        sales_state.pop('length_report', None)
        return await ask_message(update, context)

    return LENGTH_FIX

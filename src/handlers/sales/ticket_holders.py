"""TICKET_HOLDERS type handlers: filters and sub-filters."""
import re
from datetime import datetime, timezone
from typing import Dict, List

import sqlalchemy as sa
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import TypeEvent, BaseTicket, ScheduleEvent
from db.enum import TicketStatus

from .states import (
    PAGE_SIZE, SALES_PAGE_SIZE, PICK_FILTERS, PICK_FILTER_STATUS,
    PICK_FILTER_TYPE_EVENT, PICK_FILTER_THEATER_EVENT, PICK_FILTER_SCHEDULE_EVENT,
    PICK_FILTER_BASE_TICKET, PICK_TICKET_IDS, PICK_FILTER_CHILD_AGE_MIN,
    PICK_FILTER_CHILD_AGE_MAX, _get_step_info, _get_usage_text_with_highlight,
    _format_label,
)
from .ui_helpers import (
    fetch_active_theaters, paginate_list, build_theater_selection_text,
    build_theater_keyboard, _show_step,
)
from utilities.utl_kbd import (
    create_replay_markup, remove_intent_id, add_intent_id, adjust_kbd,
    add_btn_back_and_cancel,
)


async def show_pick_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    f_time = sales_state.get('f_schedule_time', 'future')
    f_show = sales_state.get('f_schedule_show', 'on')

    step_n, step_total = _get_step_info('TICKET_HOLDERS', 'filters')
    usage_block = _get_usage_text_with_highlight('TICKET_HOLDERS', step_n)
    text = f"<b>Шаг {step_n}/{step_total}: Настройка фильтров аудитории (Обладатели билетов)</b>\n\n"
    text += "Выберите критерии для отбора пользователей. Если фильтр не задан, он не учитывается.\n\n"

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
    kb = add_intent_id(kb, 'sales:filters')
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back='PICK_TYPE'))
    reply_markup = InlineKeyboardMarkup(kb)

    return await _show_step(update, context, text, reply_markup, PICK_FILTERS)


async def back_to_pick_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        from .shared_steps import show_pick_attach_theater
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
    kb = add_intent_id(kb, 'sales:f_status')
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
    kb = add_intent_id(kb, 'sales:f_type_event')
    kb.append(
        add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                postfix_for_back=PICK_FILTERS))

    reply_markup = InlineKeyboardMarkup(kb)
    text = "\n".join(lines)

    return await _show_step(update, context, text, reply_markup, PICK_FILTER_TYPE_EVENT)


async def pick_filter_type_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    selected: set = set(filters.get('type_event_ids') or [])

    if payload == "done":
        return await show_pick_filters(update, context)

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


async def pick_filter_theater_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    f_time = sales_state.get('f_schedule_time', 'future')
    f_show = sales_state.get('f_schedule_show', 'on')

    now = datetime.now(timezone.utc)
    stmt = sa.select(ScheduleEvent)

    theater_event_ids = filters.get('theater_event_ids', [])
    if theater_event_ids:
        stmt = stmt.where(ScheduleEvent.theater_event_id.in_(theater_event_ids))

    if f_time == 'past':
        stmt = stmt.where(ScheduleEvent.datetime_event < now)
    elif f_time == 'future':
        stmt = stmt.where(ScheduleEvent.datetime_event >= now)

    if f_show == 'on':
        stmt = stmt.where(ScheduleEvent.flag_turn_in_bot == True)
    elif f_show == 'off':
        stmt = stmt.where(ScheduleEvent.flag_turn_in_bot == False)

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
    kb_final = add_intent_id(kb_final, 'sales:f_schedule')
    kb_final.append(add_btn_back_and_cancel(postfix_for_cancel='sales',
                                            add_back_btn=True,
                                            postfix_for_back=PICK_FILTERS))

    reply_markup = InlineKeyboardMarkup(kb_final)
    text = "\n".join(lines)

    return await _show_step(update, context, text, reply_markup, PICK_FILTER_SCHEDULE_EVENT)


async def pick_filter_schedule_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    match = re.search(r"Стр\. (\d+)/", query.message.text)
    page = int(match.group(1)) if match else 1

    return await show_pick_filter_schedule_event(update, context, page=page)


async def show_pick_filter_base_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = context.session
    sales_state = context.user_data.get('sales', {})
    filters = sales_state.get('filters', {})
    selected: set = set(filters.get('base_ticket_ids') or [])

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
    kb = add_intent_id(kb, 'sales:f_base_ticket')
    kb.append(
        add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                postfix_for_back=PICK_FILTERS))

    reply_markup = InlineKeyboardMarkup(kb)
    text = "\n".join(lines)

    return await _show_step(update, context, text, reply_markup, PICK_FILTER_BASE_TICKET)


async def pick_filter_base_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    filters = sales_state.setdefault('filters', {})
    selected: set = set(filters.get('base_ticket_ids') or [])

    if payload == "done":
        return await show_pick_filters(update, context)

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
    btn_rows.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                            postfix_for_back=PICK_FILTERS))
    kb = btn_rows
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
    btn_rows.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                            postfix_for_back=PICK_FILTER_CHILD_AGE_MIN))
    kb = btn_rows
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

    for key in ['status', 'type_event_ids', 'theater_event_ids', 'schedule_event_ids', 'base_ticket_ids']:
        filters.pop(key, None)

    from .shared_steps import show_pick_attach_theater
    return await show_pick_attach_theater(update, context)

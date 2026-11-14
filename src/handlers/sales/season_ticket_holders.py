"""SEASON_TICKET_HOLDERS type handlers: dates, theaters, age, statuses."""
from datetime import datetime, timezone, date
from typing import Dict, List

import sqlalchemy as sa
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import ScheduleEvent
from db.enum import TicketStatus

from .states import (
    SALES_PAGE_SIZE, PICK_SEASON_START, PICK_SEASON_END, PICK_SEASON_THEATERS,
    PICK_SEASON_AGE_MIN, PICK_SEASON_AGE_MAX, PICK_SEASON_STATUSES,
    MENU, _parse_date, _get_step_info, _get_usage_text_with_highlight,
)
from .ui_helpers import (
    fetch_active_theaters, paginate_list, build_theater_selection_text,
    build_theater_keyboard, _show_step,
)
from utilities.utl_kbd import (
    remove_intent_id, add_intent_id, adjust_kbd, add_btn_back_and_cancel,
)


async def show_pick_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                                      postfix_for_back='PICK_TYPE'))
    reply_markup = InlineKeyboardMarkup(kb)
    return await _show_step(update, context, text, reply_markup, PICK_SEASON_START)


async def pick_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})

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
    sales_state = context.user_data.setdefault('sales', {})
    season_start = sales_state.get('season_start')
    step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'season_end')
    usage_block = _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)

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
    sales_state = context.user_data.setdefault('sales', {})

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        _, payload = remove_intent_id(query.data)
        if payload == 'skip':
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


async def show_pick_season_age_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    btn_rows.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                            postfix_for_back=PICK_SEASON_THEATERS))
    kb = btn_rows
    reply_markup = InlineKeyboardMarkup(kb)
    return await _show_step(update, context, text, reply_markup, PICK_SEASON_AGE_MIN)


async def pick_season_age_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        kb_btns = [InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(c_min, 11)]
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
    btn_rows.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                            postfix_for_back=PICK_SEASON_AGE_MIN))
    kb = btn_rows
    reply_markup = InlineKeyboardMarkup(kb)
    return await _show_step(update, context, text, reply_markup, PICK_SEASON_AGE_MAX)


async def pick_season_age_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    kb = add_intent_id(kb, 'sales:season_status')
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
        if not selected:
            sales_state['season_statuses'] = []
        else:
            sales_state['season_statuses'] = list(selected)
        from .shared_steps import show_pick_attach_theater
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


# --- Back navigation ---

async def back_to_season_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_start(update, context)


async def back_to_season_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_end(update, context)


async def back_to_season_theaters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    sales_state = context.user_data.setdefault('sales', {})
    page = sales_state.get('season_theater_page', 1)
    return await show_pick_season_theaters(update, context, page=page)


async def back_to_season_age_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_age_min(update, context)


async def back_to_season_age_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_age_max(update, context)


async def back_to_season_statuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    return await show_pick_season_statuses(update, context)


async def back_to_attach_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    from .shared_steps import show_pick_attach_theater
    return await show_pick_attach_theater(update, context)

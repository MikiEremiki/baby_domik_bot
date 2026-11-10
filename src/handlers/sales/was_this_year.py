"""WAS_THIS_YEAR_ON_PLAY type handlers: theater, scope, schedules, audience_theater."""
from datetime import datetime, timezone
from typing import List

import sqlalchemy as sa
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import ScheduleEvent, TheaterEvent

from .states import (
    PAGE_SIZE, SALES_PAGE_SIZE, PICK_SCOPE, PICK_SCHEDULES, PICK_AUDIENCE_THEATER,
    PICK_THEATER, MENU, _get_step_info, _get_usage_text_with_highlight,
    _format_label,
)
from .ui_helpers import (
    fetch_active_theaters, paginate_list, build_theater_selection_text,
    build_theater_keyboard, _show_step,
)
from .audience import _get_available_schedules
from utilities.utl_kbd import (
    create_replay_markup, remove_intent_id, add_intent_id, adjust_kbd,
    add_btn_back_and_cancel,
)


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
        from .states import PICK_ATTACH_THEATER
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

    if intent_id == 'sales:theater' and payload.startswith('theater_page:'):
        try:
            page = int(payload.split(':')[1])
        except (TypeError, ValueError):
            page = 1
        return await show_pick_theater(update, context, page=page)

    try:
        theater_id_val = int(payload)
    except (TypeError, ValueError):
        theater_id_val = None

    if not theater_id_val:
        await query.edit_message_text(
            'Не удалось определить спектакль. Вернитесь и выберите снова.')
        return PICK_THEATER

    sales_state['theater_event_id'] = str(theater_id_val)

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


async def pick_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, scope = remove_intent_id(query.data)

    if scope == 'manual':
        return await show_pick_schedules(update, context, page=1)

    theater_id = context.user_data['sales'].get('theater_event_id')
    if not theater_id:
        await query.edit_message_text(
            'Спектакль не выбран. Вернитесь на шаг назад.')
        return PICK_THEATER

    session = context.session
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
    rows = (await session.execute(stmt)).mappings().all()
    schedule_ids = [r['id'] for r in rows]
    context.user_data['sales']['schedule_ids'] = schedule_ids

    return await _proceed_to_audience_selection(update, context)


async def _proceed_to_audience_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper to route to the correct audience selection step based on campaign type."""
    sales_state = context.user_data.get('sales', {})
    campaign_type = sales_state.get('type')

    if campaign_type == 'TICKET_HOLDERS':
        from .shared_steps import show_build_audience
        return await show_build_audience(update, context)

    if campaign_type == 'SEASON_TICKET_HOLDERS':
        from .shared_steps import show_build_audience
        return await show_build_audience(update, context)

    return await show_pick_audience_theater(update, context)


async def show_pick_audience_theater(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE,
                                     page: int = 1):
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
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

    if intent_id == 'sales:aud_theater' and payload.startswith('page:'):
        page = int(payload.split(':')[1])
        return await show_pick_audience_theater(update, context, page=page)

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
        from .shared_steps import show_build_audience
        return await show_build_audience(update, context)

    return await show_pick_audience_theater(update, context,
                                            page=sales_state.get('aud_theater_page', 1))


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
    rows = await _get_available_schedules(session, int(theater_id))

    sales_state.setdefault('manual_selected_ids', set())
    page1 = max(1, int(page))
    sales_state['page1'] = page1

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

    event_rows = adjust_kbd(event_buttons, 5)
    event_rows = add_intent_id(event_rows, 'sales:schedule')

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

    done_row = [InlineKeyboardButton('Готово', callback_data='done')]
    done_row = add_intent_id([done_row], 'sales:schedule')

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

            context.user_data['sales']['schedule_ids'] = selected_ids
            return await _proceed_to_audience_selection(update, context)

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

    event_rows = adjust_kbd(event_buttons, 5)
    event_rows = add_intent_id(event_rows, 'sales:schedule')

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

    done_row = [InlineKeyboardButton('Готово', callback_data='done')]
    done_row = add_intent_id([done_row], 'sales:schedule')

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

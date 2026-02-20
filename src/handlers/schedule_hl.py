import logging
from datetime import datetime, timedelta
from typing import List, Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from db import db_postgres
from db.enum import TicketPriceType
from handlers.support_hl import send_settings_menu
from utilities.utl_kbd import add_btn_back_and_cancel
from utilities.utl_func import set_back_context

logger = logging.getLogger('bot.schedule_hl')

# Состояния мастера создания события расписания
(
    SCH_TYPE,
    SCH_THEATER,
    SCH_DATETIME,
    SCH_QTY_CHILD,
    SCH_QTY_ADULT,
    SCH_PRICE_TYPE,
    SCH_FLAGS,
    SCH_BT_SELECT,
    SCH_CONFIRM,
) = range(70, 79)


def _fmt_type_event(te) -> str:
    name = te.name
    if name == 'П': name = 'Р'
    return f"#{te.id} {name}"


def _fmt_theater_event(the) -> str:
    return f"#{the.id} {the.name}"


# ===== Edit entry points =====
async def schedule_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    context.user_data['new_schedule_event'] = {
        'data': {
            'type_event_id': None,
            'theater_event_id': None,
            'flag_turn_in_bot': True,
            'datetime_event': None,
            'qty_child': 0,
            'qty_adult': 0,
            'flag_gift': False,
            'flag_christmas_tree': False,
            'flag_santa': False,
            'ticket_price_type': TicketPriceType.NONE,
            'base_ticket_ids': [],
        },
        'service': {
            'is_update': False
        }
    }

    # Показываем выбор типа сразу
    types = await db_postgres.get_all_type_events(context.session)
    if not types:
        await (query.edit_message_text if query else update.effective_chat.send_message)(
            'Не найдены Типы событий. Добавьте их сначала.'
        )
        return 3

    text = 'Шаг 1/8. Выберите тип события:\n\n'
    keyboard = []
    type_buttons = []
    for t in types:
        short_name = t.name_alias or t.name
        if short_name == 'П': short_name = 'Р'
        
        text += f"• ID {t.id}: {t.name} ({short_name})\n"
        
        btn_label = f"ID {t.id} ({short_name})"
        type_buttons.append(InlineKeyboardButton(btn_label, callback_data=f'sch_tp_{t.id}'))
    
    # Группируем по 2
    for i in range(0, len(type_buttons), 2):
        keyboard.append(type_buttons[i:i + 2])
        
    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3'))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)

    context.user_data['new_schedule_event']['service']['message_id'] = message.message_id

    state = SCH_TYPE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def edit_type_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    # mark jump back to summary after selection
    context.user_data['new_schedule_event']['service']['jump_to_summary'] = True

    types = await db_postgres.get_all_type_events(context.session)
    if not types:
        await (query.edit_message_text if query else update.effective_chat.send_message)(
            'Не найдены Типы событий. Добавьте их сначала.'
        )
        return 3

    text = 'Редактирование: выберите тип события:\n\n'
    keyboard = []
    type_buttons = []
    for t in types:
        short_name = t.name_alias or t.name
        if short_name == 'П': short_name = 'Р'
        
        text += f"• ID {t.id}: {t.name} ({short_name})\n"
        
        btn_label = f"ID {t.id} ({short_name})"
        type_buttons.append(InlineKeyboardButton(btn_label, callback_data=f'sch_tp_{t.id}'))
    
    # Группируем по 2
    for i in range(0, len(type_buttons), 2):
        keyboard.append(type_buttons[i:i + 2])
        
    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=str(SCH_CONFIRM)))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.effective_chat.send_message(text, reply_markup=reply_markup)

    state = SCH_TYPE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def edit_theater_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    context.user_data['new_schedule_event']['service']['jump_to_summary'] = True
    
    # Инициализируем фильтр если его нет
    if 'filter_theater' not in context.user_data['new_schedule_event']['service']:
        context.user_data['new_schedule_event']['service']['filter_theater'] = 'actual'
    
    current_filter = context.user_data['new_schedule_event']['service']['filter_theater']
    if current_filter == 'actual':
        theaters = await db_postgres.get_all_theater_events_actual(context.session)
    else:
        theaters = await db_postgres.get_all_theater_events(context.session)
        
    if not theaters and current_filter == 'actual':
        # Если актуальных нет, пробуем показать все
        theaters = await db_postgres.get_all_theater_events(context.session)
        
    if not theaters:
        await (query.edit_message_text if query else update.effective_chat.send_message)(
            'Не найден репертуар. Сначала добавьте спектакли.'
        )
        return 3
    return await _render_theater_list(update, context, theaters, 0, back_postfix=str(SCH_CONFIRM))


async def edit_datetime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_schedule_event']['service']['jump_to_summary'] = True
    return await ask_datetime(update, context)


async def edit_qty_child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_schedule_event']['service']['jump_to_summary'] = True
    return await ask_qty_child(update, context)


async def edit_qty_adult_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_schedule_event']['service']['jump_to_summary'] = True
    return await ask_qty_adult(update, context)


async def edit_price_type_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_schedule_event']['service']['jump_to_summary'] = True
    return await ask_price_type(update, context)


async def edit_flags_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_schedule_event']['service']['edit_flags'] = True
    context.user_data['new_schedule_event']['service']['jump_to_summary'] = True
    return await ask_flags(update, context)


async def edit_bt_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_schedule_event']['service']['jump_to_summary'] = True
    return await ask_base_tickets(update, context)


async def edit_turn_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data['new_schedule_event']['data']
    data['flag_turn_in_bot'] = not data.get('flag_turn_in_bot', False)
    return await ask_schedule_summary(update, context)


async def schedule_update_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    sch_id = int(query.data.replace('schedule_event_edit_', ''))
    event = await db_postgres.get_schedule_event(context.session, sch_id)

    if not event:
        await query.edit_message_text("Событие не найдено.")
        return 3

    context.user_data['new_schedule_event'] = {
        'data': {
            'id': event.id,
            'type_event_id': event.type_event_id,
            'theater_event_id': event.theater_event_id,
            'flag_turn_in_bot': event.flag_turn_in_bot,
            'datetime_event': event.datetime_event,
            'qty_child': event.qty_child,
            'qty_child_free_seat': event.qty_child_free_seat,
            'qty_child_nonconfirm_seat': event.qty_child_nonconfirm_seat,
            'qty_adult': event.qty_adult,
            'qty_adult_free_seat': event.qty_adult_free_seat,
            'qty_adult_nonconfirm_seat': event.qty_adult_nonconfirm_seat,
            'flag_gift': event.flag_gift,
            'flag_christmas_tree': event.flag_christmas_tree,
            'flag_santa': event.flag_santa,
            'ticket_price_type': event.ticket_price_type,
            'base_ticket_ids': [bt.base_ticket_id for bt in event.base_tickets],
        },
        'service': {
            'message_id': query.message.message_id,
            'is_update': True
        }
    }

    return await ask_schedule_summary(update, context)


async def ask_schedule_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    event_data = context.user_data['new_schedule_event']['data']
    is_update = context.user_data['new_schedule_event']['service'].get('is_update', False)

    type_obj = await db_postgres.get_type_event(context.session, event_data['type_event_id'])
    theater_obj = await db_postgres.get_theater_event(context.session, event_data['theater_event_id'])

    text = (
        f"<b>{'Редактирование' if is_update else 'Подтверждение'} события расписания</b>\n\n"
        f"1. 🎭 <b>Тип:</b> {type_obj.name if type_obj else '???'}\n"
        f"2. 🎬 <b>Спектакль:</b> {theater_obj.name if theater_obj else '???'}\n"
        f"3. 📅 <b>Дата/время:</b> {event_data['datetime_event'].strftime('%d.%m.%Y %H:%M')}\n"
        f"4. 👶 <b>Места (дет):</b> {event_data['qty_child']}\n"
        f"5. 👨 <b>Места (взр):</b> {event_data['qty_adult']}\n"
        f"6. 💰 <b>Тип цены:</b> {event_data['ticket_price_type'].value if event_data['ticket_price_type'].value else 'По умолчанию'}\n"
        f"7. 🚩 <b>Флаги:</b> "
        f"{'🎁' if event_data['flag_gift'] else ''}"
        f"{'🎄' if event_data['flag_christmas_tree'] else ''}"
        f"{'🎅' if event_data['flag_santa'] else ''}\n"
        f"8. 🎟 <b>Билеты:</b> {len(event_data['base_ticket_ids']) if event_data['base_ticket_ids'] else 'Наследуются'}\n"
        f"9. 🤖 <b>В боте:</b> {'Вкл' if event_data['flag_turn_in_bot'] else 'Выкл'}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("1. Тип", callback_data='sch_edit_type'),
            InlineKeyboardButton("2. Спектакль", callback_data='sch_edit_theater'),
        ],
        [
            InlineKeyboardButton("3. Дата/время", callback_data='sch_edit_datetime'),
            InlineKeyboardButton("4. Места (дет)", callback_data='sch_edit_qty_child'),
        ],
        [
            InlineKeyboardButton("5. Места (взр)", callback_data='sch_edit_qty_adult'),
            InlineKeyboardButton("6. Тип цены", callback_data='sch_edit_price_type'),
        ],
        [
            InlineKeyboardButton("7. Флаги", callback_data='sch_edit_flags'),
            InlineKeyboardButton("8. Билеты", callback_data='sch_edit_bt'),
        ],
        [
            InlineKeyboardButton("9. Вкл/Выкл в боте", callback_data='sch_edit_turn'),
        ],
        [InlineKeyboardButton("✅ Сохранить", callback_data='sch_accept')],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3')
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['new_schedule_event']['service']['message_id'],
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

    state = SCH_CONFIRM
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    type_id = int(query.data.replace('sch_tp_', ''))
    context.user_data['new_schedule_event']['data']['type_event_id'] = type_id

    # Если редактирование — возвращаемся к сводке
    if context.user_data['new_schedule_event']['service'].get('jump_to_summary'):
        context.user_data['new_schedule_event']['service'].pop('jump_to_summary', None)
        return await ask_schedule_summary(update, context)

    # Переходим к выбору спектакля
    return await ask_theater_event(update, context)


async def ask_theater_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    # Инициализируем фильтр если его нет
    if 'filter_theater' not in context.user_data['new_schedule_event']['service']:
        context.user_data['new_schedule_event']['service']['filter_theater'] = 'actual'
        
    current_filter = context.user_data['new_schedule_event']['service']['filter_theater']
    if current_filter == 'actual':
        theaters = await db_postgres.get_all_theater_events_actual(context.session)
    else:
        theaters = await db_postgres.get_all_theater_events(context.session)

    if not theaters and current_filter == 'actual':
        # Если актуальных нет, пробуем показать все
        theaters = await db_postgres.get_all_theater_events(context.session)

    if not theaters:
        await (query.edit_message_text if query else update.effective_chat.send_message)(
            'Не найден репертуар. Сначала добавьте спектакли.'
        )
        return 3

    # Пагинация по 10 в списке
    page = 0
    return await _render_theater_list(update, context, theaters, page)


async def _render_theater_list(update: Update, context: ContextTypes.DEFAULT_TYPE, theaters, page: int, back_postfix: str = '70'):
    total = len(theaters)
    per_page = 10
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    end = start + per_page
    subset = theaters[start:end]

    current_filter = context.user_data['new_schedule_event']['service'].get('filter_theater', 'actual')

    text = 'Шаг 2/8. Выберите спектакль из репертуара:\n\n'
    item_buttons = []
    for t in subset:
        text += f"• {_fmt_theater_event(t)}\n"
        item_buttons.append(InlineKeyboardButton(text=f"ID {t.id}", callback_data=f'sch_th_t_{t.id}_{page}'))

    keyboard = []
    # Ряд кнопок элементов (по 3 в ряд)
    for i in range(0, len(item_buttons), 3):
        keyboard.append(item_buttons[i:i + 3])

    # Фильтры
    f_row = [
        InlineKeyboardButton(("✅ " if current_filter == 'actual' else "") + "Актуал", callback_data='sch_th_f_actual'),
        InlineKeyboardButton(("✅ " if current_filter == 'all' else "") + "Все", callback_data='sch_th_f_all')
    ]
    keyboard.append(f_row)

    nav = []
    if pages > 1:
        # ⏮ - в начало
        nav.append(InlineKeyboardButton('⏮', callback_data=f'sch_th_p_0'))
        # ◀️ - назад
        prev_p = max(0, page - 1)
        nav.append(InlineKeyboardButton('◀️', callback_data=f'sch_th_p_{prev_p}'))
        # Инфо
        nav.append(InlineKeyboardButton(f'{page + 1}/{pages}', callback_data=f'sch_th_page_info'))
        # ▶️ - вперед
        next_p = min(pages - 1, page + 1)
        nav.append(InlineKeyboardButton('▶️', callback_data=f'sch_th_p_{next_p}'))
        # ⏭ - в конец
        nav.append(InlineKeyboardButton('⏭', callback_data=f'sch_th_p_{pages - 1}'))
        
        keyboard.append(nav)

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=back_postfix))
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Инфо о страницах
    text += f'\nСтраница {page + 1} из {pages}'
    if update.callback_query:
        message = await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['new_schedule_event']['service']['message_id'],
            text=text,
            reply_markup=reply_markup
        )
        message = update.effective_message

    context.user_data['new_schedule_event']['service']['message_id'] = message.message_id
    state = SCH_THEATER
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_theater_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    # sch_th_t_{id}_{page} or sch_th_p_{page} or sch_th_f_{filter}
    if query.data.startswith('sch_th_t_'):
        theater_id = int(parts[3])
        context.user_data['new_schedule_event']['data']['theater_event_id'] = theater_id
        if context.user_data['new_schedule_event']['service'].get('jump_to_summary'):
            context.user_data['new_schedule_event']['service'].pop('jump_to_summary', None)
            return await ask_schedule_summary(update, context)
        return await ask_datetime(update, context)
    elif query.data.startswith('sch_th_p_'):
        page = int(parts[3])
        current_filter = context.user_data['new_schedule_event']['service'].get('filter_theater', 'actual')
        if current_filter == 'actual':
            theaters = await db_postgres.get_all_theater_events_actual(context.session)
        else:
            theaters = await db_postgres.get_all_theater_events(context.session)
        back_postfix = str(SCH_CONFIRM) if context.user_data['new_schedule_event']['service'].get('jump_to_summary') else '70'
        return await _render_theater_list(update, context, theaters, page, back_postfix=back_postfix)
    elif query.data.startswith('sch_th_f_'):
        new_filter = parts[3]
        context.user_data['new_schedule_event']['service']['filter_theater'] = new_filter
        if new_filter == 'actual':
            theaters = await db_postgres.get_all_theater_events_actual(context.session)
        else:
            theaters = await db_postgres.get_all_theater_events(context.session)
        back_postfix = str(SCH_CONFIRM) if context.user_data['new_schedule_event']['service'].get('jump_to_summary') else '70'
        return await _render_theater_list(update, context, theaters, 0, back_postfix=back_postfix)


async def ask_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    service = context.user_data['new_schedule_event']['service']
    jump = service.get('jump_to_summary', False)

    now = datetime.now()
    today_str = now.strftime('%d.%m')
    tomorrow_str = (now + timedelta(days=1)).strftime('%d.%m')

    text = (
        'Шаг 3/8. Введите дату и время показа.\n\n'
        'Форматы:\n'
        '<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n'
        '<code>ДД.ММ ЧЧ:ММ</code> (текущий год)\n\n'
        'Или выберите дату ниже и введите только время:'
    )

    back_postfix = str(SCH_CONFIRM) if jump else '71'

    keyboard = [
        [
            InlineKeyboardButton(f"Сегодня ({today_str})", callback_data=f"sch_dt_{today_str}"),
            InlineKeyboardButton(f"Завтра ({tomorrow_str})", callback_data=f"sch_dt_{tomorrow_str}"),
        ],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=back_postfix)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=service['message_id'],
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        message = query.message if query else update.effective_message

    context.user_data['new_schedule_event']['service']['message_id'] = message.message_id

    state = SCH_DATETIME
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_datetime_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    date_str = query.data.replace('sch_dt_', '')
    context.user_data['new_schedule_event']['service']['temp_date'] = date_str

    text = f'Выбрана дата {date_str}. Теперь введите время в формате ЧЧ:ММ (например, 11:00):'
    keyboard = [add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='72')]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return SCH_DATETIME


async def handle_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service = context.user_data['new_schedule_event']['service']
    data = context.user_data['new_schedule_event']['data']

    # Удаляем сообщение пользователя
    try:
        await update.effective_message.delete()
    except Exception:
        pass

    text_input = update.effective_message.text.strip()
    temp_date = service.get('temp_date')

    now = datetime.now()
    dt = None

    if temp_date:
        # Ожидаем время
        try:
            time_dt = datetime.strptime(text_input, '%H:%M')
            date_dt = datetime.strptime(temp_date, '%d.%m').replace(year=now.year)
            dt = date_dt.replace(hour=time_dt.hour, minute=time_dt.minute)
            service.pop('temp_date')
        except ValueError:
            text_err = f'Ошибка! Неверный формат времени для даты {temp_date}. Введите ЧЧ:ММ (например, 18:00):'
            keyboard = [add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='72')]
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=service['message_id'],
                text=text_err,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SCH_DATETIME
    else:
        # Полный ввод
        formats = ['%d.%m.%Y %H:%M', '%d.%m %H:%M']
        for fmt in formats:
            try:
                dt = datetime.strptime(text_input, fmt)
                if fmt == '%d.%m %H:%M':
                    dt = dt.replace(year=now.year)
                break
            except ValueError:
                continue

    if not dt:
        text_err = 'Ошибка! Неверный формат. Повторите в виде ДД.ММ.ГГГГ ЧЧ:ММ или ДД.ММ ЧЧ:ММ'
        keyboard = [add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='71')]
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=service['message_id'],
            text=text_err,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SCH_DATETIME

    data['datetime_event'] = dt
    if service.get('jump_to_summary'):
        service.pop('jump_to_summary', None)
        return await ask_schedule_summary(update, context)
    return await ask_qty_child(update, context)


async def ask_qty_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    service = context.user_data['new_schedule_event']['service']
    jump = service.get('jump_to_summary', False)

    text = 'Шаг 4/8. Введите количество детских мест (целое число):'
    if jump:
        text = 'Редактирование: введите количество детских мест (целое число):'

    keyboard = [add_btn_back_and_cancel(
        postfix_for_cancel='settings',
        add_back_btn=True,
        postfix_for_back=str(SCH_CONFIRM) if jump else '72'
    )]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=service['message_id'],
            text=text,
            reply_markup=reply_markup
        )

    state = SCH_QTY_CHILD
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_qty_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service = context.user_data['new_schedule_event']['service']
    data = context.user_data['new_schedule_event']['data']

    # Удаляем сообщение пользователя
    try:
        await update.effective_message.delete()
    except Exception:
        pass

    try:
        val = int(update.effective_message.text)
        if val < 0:
            raise ValueError
    except ValueError:
        text = 'Ошибка! Введите неотрицательное целое число для детских мест:'
        keyboard = [add_btn_back_and_cancel(
            postfix_for_cancel='settings',
            add_back_btn=True,
            postfix_for_back=str(SCH_CONFIRM) if service.get('jump_to_summary') else '72'
        )]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=service['message_id'],
            text=text,
            reply_markup=reply_markup
        )
        return SCH_QTY_CHILD

    data['qty_child'] = val
    if service.get('jump_to_summary'):
        service.pop('jump_to_summary', None)
        return await ask_schedule_summary(update, context)
    return await ask_qty_adult(update, context)


async def ask_qty_adult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    service = context.user_data['new_schedule_event']['service']
    jump = service.get('jump_to_summary', False)

    text = 'Шаг 5/8. Введите количество взрослых мест (целое число):'
    if jump:
        text = 'Редактирование: введите количество взрослых мест (целое число):'

    keyboard = [add_btn_back_and_cancel(
        postfix_for_cancel='settings',
        add_back_btn=True,
        postfix_for_back=str(SCH_CONFIRM) if jump else '73'
    )]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=service['message_id'],
            text=text,
            reply_markup=reply_markup
        )

    state = SCH_QTY_ADULT
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_qty_adult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service = context.user_data['new_schedule_event']['service']
    data = context.user_data['new_schedule_event']['data']

    # Удаляем сообщение пользователя
    try:
        await update.effective_message.delete()
    except Exception:
        pass

    try:
        val = int(update.effective_message.text)
        if val < 0:
            raise ValueError
    except ValueError:
        text = 'Ошибка! Введите неотрицательное целое число для взрослых мест:'
        keyboard = [add_btn_back_and_cancel(
            postfix_for_cancel='settings',
            add_back_btn=True,
            postfix_for_back=str(SCH_CONFIRM) if service.get('jump_to_summary') else '73'
        )]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=service['message_id'],
            text=text,
            reply_markup=reply_markup
        )
        return SCH_QTY_ADULT

    data['qty_adult'] = val
    if service.get('jump_to_summary'):
        service.pop('jump_to_summary', None)
        return await ask_schedule_summary(update, context)
    return await ask_price_type(update, context)


async def ask_price_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    service = context.user_data['new_schedule_event']['service']
    jump = service.get('jump_to_summary', False)

    text = 'Шаг 6/8. Выберите тип стоимости:'
    keyboard = [
        [InlineKeyboardButton('По умолчанию', callback_data='sch_pt_NONE')],
        [InlineKeyboardButton('Будни', callback_data='sch_pt_weekday')],
        [InlineKeyboardButton('Выходные', callback_data='sch_pt_weekend')],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=(str(SCH_CONFIRM) if jump else '73'))
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=service['message_id'],
            text=text,
            reply_markup=reply_markup
        )
        message = query.message if query else update.effective_message

    context.user_data['new_schedule_event']['service']['message_id'] = message.message_id
    state = SCH_PRICE_TYPE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_price_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    val = query.data.replace('sch_pt_', '')
    if val == 'NONE':
        tpt = TicketPriceType.NONE
    else:
        tpt = TicketPriceType[val]
    context.user_data['new_schedule_event']['data']['ticket_price_type'] = tpt

    if context.user_data['new_schedule_event']['service'].get('jump_to_summary'):
        context.user_data['new_schedule_event']['service'].pop('jump_to_summary', None)
        return await ask_schedule_summary(update, context)
    return await ask_flags(update, context)


async def ask_flags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data['new_schedule_event']['data']
    service = context.user_data['new_schedule_event']['service']
    jump = service.get('jump_to_summary') or service.get('is_update')

    text = (
        'Шаг 7/8. Настройте флаги:\n\n'
        f"Подарок: {'✅' if data.get('flag_gift') else '❌'}\n"
        f"Елка: {'✅' if data.get('flag_christmas_tree') else '❌'}\n"
        f"Дед Мороз: {'✅' if data.get('flag_santa') else '❌'}"
    )

    keyboard = [
        [InlineKeyboardButton('Подарок', callback_data='sch_fg')],
        [InlineKeyboardButton('Елка', callback_data='sch_ft')],
        [InlineKeyboardButton('Дед Мороз', callback_data='sch_fs')],
    ]
    # В режиме редактирования добавляем кнопку завершения, в режиме создания - кнопку перехода к билетам
    if jump:
        keyboard.append([InlineKeyboardButton('Готово', callback_data='sch_flags_done')])
    else:
        keyboard.append([InlineKeyboardButton('Билеты ➡️', callback_data='sch_next_bt')])
    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=(str(SCH_CONFIRM) if jump else '74')))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        message = await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=service['message_id'],
            text=text,
            reply_markup=reply_markup
        )
        message = update.effective_message

    context.user_data['new_schedule_event']['service']['message_id'] = message.message_id
    state = SCH_FLAGS
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_flags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data['new_schedule_event']['data']

    if query.data == 'sch_fg':
        data['flag_gift'] = not data.get('flag_gift', False)
        return await ask_flags(update, context)
    if query.data == 'sch_ft':
        data['flag_christmas_tree'] = not data.get('flag_christmas_tree', False)
        return await ask_flags(update, context)
    if query.data == 'sch_fs':
        data['flag_santa'] = not data.get('flag_santa', False)
        return await ask_flags(update, context)
    if query.data == 'sch_flags_done':
        # Завершаем редактирование флагов
        return await ask_schedule_summary(update, context)

    # Далее -> к выбору базовых билетов
    # Если редактируем флаги, то по кнопке Далее возвращаемся к сводке
    if context.user_data['new_schedule_event']['service'].get('edit_flags'):
        context.user_data['new_schedule_event']['service'].pop('edit_flags', None)
        return await ask_schedule_summary(update, context)
    return await ask_base_tickets(update, context)


async def _render_multi_select(update: Update,
                               context: ContextTypes.DEFAULT_TYPE,
                               items: List,
                               selected_ids: list[int],
                               page: int,
                               per_page: int,
                               prefix: str,
                               label_getter,
                               back_postfix: str = '75'):
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    end = start + per_page
    subset = items[start:end]

    text = 'Выберите элементы:\n\n'
    item_buttons = []
    for it in subset:
        it_id = getattr(it, 'base_ticket_id', getattr(it, 'id', None))
        mark = '✅' if it_id in selected_ids else '▫️'
        label = label_getter(it)
        text += f"• {label}\n"
        item_buttons.append(
            InlineKeyboardButton(f"{mark} ID {it_id}", callback_data=f"{prefix}_t_{it_id}_{page}")
        )

    keyboard = []
    # Ряд кнопок элементов (по 3 в ряд)
    for i in range(0, len(item_buttons), 3):
        keyboard.append(item_buttons[i:i + 3])

    nav_row = []
    if pages > 1:
        # ⏮ - в начало
        nav_row.append(InlineKeyboardButton('⏮', callback_data=f'{prefix}_p_0'))
        # ◀️ - назад
        prev_p = max(0, page - 1)
        nav_row.append(InlineKeyboardButton('◀️', callback_data=f'{prefix}_p_{prev_p}'))
        # Инфо
        nav_row.append(InlineKeyboardButton(f'{page + 1}/{pages}', callback_data=f'{prefix}_page_info'))
        # ▶️ - вперед
        next_p = min(pages - 1, page + 1)
        nav_row.append(InlineKeyboardButton('▶️', callback_data=f'{prefix}_p_{next_p}'))
        # ⏭ - в конец
        nav_row.append(InlineKeyboardButton('⏭', callback_data=f'{prefix}_p_{pages - 1}'))
        
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton('Пропустить (наследовать)', callback_data=f"{prefix}_skip")])
    keyboard.append([InlineKeyboardButton('Готово', callback_data=f"{prefix}_done")])
    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=back_postfix))

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Инфо о страницах
    text += f'\nСтраница {page + 1} из {pages}'
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.effective_chat.send_message(text, reply_markup=reply_markup)


async def ask_base_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data['new_schedule_event']['data']
    service = context.user_data['new_schedule_event']['service']
    selected = data.get('base_ticket_ids', []) or []
    items = await db_postgres.get_all_base_tickets(context.session)

    back_postfix = str(SCH_CONFIRM) if (service.get('jump_to_summary') or service.get('is_update')) else '75'

    await _render_multi_select(
        update, context, items, selected, page=0, per_page=10,
        prefix='sch_bt',
        label_getter=lambda x: f"#{x.base_ticket_id} {x.name}",
        back_postfix=back_postfix
    )
    state = SCH_BT_SELECT
    await set_back_context(context, state, 'base_tickets', None)
    context.user_data['STATE'] = state
    return state


async def handle_base_tickets_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = context.user_data['new_schedule_event']['data']
    selected = data.get('base_ticket_ids', []) or []

    parts = query.data.split('_')
    if query.data.startswith('sch_bt_t_'):
        it_id = int(parts[3])
        page = int(parts[4]) if len(parts) > 4 else 0
        if it_id in selected:
            selected.remove(it_id)
        else:
            selected.append(it_id)
        data['base_ticket_ids'] = selected
        items = await db_postgres.get_all_base_tickets(context.session)
        back_postfix = str(SCH_CONFIRM) if context.user_data['new_schedule_event']['service'].get('is_update') else '75'
        await _render_multi_select(update, context, items, selected, page, 10, 'sch_bt', lambda x: f"#{x.base_ticket_id} {x.name}", back_postfix=back_postfix)
        return SCH_BT_SELECT
    elif query.data.startswith('sch_bt_p_'):
        page = int(parts[3])
        items = await db_postgres.get_all_base_tickets(context.session)
        back_postfix = str(SCH_CONFIRM) if context.user_data['new_schedule_event']['service'].get('is_update') else '75'
        await _render_multi_select(update, context, items, selected, page, 10, 'sch_bt', lambda x: f"#{x.base_ticket_id} {x.name}", back_postfix=back_postfix)
        return SCH_BT_SELECT
    elif query.data.startswith('sch_bt_skip'):
        data['base_ticket_ids'] = []
        if context.user_data['new_schedule_event']['service'].get('is_update'):
            return await ask_schedule_summary(update, context)
        return await ask_summary(update, context)
    else:  # done
        if context.user_data['new_schedule_event']['service'].get('is_update'):
            return await ask_schedule_summary(update, context)
        return await ask_summary(update, context)


async def ask_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data['new_schedule_event']['data']

    # Получим имена выбранных сущностей
    type_obj = None
    theater_obj = None
    try:
        type_obj = next((t for t in await db_postgres.get_all_type_events(context.session) if t.id == data['type_event_id']), None)
        theater_obj = next((t for t in await db_postgres.get_all_theater_events(context.session) if t.id == data['theater_event_id']), None)
    except Exception:
        pass

    summary = (
        '<b>Проверьте данные события</b>\n\n'
        f"Тип: {(_fmt_type_event(type_obj) if type_obj else data.get('type_event_id'))}\n"
        f"Спектакль: {(_fmt_theater_event(theater_obj) if theater_obj else data.get('theater_event_id'))}\n"
        f"Дата/время: {data['datetime_event'].strftime('%d.%m.%Y %H:%M')}\n"
        f"Места: {data.get('qty_child', 0)} дет / {data.get('qty_adult', 0)} взр\n"
        f"Стоимость: {data.get('ticket_price_type').name}\n"
        f"Флаги: 🎁={'✅' if data.get('flag_gift') else '❌'}, 🎄={'✅' if data.get('flag_christmas_tree') else '❌'}, 🧑‍🎄={'✅' if data.get('flag_santa') else '❌'}\n"
        f"Билеты: {'наследовать' if not data.get('base_ticket_ids') else str(len(data['base_ticket_ids'])) + ' шт.'}"
    )

    keyboard = [
        [InlineKeyboardButton('✅ Подтвердить и создать', callback_data='sch_accept')],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='76')
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=reply_markup)
    else:
        await update.effective_chat.send_message(summary, reply_markup=reply_markup)

    state = SCH_CONFIRM
    await set_back_context(context, state, summary, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    payload = context.user_data['new_schedule_event']['data'].copy()
    base_ticket_ids = payload.pop('base_ticket_ids', [])
    is_update = context.user_data['new_schedule_event']['service'].get('is_update', False)

    try:
        if is_update:
            sid = payload.pop('id')
            await db_postgres.update_schedule_event(context.session, sid, **payload, base_ticket_ids=base_ticket_ids)
            await query.answer('Событие обновлено')
        else:
            await db_postgres.create_schedule_event(context.session, **payload, base_ticket_ids=base_ticket_ids)
            await query.answer('Событие создано')
    except Exception as e:
        logger.exception(f'Ошибка сохранения расписания: {e}')
        await query.answer(f'Ошибка: {e}', show_alert=True)
        return SCH_CONFIRM

    # Возврат в меню настроек Расписания
    return await send_settings_menu(update, context, 'schedule_event')

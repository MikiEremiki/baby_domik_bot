import copy
import html
import logging
import re
from datetime import time as dt_time

from sulguk import transform_html

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest

from db import db_postgres
from db.enum import AutoSendingTrigger
from settings.settings import ADMIN_ID
from utilities.utl_func import set_back_context
from utilities.utl_kbd import (
    create_kbd_crud, add_btn_back_and_cancel,
)

auto_sending_hl_logger = logging.getLogger('bot.auto_sending_hl')


# ─── State constants ───────────────────────────────────────────────────────────

AUTO_SENDING_NAME = 100
AUTO_SENDING_TRIGGER = 101
AUTO_SENDING_THEATER = 102
AUTO_SENDING_OFFSET = 103
AUTO_SENDING_WINDOW = 104
AUTO_SENDING_PRECISE = 105
AUTO_SENDING_CHANNELS = 106
AUTO_SENDING_TEXT = 107
AUTO_SENDING_CONFIRM = 108
AUTO_SENDING_EDIT_FIELD = 109
AUTO_SENDING_MANUAL_MODE = 110
AUTO_SENDING_MANUAL_ID = 111


# ─── Auto-sending admin menu ───────────────────────────────────────────────────

async def auto_sending_select(
        update: Update,
        context,
):
    """List all auto-sendings with active flag and theater binding."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_ID:
        auto_sending_hl_logger.warning(
            "Пользователь %s попытался открыть рассылки без прав администратора",
            user_id
        )
        return context.user_data.get('STATE', 2)

    query = update.callback_query
    if query:
        try:
            await query.answer()
        except BadRequest:
            pass
        data = query.data or ""
    else:
        data = ""

    page = 0
    match_p = re.search(r'_p_(\d+)', data)
    if match_p:
        page = int(match_p.group(1))

    res = await db_postgres.get_all_auto_sendings(context.session)
    total = len(res)
    limit = 20
    pages = max(1, (total + limit - 1) // limit)
    page = max(0, min(page, pages - 1))
    start = page * limit
    end = start + limit
    subset = res[start:end]

    text = '<b>Список рассылок</b><br><br>'
    text += '✅/❌ — активна/неактивна<br><br>'
    if subset:
        for row in subset:
            trigger_label = row.trigger.value
            active = '✅' if row.is_active else '❌'
            theater = f" (ID {row.theater_event_id})" if row.theater_event_id else " (все)"
            text += f'• ID {row.id}: {active} [{trigger_label}] {row.name}{theater}<br>'
    else:
        text += 'Список пуст.'

    text += f'<br>Страница {page + 1} из {pages}'

    # Build keyboard with ID buttons only
    keyboard = []
    for row in subset:
        active = '✅' if row.is_active else '❌'
        keyboard.append([
            InlineKeyboardButton(f"ID {row.id} {active}", callback_data=f'auto_sending_edit_{row.id}'),
        ])

    # Pagination
    if pages > 1:
        nav_row = []
        nav_row.append(InlineKeyboardButton('⏮', callback_data='auto_sending_select_p_0'))
        prev_page = max(0, page - 1)
        nav_row.append(InlineKeyboardButton('◀️', callback_data=f'auto_sending_select_p_{prev_page}'))
        nav_row.append(InlineKeyboardButton(f'{page + 1} / {pages}', callback_data='auto_sending_select_page_info'))
        next_page = min(pages - 1, page + 1)
        nav_row.append(InlineKeyboardButton('▶️', callback_data=f'auto_sending_select_p_{next_page}'))
        nav_row.append(InlineKeyboardButton('⏭', callback_data=f'auto_sending_select_p_{pages - 1}'))
        keyboard.append(nav_row)

    # CRUD button: Add only (without back/cancel, added below)
    crud_markup = create_kbd_crud('auto_sending', add_only=True)
    for row in crud_markup.inline_keyboard:
        if not any(isinstance(btn, InlineKeyboardButton) and btn.text in ('Назад', 'Отменить') for btn in row):
            keyboard.append(row)

    # Back/Cancel
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='2'))

    reply_markup = InlineKeyboardMarkup(keyboard)

    res = transform_html(text)
    try:
        if query:
            await query.edit_message_text(res.text, entities=res.entities, reply_markup=reply_markup, parse_mode=None)
        else:
            await update.effective_chat.send_message(res.text, entities=res.entities, reply_markup=reply_markup, parse_mode=None)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise e

    state = 3
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state

    if query:
        try:
            await query.answer()
        except BadRequest:
            pass
    return state


async def auto_sending_create_start(update: Update, context):
    """Start the auto-sending creation wizard."""
    query = update.callback_query
    await query.answer()

    context.user_data['new_auto_sending'] = {
        'data': {},
        'service': {},
    }
    return await auto_sending_ask_name(update, context)


async def auto_sending_ask_name(update: Update, context):
    """Ask for the sending name."""
    text = "Введите название рассылки:\n\n"
    text += "Примеры: «Напоминание за день», «Материалы после оплаты», «Запрос отзыва»"

    reply_markup = InlineKeyboardMarkup([
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3')
    ])
    await query_or_message(update, context, text, reply_markup)
    return AUTO_SENDING_NAME


async def auto_sending_handle_name(update: Update, context):
    """Handle name input — both creation and edit modes."""
    text = update.effective_message.text.strip()
    if not text:
        await update.effective_chat.send_message("Название не может быть пустым.")
        return AUTO_SENDING_NAME

    # Check if we're in edit mode
    if 'editing_auto_sending' in context.user_data:
        context.user_data['editing_auto_sending']['data']['name'] = text
        await update.effective_chat.send_message("Название обновлено. Выберите следующее поле или вернитесь назад.")
        return await auto_sending_edit_start_from_data(update, context)

    # Creation mode
    context.user_data['new_auto_sending']['data']['name'] = text
    return await auto_sending_ask_trigger(update, context)


async def auto_sending_ask_trigger(update: Update, context):
    """Ask for the trigger type."""
    text = ""
    
    # Check if we're in edit mode
    is_edit = 'editing_auto_sending' in context.user_data
    if is_edit:
        current_trigger = context.user_data['editing_auto_sending']['data'].get('trigger')
        trigger_label = '📅 EVENT' if current_trigger == AutoSendingTrigger.EVENT else '💳 PAYMENT'
        text = f"Текущий триггер: {trigger_label}<br><br>"
    
    text += "Выберите триггер рассылки:"
    back_btn = InlineKeyboardButton('Назад', callback_data='as_back_to_edit') if is_edit else \
        InlineKeyboardButton('Назад', callback_data='Назад-3')
    cancel_btn = InlineKeyboardButton('Отменить', callback_data='Отменить-settings')

    keyboard = [
        [InlineKeyboardButton('📅 EVENT (относительно сеанса)', callback_data='as_trig_event')],
        [InlineKeyboardButton('💳 PAYMENT (после оплаты)', callback_data='as_trig_payment')],
        [back_btn, cancel_btn],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query_or_message(update, context, text, reply_markup)
    return AUTO_SENDING_TRIGGER


async def auto_sending_handle_trigger(update: Update, context):
    """Handle trigger selection."""
    query = update.callback_query
    await query.answer()
    trigger = AutoSendingTrigger.EVENT if 'event' in query.data else AutoSendingTrigger.PAYMENT
    context.user_data['new_auto_sending']['data']['trigger'] = trigger
    if 'editing_auto_sending' in context.user_data:
        context.user_data['editing_auto_sending']['data']['trigger'] = trigger
        return await auto_sending_edit_start_from_data(update, context)
    return await auto_sending_ask_theater(update, context)


async def auto_sending_ask_theater(update: Update, context):
    """Ask which theater event (or all)."""
    is_edit = 'editing_auto_sending' in context.user_data
    text = ""
    if is_edit:
        theater_id = context.user_data['editing_auto_sending']['data'].get('theater_event_id')
        if theater_id is None:
            current_theater = 'Все спектакли'
        else:
            current_theater = f'Спектакль ID {theater_id}'
        text = f"Текущий спектакль: {current_theater}<br><br>"
    text += "Привязать к спектаклю или ко всем?<br><br>"
    text += "«Все» — рассылка применяется ко всем спектаклям"
    back_btn = InlineKeyboardButton('Назад', callback_data='as_back_to_edit') if is_edit else \
        InlineKeyboardButton('Назад', callback_data='Назад-3')
    cancel_btn = InlineKeyboardButton('Отменить', callback_data='Отменить-settings')

    keyboard = [
        [InlineKeyboardButton('Все спектакли', callback_data='as_theater_all')],
        [InlineKeyboardButton('Конкретный спектакль', callback_data='as_theater_specific')],
        [back_btn, cancel_btn],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query_or_message(update, context, text, reply_markup)
    return AUTO_SENDING_THEATER


async def auto_sending_handle_theater(update: Update, context):
    """Handle theater selection."""
    query = update.callback_query
    await query.answer()

    if 'all' in query.data:
        context.user_data['new_auto_sending']['data']['theater_event_id'] = None
        if 'editing_auto_sending' in context.user_data:
            context.user_data['editing_auto_sending']['data']['theater_event_id'] = None
            return await auto_sending_edit_start_from_data(update, context)
        return await auto_sending_ask_offset(update, context)
    else:
        # Show theater list
        theaters = await db_postgres.get_all_theater_events(context.session)
        if not theaters:
            await query.edit_message_text("Нет спектаклей в базе данных.")
            return AUTO_SENDING_THEATER

        text = "Выберите спектакль:"
        keyboard = []
        for te in theaters:
            keyboard.append([InlineKeyboardButton(
                f"ID {te.id}: {te.name}",
                callback_data=f"as_theater_{te.id}"
            )])
        # Check if we're in edit mode
        is_edit = 'editing_auto_sending' in context.user_data
        back_btn = InlineKeyboardButton('Назад', callback_data='as_back_to_edit') if is_edit else \
            InlineKeyboardButton('Назад', callback_data='Назад-3')
        cancel_btn = InlineKeyboardButton('Отменить', callback_data='Отменить-settings')
        keyboard.append([back_btn, cancel_btn])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup)
        return AUTO_SENDING_THEATER


async def auto_sending_handle_theater_id(update: Update, context):
    """Handle specific theater ID selection."""
    query = update.callback_query
    await query.answer()
    try:
        theater_id = int(query.data.replace('as_theater_', ''))
    except ValueError:
        await query.answer("Неверный ID спектакля", show_alert=True)
        return 3
    context.user_data['new_auto_sending']['data']['theater_event_id'] = theater_id
    if 'editing_auto_sending' in context.user_data:
        context.user_data['editing_auto_sending']['data']['theater_event_id'] = theater_id
        return await auto_sending_edit_start_from_data(update, context)
    return await auto_sending_ask_offset(update, context)


async def auto_sending_ask_offset(update: Update, context):
    """Ask for offset in minutes."""
    trigger = context.user_data['new_auto_sending']['data'].get('trigger')
    
    # Check if we're in edit mode
    is_edit = 'editing_auto_sending' in context.user_data
    text = ""
    if is_edit:
        current_offset = context.user_data['editing_auto_sending']['data'].get('offset_minutes', 0)
        text = f"Текущее смещение: {current_offset} мин<br><br>"
    
    if trigger == AutoSendingTrigger.EVENT:
        text += "Введите смещение в минутах от начала сеанса:<br><br>"
        text += "Отрицательное — до сеанса (например, -1500 = за 1 день 1 час)<br>"
        text += "Положительное — после сеанса (например, +240 = через 4 часа)"
    else:
        text += "Введите смещение в минутах (для PAYMENT обычно 0 — сразу после оплаты)"
    back_btn = InlineKeyboardButton('Назад', callback_data='as_back_to_edit') if is_edit else \
        InlineKeyboardButton('Назад', callback_data='Назад-3')
    cancel_btn = InlineKeyboardButton('Отменить', callback_data='Отменить-settings')

    reply_markup = InlineKeyboardMarkup([
        [back_btn, cancel_btn]
    ])
    await query_or_message(update, context, text, reply_markup)
    return AUTO_SENDING_OFFSET


async def auto_sending_handle_offset(update: Update, context):
    """Handle offset input."""
    try:
        offset = int(update.effective_message.text.strip())
    except (ValueError, AttributeError):
        await update.effective_chat.send_message("Пожалуйста, введите число (минуты).")
        return AUTO_SENDING_OFFSET

    context.user_data['new_auto_sending']['data']['offset_minutes'] = offset
    if 'editing_auto_sending' in context.user_data:
        context.user_data['editing_auto_sending']['data']['offset_minutes'] = offset
        return await auto_sending_edit_start_from_data(update, context)
    return await auto_sending_ask_window(update, context)


async def auto_sending_ask_window(update: Update, context):
    """Ask for time window (start-end) or skip."""
    # Check if we're in edit mode
    is_edit = 'editing_auto_sending' in context.user_data
    text = ""
    if is_edit:
        ws = context.user_data['editing_auto_sending']['data'].get('window_start')
        we = context.user_data['editing_auto_sending']['data'].get('window_end')
        if ws and we:
            current_window = f"{ws.strftime('%H:%M')} — {we.strftime('%H:%M')}"
        else:
            current_window = 'Нет (любое время)'
        text = f"Текущее окно: {current_window}<br><br>"
    
    text += "Окно отправки (час:минута — час:минута) или пропустить:<br><br>"
    text += "Пример: 08:00-21:00 — отправка только в это время<br>"
    text += "Если пропустить, отправка в любое время"
    back_btn = InlineKeyboardButton('Назад', callback_data='as_back_to_edit') if is_edit else \
        InlineKeyboardButton('Назад', callback_data='Назад-3')
    cancel_btn = InlineKeyboardButton('Отменить', callback_data='Отменить-settings')

    keyboard = [
        [InlineKeyboardButton('Пропустить', callback_data='as_window_skip')],
        [back_btn, cancel_btn],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query_or_message(update, context, text, reply_markup)
    return AUTO_SENDING_WINDOW


async def auto_sending_handle_window(update: Update, context):
    """Handle window input."""
    text = update.effective_message.text.strip()
    window_start = None
    window_end = None

    if text and text != 'Пропустить':
        try:
            parts = text.split('-')
            if len(parts) == 2:
                start_parts = parts[0].strip().split(':')
                end_parts = parts[1].strip().split(':')
                window_start = dt_time(int(start_parts[0]), int(start_parts[1]))
                window_end = dt_time(int(end_parts[0]), int(end_parts[1]))
            else:
                await update.effective_chat.send_message(
                    "Формат: ЧЧ:ММ-ЧЧ:ММ, например 08:00-21:00"
                )
                return AUTO_SENDING_WINDOW
        except (ValueError, IndexError):
            await update.effective_chat.send_message(
                "Неверный формат. Пример: 08:00-21:00"
            )
            return AUTO_SENDING_WINDOW

    context.user_data['new_auto_sending']['data']['window_start'] = window_start
    context.user_data['new_auto_sending']['data']['window_end'] = window_end
    if 'editing_auto_sending' in context.user_data:
        context.user_data['editing_auto_sending']['data']['window_start'] = window_start
        context.user_data['editing_auto_sending']['data']['window_end'] = window_end
        return await auto_sending_edit_start_from_data(update, context)
    return await auto_sending_ask_precise(update, context)


async def auto_sending_handle_window_skip(update: Update, context):
    """Handle window skip."""
    query = update.callback_query
    await query.answer()
    context.user_data['new_auto_sending']['data']['window_start'] = None
    context.user_data['new_auto_sending']['data']['window_end'] = None
    if 'editing_auto_sending' in context.user_data:
        context.user_data['editing_auto_sending']['data']['window_start'] = None
        context.user_data['editing_auto_sending']['data']['window_end'] = None
        return await auto_sending_edit_start_from_data(update, context)
    return await auto_sending_ask_precise(update, context)


async def auto_sending_ask_precise(update: Update, context):
    """Ask for precise flag."""
    # Check if we're in edit mode
    is_edit = 'editing_auto_sending' in context.user_data
    text = ""
    if is_edit:
        current_precise = context.user_data['editing_auto_sending']['data'].get('precise', False)
        text = f"Текущая точность: {'Да' if current_precise else 'Нет'}<br><br>"
    
    text += "Точная отправка?<br><br>"
    text += "Да — отправка в точную минуту (±5 мин)<br>"
    text += "Нет — отправка при следующем тике (каждые 5 мин)"
    back_btn = InlineKeyboardButton('Назад', callback_data='as_back_to_edit') if is_edit else \
        InlineKeyboardButton('Назад', callback_data='Назад-3')
    cancel_btn = InlineKeyboardButton('Отменить', callback_data='Отменить-settings')

    keyboard = [
        [InlineKeyboardButton('Да', callback_data='as_precise_yes')],
        [InlineKeyboardButton('Нет', callback_data='as_precise_no')],
        [back_btn, cancel_btn],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query_or_message(update, context, text, reply_markup)
    return AUTO_SENDING_PRECISE


async def auto_sending_handle_precise(update: Update, context):
    """Handle precise selection."""
    query = update.callback_query
    await query.answer()
    precise = 'yes' in query.data
    context.user_data['new_auto_sending']['data']['precise'] = precise
    if 'editing_auto_sending' in context.user_data:
        context.user_data['editing_auto_sending']['data']['precise'] = precise
        return await auto_sending_edit_start_from_data(update, context)
    return await auto_sending_ask_channels(update, context)


async def auto_sending_ask_channels(update: Update, context):
    """Ask for channels (bot/website)."""
    # Check if we're in edit mode
    is_edit = 'editing_auto_sending' in context.user_data
    text = ""
    if is_edit:
        bot = context.user_data['editing_auto_sending']['data'].get('send_via_bot', False)
        web = context.user_data['editing_auto_sending']['data'].get('send_via_website', False)
        if bot and web:
            current_ch = '🤖+🌐 Бот и сайт'
        elif bot:
            current_ch = '🤖 Только бот'
        elif web:
            current_ch = '🌐 Только сайт'
        else:
            current_ch = 'Нет'
        text = f"Текущие каналы: {current_ch}<br><br>"
    
    text += "Каналы отправки:"
    back_btn = InlineKeyboardButton('Назад', callback_data='as_back_to_edit') if is_edit else \
        InlineKeyboardButton('Назад', callback_data='Назад-3')
    cancel_btn = InlineKeyboardButton('Отменить', callback_data='Отменить-settings')

    keyboard = [
        [InlineKeyboardButton('🤖 Только бот', callback_data='as_ch_bot')],
        [InlineKeyboardButton('🌐 Только сайт', callback_data='as_ch_web')],
        [InlineKeyboardButton('🤖+🌐 Бот и сайт', callback_data='as_ch_both')],
        [back_btn, cancel_btn],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query_or_message(update, context, text, reply_markup)
    return AUTO_SENDING_CHANNELS


async def auto_sending_handle_channels(update: Update, context):
    """Handle channel selection."""
    query = update.callback_query
    await query.answer()

    if query.data == 'as_ch_bot':
        context.user_data['new_auto_sending']['data']['send_via_bot'] = True
        context.user_data['new_auto_sending']['data']['send_via_website'] = False
    elif query.data == 'as_ch_web':
        context.user_data['new_auto_sending']['data']['send_via_bot'] = False
        context.user_data['new_auto_sending']['data']['send_via_website'] = True
    elif query.data == 'as_ch_both':
        context.user_data['new_auto_sending']['data']['send_via_bot'] = True
        context.user_data['new_auto_sending']['data']['send_via_website'] = True

    if 'editing_auto_sending' in context.user_data:
        context.user_data['editing_auto_sending']['data']['send_via_bot'] = context.user_data['new_auto_sending']['data']['send_via_bot']
        context.user_data['editing_auto_sending']['data']['send_via_website'] = context.user_data['new_auto_sending']['data']['send_via_website']
        return await auto_sending_edit_start_from_data(update, context)
    return await auto_sending_ask_text(update, context)


async def auto_sending_ask_text(update: Update, context):
    """Ask for the HTML text."""
    # Check if we're in edit mode
    is_edit = 'editing_auto_sending' in context.user_data
    if is_edit:
        current_text = context.user_data['editing_auto_sending']['data'].get('text', '')
        raw_preview = current_text[:100] + '...' if len(current_text) > 100 else current_text
        preview = transform_html(raw_preview).text
        text = f"Текущий текст:<br><br>{preview}<br><br>"
    else:
        text = ""
    
    text += "Отправьте текст рассылки в формате HTML:<br><br>"
    text += "Доступные плейсхолдеры:<br>"
    text += "{event_name} — название спектакля<br>"
    text += "{date} — дата сеанса<br>"
    text += "{time} — время сеанса<br>"
    text += "{ticket_ids} — ID билетов<br>"
    text += "{place} — локация мероприятия<br>"
    text += "{refund_info} — информация о возврате"
    back_btn = InlineKeyboardButton('Назад', callback_data='as_back_to_edit') if is_edit else \
        InlineKeyboardButton('Назад', callback_data='Назад-3')
    cancel_btn = InlineKeyboardButton('Отменить', callback_data='Отменить-settings')

    reply_markup = InlineKeyboardMarkup([
        [back_btn, cancel_btn]
    ])
    await query_or_message(update, context, text, reply_markup)
    return AUTO_SENDING_TEXT


async def auto_sending_handle_text(update: Update, context):
    """Handle text input with HTML validation and length check."""
    msg = update.effective_message

    # text_html already converts all Telegram entities (links, bold, italic, etc.)
    # into proper HTML tags — no manual entity parsing needed.
    text = msg.text_html or ""

    # Convert newlines to <br> for HTML storage
    # Telegram sends \n for line breaks, but we need <br> for HTML format
    text = text.replace('\n', '<br>')

    # Validate HTML through sulguk (only validates, we keep the original HTML)
    try:
        transform_html(text)  # Validate by calling, but don't use the result
    except Exception as e:
        await update.effective_chat.send_message(
            f"❌ Неверный HTML: {e}<br><br>"
            "Пожалуйста, проверьте текст и отправьте его ещё раз."
        )
        return AUTO_SENDING_TEXT

    # Store the HTML text (with <br> for line breaks)
    context.user_data['new_auto_sending']['data']['text'] = text

    if 'editing_auto_sending' in context.user_data:
        context.user_data['editing_auto_sending']['data']['text'] = text
        return await auto_sending_edit_start_from_data(update, context)

    # Length check with placeholder warning
    preview_ctx = {
        'event_name': 'Название спектакля',
        'date': '01.01.2026',
        'time': '18:00',
        'ticket_ids': '123, 456',
        'place': '📍 Название площадки: адрес',
        'refund_info': 'Возврат возможен за 3 дня',
    }
    from schedule.auto_sending import render_text
    rendered = render_text(text, preview_ctx, sending_name='preview')
    length_warning = ""
    if len(rendered) > 4096:
        length_warning = (
            f"<br><br>⚠️ <b>Внимание!</b> После подстановки плейсхолдеров текст "
            f"составляет {len(rendered)} символов (>4096). "
            f"Финальная длина зависит от данных билета — возможно, текст будет обрезан."
        )

    # Build summary
    data = context.user_data['new_auto_sending']['data']
    summary = "<b>Итог:</b><br><br>"
    summary += f"Название: {data['name']}<br>"
    summary += f"Триггер: {data['trigger'].value}<br>"
    summary += f"Смещение: {data['offset_minutes']} мин<br>"
    if data.get('theater_event_id') is not None:
        summary += f"Спектакль: ID {data['theater_event_id']}<br>"
    else:
        summary += "Спектакль: все<br>"
    if data.get('window_start'):
        summary += f"Окно: {data['window_start']} — {data['window_end']}<br>"
    summary += f"Точная: {'Да' if data['precise'] else 'Нет'}<br>"
    summary += f"Бот: {'Да' if data['send_via_bot'] else 'Нет'}<br>"
    summary += f"Сайт: {'Да' if data['send_via_website'] else 'Нет'}<br>"
    # Escape HTML in code block so tags display as text
    code_text = html.escape(text[:200])
    summary += f"<br>Текст:<br><code>{code_text}</code>"
    if len(text) > 200:
        summary += "..."
    summary += length_warning

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('Подтвердить', callback_data='as_accept')],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3'),
    ])
    res = transform_html(summary)
    await update.effective_chat.send_message(res.text, entities=res.entities, reply_markup=reply_markup, parse_mode=None)
    return AUTO_SENDING_CONFIRM


async def auto_sending_confirm_create(update: Update, context):
    """Confirm and create the auto-sending."""
    query = update.callback_query
    await query.answer()

    data = context.user_data['new_auto_sending']['data']

    sending = await db_postgres.create_auto_sending(
        context.session,
        name=data['name'],
        trigger=data['trigger'],
        text=data['text'],
        offset_minutes=data['offset_minutes'],
        window_start=data.get('window_start'),
        window_end=data.get('window_end'),
        precise=data['precise'],
        theater_event_id=data.get('theater_event_id'),
        send_via_bot=data['send_via_bot'],
        send_via_website=data['send_via_website'],
        is_active=True,
    )

    context.user_data.pop('new_auto_sending')
    await query.answer(f"«{data['name']}» — создана")
    return await auto_sending_select(update, context)


# ─── Edit auto-sending ─────────────────────────────────────────────────────────

def _get_field(sending, data, field: str):
    """Extract a field value, preferring edited data over DB sending."""
    if data is not None:
        return data.get(field, getattr(sending, field))
    return getattr(sending, field)


def _format_offset(offset_minutes: int) -> str:
    """Format offset minutes to human-readable string like '+2ч 30мин'."""
    offset_hours = offset_minutes // 60
    offset_mins = abs(offset_minutes) % 60
    if offset_minutes < 0:
        return f"-{abs(offset_hours)}ч {offset_mins}мин" if offset_mins else f"-{abs(offset_hours)}ч"
    else:
        return f"+{offset_hours}ч {offset_mins}мин" if offset_mins else f"+{offset_hours}ч"


def _format_window(window_start, window_end) -> str:
    """Format time window to display string."""
    if window_start and window_end:
        return f"{window_start.strftime('%H:%M')} — {window_end.strftime('%H:%M')}"
    return 'Нет (любое время)'


def _format_channels(send_via_bot: bool, send_via_website: bool) -> str:
    """Format channels to display string."""
    channels = []
    if send_via_bot:
        channels.append('🤖 Бот')
    if send_via_website:
        channels.append('🌐 Сайт')
    return ' и '.join(channels) if channels else 'Нет'


def _format_text_preview(text_val: str) -> str:
    """Format text preview, truncating to 100 chars."""
    raw_preview = text_val[:100] + '...' if len(text_val) > 100 else text_val
    return transform_html(raw_preview).text


def _format_sending_summary(sending, data=None) -> str:
    """Format auto-sending parameters for display in the edit menu.
    
    If data dict is provided, uses it instead of sending object attributes
    (for showing edited but not yet saved values).
    """
    trigger = _get_field(sending, data, 'trigger')
    name = _get_field(sending, data, 'name')
    theater_id = _get_field(sending, data, 'theater_event_id')
    offset_minutes = _get_field(sending, data, 'offset_minutes')
    window_start = _get_field(sending, data, 'window_start')
    window_end = _get_field(sending, data, 'window_end')
    precise = _get_field(sending, data, 'precise')
    send_via_bot = _get_field(sending, data, 'send_via_bot')
    send_via_website = _get_field(sending, data, 'send_via_website')
    text_val = _get_field(sending, data, 'text')
    is_active = _get_field(sending, data, 'is_active')
    
    trigger_label = '📅 EVENT (относительно сеанса)' if trigger == AutoSendingTrigger.EVENT else '💳 PAYMENT (после оплаты)'
    theater_info = 'Все спектакли' if theater_id is None else f"Спектакль ID {theater_id}"
    offset_str = _format_offset(offset_minutes)
    window_str = _format_window(window_start, window_end)
    channels_str = _format_channels(send_via_bot, send_via_website)
    precise_str = 'Да (строго по смещению)' if precise else 'Нет (в пределах окна)'
    text_preview = _format_text_preview(text_val)
    
    lines = [
        f"Редактирование: {name}",
        f"",
        f"📌 Триггер: {trigger_label}",
        f"🎭 Спектакль: {theater_info}",
        f"⏱ Смещение: {offset_str} от триггера",
        f"🕐 Окно отправки: {window_str}",
        f"🎯 Точность: {precise_str}",
        f"📡 Каналы: {channels_str}",
        f"{'🟢 Активна' if is_active else '🔴 Неактивна'}",
        f"",
        f"📝 Текст:",
        f"{text_preview}",
        f"",
        f"Выберите поле для изменения:",
    ]
    return '<br>'.join(lines)


async def auto_sending_edit_start(update: Update, context):
    """Show edit menu for a specific sending."""
    query = update.callback_query
    await query.answer()

    try:
        sending_id = int(query.data.replace('auto_sending_edit_', ''))
    except ValueError:
        await query.answer("Неверный ID рассылки", show_alert=True)
        return 3
    sending = await db_postgres.get_auto_sending_by_id(context.session, sending_id)
    if not sending:
        await query.edit_message_text("Рассылка не найдена.")
        return 3

    sending_data = {
        'name': sending.name,
        'trigger': sending.trigger,
        'offset_minutes': sending.offset_minutes,
        'window_start': sending.window_start,
        'window_end': sending.window_end,
        'precise': sending.precise,
        'theater_event_id': sending.theater_event_id,
        'send_via_bot': sending.send_via_bot,
        'send_via_website': sending.send_via_website,
        'text': sending.text,
        'is_active': sending.is_active,
    }
    context.user_data['editing_auto_sending'] = {
        'id': sending_id,
        'data': sending_data,
        'original': copy.deepcopy(sending_data),
    }

    text = _format_sending_summary(sending)
    toggle_label = '🔴 Выкл' if sending.is_active else '🟢 Вкл'
    keyboard = [
        [InlineKeyboardButton('Название', callback_data='as_edit_name'),
         InlineKeyboardButton('Триггер', callback_data='as_edit_trigger')],
        [InlineKeyboardButton('Спектакль', callback_data='as_edit_theater'),
         InlineKeyboardButton('Смещение', callback_data='as_edit_offset')],
        [InlineKeyboardButton('Окно', callback_data='as_edit_window'),
         InlineKeyboardButton('Точность', callback_data='as_edit_precise')],
        [InlineKeyboardButton('Каналы', callback_data='as_edit_channels'),
         InlineKeyboardButton('Текст', callback_data='as_edit_text')],
        [InlineKeyboardButton(toggle_label, callback_data=f'as_toggle_{sending_id}'),
         InlineKeyboardButton('✉️ Ручная отправка', callback_data=f'as_manual_{sending_id}')],
        [InlineKeyboardButton('🗑 Удалить', callback_data=f'as_delete_{sending_id}')],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3'),
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    result = transform_html(text)
    await query.edit_message_text(result.text,
                                  entities=result.entities,
                                  reply_markup=reply_markup,
                                  parse_mode=None)
    return AUTO_SENDING_EDIT_FIELD


async def auto_sending_handle_edit_field(update: Update, context):
    """Route to the appropriate field editor."""
    query = update.callback_query
    await query.answer()
    field = query.data.replace('as_edit_', '')

    # Initialize new_auto_sending from editing_auto_sending for the ask/handle chain
    editing = context.user_data['editing_auto_sending']
    context.user_data['new_auto_sending'] = {
        'data': copy.deepcopy(editing['data'])
    }

    if field == 'name':
        return await auto_sending_ask_name_edit(update, context)
    elif field == 'trigger':
        return await auto_sending_ask_trigger(update, context)
    elif field == 'theater':
        return await auto_sending_ask_theater(update, context)
    elif field == 'offset':
        return await auto_sending_ask_offset(update, context)
    elif field == 'window':
        return await auto_sending_ask_window(update, context)
    elif field == 'precise':
        return await auto_sending_ask_precise(update, context)
    elif field == 'channels':
        return await auto_sending_ask_channels(update, context)
    elif field == 'text':
        return await auto_sending_ask_text(update, context)
    else:
        return AUTO_SENDING_EDIT_FIELD


async def auto_sending_back_from_edit(update: Update, context):
    """Back button from edit menu to sending list — cleans up editing context."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop('editing_auto_sending', None)
    return await auto_sending_select(update, context)


async def auto_sending_back_to_edit(update: Update, context):
    """Back button handler for edit mode - returns to edit menu."""
    query = update.callback_query
    await query.answer()
    return await auto_sending_edit_start_from_data(update, context)


async def auto_sending_ask_name_edit(update: Update, context):
    """Ask for new name during edit."""
    current = context.user_data['editing_auto_sending']['data']['name']
    text = f"Текущее название: {current}<br><br>Введите новое название:"
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('Назад', callback_data='as_back_to_edit'),
         InlineKeyboardButton('Отменить', callback_data='Отменить-settings')]
    ])
    await query_or_message(update, context, text, reply_markup)
    return AUTO_SENDING_NAME



def _has_changes(editing: dict) -> bool:
    """Check if edited data differs from original."""
    original = editing.get('original', {})
    data = editing['data']
    # Check is_active separately since it's not in the main data loop always
    if 'is_active' in data and 'is_active' in original:
        if data['is_active'] != original['is_active']:
            return True
    for key in data:
        if key == 'is_active':
            continue
        if key in original:
            orig_val = original[key]
            new_val = data[key]
            if orig_val != new_val:
                return True
    return False


async def auto_sending_edit_start_from_data(update: Update, context):
    """Re-show edit menu from current data."""
    sending_id = context.user_data['editing_auto_sending']['id']
    sending = await db_postgres.get_auto_sending_by_id(context.session, sending_id)
    editing = context.user_data['editing_auto_sending']
    # Use edited data to show current state, not saved DB values
    text = _format_sending_summary(sending, data=editing['data'])
    
    has_changes = _has_changes(editing)
    if has_changes:
        text = text.replace("Редактирование:", "✅ Сохранить и редактировать:")
    
    is_active = editing['data'].get('is_active', sending.is_active)
    toggle_label = '🔴 Выкл' if is_active else '🟢 Вкл'
    keyboard = [
        [InlineKeyboardButton('Название', callback_data='as_edit_name'),
         InlineKeyboardButton('Триггер', callback_data='as_edit_trigger')],
        [InlineKeyboardButton('Спектакль', callback_data='as_edit_theater'),
         InlineKeyboardButton('Смещение', callback_data='as_edit_offset')],
        [InlineKeyboardButton('Окно', callback_data='as_edit_window'),
         InlineKeyboardButton('Точность', callback_data='as_edit_precise')],
        [InlineKeyboardButton('Каналы', callback_data='as_edit_channels'),
         InlineKeyboardButton('Текст', callback_data='as_edit_text')],
    ]
    if has_changes:
        keyboard.append([
            InlineKeyboardButton('💾 Сохранить', callback_data='as_edit_save'),
            InlineKeyboardButton(toggle_label, callback_data=f'as_toggle_{sending_id}')
        ])
    keyboard.extend([
        [InlineKeyboardButton('✉️ Ручная отправка', callback_data=f'as_manual_{sending_id}'),
         InlineKeyboardButton('🗑 Удалить', callback_data=f'as_delete_{sending_id}')],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3'),
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    result = transform_html(text)
    query = update.callback_query
    if query:
        try:
            await query.edit_message_text(result.text,
                                          entities=result.entities,
                                          reply_markup=reply_markup,
                                          parse_mode=None)
        except BadRequest:
            await update.effective_chat.send_message(result.text,
                                                      entities=result.entities,
                                                      reply_markup=reply_markup,
                                                      parse_mode=None)
    else:
        await update.effective_chat.send_message(result.text,
                                                  entities=result.entities,
                                                  reply_markup=reply_markup,
                                                  parse_mode=None)
    return AUTO_SENDING_EDIT_FIELD


async def auto_sending_save_edit(update: Update, context):
    """Save edited auto-sending."""
    query = update.callback_query
    await query.answer()

    sending_id = context.user_data['editing_auto_sending']['id']
    data = context.user_data['editing_auto_sending']['data']

    # Validate text if present (only validate, keep original HTML)
    if data.get('text'):
        try:
            transform_html(data['text'])  # Validate by calling, don't transform
        except Exception as e:
            await query.edit_message_text(f"❌ Неверный HTML в тексте: {e}")
            return AUTO_SENDING_EDIT_FIELD

    await db_postgres.update_auto_sending(
        context.session,
        sending_id,
        **{k: v for k, v in data.items() if k != 'id'},
    )

    context.user_data.pop('editing_auto_sending')
    await query.answer("Сохранено")
    return await auto_sending_select(update, context)


# ─── Toggle active / Delete ────────────────────────────────────────────────────

async def auto_sending_toggle_active(update: Update, context):
    """Toggle is_active flag."""
    query = update.callback_query
    await query.answer()

    try:
        sending_id = int(query.data.replace('as_toggle_', ''))
    except ValueError:
        await query.answer("Неверный ID рассылки", show_alert=True)
        return 3
    
    # If in edit mode, update data dict instead of DB
    if 'editing_auto_sending' in context.user_data:
        editing = context.user_data['editing_auto_sending']
        new_status = not editing['data'].get('is_active', True)
        editing['data']['is_active'] = new_status
        status_text = 'активна' if new_status else 'неактивна'
        await query.answer(f"Статус изменён: {status_text}")
        return await auto_sending_edit_start_from_data(update, context)
    
    # Otherwise, apply immediately (from list view)
    sending = await db_postgres.get_auto_sending_by_id(context.session, sending_id)
    if not sending:
        await query.edit_message_text("Рассылка не найдена.")
        return 3

    new_status = not sending.is_active
    await db_postgres.update_auto_sending(
        context.session, sending_id, is_active=new_status
    )

    status_text = 'активна' if new_status else 'неактивна'
    await query.answer(f"«{sending.name}» — {status_text}")
    return await auto_sending_select(update, context)


async def auto_sending_delete_start(update: Update, context):
    """Ask for confirmation to delete."""
    query = update.callback_query
    await query.answer()

    try:
        sending_id = int(query.data.replace('as_delete_', ''))
    except ValueError:
        await query.answer("Неверный ID рассылки", show_alert=True)
        return 3
    sending = await db_postgres.get_auto_sending_by_id(context.session, sending_id)
    if not sending:
        await query.edit_message_text("Рассылка не найдена.")
        return 3

    text = f"Удалить рассылку «{sending.name}»?"
    keyboard = [
        [InlineKeyboardButton('Да, удалить', callback_data=f'as_confirm_del_{sending_id}')],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3'),
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return 3


async def auto_sending_confirm_delete(update: Update, context):
    """Confirm and delete."""
    query = update.callback_query
    await query.answer()

    try:
        sending_id = int(query.data.replace('as_confirm_del_', ''))
    except ValueError:
        await query.answer("Неверный ID рассылки", show_alert=True)
        return 3
    await db_postgres.delete_auto_sending(context.session, sending_id)

    await query.answer("Удалено")
    return await auto_sending_select(update, context)


# ─── Manual send ───────────────────────────────────────────────────────────────

def _build_manual_send_keyboard(sending_id: int, force_resend: bool) -> InlineKeyboardMarkup:
    """Build keyboard for manual send menu."""
    force_label = '🔄 Повторная отправка ✅' if force_resend else '🔄 Повторная отправка'
    keyboard = [
        [InlineKeyboardButton('По билету (ticket_id)', callback_data='as_manual_by_ticket')],
        [InlineKeyboardButton('По сеансу (schedule_event_id)', callback_data='as_manual_by_session')],
        [InlineKeyboardButton('👁 Превью себе', callback_data=f'as_preview_{sending_id}')],
        [InlineKeyboardButton(force_label, callback_data='as_manual_force')],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3'),
    ]
    return InlineKeyboardMarkup(keyboard)


async def auto_sending_manual_send_start(update: Update, context):
    """Start manual send flow: choose mode (by ticket / by session)."""
    query = update.callback_query
    await query.answer()

    try:
        sending_id = int(query.data.replace('as_manual_', ''))
    except ValueError:
        await query.answer("Неверный ID рассылки", show_alert=True)
        return 3
    context.user_data['manual_sending_id'] = sending_id
    context.user_data['manual_force_resend'] = False

    text = "Режим ручной отправки:"
    force_resend = context.user_data.get('manual_force_resend', False)
    reply_markup = _build_manual_send_keyboard(sending_id, force_resend)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return AUTO_SENDING_MANUAL_MODE


async def auto_sending_toggle_force_resend(update: Update, context):
    """Toggle force resend mode."""
    query = update.callback_query
    await query.answer()

    context.user_data['manual_force_resend'] = not context.user_data.get('manual_force_resend', False)
    return await auto_sending_manual_send_start_from_data(update, context)


async def auto_sending_manual_send_start_from_data(update: Update, context):
    """Re-show manual send menu from current data."""
    query = update.callback_query
    if query:
        await query.answer()

    sending_id = context.user_data.get('manual_sending_id')
    if not sending_id:
        return await auto_sending_select(update, context)

    text = "Режим ручной отправки:"
    force_resend = context.user_data.get('manual_force_resend', False)
    reply_markup = _build_manual_send_keyboard(sending_id, force_resend)
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest:
        await update.effective_chat.send_message(text, reply_markup=reply_markup)
    return AUTO_SENDING_MANUAL_MODE


async def auto_sending_handle_manual_mode(update: Update, context):
    """Handle manual send mode selection."""
    query = update.callback_query
    await query.answer()

    if 'ticket' in query.data:
        context.user_data['manual_send_mode'] = 'ticket'
        text = "Введите ID билета:"
    else:
        context.user_data['manual_send_mode'] = 'session'
        text = "Введите ID сеанса (schedule_event_id):"

    reply_markup = InlineKeyboardMarkup([
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3')
    ])
    await query.edit_message_text(text, reply_markup=reply_markup)
    return AUTO_SENDING_MANUAL_ID


async def auto_sending_send_preview_to_self(update: Update, context):
    """Send a preview of the auto-sending message to the admin's chat."""
    query = update.callback_query
    await query.answer()

    try:
        sending_id = int(query.data.replace('as_preview_', ''))
    except ValueError:
        await query.answer("Неверный ID рассылки", show_alert=True)
        return 3
    sending = await db_postgres.get_auto_sending_by_id(context.session, sending_id)
    if not sending:
        await query.edit_message_text("Рассылка не найдена.")
        return AUTO_SENDING_MANUAL_MODE

    from schedule.auto_sending import render_text

    # Demo context with sample placeholder values
    demo_ctx = {
        'event_name': 'В поход с котом (путешествие)\n👶🏼3-6⏳50мин',
        'date': '04.10 (вс)',
        'time': '16:30',
        'ticket_ids': '5021',
        'place': '📍 Детский театр «Домик»: ул. Пушкина, 1',
        'refund_info': '',
    }

    text = render_text(sending.text, demo_ctx, sending_name=sending.name)
    transformed = transform_html(text)

    admin_chat_id = update.effective_chat.id
    try:
        await context.bot.send_message(
            chat_id=admin_chat_id,
            text=transformed.text,
            entities=transformed.entities,
            parse_mode=None,
        )
        await query.answer("Превью отправлено")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка отправки превью: {e}")
        return AUTO_SENDING_MANUAL_MODE

    return AUTO_SENDING_MANUAL_MODE


async def _build_recipient_ctx(schedule_event, ticket_ids_str: str) -> dict:
    """Build the recipient context dict for manual auto-sending.

    Delegates to the shared ``new_recipient_ctx`` factory so that the 6-key
    structure is defined in one place.  Supports ``schedule_event=None``
    (fallback dashes) which the shared ``build_recipient_ctx`` does not need.
    """
    from schedule.auto_sending import new_recipient_ctx
    from utilities.utl_func import get_formatted_date_and_time_of_event, get_full_name_event
    from utilities.utl_place import format_place_footnote

    if schedule_event:
        event_name = get_full_name_event(schedule_event.theater_event)
        date_str, time_str = await get_formatted_date_and_time_of_event(schedule_event)
        place_str = format_place_footnote(schedule_event.place) if schedule_event.place else ''
    else:
        event_name = '—'
        date_str = '—'
        time_str = '—'
        place_str = ''

    return new_recipient_ctx(
        event_name=event_name,
        date=date_str,
        time=time_str,
        ticket_ids=ticket_ids_str,
        place=place_str,
    )


async def _manual_send_by_ticket(context, target_id: int):
    """Build recipients list for manual send by ticket ID."""
    from schedule.auto_sending import Recipient

    ticket = await db_postgres.get_ticket(context.session, target_id)
    if not ticket:
        return None, f"Билет {target_id} не найден.", []

    if ticket.user is None:
        return None, "⚠️ Билет куплен без привязки пользователя, отправка невозможна.", []

    user = ticket.user
    if user.chat_id == 0:
        return None, "⚠️ Пользователь без привязки Telegram, отправка пропущена.", []

    se = ticket.schedule_event_id
    schedule_event = None
    if se:
        schedule_event = await db_postgres.get_schedule_event(context.session, se)

    ctx = await _build_recipient_ctx(schedule_event, str(ticket.id))
    recipients = [Recipient(user=user, ctx=ctx, dedup_key=f"t:{ticket.id}", schedule_event_id=se)]
    return recipients, None, []


async def _manual_send_by_session(context, target_id: int):
    """Build recipients list for manual send by session ID."""
    from schedule.auto_sending import Recipient
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import selectinload
    from db.enum import TicketStatus
    from db.models import Ticket as TicketModel, User as UserModel, UserStatus

    schedule_event = await db_postgres.get_schedule_event(context.session, target_id)
    if not schedule_event:
        return None, f"Сеанс {target_id} не найден.", []

    stmt = (
        sa_select(TicketModel)
        .options(
            selectinload(TicketModel.user)
            .selectinload(UserModel.status),
        )
        .where(
            TicketModel.schedule_event_id == target_id,
            TicketModel.status.in_([TicketStatus.PAID, TicketStatus.APPROVED]),
        )
    )
    tickets = (await context.session.execute(stmt)).scalars().all()

    from schedule.auto_sending import group_tickets_by_user
    user_tickets, no_user_ticket_ids = group_tickets_by_user(tickets)

    recipients = []
    for uid, tix in user_tickets.items():
        ticket_ids = ", ".join(str(t.id) for t in tix)
        ctx = await _build_recipient_ctx(schedule_event, ticket_ids)
        recipients.append(Recipient(
            user=tix[0].user,
            ctx=ctx,
            dedup_key=f"se:{target_id}",
            schedule_event_id=target_id,
        ))
    return recipients, None, no_user_ticket_ids


def _format_send_stats(stats: dict) -> str:
    """Format dispatch stats into a human-readable message."""
    sent = stats['sent']
    dedup_skipped = stats['dedup_skipped']
    no_chat_skipped = stats['no_chat_skipped']
    blocked_skipped = stats['blocked_skipped']
    not_sent_via_bot_skipped = stats['not_sent_via_bot_skipped']
    no_user_skipped = stats.get('no_user_skipped', [])

    skip_total = dedup_skipped + no_chat_skipped + blocked_skipped + not_sent_via_bot_skipped + len(no_user_skipped)
    if sent == 0 and skip_total > 0:
        msg = "⚠️ Рассылка не была отправлена ни одному получателю.<br><br>"
    else:
        msg = f"Отправлено: {sent} получателей<br>"

    if dedup_skipped > 0:
        msg += f"Пропущено (уже отправлено): {dedup_skipped}<br>"
    if no_chat_skipped > 0:
        msg += f"Пропущено (без привязки Telegram): {no_chat_skipped}<br>"
    if blocked_skipped > 0:
        msg += f"Пропущено (заблокирован): {blocked_skipped}<br>"
    if not_sent_via_bot_skipped > 0:
        msg += f"Пропущено (отправка через бот выключена): {not_sent_via_bot_skipped}<br>"
    if no_user_skipped:
        ids_str = ", ".join(str(tid) for tid in no_user_skipped)
        msg += f"Пропущено (билет без пользователя): {len(no_user_skipped)} (IDs: {ids_str})<br>"

    return msg.rstrip('<br>')


async def auto_sending_handle_manual_id(update: Update, context):
    """Execute manual send."""
    sending_id = context.user_data.get('manual_sending_id')
    mode = context.user_data.get('manual_send_mode')

    try:
        target_id = int(update.effective_message.text.strip())
    except (ValueError, AttributeError):
        await update.effective_chat.send_message("Пожалуйста, введите числовой ID.")
        return AUTO_SENDING_MANUAL_ID

    sending = await db_postgres.get_auto_sending_by_id(context.session, sending_id)
    if not sending:
        await update.effective_chat.send_message("Рассылка не найдена.")
        context.user_data.pop('manual_sending_id', None)
        return 3

    # Build recipients based on mode
    if mode == 'ticket':
        recipients, error, no_user_ticket_ids = await _manual_send_by_ticket(context, target_id)
    else:
        recipients, error, no_user_ticket_ids = await _manual_send_by_session(context, target_id)

    if error:
        await update.effective_chat.send_message(error)
        context.user_data.pop('manual_sending_id', None)
        return AUTO_SENDING_MANUAL_ID

    if not recipients and not no_user_ticket_ids:
        await update.effective_chat.send_message("Получатели не найдены.")
        context.user_data.pop('manual_sending_id', None)
        return AUTO_SENDING_MANUAL_ID

    # Dispatch
    from schedule.auto_sending import dispatch_auto_sending
    auto_sending_hl_logger.info("Manual sending")
    force_resend = context.user_data.pop('manual_force_resend', False)
    stats = await dispatch_auto_sending(
        context, context.session, sending, recipients, force_resend=force_resend)
    auto_sending_hl_logger.info("Manual sending dispatched")

    # Add no-user skipped info
    if no_user_ticket_ids:
        stats['no_user_skipped'] = no_user_ticket_ids

    # Report stats
    msg = _format_send_stats(stats)
    res = transform_html(msg)
    await update.effective_chat.send_message(res.text, entities=res.entities, parse_mode=None)
    context.user_data.pop('manual_sending_id', None)
    return await auto_sending_select(update, context)


# ─── Helper ────────────────────────────────────────────────────────────────────

async def query_or_message(update: Update, context,
                           text: str, reply_markup: InlineKeyboardMarkup):
    """Send or edit message depending on whether we have a callback query."""
    res = transform_html(text)
    query = update.callback_query
    if query:
        try:
            await query.edit_message_text(res.text, entities=res.entities, reply_markup=reply_markup, parse_mode=None)
        except BadRequest:
            await update.effective_chat.send_message(res.text, entities=res.entities, reply_markup=reply_markup, parse_mode=None)
    else:
        await update.effective_chat.send_message(res.text, entities=res.entities, reply_markup=reply_markup, parse_mode=None)

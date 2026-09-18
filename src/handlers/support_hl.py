import logging
import re

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest
from telegram.ext import ContextTypes, TypeHandler, ConversationHandler

from db import db_postgres
from db.enum import PriceType, TicketPriceType, PromotionDiscountType
from handlers import init_conv_hl_dialog, place_hl
from settings.settings import (
    RESERVE_TIMEOUT, COMMAND_DICT, DICT_CONVERT_MONTH_NUMBER_TO_STR,
    ADMIN_ID)
from utilities.utl_func import to_moscow_dt
from utilities.schemas import (
    kv_name_attr_schedule_event,
    kv_name_attr_theater_event,
    kv_name_attr_promotion)
from utilities.utl_func import set_back_context
from utilities.utl_kbd import (
    create_kbd_crud, create_kbd_confirm, add_btn_back_and_cancel,
    add_intent_id, remove_intent_id,
)

support_hl_logger = logging.getLogger('bot.support_hl')


def get_validated_data(string, option):
    query = string.split('\n')
    data = {}
    for kv in query:
        key, value = kv.split('=')
        validated_value = validate_value(value, option)
        if option == 'theater':
            for k, v in kv_name_attr_theater_event.items():
                if key == v:
                    data[k] = validated_value
        if option == 'schedule':
            for k, v in kv_name_attr_schedule_event.items():
                if key == v:
                    data[k] = validated_value
    return data


def validate_value(value, option):
    if value == 'Да':
        value = True
    if value == 'Нет':
        value = False
    if option == 'theater':
        if value == 'По умолчанию':
            value = PriceType.NONE
        if value == 'Базовая стоимость':
            value = PriceType.BASE_PRICE
        if value == 'Опции':
            value = PriceType.OPTIONS
        if value == 'Индивидуальная':
            value = PriceType.INDIVIDUAL
    if option == 'schedule':
        if value == 'По умолчанию':
            value = TicketPriceType.NONE
        if value == 'будни':
            value = TicketPriceType.weekday
        if value == 'выходные':
            value = TicketPriceType.weekend

    return value


async def start_settings(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    await init_conv_hl_dialog(update, context)
    user_is_admin = update.effective_user.id in ADMIN_ID

    button_db = InlineKeyboardButton(text='База данных', callback_data='db')
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=False)
    keyboard = [[button_db, ]]
    if user_is_admin:
        button_updates = InlineKeyboardButton(text='Обновление данных',
                                              callback_data='update_data')
        button_user_status = InlineKeyboardButton(text='Статусы пользователей',
                                                  callback_data='user_status_help')
        keyboard.extend([
            [button_updates, ],
            [button_user_status, ],
        ])
    keyboard.append([*button_cancel, ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите что хотите настроить'
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    state = 1
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_db_settings(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass

    user_is_admin = update.effective_user.id in ADMIN_ID

    button_base_ticket = InlineKeyboardButton(text='Базовые билеты',
                                              callback_data='base_ticket')
    button_event_type = InlineKeyboardButton(text='Типы показов',
                                             callback_data='event_type')
    button_event = InlineKeyboardButton(text='Репертуар',
                                        callback_data='theater_event')
    button_schedule = InlineKeyboardButton(text='Расписание',
                                           callback_data='schedule_event')
    button_promotion = InlineKeyboardButton(text='Промокоды/Акции',
                                            callback_data='promotion')
    button_place = InlineKeyboardButton(text='Локации',
                                        callback_data='place')
    button_back_and_cancel = add_btn_back_and_cancel(
        postfix_for_cancel='settings',
        postfix_for_back='1')
    keyboard = [[button_schedule,]]
    if user_is_admin:
        keyboard.extend([
            [
                button_base_ticket,
                button_event_type,
            ],
            [
                button_event,
                button_promotion,
            ],
            [
                button_place,
            ],
        ])
    keyboard.append([*button_back_and_cancel, ])

    # Добавляем intent-id только к функциональным кнопкам, но НЕ к ряду Назад/Отменить
    keyboard_intented = add_intent_id(keyboard[:-1], intent_id='db')
    keyboard = keyboard_intented + [keyboard[-1]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите что хотите настроить'
    await query.edit_message_text(text=text, reply_markup=reply_markup)

    state = 2
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def get_updates_option(update: Update,
                             context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass

    user_id = update.effective_user.id
    if user_id not in ADMIN_ID:
        support_hl_logger.warning(
            "Пользователь %s попытался открыть меню обновления данных без прав администратора",
            user_id
        )
        return context.user_data.get('STATE', 1)

    btn_update_place_data = InlineKeyboardButton(
        COMMAND_DICT['UP_PLACE_DATA'][1],
        callback_data=COMMAND_DICT['UP_PLACE_DATA'][0])
    btn_update_base_ticket_data = InlineKeyboardButton(
        COMMAND_DICT['UP_BT_DATA'][1],
        callback_data=COMMAND_DICT['UP_BT_DATA'][0])
    btn_update_special_ticket_price = InlineKeyboardButton(
        COMMAND_DICT['UP_SPEC_PRICE'][1],
        callback_data=COMMAND_DICT['UP_SPEC_PRICE'][0])
    btn_update_schedule_event_data = InlineKeyboardButton(
        COMMAND_DICT['UP_SE_DATA'][1],
        callback_data=COMMAND_DICT['UP_SE_DATA'][0])
    btn_update_theater_event_data = InlineKeyboardButton(
        COMMAND_DICT['UP_TE_DATA'][1],
        callback_data=COMMAND_DICT['UP_TE_DATA'][0])
    btn_update_custom_made_format_data = InlineKeyboardButton(
        COMMAND_DICT['UP_CMF_DATA'][1],
        callback_data=COMMAND_DICT['UP_CMF_DATA'][0])
    btn_update_promotion_data = InlineKeyboardButton(
        COMMAND_DICT['UP_PROM_DATA'][1],
        callback_data=COMMAND_DICT['UP_PROM_DATA'][0])
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            postfix_for_back='1')
    keyboard = [
        [btn_update_place_data],
        [btn_update_base_ticket_data,
         btn_update_special_ticket_price],
        [btn_update_schedule_event_data,
         btn_update_theater_event_data],
        [btn_update_custom_made_format_data,
         btn_update_promotion_data],
        [*button_cancel, ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите что хотите настроить\n\n'
    text += (
        f'{COMMAND_DICT['UP_PLACE_DATA'][1]}\n'
        f'{COMMAND_DICT['UP_BT_DATA'][1]}\n'
        f'{COMMAND_DICT['UP_SPEC_PRICE'][1]}\n'
        f'{COMMAND_DICT['UP_SE_DATA'][1]}\n'
        f'{COMMAND_DICT['UP_TE_DATA'][1]}\n'
        f'{COMMAND_DICT['UP_CMF_DATA'][1]}\n'
        f'{COMMAND_DICT['UP_PROM_DATA'][1]}\n'
    )
    await query.edit_message_text(text=text, reply_markup=reply_markup)

    state = 'updates'
    await set_back_context(context, state.upper(), text, reply_markup)

    return state


async def send_settings_menu(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE',
        pre_name_crud: str
):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass

    reply_markup = create_kbd_crud(pre_name_crud)

    text = 'Выберите что хотите настроить'
    await query.edit_message_text(text=text, reply_markup=reply_markup)

    context.user_data['reply_markup'] = reply_markup

    state = 3
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def get_settings(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass
    _, callback_data = remove_intent_id(query.data)

    user_id = update.effective_user.id
    if user_id not in ADMIN_ID and callback_data != 'schedule_event':
        support_hl_logger.warning(
            "Пользователь %s попытался открыть раздел %s без прав администратора",
            user_id, callback_data
        )
        return context.user_data.get('STATE', 2)

    if callback_data == 'theater_event':
        return await theater_event_select(update, context)
    elif callback_data == 'schedule_event':
        return await schedule_event_select(update, context)
    elif callback_data == 'promotion':
        return await promotion_select(update, context)
    elif callback_data == 'base_ticket':
        return await base_ticket_select(update, context)
    elif callback_data == 'event_type':
        return await event_type_select(update, context)
    elif callback_data == 'place':
        return await place_hl.place_select(update, context)

    state = await send_settings_menu(update, context, callback_data)

    return state


async def _paginated_select(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE',
        items: list,
        title: str,
        formatter,
        prefix: str,
        page: int = 0,
        limit: int = 20,
        filters: dict | list = None,
        current_filter: str | dict = None,
        extra_rows: list = None
):
    query = update.callback_query
    total = len(items)
    pages = max(1, (total + limit - 1) // limit)
    page = max(0, min(page, pages - 1))

    start = page * limit
    end = start + limit
    subset = items[start:end]

    text = f'<b>{title}</b>\n\n'
    item_buttons = []
    crud_name = prefix.replace('_select', '')
    if subset:
        for row in subset:
            text += formatter(row)
            item_id = getattr(row, 'id', getattr(row, 'base_ticket_id', None))
            # Для промокодов используем их существующий префикс, если это они
            cb_data = f'upd_prom_{item_id}' if crud_name == 'promotion' else f'{crud_name}_edit_{item_id}'
            item_buttons.append(InlineKeyboardButton(text=f"ID {item_id}", callback_data=cb_data))
    else:
        text += 'Список пуст.'

    # Инфо о страницах в самом конце отделено пустой строкой
    text += f'\nСтраница {page + 1} из {pages}'

    keyboard = []
    # Ряд кнопок элементов (по 3 в ряд)
    for i in range(0, len(item_buttons), 3):
        keyboard.append(item_buttons[i:i + 3])

    # Ряд пагинации
    if pages > 1:
        nav_row = []
        # ⏮ - в начало
        nav_row.append(InlineKeyboardButton('⏮', callback_data=f'{prefix}_p_0'))

        # ◀️ - назад
        prev_page = max(0, page - 1)
        nav_row.append(InlineKeyboardButton('◀️', callback_data=f'{prefix}_p_{prev_page}'))

        # 🔢 Текущая / выбор
        nav_row.append(InlineKeyboardButton(f'{page + 1} / {pages}', callback_data=f'{prefix}_page_info'))

        # ▶️ - вперед
        next_page = min(pages - 1, page + 1)
        nav_row.append(InlineKeyboardButton('▶️', callback_data=f'{prefix}_p_{next_page}'))

        # ⏭ - в конец
        nav_row.append(InlineKeyboardButton('⏭', callback_data=f'{prefix}_p_{pages - 1}'))

        keyboard.append(nav_row)

    # Ряд фильтров
    if filters:
        if isinstance(filters, list):
            # filters: [{'act': {'actual': 'Актуальные', ...}}, {'type': {...}}, ...]
            for filter_group in filters:
                filter_row = []
                for cat_key, cat_items in filter_group.items():
                    for f_key, f_label in cat_items.items():
                        is_active = False
                        if isinstance(current_filter, dict):
                            is_active = current_filter.get(cat_key) == str(f_key)
                        
                        label = f"✅ {f_label}" if is_active else f_label
                        filter_row.append(InlineKeyboardButton(label, callback_data=f'{prefix}_f_{cat_key}_{f_key}'))
                    # Разбиваем строку фильтров, если их слишком много (например, больше 4)
                    for chunk in [filter_row[i:i + 4] for i in range(0, len(filter_row), 4)]:
                        keyboard.append(chunk)
        else:
            # Поддержка двух форматов словаря:
            # 1) Плоский: {'actual': 'Актуальные', 'all': 'Все'}
            # 2) Группированный: {'act': {'actual': 'Актуал', 'all': 'Все'}}
            if any(isinstance(v, dict) for v in filters.values()):
                # Группированный вариант — формируем кнопки как для списка групп
                for cat_key, cat_items in filters.items():
                    filter_row = []
                    for f_key, f_label in cat_items.items():
                        is_active = False
                        if isinstance(current_filter, dict):
                            is_active = current_filter.get(cat_key) == str(f_key)
                        label = f"✅ {f_label}" if is_active else f_label
                        filter_row.append(InlineKeyboardButton(label, callback_data=f'{prefix}_f_{cat_key}_{f_key}'))
                    # Разбиваем строку фильтров на части по 4
                    for chunk in [filter_row[i:i + 4] for i in range(0, len(filter_row), 4)]:
                        keyboard.append(chunk)
            else:
                # Плоский вариант — простые переключатели без категорий
                filter_row = []
                for f_key, f_label in filters.items():
                    label = f"✅ {f_label}" if f_key == current_filter else f_label
                    filter_row.append(InlineKeyboardButton(label, callback_data=f'{prefix}_f_{f_key}'))
                keyboard.append(filter_row)

    # Кастомные ряды (например, кнопки меню фильтров)
    if extra_rows:
        for row in extra_rows:
            keyboard.append(row)

    # Кнопки CRUD (под списком) - только "Добавить"
    crud_markup = create_kbd_crud(crud_name, add_only=True)
    for row in crud_markup.inline_keyboard:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if query:
            await query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await update.effective_chat.send_message(text, reply_markup=reply_markup)
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


async def theater_event_select(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    user_id = update.effective_user.id
    if user_id not in ADMIN_ID:
        support_hl_logger.warning(
            "Пользователь %s попытался просмотреть репертуар без прав администратора",
            user_id
        )
        return context.user_data.get('STATE', 2)

    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass
    data = query.data or ""

    page = 0
    match_p = re.search(r'_p_(\d+)', data)
    if match_p:
        page = int(match_p.group(1))

    current_filter = context.user_data.get('filter_theater_event', 'actual')
    match_f = re.search(r'_f_(\w+)', data)
    if match_f:
        current_filter = match_f.group(1)
        context.user_data['filter_theater_event'] = current_filter
        page = 0

    if current_filter == 'actual':
        res = await db_postgres.get_all_theater_events_actual(context.session)
    else:
        res = await db_postgres.get_all_theater_events(context.session)

    filters = {'actual': 'Актуальные', 'all': 'Все'}

    return await _paginated_select(
        update, context, res,
        'Список репертуара',
        lambda row: f'• ID {row.id}: {row.name}\n',
        'theater_event_select',
        page,
        filters=filters,
        current_filter=current_filter
    )


async def schedule_event_select(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass
    data = query.data or ""

    page = 0
    match_p = re.search(r'_p_(\d+)', data)
    if match_p:
        page = int(match_p.group(1))

    # Фильтры
    actual_f = context.user_data.get('filter_schedule_actual', 'actual')
    type_f = context.user_data.get('filter_schedule_type', 'all')
    month_f = context.user_data.get('filter_schedule_month', 'all')

    match_f_cat = re.search(r'_f_(\w+)_(\w+)', data)
    if match_f_cat:
        cat = match_f_cat.group(1)
        val = match_f_cat.group(2)
        if cat == 'act':
            actual_f = val
            context.user_data['filter_schedule_actual'] = val
        elif cat == 'type':
            type_f = val
            context.user_data['filter_schedule_type'] = val
        elif cat == 'month':
            month_f = val
            context.user_data['filter_schedule_month'] = val
        page = 0
    else:
        # Старый формат или прямое переключение
        match_f = re.search(r'_f_(\w+)$', data)
        if match_f:
            val = match_f.group(1)
            if val in ['actual', 'all']:
                actual_f = val
                context.user_data['filter_schedule_actual'] = val
            page = 0

    # Проверка на вызов меню фильтрации (2-шаговый выбор)
    if '_f_menu_type' in data:
        types = await db_postgres.get_all_type_events(context.session)
        text = "<b>Выберите тип события для фильтрации:</b>\n\n"
        keyboard = []
        # Кнопка "Все типы"
        keyboard.append([InlineKeyboardButton(("✅ " if type_f == 'all' else "") + "Все типы", callback_data='schedule_event_select_f_type_all')])
        
        type_buttons = []
        for t in types:
            short_name = t.name_alias or t.name

            text += f"• ID {t.id}: {t.name} ({short_name})\n"
            
            is_active = type_f == str(t.id)
            btn_label = ("✅ " if is_active else "") + f"ID {t.id} ({short_name})"
            type_buttons.append(InlineKeyboardButton(btn_label, callback_data=f'schedule_event_select_f_type_{t.id}'))
        
        # Группируем по 2
        for i in range(0, len(type_buttons), 2):
            keyboard.append(type_buttons[i:i + 2])
        
        keyboard.append(add_btn_back_and_cancel(add_cancel_btn=False, add_back_btn=True, postfix_for_back='3'))
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return 3

    if '_f_menu_month' in data:
        # Получаем доступные месяцы для текущих фильтров (кроме самого месяца)
        temp_res = await db_postgres.get_schedule_events_filtered(
            context.session,
            actual_only=(actual_f == 'actual'),
            type_id=type_f,
            month='all'
        )
        available_months = sorted(list(set(event.datetime_event.month for event in temp_res)))
        
        text = "<b>Выберите месяц для фильтрации:</b>\n\n"
        keyboard = []
        # Кнопка "Все месяцы"
        keyboard.append([InlineKeyboardButton(("✅ " if month_f == 'all' else "") + "Все месяцы", callback_data='schedule_event_select_f_month_all')])
        
        # Кнопки месяцев: цифрами, по 3 в ряд
        month_buttons = []
        for m in available_months:
            is_active = month_f == str(m)
            btn_text = ("✅ " if is_active else "") + str(m)
            month_buttons.append(InlineKeyboardButton(btn_text, callback_data=f'schedule_event_select_f_month_{m}'))
        for i in range(0, len(month_buttons), 3):
            keyboard.append(month_buttons[i:i + 3])
            
        keyboard.append(add_btn_back_and_cancel(add_cancel_btn=False, add_back_btn=True, postfix_for_back='3'))
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return 3

    # Обычный показ списка
    res = await db_postgres.get_schedule_events_filtered(
        context.session,
        actual_only=(actual_f == 'actual'),
        type_id=type_f,
        month=month_f
    )

    # Определяем метки для кнопок меню
    type_label = "Все"
    if type_f != 'all':
        t_obj = await db_postgres.get_type_event(context.session, int(type_f))
        if t_obj:
            type_label = t_obj.name_alias or t_obj.name
            if len(type_label) > 15: type_label = type_label[:12] + ".."

    month_label = "Все"
    if month_f != 'all':
        month_label = DICT_CONVERT_MONTH_NUMBER_TO_STR[int(month_f)]

    # Формируем фильтры для _paginated_select (только переключатели меню)
    filters = [
        {'act': {'actual': 'Актуал', 'all': 'Все'}},
        # Кастомная строка с кнопками открытия меню
    ]
    
    # Дополнительные кнопки будут добавлены вручную через расширение логики _paginated_select или прямо здесь
    # Но проще изменить _paginated_select, чтобы он принимал готовые ряды кнопок или расширить его.
    # В данном случае я передам пустые фильтры и добавлю кнопки меню в основной клавиатуре.
    
    current_filters = {
        'act': actual_f
    }

    def schedule_formatter(row):
        type_name = row.type_event.name_alias if row.type_event else "???"
        # Заменяем П на Р
        if type_name == 'П': type_name = 'Р'
        
        theater_name = row.theater_event.name if row.theater_event else "???"
        if len(theater_name) > 30:
            theater_name = theater_name[:27] + "..."
        dt_str = to_moscow_dt(row.datetime_event).strftime("%d.%m %H:%M")
        
        # Статус вкл/выкл
        status_bot = '🤖' if row.flag_turn_in_bot else '🚫'
        
        return f'• ID {row.id}: {status_bot} [{type_name}] {theater_name} ({dt_str})\n'

    # Мы не можем легко добавить кастомные ряды в _paginated_select без его изменения.
    # Изменим _paginated_select, чтобы он поддерживал доп. ряды (extra_rows)
    
    extra_rows = [
        [
            InlineKeyboardButton(f"🎭 Тип: {type_label}", callback_data='schedule_event_select_f_menu_type'),
            InlineKeyboardButton(f"📅 Месяц: {month_label}", callback_data='schedule_event_select_f_menu_month')
        ]
    ]

    # Сноска с пояснениями
    text_explanation = (
        '\n\nПояснения:\n'
        '🤖/🚫 - в боте/скрыт\n'
        '[Р/НГ/...] - тип события (Репертуарный/Новогодний/...)'
    )

    return await _paginated_select(
        update, context, res,
        'Список расписания' + text_explanation,
        schedule_formatter,
        'schedule_event_select',
        page,
        filters=filters,  # Передаем список групп фильтров
        current_filter=current_filters,  # Текущее состояние по категориям
        extra_rows=extra_rows
    )


async def promotion_select(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    user_id = update.effective_user.id
    if user_id not in ADMIN_ID:
        support_hl_logger.warning(
            "Пользователь %s попытался просмотреть промокоды без прав администратора",
            user_id
        )
        return context.user_data.get('STATE', 2)

    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass
    data = query.data or ""

    page = 0
    match_p = re.search(r'_p_(\d+)', data)
    if match_p:
        page = int(match_p.group(1))

    current_filter = context.user_data.get('filter_promotion', 'actual')
    match_f = re.search(r'_f_(\w+)', data)
    if match_f:
        current_filter = match_f.group(1)
        context.user_data['filter_promotion'] = current_filter
        page = 0

    if current_filter == 'actual':
        res = await db_postgres.get_all_promotions_actual(context.session)
    else:
        res = await db_postgres.get_all_promotions(context.session)

    filters = {'actual': 'Актуальные', 'all': 'Все'}

    def promo_formatter(row):
        active = '✅' if row.flag_active else '❌'
        visible = '👁' if row.is_visible_as_option else '👻'
        return f'• ID {row.id}: <code>{row.code}</code> ({row.discount}{"%" if row.discount_type == PromotionDiscountType.percentage else "р"}) {active}{visible}\n'

    text_explanation = (
        'Пояснение:\n'
        '✅/❌ - активен/неактивен\n'
        '👁/👻 - виден/скрыт как опция'
    )

    return await _paginated_select(
        update, context, res,
        f'Список Промокодов\n{text_explanation}',
        promo_formatter,
        'promotion_select',
        page,
        filters=filters,
        current_filter=current_filter
    )


async def base_ticket_select(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    user_id = update.effective_user.id
    if user_id not in ADMIN_ID:
        support_hl_logger.warning(
            "Пользователь %s попытался просмотреть базовые билеты без прав администратора",
            user_id
        )
        return context.user_data.get('STATE', 2)

    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass
    data = query.data or ""

    page = 0
    match_p = re.search(r'_p_(\d+)', data)
    if match_p:
        page = int(match_p.group(1))

    current_filter = context.user_data.get('filter_base_ticket', 'actual')
    match_f = re.search(r'_f_(\w+)', data)
    if match_f:
        current_filter = match_f.group(1)
        context.user_data['filter_base_ticket'] = current_filter
        page = 0

    if current_filter == 'actual':
        res = await db_postgres.get_all_base_tickets_actual(context.session)
    else:
        res = await db_postgres.get_all_base_tickets(context.session)

    filters = {'actual': 'Актуальные', 'all': 'Все'}

    return await _paginated_select(
        update, context, res,
        'Список базовых билетов',
        lambda row: f'• ID {row.base_ticket_id}: {row.name}\n',
        'base_ticket_select',
        page,
        filters=filters,
        current_filter=current_filter
    )


async def event_type_select(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    user_id = update.effective_user.id
    if user_id not in ADMIN_ID:
        support_hl_logger.warning(
            "Пользователь %s попытался просмотреть типы показов без прав администратора",
            user_id
        )
        return context.user_data.get('STATE', 2)

    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass
    data = query.data or ""

    page = 0
    match_p = re.search(r'_p_(\d+)', data)
    if match_p:
        page = int(match_p.group(1))

    res = await db_postgres.get_all_type_events(context.session)

    return await _paginated_select(
        update, context, res,
        'Список типов показов',
        lambda row: f'• ID {row.id}: {row.name}\n',
        'event_type_select',
        page
    )


async def theater_event_update_start(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Редактирование репертуара через мастер пока не реализовано. Давайте уточним, какие поля нужно менять?",
        reply_markup=InlineKeyboardMarkup([
            add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3')
        ])
    )
    return 3


async def base_ticket_update_start(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Редактирование базовых билетов через бот появится позже. Уточните пожелания.",
        reply_markup=InlineKeyboardMarkup([
            add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3')
        ])
    )
    return 3


async def event_type_update_start(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Редактирование типов показов через бот появится позже.",
        reply_markup=InlineKeyboardMarkup([
            add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3')
        ])
    )
    return 3


async def theater_event_preview(
        update: Update,
        _: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    text = (
        f'{kv_name_attr_theater_event['name']}=Название\n'
        f'{kv_name_attr_theater_event['min_age_child']}=1\n'
        f'{kv_name_attr_theater_event['max_age_child']}=0\n'
        f'{kv_name_attr_theater_event['show_emoji']}=\n'
        f'{kv_name_attr_theater_event['flag_premier']}=Нет\n'
        f'{kv_name_attr_theater_event['flag_active_repertoire']}=Да\n'
        f'{kv_name_attr_theater_event['flag_active_bd']}=Нет\n'
        f'{kv_name_attr_theater_event['max_num_child_bd']}=8\n'
        f'{kv_name_attr_theater_event['max_num_adult_bd']}=10\n'
        f'{kv_name_attr_theater_event['flag_indiv_cost']}=Нет\n'
        f'{kv_name_attr_theater_event['price_type']}=По умолчанию/Базовая стоимость/Опции/Индивидуальная\n'
        f'{kv_name_attr_theater_event['note']}=\n'
    )
    await query.edit_message_text(text)
    try:
        await query.answer()
    except BadRequest:
        pass

    return 41


async def schedule_event_preview(
        update: Update,
        _: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    text = (f'{kv_name_attr_schedule_event['type_event_id']}=\n'
            f'{kv_name_attr_schedule_event['theater_event_id']}=\n'
            f'{kv_name_attr_schedule_event['flag_turn_in_bot']}=Нет\n'
            f'{kv_name_attr_schedule_event['datetime_event']}=2024-01-01T00:00 +3\n'
            f'{kv_name_attr_schedule_event['qty_child']}=8\n'
            f'{kv_name_attr_schedule_event['qty_adult']}=10\n'
            f'{kv_name_attr_schedule_event['flag_gift']}=Нет\n'
            f'{kv_name_attr_schedule_event['flag_christmas_tree']}=Нет\n'
            f'{kv_name_attr_schedule_event['flag_santa']}=Нет\n'
            f'{kv_name_attr_schedule_event['ticket_price_type']}=По умолчанию/будни/выходные\n')
    await query.edit_message_text(text)
    try:
        await query.answer()
    except BadRequest:
        pass

    return 42


async def theater_event_check(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get('support_message_id')
        )
    except Exception:
        pass

    await update.effective_chat.send_message(
        'Проверьте и отправьте текст еще раз или нажмите подтвердить')

    reply_markup = create_kbd_confirm()

    text = update.effective_message.text
    message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    context.user_data['support_message_id'] = message.message_id

    context.user_data['theater_event'] = get_validated_data(text, 'theater')
    return 41


async def schedule_event_check(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get('support_message_id')
        )
    except Exception:
        pass

    await update.effective_chat.send_message(
        'Проверьте и отправьте текст еще раз или нажмите подтвердить')

    reply_markup = create_kbd_confirm()

    text = update.effective_message.text
    message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    context.user_data['support_message_id'] = message.message_id

    context.user_data['schedule_event'] = get_validated_data(text, 'schedule')
    return 42




async def promotion_preview(
        update: Update,
        _: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    text = (
        f"{kv_name_attr_promotion['name']}=Название\n"
        f"{kv_name_attr_promotion['code']}=PROMO10\n"
        f"{kv_name_attr_promotion['discount']}=10\n"
        f"{kv_name_attr_promotion['discount_type']}=percentage\n"
        f"{kv_name_attr_promotion['start_date']}=\n"
        f"{kv_name_attr_promotion['expire_date']}=\n"
        f"{kv_name_attr_promotion['is_visible_as_option']}=Нет\n"
        f"{kv_name_attr_promotion['min_purchase_sum']}=0\n"
        f"{kv_name_attr_promotion['max_count_of_usage']}=0\n"
        f"{kv_name_attr_promotion['description_user']}=\n"
    )
    await query.edit_message_text(text)
    try:
        await query.answer()
    except BadRequest:
        pass

    return 43


async def promotion_check(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get('support_message_id')
        )
    except Exception:
        pass

    await update.effective_chat.send_message(
        'Проверьте и отправьте текст еще раз или нажмите подтвердить')

    reply_markup = create_kbd_confirm()

    text = update.effective_message.text
    message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    context.user_data['support_message_id'] = message.message_id

    context.user_data['promotion'] = get_validated_data(text, 'promotion')
    return 43


async def promotion_create(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    promotion = context.user_data['promotion']
    reply_markup = context.user_data['reply_markup']

    res = await db_postgres.create_promotion(
        context.session,
        promotion
    )

    context.user_data.pop('promotion')
    await query.answer()
    if res:
        await query.answer(f"{promotion['code']} — успешно добавлено")
        return await choice_db_settings(update, context)
    else:
        text = 'Попробуйте еще раз или обратитесь в тех поддержку'
        await query.edit_message_text(text)
        return 43


async def theater_event_create(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    theater_event = context.user_data['theater_event']
    reply_markup = context.user_data['reply_markup']

    res = await db_postgres.create_theater_event(
        context.session,
        **theater_event
    )

    context.user_data.pop('theater_event')
    await query.answer()
    if res:
        await query.answer(f"{theater_event['name']} — успешно добавлено")
        return await choice_db_settings(update, context)
    else:
        text = 'Попробуйте еще раз или обратитесь в тех поддержку'
        await query.edit_message_text(text)
        return 41


async def schedule_event_create(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    schedule_event = context.user_data['schedule_event']
    reply_markup = context.user_data['reply_markup']

    res = await db_postgres.create_schedule_event(
        context.session,
        **schedule_event
    )

    context.user_data.pop('schedule_event')
    await query.answer()
    if res:
        # Получаю элемент репертуара, так как название есть только в репертуаре
        the = await db_postgres.get_theater_event(
            context.session,
            schedule_event['theater_event_id'])
        await query.answer(f"{the.name} — успешно добавлено")
        return await choice_db_settings(update, context)
    else:
        text = 'Попробуйте еще раз или обратитесь в тех поддержку'
        await query.edit_message_text(text)
        return 42


async def conversation_timeout(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
) -> int:
    """Informs the user that the operation has timed out,
    calls :meth:`remove_reply_markup` and ends the conversation.
    :return:
        int: :attr:`telegram.ext.ConversationHandler.END`.
    """
    user = context.user_data.get('user', update.effective_user)

    await update.effective_chat.send_message(
        'От Вас долго не было ответа, пожалуйста выполните новый запрос',
        message_thread_id=update.effective_message.message_thread_id
    )

    support_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            f'AFK уже {RESERVE_TIMEOUT} мин'
        ]
    ))
    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)

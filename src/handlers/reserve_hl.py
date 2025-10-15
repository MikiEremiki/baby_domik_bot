import logging
import pprint
from datetime import datetime

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, Message,
)
from telegram.error import TimedOut, NetworkError, BadRequest
from telegram.ext import (
    ContextTypes, ConversationHandler, TypeHandler, ApplicationHandlerStop)
from telegram.constants import ChatType, ChatAction

from api.gspread_pub import (
    publish_write_client_reserve, publish_write_client_list_waiting)
from db import db_postgres, BaseTicket
from db.db_googlesheets import decrease_free_seat
from db.db_postgres import get_schedule_theater_base_tickets
from db.enum import TicketStatus
from handlers import init_conv_hl_dialog, check_user_db
from handlers.email_hl import check_email_and_update_user
from handlers.sub_hl import (
    request_phone_number,
    send_breaf_message, send_message_about_list_waiting,
    remove_button_from_last_message,
    create_and_send_payment, processing_successful_payment,
    get_theater_and_schedule_events_by_month,
)
from api.googlesheets import write_client_list_waiting, write_client_reserve
from utilities.utl_check import (
    check_available_seats, check_available_ticket_by_free_seat,
    check_entered_command, check_topic, check_input_text, is_skip_ticket
)
from utilities.utl_func import (
    extract_phone_number_from_text, set_back_context, check_phone_number,
    get_full_name_event, get_formatted_date_and_time_of_event,
    create_event_names_text, get_type_event_ids_by_command, clean_context,
    add_clients_data_to_text, add_qty_visitors_to_text,
    filter_schedule_event_by_active, get_unique_months,
    clean_replay_kb_and_send_typing_action,
    create_str_info_by_schedule_event_id,
    get_schedule_event_ids_studio, clean_context_on_end_handler, get_emoji
)
from utilities.utl_googlesheets import update_ticket_db_and_gspread
from utilities.utl_ticket import (
    cancel_tickets_db_and_gspread, create_tickets_and_people)
from utilities.utl_kbd import (
    create_kbd_schedule, create_replay_markup, add_btn_back_and_cancel,
    create_kbd_and_text_tickets_for_choice,
    create_kbd_for_date_in_reserve, create_kbd_with_months,
    adjust_kbd, remove_intent_id, add_intent_id,
    create_kbd_unique_dates, create_kbd_for_time_by_date,
    create_phone_confirm_btn, create_child_confirm_btn,
)
from settings.settings import (
    ADMIN_GROUP, COMMAND_DICT, SUPPORT_DATA, RESERVE_TIMEOUT
)

reserve_hl_logger = logging.getLogger('bot.reserve_hl')


async def choice_mode(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Начальный шаг выбора способа подбора мероприятий: по дате или по репертуару.
    Возвращает состояние MODE.
    """
    query = update.callback_query
    if not (context.user_data.get('command', False) and query):
        await init_conv_hl_dialog(update, context)
        await check_user_db(update, context)

    if update.effective_message.is_topic_message:
        if context.user_data.get('command', False) and query:
            await query.answer()
            await query.delete_message()
        is_correct_topic = await check_topic(update, context)
        if not is_correct_topic:
            context.user_data['conv_hl_run'] = False
            return ConversationHandler.END

    command = context.user_data['command']
    postfix_for_cancel = command
    context.user_data['postfix_for_cancel'] = postfix_for_cancel

    user = context.user_data.setdefault('user', update.effective_user)
    reserve_hl_logger.info(f'Пользователь начал выбор режима подбора: {user}')

    text = 'Как будем выбирать мероприятия?'

    # Две кнопки: По календарю и По репертуару
    kb = [
        InlineKeyboardButton('По календарю', callback_data='DATE'),
        InlineKeyboardButton('По репертуару', callback_data='REPERTOIRE'),
    ]
    reply_markup = await create_replay_markup(
        kb,
        intent_id='MODE',
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        add_back_btn=False,
        size_row=2,
    )

    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.effective_message.message_thread_id
    )

    state = 'MODE'
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    if context.user_data.get('command', False) and query:
        await query.answer()
        await query.delete_message()
    return state


async def choice_show_by_repertoire(update: Update,
                                    context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Репертуарный путь: сначала выбор группы спектаклей (Домика/Приглашенные),
    затем список спектаклей выбранной группы без фильтра по месяцу.
    Возвращает состояние REP_GROUP или SHOW.
    """
    query = update.callback_query
    # Устанавливаем режим выбора: репертуар
    context.user_data['select_mode'] = 'REPERTOIRE'
    if query:
        try:
            await query.answer()
        except TimedOut as e:
            reserve_hl_logger.error(e)

    command = context.user_data['command']
    postfix_for_cancel = context.user_data.get('postfix_for_cancel', command)

    # Определяем, что выбрал пользователь: вход в репертуар или выбор группы
    intent_id = None
    payload = None
    if query:
        try:
            intent_id, payload = remove_intent_id(query.data)
        except Exception:
            intent_id, payload = (None, None)

    # Шаг 1: показать выбор группы спектаклей
    if (
            intent_id == 'MODE' or
            intent_id is None or
            intent_id == 'REP_GROUP' and payload in (None, '')
    ):
        text = 'Выберите репертуарную группу'
        kb = [
            InlineKeyboardButton('Домика', callback_data='DOMIK'),
            InlineKeyboardButton('Приглашенные', callback_data='INVITED'),
        ]
        # Клавиатура: намеренно используем intent REP_GROUP, чтобы следующий клик обрабатывался здесь же
        reply_markup = await create_replay_markup(
            kb,
            intent_id='REP_GROUP',
            postfix_for_cancel=postfix_for_cancel,
            postfix_for_back='MODE',
            size_row=2,
        )
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=update.effective_message.message_thread_id,
        )
        state = 'REP_GROUP'
        await set_back_context(context, state, text, reply_markup)
        context.user_data['STATE'] = state
        # Не удаляем предыдущее сообщение, если это прямой вход без query
        if query:
            try:
                await query.delete_message()
            except BadRequest as e:
                reserve_hl_logger.error(e)
        return state

    # Шаг 2: выбрана конкретная группа (DOMIK/INVITED) — формируем список спектаклей
    # Сохраним выбор группы для Back
    group = payload or context.user_data.get('repertoire_group')
    if payload in ('DOMIK', 'INVITED'):
        context.user_data['repertoire_group'] = payload
        group = payload

    type_event_ids = await get_type_event_ids_by_command(command)
    schedule_events = await db_postgres.get_schedule_events_by_type_actual(
        context.session, type_event_ids)
    schedule_events = await filter_schedule_event_by_active(schedule_events)

    # Фильтрация по группе: invited -> type_event_id == 14, Домика -> все, кроме 14
    INVITED_TYPE_ID = 14
    if group == 'INVITED':
        schedule_events = [ev for ev in schedule_events if
                           ev.type_event_id == INVITED_TYPE_ID]
        group_title = 'Приглашенные'
    else:
        schedule_events = [ev for ev in schedule_events if
                           ev.type_event_id != INVITED_TYPE_ID]
        group_title = 'Домика'

    # Собираем уникальные спектакли по порядку появления в расписании
    theater_event_id_order = []
    for ev in schedule_events:
        if ev.theater_event_id not in theater_event_id_order:
            theater_event_id_order.append(ev.theater_event_id)
    theater_events = await db_postgres.get_theater_events_by_ids(
        context.session, theater_event_id_order)
    theater_events = sorted(
        theater_events,
        key=lambda e: theater_event_id_order.index(e.id)
    )
    enum_theater_events = tuple(enumerate(theater_events, start=1))

    text_legend = context.bot_data['texts']['text_legend']
    text = f'<b>{group_title}</b>\n\n'
    text += '<b>Выберите мероприятие\n</b>' + text_legend
    text = await create_event_names_text(enum_theater_events, text)

    state = 'SHOW'

    keyboard = await create_kbd_schedule(enum_theater_events)
    reply_markup = await create_replay_markup(
        keyboard,
        intent_id=state,
        postfix_for_cancel=postfix_for_cancel,
        postfix_for_back='REP_GROUP',
        size_row=4,
    )

    # Отправляем текст со списком спектаклей
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.effective_message.message_thread_id,
    )

    # Сохраняем IDs всех событий, чтобы следующий шаг отобрал нужные по спектаклю
    schedule_event_ids = [item.id for item in schedule_events]
    state_data = context.user_data['reserve_user_data'][state] = {}
    state_data['schedule_event_ids'] = schedule_event_ids

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state

    if query:
        try:
            await query.delete_message()
        except BadRequest as e:
            reserve_hl_logger.error(e)
    return state


async def choice_month(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Функция отправляет пользователю список месяцев.

    С сообщением передается inline клавиатура, для выбора подходящего варианта
    :return: возвращает state MONTH
    """
    query = update.callback_query
    if not (context.user_data.get('command', False) and query):
        await init_conv_hl_dialog(update, context)
        await check_user_db(update, context)

    if update.effective_message.is_topic_message:
        if context.user_data.get('command', False) and query:
            await query.answer()
            await query.delete_message()
        is_correct_topic = await check_topic(update, context)
        if not is_correct_topic:
            context.user_data['conv_hl_run'] = False
            return ConversationHandler.END

    command = context.user_data['command']
    postfix_for_cancel = command
    context.user_data['postfix_for_cancel'] = postfix_for_cancel

    user = context.user_data.setdefault('user', update.effective_user)
    reserve_hl_logger.info(f'Пользователь начал выбор месяца: {user}')

    # Устанавливаем режим выбора, если пришли из шага MODE (По календарю/По репертуару)
    if query:
        try:
            intent_id_mode, callback_data = remove_intent_id(query.data)
        except Exception:
            intent_id_mode, callback_data = (None, None)
        if intent_id_mode == 'MODE':
            if callback_data == 'DATE':
                # По календарю => далее после выбора месяца показываем даты
                context.user_data['select_mode'] = 'DATE'
            else:
                # По репертуару => далее после выбора месяца показываем спектакли
                context.user_data['select_mode'] = 'REPERTOIRE'

    type_event_ids = await get_type_event_ids_by_command(command)
    schedule_events = await db_postgres.get_schedule_events_by_type_actual(
        context.session, type_event_ids)
    schedule_events = await filter_schedule_event_by_active(schedule_events)
    months = get_unique_months(schedule_events)
    message = await clean_replay_kb_and_send_typing_action(update)
    text = 'Выберите месяц'
    keyboard = await create_kbd_with_months(months)
    keyboard = adjust_kbd(keyboard, 1)
    state = 'MONTH'
    keyboard = add_intent_id(keyboard, state)
    # Показываем кнопку Назад в MONTH только если есть состояние MODE (вошли через выбор режима)
    has_mode = 'MODE' in context.user_data.get('reserve_user_data', {}).get(
        'back', {})
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        add_back_btn=has_mode,
        postfix_for_back='MODE' if has_mode else None
    ))
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=message.message_id
    )
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.effective_message.message_thread_id
    )

    schedule_event_ids = [item.id for item in schedule_events]
    state_data = context.user_data['reserve_user_data'][state] = {}
    state_data['schedule_event_ids'] = schedule_event_ids
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_show(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    """
    Функция отправляет пользователю список спектаклей с датами.

    С сообщением передается inline клавиатура, для выбора подходящего варианта
    :return: возвращает state DATE
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)
    reserve_user_data = context.user_data['reserve_user_data']

    intent_id, callback_data = remove_intent_id(query.data)
    is_pagination = intent_id == 'SHOW_PAGE'
    if is_pagination:
        number_of_month_str = reserve_user_data.get('number_of_month_str')
    else:
        await query.delete_message()
        number_of_month_str = callback_data

    reserve_hl_logger.info(f'Пользователь выбрал месяц: {number_of_month_str}')
    state = context.user_data['STATE']
    schedule_event_ids = reserve_user_data[state]['schedule_event_ids']
    schedule_events = await db_postgres.get_schedule_events_by_ids(
        context.session, schedule_event_ids)

    try:
        enum_theater_events, schedule_events_filter_by_month = await (
            get_theater_and_schedule_events_by_month(
                context, schedule_events, number_of_month_str)
        )
    except ValueError as e:
        reserve_hl_logger.error(e)
        return state

    text_legend = context.bot_data['texts']['text_legend']

    # Режим выбора: если выбран «По календарю», после месяца показываем даты
    select_mode = context.user_data.get('select_mode')
    if (not is_pagination) and (select_mode == 'DATE'):
        # Показываем только уникальные даты без разделения по спектаклям
        text = '<b>Выберите удобную дату\n</b>' + text_legend
        state = 'DATE'
        keyboard = await create_kbd_unique_dates(
            schedule_events_filter_by_month,
        )
        reply_markup = await create_replay_markup(
            keyboard,
            intent_id=state,
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back='MONTH',
            size_row=2
        )
    else:
        # Список спектаклей и пагинация
        all_events = list(enum_theater_events)
        page_size = 5
        total_items = len(all_events)
        use_pagination = total_items > page_size

        # Текущая страница
        page = 1
        if is_pagination:
            try:
                page = int(callback_data)
            except (TypeError, ValueError):
                page = 1

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        events_page = all_events[
            start_idx:end_idx] if use_pagination else all_events

        text = '<b>Выберите мероприятие\n</b>' + text_legend
        text = await create_event_names_text(tuple(events_page), text)

        state = 'SHOW'

        if use_pagination:
            # Кнопки спектаклей с интентом SHOW
            event_buttons = await create_kbd_schedule(tuple(events_page))
            event_rows = adjust_kbd(event_buttons, 5)
            event_rows = add_intent_id(event_rows, state)

            # Кнопки навигации с интентом SHOW_PAGE
            pages_total = (total_items + page_size - 1) // page_size
            nav_row = []
            if page > 1:
                nav_row.append(
                    InlineKeyboardButton('« Пред', callback_data=str(page - 1)))
            nav_row.append(InlineKeyboardButton(f'{page}/{pages_total}',
                                                callback_data=str(page)))
            if page < pages_total:
                nav_row.append(
                    InlineKeyboardButton('След »', callback_data=str(page + 1)))
            nav_rows = add_intent_id([nav_row], 'SHOW_PAGE')

            kb = event_rows + nav_rows
            kb.append(add_btn_back_and_cancel(
                postfix_for_cancel=context.user_data['postfix_for_cancel'],
                add_back_btn=True,
                postfix_for_back='MONTH'
            ))
            reply_markup = InlineKeyboardMarkup(kb)
        else:
            keyboard = await create_kbd_schedule(tuple(events_page))
            reply_markup = await create_replay_markup(
                keyboard,
                intent_id=state,
                postfix_for_cancel=context.user_data['postfix_for_cancel'],
                postfix_for_back='MONTH',
                size_row=4
            )

    photo = (
        context.bot_data
        .get('afisha', {})
        .get(int(number_of_month_str), False)
    )

    if is_pagination:
        if (
                update.effective_chat.type == ChatType.PRIVATE and
                photo and
                update.effective_message.photo
        ):
            try:
                await query.edit_message_caption(
                    caption=text,
                    reply_markup=reply_markup,
                )
            except BadRequest as e:
                if 'Message is not modified' in str(e):
                    reserve_hl_logger.info(
                        'Игнорируем клик по текущей странице (без изменений)')
                else:
                    reserve_hl_logger.error(e)
        else:
            try:
                await query.edit_message_text(
                    text=text, reply_markup=reply_markup)
            except BadRequest as e:
                if 'Message is not modified' in str(e):
                    reserve_hl_logger.info(
                        'Игнорируем клик по текущей странице (без изменений)')
                else:
                    reserve_hl_logger.error(e)
    else:
        if update.effective_chat.type == ChatType.PRIVATE and photo:
            await update.effective_chat.send_photo(
                photo=photo,
                caption=text,
                reply_markup=reply_markup,
            )
        else:
            await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup,
                message_thread_id=update.effective_message.message_thread_id,
            )

    reserve_user_data['number_of_month_str'] = number_of_month_str
    schedule_event_ids = [item.id for item in schedule_events_filter_by_month]
    state_data = context.user_data['reserve_user_data'][state] = {}
    state_data['schedule_event_ids'] = schedule_event_ids

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_date(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Репертуарный путь: объединяем выбор даты и времени в один шаг.
    - В режиме По репертуару (select_mode == 'REPERTOIRE') после выбора спектакля
      показываем сразу кнопки Дата + Время (каждая кнопка = конкретный показ).
    - Для остальных режимов (или для команды list_wait) сохраняем прежнее поведение.

    С сообщением передается inline клавиатура, для выбора подходящего варианта.
    Возвращает state TIME (в репертуаре) или DATE/LIST_WAIT в остальных случаях.
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)

    _, callback_data = remove_intent_id(query.data)
    theater_event_id = int(callback_data)
    reserve_user_data = context.user_data['reserve_user_data']
    number_of_month_str = reserve_user_data.get('number_of_month_str')

    prev_state = context.user_data['STATE']
    schedule_event_ids = reserve_user_data[prev_state]['schedule_event_ids']
    theater_event = await db_postgres.get_theater_event(
        context.session, theater_event_id)
    schedule_events = await db_postgres.get_schedule_events_by_ids_and_theater(
        context.session, schedule_event_ids, [theater_event_id])

    # Режим выбора
    select_mode = context.user_data.get('select_mode')

    # Если репертуар и не лист ожидания — объединяем дату и время в один шаг
    if select_mode == 'REPERTOIRE' and context.user_data.get(
            'command') != 'list_wait':
        # Кнопки: все показы выбранного спектакля (ДАТА ВРЕМЯ + флаги)
        schedule_events_sorted = sorted(schedule_events,
                                        key=lambda e: e.datetime_event)
        keyboard = []
        unique_times = []
        seen_times = set()
        for s_ev in schedule_events_sorted:
            date_txt, time_txt = await get_formatted_date_and_time_of_event(s_ev)
            text_emoji = await get_emoji(s_ev)
            btn_text = f"{date_txt} {time_txt}{text_emoji}"
            keyboard.append(
                InlineKeyboardButton(text=btn_text, callback_data=str(s_ev.id)))
            # Копим список уникальных времен для текста
            if time_txt not in seen_times:
                seen_times.add(time_txt)
                unique_times.append(time_txt)

        reply_markup = await create_replay_markup(
            keyboard,
            intent_id='TIME',
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back='SHOW',
            size_row=2
        )

        full_name, _text = await get_text_for_reserve(schedule_events,
                                                      theater_event)

        text = (f'Вы выбрали мероприятие:\n'
                f'<b>{full_name}</b>\n\n')
        if unique_times:
            text += '<b>Доступное время:</b> ' + ', '.join(
                unique_times) + '\n\n'
        text += f'<i>Выберите удобные дату и время</i>\n\n{_text}'

        # Информация о свободных местах по каждому показу
        if schedule_events_sorted:
            text += '<b>Свободные места:</b>\n'
            for s_ev in schedule_events_sorted:
                date_txt, time_txt = await get_formatted_date_and_time_of_event(
                    s_ev)
                qty_child = max(int(s_ev.qty_child_free_seat), 0)
                qty_adult = max(int(s_ev.qty_adult_free_seat), 0)
                text += f"{date_txt} {time_txt} — {qty_child} дет | {qty_adult} взр\n"

        photo = False
        if number_of_month_str is not None and select_mode == 'DATE':
            try:
                photo = (
                    context.bot_data
                    .get('afisha', {})
                    .get(int(number_of_month_str), False)
                )
            except (TypeError, ValueError):
                photo = False
        if update.effective_chat.type == ChatType.PRIVATE and photo:
            await query.edit_message_caption(
                caption=text, reply_markup=reply_markup)
        else:
            await query.edit_message_text(
                text=text, reply_markup=reply_markup)

        # Переходим сразу к TIME
        state = 'TIME'
        schedule_event_ids = [item.id for item in schedule_events]
        state_data = context.user_data['reserve_user_data'][state] = {}
        state_data['schedule_event_ids'] = schedule_event_ids

        await set_back_context(context, state, text, reply_markup)
        context.user_data['STATE'] = state
        return state

    # ---------- Прежнее поведение для остальных случаев ----------
    # Определяем конечный state экрана (DATE/LIST_WAIT)
    if context.user_data['command'] == 'list_wait':
        state = 'LIST_WAIT'
    else:
        state = 'DATE'

    by_date, unique_times = await unique_events_group_by_date(schedule_events)

    # Строим клавиатуру: либо обычные даты (DATE), либо прямые кнопки дата+время (TIME)
    use_direct_time = (state != 'LIST_WAIT') and all(
        len(v) == 1 for v in by_date.values()) and len(by_date) > 0

    if use_direct_time:
        # Прямые кнопки на TIME c текстом Дата + Время (+эмодзи опций)
        keyboard = []
        for d, ev_list in sorted(by_date.items()):
            s_ev = ev_list[0]
            date_txt, time_txt = await get_formatted_date_and_time_of_event(s_ev)
            text_emoji = await get_emoji(s_ev)
            btn_text = f"{date_txt} {time_txt}{text_emoji}"
            keyboard.append(
                InlineKeyboardButton(text=btn_text, callback_data=str(s_ev.id)))
        reply_markup = await create_replay_markup(
            keyboard,
            intent_id='TIME',
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back='SHOW',
            size_row=2
        )
        state = 'TIME'
    else:
        # Обычные кнопки дат (далее выбор времени)
        keyboard = await create_kbd_for_date_in_reserve(schedule_events)
        reply_markup = await create_replay_markup(
            keyboard,
            intent_id=state,
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back='SHOW',
            size_row=2
        )

    full_name, _text = await get_text_for_reserve(schedule_events,
                                                  theater_event)

    text = (f'Вы выбрали мероприятие:\n'
            f'<b>{full_name}</b>\n\n')

    # Добавим строку с доступными временами (уникальные значения)
    if unique_times:
        text += '<b>Доступное время:</b> ' + ', '.join(unique_times) + '\n\n'

    # Подсказка по следующему шагу
    if use_direct_time:
        text += '<i>Выберите удобную дату и время</i>\n\n'
    else:
        text += '<i>Выберите удобную дату</i>\n\n'
    text += f'{_text}'

    # Информация о свободных местах
    if use_direct_time:
        text += '\n<b>Свободные места:</b>\n'
        for d, ev_list in sorted(by_date.items()):
            s_ev = ev_list[0]
            date_txt, time_txt = await get_formatted_date_and_time_of_event(s_ev)
            qty_child = max(int(s_ev.qty_child_free_seat), 0)
            qty_adult = max(int(s_ev.qty_adult_free_seat), 0)
            text += f"{date_txt} {time_txt} — {qty_child} дет | {qty_adult} взр\n"
    else:
        # Суммарно по датам (на выбранную дату времена покажем на следующем шаге)
        text += '\n<b>Свободные места по датам (суммарно):</b>\n'
        for d in sorted(by_date.keys()):
            evs = by_date[d]
            qty_child = sum(max(int(e.qty_child_free_seat), 0) for e in evs)
            qty_adult = sum(max(int(e.qty_adult_free_seat), 0) for e in evs)
            text += f"{d.strftime('%d.%m')} — {qty_child} дет | {qty_adult} взр\n"

    photo = False
    if number_of_month_str is not None:
        try:
            photo = (
                context.bot_data
                .get('afisha', {})
                .get(int(number_of_month_str), False)
            )
        except (TypeError, ValueError):
            photo = False
    if update.effective_chat.type == ChatType.PRIVATE and photo:
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text, reply_markup=reply_markup)
    else:
        await query.edit_message_text(
            text=text, reply_markup=reply_markup)

    # Сохраним id событий выбранного спектакля для следующего шага
    schedule_event_ids = [item.id for item in schedule_events]
    state_data = reserve_user_data[state] = {}
    state_data['schedule_event_ids'] = schedule_event_ids

    reserve_user_data['theater_event_id'] = theater_event_id

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def unique_events_group_by_date(schedule_events):
    # Группируем события по дате и собираем список уникальных времен
    from collections import defaultdict
    by_date: dict = defaultdict(list)
    unique_times = []
    seen_times = set()
    for ev in schedule_events:
        d = ev.datetime_event.date()
        by_date[d].append(ev)
        try:
            _, time_txt = await get_formatted_date_and_time_of_event(ev)
        except Exception as e:
            reserve_hl_logger.error(e)
            time_txt = ev.datetime_event.strftime('%H:%M')
        if time_txt not in seen_times:
            seen_times.add(time_txt)
            unique_times.append(time_txt)
    return by_date, unique_times


async def choice_month_rep_continue(update: Update,
                                    context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Обработка выбора месяца в репертуарном режиме после выбора спектакля.
    Показывает доступные даты для выбранного спектакля в выбранном месяце
    и отправляет афишу месяца (если доступна).
    Возвращает состояние DATE (или LIST_WAIT для list_wait).
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)

    # Достаем выбранный месяц
    _, callback_data = remove_intent_id(query.data)
    number_of_month_str = callback_data
    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['number_of_month_str'] = number_of_month_str

    # Контекст: после шага MONTH в репертуаре мы сохранили список id событий по выбранному спектаклю
    state_prev = 'MONTH'
    schedule_event_ids = reserve_user_data[state_prev]['schedule_event_ids']
    schedule_events = await db_postgres.get_schedule_events_by_ids(
        context.session, schedule_event_ids)

    # Оставляем только события выбранного месяца
    schedule_events = [ev for ev in schedule_events if
                       ev.datetime_event.month == int(number_of_month_str)]

    theater_event_id = int(reserve_user_data.get('selected_theater_event_id'))
    theater_event = await db_postgres.get_theater_event(context.session,
                                                        theater_event_id)

    # Строим клавиатуру с датами
    keyboard = await create_kbd_for_date_in_reserve(schedule_events)
    if context.user_data['command'] == 'list_wait':
        state = 'LIST_WAIT'
    else:
        state = 'DATE'
    reply_markup = await create_replay_markup(
        keyboard,
        intent_id=state,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='SHOW',
        size_row=2
    )

    full_name, _text = await get_text_for_reserve(schedule_events,
                                                  theater_event)

    text = (f'Вы выбрали мероприятие:\n'
            f'<b>{full_name}</b>\n\n'
            f'<i>Выберите удобную дату</i>\n\n'
            f'{_text}')

    # Переходим от текстового сообщения к фото с подписью, если возможно
    photo = (
        context.bot_data
        .get('afisha', {})
        .get(int(number_of_month_str), False)
    )

    # Удаляем сообщение с выбором месяца и отправляем новое
    try:
        await query.delete_message()
    except BadRequest as e:
        reserve_hl_logger.error(e)

    if update.effective_chat.type == ChatType.PRIVATE and photo:
        await update.effective_chat.send_photo(
            photo=photo,
            caption=text,
            reply_markup=reply_markup,
            message_thread_id=update.effective_message.message_thread_id,
        )
    else:
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=update.effective_message.message_thread_id,
        )

    schedule_event_ids = [item.id for item in schedule_events]
    state_data = context.user_data['reserve_user_data'][state] = {}
    state_data['schedule_event_ids'] = schedule_event_ids

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def get_text_for_reserve(schedule_events, theater_event):
    flag_gift = any(ev.flag_gift for ev in schedule_events)
    flag_christmas_tree = any(
        ev.flag_christmas_tree for ev in schedule_events)
    flag_santa = any(ev.flag_santa for ev in schedule_events)

    full_name = get_full_name_event(theater_event)
    _text = ''
    if flag_gift:
        _text += f'{SUPPORT_DATA['Подарок'][0]} - {SUPPORT_DATA['Подарок'][1]}\n'
    if flag_christmas_tree:
        _text += f'{SUPPORT_DATA['Елка'][0]} - {SUPPORT_DATA['Елка'][1]}\n'
    if flag_santa:
        _text += f'{SUPPORT_DATA['Дед'][0]} - {SUPPORT_DATA['Дед'][1]}\n'
    return full_name, _text


async def choice_time(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Обработка выбора даты/спектакля.
    Два сценария:
    1) Старый путь (после выбора спектакля): callback_data = 'theater_event_id|YYYY-MM-DD' → показываем время для выбранного спектакля.
    2) Новый путь «по календарю»: callback_data = 'YYYY-MM-DD' → показываем список вариантов (спектакль + время) на выбранную дату.

    Возвращает state TIME (или LIST для команды list).
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)
    _, callback_data = remove_intent_id(query.data)

    check_command_studio = check_entered_command(context, 'studio')

    # Новый путь: выбрана только дата (по календарю)
    selected_date = callback_data
    reserve_user_data = context.user_data['reserve_user_data']
    state_prev = context.user_data['STATE']  # Должен быть 'DATE'
    schedule_event_ids = reserve_user_data[state_prev]['schedule_event_ids']
    schedule_events_all = await db_postgres.get_schedule_events_by_ids(
        context.session, schedule_event_ids)

    # Фильтруем события выбранной даты
    try:
        selected_date_dt = datetime.fromisoformat(selected_date).date()
    except ValueError:
        selected_date_dt = datetime.strptime(selected_date, '%Y-%m-%d').date()
    schedule_events = [
        ev for ev in schedule_events_all if
        ev.datetime_event.date() == selected_date_dt
    ]

    # Список спектаклей и их порядок для легенды и эмодзи
    theater_event_id_order = []
    for ev in schedule_events:
        if ev.theater_event_id not in theater_event_id_order:
            theater_event_id_order.append(ev.theater_event_id)
    theater_events = await db_postgres.get_theater_events_by_ids(
        context.session, theater_event_id_order)
    theater_events = sorted(
        theater_events,
        key=lambda e: theater_event_id_order.index(e.id)
    )
    enum_theater_events = tuple(enumerate(theater_events, start=1))

    # Клавиатура: варианты (спектакль + время)
    keyboard = await create_kbd_for_time_by_date(schedule_events,
                                                 enum_theater_events)

    # Определяем следующее состояние
    if context.user_data.get('command', False) == 'list':
        state = 'LIST'
    else:
        state = 'TIME'

    reply_markup = await create_replay_markup(
        keyboard,
        intent_id=state,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='DATE',
        size_row=1
    )

    # Текст с легендой по спектаклям
    text = (
        f"Вы выбрали дату:\n<b>{selected_date_dt.strftime('%d.%m')}</b>\n\n"
        f"<b>Выберите спектакль и удобное время</b>\n\n"
    )
    text = await create_event_names_text(enum_theater_events, text)
    text += ('<i>Вы также можете выбрать вариант с 0 кол-вом мест '
             'для записи в лист ожидания на данное время</i>\n\n'
             'Кол-во свободных мест:\n')

    if check_command_studio:
        text += '⬇️<i>Время</i> | <i>Детских</i>⬇️'
    else:
        text += '⬇️<i>Время</i> | <i>Детских</i> | <i>Взрослых</i>⬇️'

    await query.delete_message()
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.effective_message.message_thread_id
    )

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_option_of_reserve(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю,
    дате, времени и варианты бронирования

    С сообщением передается inline клавиатура, для выбора подходящего варианта
    :return: возвращает state ORDER
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)
    message = await update.effective_chat.send_message(
        'Загружаю данные по билетам...')

    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)

    _, callback_data = remove_intent_id(query.data)
    choice_event_id = int(callback_data)

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['choose_schedule_event_id'] = choice_event_id

    (
        base_tickets,
        schedule_event,
        theater_event,
        type_event
    ) = await get_schedule_theater_base_tickets(context, choice_event_id)

    # Гарантируем наличие id выбранного спектакля для дальнейших шагов оплаты
    reserve_user_data['choose_theater_event_id'] = theater_event.id

    text_select_event = await create_str_info_by_schedule_event_id(
        context, choice_event_id)

    reserve_user_data['text_select_event'] = text_select_event

    check_command_reserve = check_entered_command(context, 'reserve')
    only_child = False
    text = (f'Кол-во свободных мест: '
            f'<i>'
            f'{schedule_event.qty_child_free_seat} дет'
            f' | '
            f'{schedule_event.qty_adult_free_seat} взр'
            f'</i>\n')

    check_command_studio = check_entered_command(context, 'studio')
    if check_command_studio:
        only_child = True
        text = (f'Кол-во свободных мест: '
                f'<i>'
                f'{schedule_event.qty_child_free_seat} дет'
                f'</i>\n')

    check_command = check_command_reserve or check_command_studio
    check_seats = check_available_seats(schedule_event, only_child=only_child)
    if check_command and not check_seats:
        try:
            await message.delete()
        except BadRequest as e:
            reserve_hl_logger.error(e)

        no_seats_text = (
                text_select_event +
                '\nК сожалению, на выбранное время свободных мест нет.\n'
                'Запишитесь в лист ожидания, иногда случаются переносы или '
                'отмены!\n'
                'Если это случится вам поступит уведомление от бота или с вами '
                'свяжется администратор\n\n'
                '<b>Выберите дальнейшие действия:</b>'
        )

        keyboard = [
            InlineKeyboardButton('Записаться в лист ожидания',
                                 callback_data='WAIT'),
            InlineKeyboardButton('В начало', callback_data='OTHER_TIME'),
        ]
        reply_markup = await create_replay_markup(
            keyboard,
            intent_id='CHOOSING',
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            add_back_btn=True,
            postfix_for_back='TIME',
            size_row=1,
        )

        # Показываем экран выбора действий
        await query.edit_message_text(no_seats_text, reply_markup=reply_markup)

        # Сохраняем состояние и контекст для возврата Назад
        state = 'CHOOSING'
        await set_back_context(context, state, no_seats_text, reply_markup)
        context.user_data['STATE'] = state
        return state

    await message.edit_text('Формирую список доступных билетов...')

    text = text_select_event + text
    text += '\n<b>Выберите подходящий вариант бронирования:</b>\n'

    base_tickets_filtered = []
    for i, ticket in enumerate(base_tickets):
        check_ticket = check_available_ticket_by_free_seat(
            schedule_event, theater_event, type_event, ticket, only_child)
        if not ticket.flag_active or (check_command and not check_ticket):
            continue
        base_tickets_filtered.append(ticket)

    keyboard, text = await create_kbd_and_text_tickets_for_choice(
        context, text, base_tickets_filtered, schedule_event, theater_event)

    state = 'TICKET'
    intent_id = state
    postfix_for_cancel = context.user_data['postfix_for_cancel']
    postfix_for_back = 'TIME'
    size_row = 5
    keyboard = adjust_kbd(keyboard, size_row)
    keyboard = add_intent_id(keyboard, intent_id)
    keyboard.append([InlineKeyboardButton('Записаться в лист ожидания',
                                          callback_data='CHOOSING|WAIT')])
    keyboard.append(
        add_btn_back_and_cancel(add_cancel_btn=True,
                                postfix_for_cancel=postfix_for_cancel,
                                add_back_btn=True,
                                postfix_for_back=postfix_for_back)
    )
    reply_markup = InlineKeyboardMarkup(keyboard)

    text += ('__________\n'
             '<i>Если вы хотите оформить несколько билетов, '
             'то каждая бронь оформляется отдельно.</i>\n'
             '__________\n'
             '<i>МНОГОДЕТНЫМ:\n'
             '1. Пришлите удостоверение многодетной семьи администратору\n'
             '2. Дождитесь ответа\n'
             '3. Оплатите билет со скидкой 10% от цены, которая указана выше</i>')

    await message.delete()

    if update.effective_message.photo:
        await query.edit_message_caption(caption=text,
                                         reply_markup=reply_markup)
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup)

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def get_email(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    if not query:
        await check_email_and_update_user(update, context)

    reserve_user_data = context.user_data['reserve_user_data']

    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    price = reserve_user_data['chose_price']
    text_select_event = reserve_user_data['text_select_event']

    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)
    text = text_select_event + (f'Вариант бронирования:\n'
                                f'{chose_base_ticket.name} '
                                f'{int(price)}руб\n')

    context.user_data['common_data']['text_for_notification_massage'] = text

    await update.effective_chat.send_message(text=text)
    message = await update.effective_chat.send_message(
        'Проверяю наличие свободных мест...')
    await update.effective_chat.send_action(ChatAction.TYPING)

    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    schedule_event = await db_postgres.get_schedule_event(
        context.session, schedule_event_id)
    context.session.add(schedule_event)
    await context.session.refresh(schedule_event)
    theater_event = await db_postgres.get_theater_event(context.session,
                                                        schedule_event.theater_event_id)
    type_event = await db_postgres.get_type_event(context.session,
                                                  schedule_event.type_event_id)

    check_command = check_entered_command(context, 'reserve')
    only_child = None
    if check_command:
        only_child = False
    check_command = check_entered_command(context, 'studio')
    if check_command:
        only_child = True
    if only_child is None:
        reserve_hl_logger.error(f'{only_child=}')
        raise ApplicationHandlerStop

    check_ticket = check_available_ticket_by_free_seat(
        schedule_event, theater_event, type_event, chose_base_ticket, only_child)
    if query:
        await query.answer()
        await query.delete_message()
    if check_command and not check_ticket:
        await message.delete()
        await send_message_about_list_waiting(update, context)

        state = 'CHOOSING'
        context.user_data['STATE'] = state
        return state

    reserve_hl_logger.info('Получено разрешение на бронирование')

    message = await message.edit_text(
        'Проверка пройдена, готовлю дальнейшие шаги...')
    await update.effective_chat.send_action(ChatAction.TYPING)

    await message.delete()
    message = await send_breaf_message(update, context)

    reserve_user_data['message_id'] = message.message_id
    state = 'FORMA'
    context.user_data['STATE'] = state
    return state


async def get_adult(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    reserve_user_data = context.user_data['reserve_user_data']

    await context.bot.edit_message_reply_markup(
        update.effective_chat.id,
        message_id=reserve_user_data['message_id']
    )
    text = update.effective_message.text

    message = await send_msg_get_phone(update, context)

    reserve_user_data['client_data']['name_adult'] = text
    reserve_user_data['message_id'] = message.message_id
    state = 'PHONE'
    context.user_data['STATE'] = state
    return state


async def get_phone(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    reserve_user_data = context.user_data['reserve_user_data']

    await context.bot.edit_message_reply_markup(
        update.effective_chat.id,
        message_id=reserve_user_data['message_id']
    )
    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        message = await request_phone_number(update, context)
        reserve_user_data['message_id'] = message.message_id
        return context.user_data['STATE']

    message = await send_msg_get_child(update, context)

    reserve_user_data['client_data']['phone'] = phone
    reserve_user_data['message_id'] = message.message_id
    state = 'CHILDREN'
    context.user_data['STATE'] = state
    return state


async def get_children(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    reserve_user_data = context.user_data['reserve_user_data']

    await context.bot.edit_message_reply_markup(
        update.effective_chat.id,
        message_id=reserve_user_data['message_id']
    )
    await update.effective_chat.send_action(ChatAction.TYPING)

    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    if chose_base_ticket.quality_of_children > 0:
        wrong_input_data_text = (
            'Проверьте, что указали возраст правильно\n'
            'Например:\n'
            'Сергей 2\n'
            'Юля 3\n'
            '__________\n'
            '<i> - Если детей несколько, напишите всех в одном сообщении\n'
            ' - Один ребенок = одна строка\n'
            ' - Не используйте дополнительные слова и пунктуацию, '
            'кроме тех, что указаны в примерах</i>'
        )
        text = update.effective_message.text
        keyboard = [add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=False)]
        reply_markup = InlineKeyboardMarkup(keyboard)

        result = await check_children_names(
            update, context, wrong_input_data_text)
        if not result:
            return context.user_data['STATE']
        reserve_hl_logger.info('Проверка пройдена успешно')

        processed_data_on_children = [item.split() for item in text.split('\n')]

        if not isinstance(processed_data_on_children[0], list):
            message = await update.effective_chat.send_message(
                text=f'Вы ввели:\n{text}' + wrong_input_data_text,
                reply_markup=reply_markup
            )
            reserve_user_data['message_id'] = message.message_id
            state = 'CHILDREN'
            context.user_data['STATE'] = state
            return state

        if len(processed_data_on_children) != chose_base_ticket.quality_of_children:
            message = await update.effective_chat.send_message(
                text=f'Кол-во детей, которое определено: '
                     f'{len(processed_data_on_children)}\n'
                     f'Кол-во детей, согласно выбранному билету: '
                     f'{chose_base_ticket.quality_of_children}\n'
                     f'Повторите ввод еще раз, проверьте что каждый ребенок на '
                     f'отдельной строке.\n\nНапример:\nИван 1\nМарина 3',
                reply_markup=reply_markup
            )
            reserve_user_data['message_id'] = message.message_id
            state = 'CHILDREN'
            context.user_data['STATE'] = state
            return state
    else:
        processed_data_on_children = [['0', '0']]

    client_data = reserve_user_data['client_data']
    client_data['data_children'] = processed_data_on_children
    reserve_user_data['original_child_text'] = update.effective_message.text

    command = context.user_data.get('command', False)
    if '_admin' in command:
        schedule_event_id = reserve_user_data['choose_schedule_event_id']
        await get_schedule_event_ids_studio(context)
        await update.effective_chat.send_action(ChatAction.TYPING)

        text = 'Создаю новые билеты в бд...'
        reserve_hl_logger.info(text)
        message = await update.effective_chat.send_message(text)
        ticket_ids = await create_tickets_and_people(
            update, context, TicketStatus.CREATED)

        text += '\nЗаписываю новый билет в клиентскую базу...'
        try:
            await message.edit_text(text)
        except TimedOut as e:
            reserve_hl_logger.error(e)
            reserve_hl_logger.info(text)
        sheet_id_domik = context.config.sheets.sheet_id_domik
        chat_id = update.effective_chat.id
        base_ticket_dto = chose_base_ticket.to_dto()
        ticket_status_value = str(TicketStatus.CREATED.value)
        reserve_user_data = context.user_data['reserve_user_data']
        try:
            await publish_write_client_reserve(
                sheet_id_domik,
                reserve_user_data,
                chat_id,
                base_ticket_dto,
                ticket_status_value
            )
        except Exception as e:
            reserve_hl_logger.exception(
                f'Failed to publish gspread task, fallback to direct call: {e}')
            res = await write_client_reserve(sheet_id_domik,
                                             reserve_user_data,
                                             chat_id,
                                             base_ticket_dto,
                                             ticket_status_value)
            if res == 0:
                await context.bot.send_message(
                    chat_id=context.config.bot.developer_chat_id,
                    text=f'Не записался билет {ticket_ids} в клиентскую базу')

        text += '\nУменьшаю кол-во свободных мест...'
        try:
            await message.edit_text(text)
        except TimedOut as e:
            reserve_hl_logger.error(e)
            reserve_hl_logger.info(text)
        result = await decrease_free_seat(
            context, schedule_event_id, chose_base_ticket_id)
        if not result:
            for ticket_id in ticket_ids:
                await update_ticket_db_and_gspread(context,
                                                   ticket_id,
                                                   status=TicketStatus.CANCELED)
            text += ('\nНе уменьшились свободные места'
                     '\nНовый билет отменен'
                     '\nНеобходимо повторить резервирование заново')
            try:
                await message.edit_text(text)
            except TimedOut as e:
                reserve_hl_logger.error(e)
                reserve_hl_logger.info(text)
            context.user_data['conv_hl_run'] = False
            await clean_context_on_end_handler(reserve_hl_logger, context)
            return ConversationHandler.END

        text += '\nПоследняя проверка...'
        try:
            await message.edit_text(text)
        except TimedOut as e:
            reserve_hl_logger.error(e)
            reserve_hl_logger.info(text)
        await processing_successful_payment(update, context)

        state = ConversationHandler.END
        context.user_data['conv_hl_run'] = False
    else:
        state = await create_and_send_payment(update, context)
        if state is None:
            state = 'PAID'
    context.user_data['STATE'] = state
    return state


async def get_child_text_and_reply(
        base_ticket: BaseTicket,
        child,
        context: 'ContextTypes.DEFAULT_TYPE'
) -> tuple[str, InlineKeyboardMarkup]:
    back_and_cancel = add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
        add_back_btn=False)
    if base_ticket.quality_of_children > 0:
        text = '<b>Напишите, имя и сколько полных лет ребенку</b>\n\n'
        text_help = """__________
Например:
Сергей 2
Юля 3
__________
<i> - Если детей несколько, напишите всех в одном сообщении
 - Один ребенок = одна строка
 - Не используйте дополнительные слова и пунктуацию, кроме тех, что указаны в примерах</i>"""
        keyboard = [back_and_cancel]
        if base_ticket.quality_of_children == 1:
            child_confirm_btn, text_child = await create_child_confirm_btn(
                text, child)
            if child_confirm_btn:
                keyboard.insert(0, child_confirm_btn)
                text = text_child
        text += text_help
    else:
        text = 'Нажмите <b>Далее</b>'
        next_btn = InlineKeyboardButton(
            'Далее',
            callback_data='Далее'
        )
        keyboard = [[next_btn], [back_and_cancel]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    return text, reply_markup


async def send_msg_get_child(update: Update,
                             context: 'ContextTypes.DEFAULT_TYPE') -> Message:
    reserve_user_data = context.user_data['reserve_user_data']
    base_ticket_id = reserve_user_data['chose_base_ticket_id']
    base_ticket = await db_postgres.get_base_ticket(context.session,
                                                    base_ticket_id)
    child = await db_postgres.get_child(context.session,
                                        update.effective_user.id)
    text, reply_markup = await get_child_text_and_reply(
        base_ticket, child, context)

    message = await update.effective_chat.send_message(
        text=text, reply_markup=reply_markup)
    return message


async def send_msg_get_phone(update: Update,
                             context: 'ContextTypes.DEFAULT_TYPE') -> Message:
    text_prompt = '<b>Напишите номер телефона</b>\n\n'
    phone = await db_postgres.get_phone(context.session,
                                        update.effective_user.id)
    phone_confirm_btn, text_prompt = await create_phone_confirm_btn(
        text_prompt, phone)

    back_and_cancel = add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
        add_back_btn=False)

    if phone_confirm_btn:
        keyboard = [phone_confirm_btn, back_and_cancel]
    else:
        keyboard = [back_and_cancel]

    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.effective_chat.send_message(
        text=text_prompt,
        reply_markup=reply_markup
    )
    return message


async def check_children_names(update: Update,
                               context: 'ContextTypes.DEFAULT_TYPE',
                               text):
    reserve_user_data = context.user_data['reserve_user_data']
    result = await check_input_text(update.effective_message.text)
    if not result:
        keyboard = [add_btn_back_and_cancel(
            context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=False)]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
        )
        reserve_user_data['message_id'] = message.message_id
    return result


async def forward_photo_or_file(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    await remove_button_from_last_message(update, context)

    await processing_successful_payment(update, context)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    context.user_data['conv_hl_run'] = False
    return state


async def processing_successful_notification(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    await processing_successful_payment(update, context)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    context.user_data['conv_hl_run'] = False
    return state


async def conversation_timeout(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
) -> int:
    """Informs the user that the operation has timed out,
    calls: meth:`remove_reply_markup` and ends the conversation.
    :return:
        Int: attr:`telegram.ext.ConversationHandler.END`.
    """
    user = context.user_data['user']
    if context.user_data['STATE'] == 'PAID':
        reserve_hl_logger.info('Отправка чека об оплате не была совершена')
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['common_data']['message_id_buy_info']
        )
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, бронь отменена, '
            'пожалуйста выполните новый запрос\n'
            'Если вы уже сделали оплату, но не отправили чек об оплате, '
            'выполните оформление повторно и приложите данный чек\n'
            f'/{COMMAND_DICT['RESERVE'][0]}\n\n'
            'Если свободных мест не будет свяжитесь с Администратором:\n'
            f'{context.bot_data['admin']['contacts']}'
        )
        reserve_hl_logger.info(pprint.pformat(context.user_data))

    else:
        # TODO Прописать дополнительную обработку states, для этапов опроса
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос',
            message_thread_id=update.effective_message.message_thread_id
        )

    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            f'AFK уже {RESERVE_TIMEOUT} мин'
        ]
    ))
    reserve_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')

    await cancel_tickets_db_and_gspread(update, context)

    await clean_context(context)
    context.user_data['conv_hl_run'] = False
    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)


async def send_clients_data(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)

    _, callback_data = remove_intent_id(query.data)
    event_id = int(callback_data)
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    theater_event = await db_postgres.get_theater_event(
        context.session, schedule_event.theater_event_id)
    date_event, time_event = await get_formatted_date_and_time_of_event(
        schedule_event)
    tickets = schedule_event.tickets
    base_ticket_and_tickets = []
    for ticket in tickets:
        base_ticket = await db_postgres.get_base_ticket(context.session,
                                                        ticket.base_ticket_id)
        if not is_skip_ticket(ticket.status):
            base_ticket_and_tickets.append((base_ticket, ticket))

    try:
        await query.edit_message_text('Загружаю данные покупателей')
    except TimedOut as e:
        reserve_hl_logger.error(e)

    text = f'#Мероприятие <code>{event_id}</code>\n'
    text += (f'Список людей на\n'
             f'<b>{theater_event.name}\n'
             f'{date_event} в '
             f'{time_event}</b>\n')

    text += await add_qty_visitors_to_text(base_ticket_and_tickets)

    text += await add_clients_data_to_text(base_ticket_and_tickets)

    await query.edit_message_text(text)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    try:
        await query.answer()
    except NetworkError as e:
        reserve_hl_logger.error(e)
    context.user_data['conv_hl_run'] = False
    return state


async def write_list_of_waiting(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query
    await query.answer()

    # Предложим последний введенный телефон (если есть)
    text_prompt = '<b>Напишите номер телефона</b>\n\n'
    phone = await db_postgres.get_phone(context.session,
                                        update.effective_user.id)
    phone_confirm_btn, text_prompt = await create_phone_confirm_btn(text_prompt,
                                                                    phone)

    state = 'PHONE_FOR_WAITING'
    if phone_confirm_btn:
        reply_markup = await create_replay_markup(
            phone_confirm_btn,
            state,
            postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=True,
            postfix_for_back=context.user_data['STATE']
        )
        await query.edit_message_text(text=text_prompt,
                                      reply_markup=reply_markup)
    else:
        await query.edit_message_text(text=text_prompt)

    context.user_data['STATE'] = state
    return state


async def adult_confirm(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Обработчик подтверждения ранее введенного имени (inline-button).
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)

    await query.edit_message_text(update.effective_message.text + '\nДа')

    reserve_user_data = context.user_data['reserve_user_data']
    try:
        await context.bot.edit_message_reply_markup(
            update.effective_chat.id,
            message_id=reserve_user_data['message_id']
        )
    except BadRequest as e:
        reserve_hl_logger.error(e)

    message = await send_msg_get_phone(update, context)

    reserve_user_data['message_id'] = message.message_id
    state = 'PHONE'
    context.user_data['STATE'] = state
    return state


async def phone_confirm(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Обработчик подтверждения ранее введенного телефона (inline-button).
    Работает в двух состояниях:
    - PHONE: подставляет телефон и переходит к CHILDREN (как в get_phone)
    - PHONE_FOR_WAITING: подставляет телефон и оформляет запись в лист ожидания
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)

    await query.edit_message_text(update.effective_message.text + '\nДа')

    data = query.data
    phone = None
    if '|' in data:
        phone = data.split('|', maxsplit=1)[1]

    state = context.user_data.get('STATE')
    reserve_user_data = context.user_data['reserve_user_data']
    if not phone:
        message = await request_phone_number(update, context)
        reserve_user_data['message_id'] = message.message_id
        return state

    if state == 'PHONE_FOR_WAITING':
        # Лист ожидания: отправляем сразу
        await send_admin_info_add_list_wait(context, phone)

        text_user = ('Вы добавлены в лист ожидания, '
                     'если место освободится, то с вами свяжутся. '
                     'Если у вас есть вопросы, вы можете связаться с Администратором:\n'
                     f"{context.bot_data['admin']['contacts']}\n\n")
        use_command_text = 'Используйте команды:\n'
        reserve_text = (f'/{COMMAND_DICT['RESERVE'][0]} - для повторного '
                        f'резервирования свободных мест на мероприятие\n')
        text = text_user + use_command_text + reserve_text
        await query.edit_message_text(text)

        state = ConversationHandler.END
        context.user_data['STATE'] = state
        context.user_data['conv_hl_run'] = False
        return state

    if state == 'PHONE':
        # Удалим клавиатуру с предыдущего сообщения запроса телефона
        try:
            await context.bot.edit_message_reply_markup(
                update.effective_chat.id,
                message_id=reserve_user_data['message_id']
            )
        except BadRequest as e:
            reserve_hl_logger.error(e)

        message = await send_msg_get_child(update, context)

        reserve_user_data['client_data']['phone'] = phone
        reserve_user_data['message_id'] = message.message_id
        state = 'CHILDREN'
        context.user_data['STATE'] = state
        return state

    # Иначе остаемся в текущем состоянии
    return state


async def child_confirm(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Обработчик подтверждения ранее введенного имени (inline-button).
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)

    await query.edit_message_text(update.effective_message.text + '\nДа')

    data = query.data
    child = None
    if '|' in data:
        child = data.split('|', maxsplit=1)[1]
    processed_data_on_children = [item.split() for item in child.split('\n')]

    reserve_user_data = context.user_data['reserve_user_data']
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    client_data = reserve_user_data['client_data']
    client_data['data_children'] = processed_data_on_children
    reserve_user_data['original_child_text'] = child

    command = context.user_data.get('command', False)
    if '_admin' in command:
        schedule_event_id = reserve_user_data['choose_schedule_event_id']
        await get_schedule_event_ids_studio(context)
        await update.effective_chat.send_action(ChatAction.TYPING)

        text = 'Создаю новые билеты в бд...'
        reserve_hl_logger.info(text)
        message = await update.effective_chat.send_message(text)
        ticket_ids = await create_tickets_and_people(
            update, context, TicketStatus.CREATED)

        text += '\nЗаписываю новый билет в клиентскую базу...'
        try:
            await message.edit_text(text)
        except TimedOut as e:
            reserve_hl_logger.error(e)
            reserve_hl_logger.info(text)
        sheet_id_domik = context.config.sheets.sheet_id_domik
        chat_id = update.effective_chat.id
        base_ticket_dto = chose_base_ticket.to_dto()
        ticket_status_value = str(TicketStatus.CREATED.value)
        reserve_user_data = context.user_data['reserve_user_data']
        try:
            await publish_write_client_reserve(
                sheet_id_domik,
                reserve_user_data,
                chat_id,
                base_ticket_dto,
                ticket_status_value
            )
        except Exception as e:
            reserve_hl_logger.exception(
                f'Failed to publish gspread task, fallback to direct call: {e}')
            res = await write_client_reserve(sheet_id_domik,
                                             reserve_user_data,
                                             chat_id,
                                             base_ticket_dto,
                                             ticket_status_value)
            if res == 0:
                await context.bot.send_message(
                    chat_id=context.config.bot.developer_chat_id,
                    text=f'Не записался билет {ticket_ids} в клиентскую базу')

        text += '\nУменьшаю кол-во свободных мест...'
        try:
            await message.edit_text(text)
        except TimedOut as e:
            reserve_hl_logger.error(e)
            reserve_hl_logger.info(text)
        result = await decrease_free_seat(
            context, schedule_event_id, chose_base_ticket_id)
        if not result:
            for ticket_id in ticket_ids:
                await update_ticket_db_and_gspread(context,
                                                   ticket_id,
                                                   status=TicketStatus.CANCELED)
            text += ('\nНе уменьшились свободные места'
                     '\nНовый билет отменен'
                     '\nНеобходимо повторить резервирование заново')
            try:
                await message.edit_text(text)
            except TimedOut as e:
                reserve_hl_logger.error(e)
                reserve_hl_logger.info(text)
            context.user_data['conv_hl_run'] = False
            await clean_context_on_end_handler(reserve_hl_logger, context)
            return ConversationHandler.END

        text += '\nПоследняя проверка...'
        try:
            await message.edit_text(text)
        except TimedOut as e:
            reserve_hl_logger.error(e)
            reserve_hl_logger.info(text)
        await processing_successful_payment(update, context)

        state = ConversationHandler.END
        context.user_data['conv_hl_run'] = False
    else:
        state = await create_and_send_payment(update, context)
        if state is None:
            state = 'PAID'
    context.user_data['STATE'] = state
    return state


async def _publish_write_client_list_waiting(sheet_id_domik,
                                             context: 'ContextTypes.DEFAULT_TYPE'):
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    user = context.user_data['user']
    user_id = user.id
    username = user.username
    full_name = user.full_name
    phone = reserve_user_data['client_data']['phone']
    ctx = {
        'user_id': user_id,
        'username': username,
        'full_name': full_name,
        'phone': phone,
        'schedule_event_id': schedule_event_id
    }
    try:
        await publish_write_client_list_waiting(sheet_id_domik, ctx)
    except Exception as e:
        reserve_hl_logger.exception(
            f"Failed to publish gspread task, fallback to direct call: {e}")
        await write_client_list_waiting(sheet_id_domik, ctx)


async def get_phone_for_waiting(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    reserve_user_data = context.user_data['reserve_user_data']

    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        message = await request_phone_number(update, context)
        reserve_user_data['message_id'] = message.message_id
        return context.user_data['STATE']

    await send_admin_info_add_list_wait(context, phone)

    text = ('Вы добавлены в лист ожидания.\n'
            'Если место освободится, то мы с вами свяжемся.\n'
            'Если вам подходят разные даты и время, то '
            'запишитесь пожалуйста на каждое мероприятие\n\n'
            'Если у вас есть вопросы, вы можете написать их в '
            'свободной форме боту или связаться с Администратором:\n'
            f'{context.bot_data['admin']['contacts']}\n\n')
    use_command_text = 'Используйте команды:\n'
    reserve_text = (f'/{COMMAND_DICT['RESERVE'][0]} - для повторного '
                    f'резервирования свободных мест на мероприятие\n')
    await update.effective_chat.send_message(
        text=text + use_command_text + reserve_text
    )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    context.user_data['conv_hl_run'] = False
    return state


async def send_admin_info_add_list_wait(context: 'ContextTypes.DEFAULT_TYPE',
                                        phone: str):
    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['client_data']['phone'] = phone
    text = reserve_user_data['text_select_event'] + '+7' + phone

    user = context.user_data['user']
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Лист ожидания', None))
    text = (f'#Лист_ожидания\n'
            f'Пользователь @{user.username} {user.full_name}\n'
            f'Запросил добавление в лист ожидания\n' + text)
    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=text,
        message_thread_id=thread_id
    )
    sheet_id_domik = context.config.sheets.sheet_id_domik
    await _publish_write_client_list_waiting(sheet_id_domik, context)

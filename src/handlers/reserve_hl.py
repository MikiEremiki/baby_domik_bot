import logging
import pprint
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.error import TimedOut
from telegram.ext import ContextTypes, ConversationHandler, TypeHandler
from telegram.constants import ChatType, ChatAction

from db import db_postgres
from db.db_googlesheets import decrease_free_seat
from db.db_postgres import get_schedule_theater_base_tickets
from db.enum import TicketStatus
from handlers import init_conv_hl_dialog, check_user_db
from handlers.email_hl import check_email_and_update_user
from handlers.sub_hl import (
    request_phone_number,
    send_breaf_message,
    send_message_about_list_waiting,
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
    get_full_name_event, render_text_for_choice_time,
    get_formatted_date_and_time_of_event,
    create_event_names_text, get_events_for_time_hl,
    get_type_event_ids_by_command, clean_context,
    add_clients_data_to_text, add_qty_visitors_to_text,
    filter_schedule_event_by_active, get_unique_months,
    clean_replay_kb_and_send_typing_action,
    create_str_info_by_schedule_event_id,
    get_schedule_event_ids_studio, clean_context_on_end_handler
)
from utilities.utl_googlesheets import update_ticket_db_and_gspread
from utilities.utl_ticket import (
    cancel_tickets_db_and_gspread, create_tickets_and_people)
from utilities.utl_kbd import (
    create_kbd_schedule_and_date, create_kbd_schedule,
    create_kbd_for_time_in_reserve, create_replay_markup,
    create_kbd_and_text_tickets_for_choice, create_kbd_for_time_in_studio,
    create_kbd_for_date_in_reserve, remove_intent_id, create_kbd_with_months,
    adjust_kbd, add_btn_back_and_cancel,
)
from settings.settings import (
    ADMIN_GROUP, COMMAND_DICT, SUPPORT_DATA, RESERVE_TIMEOUT
)

reserve_hl_logger = logging.getLogger('bot.reserve_hl')


async def choice_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю список месяцев.

    С сообщением передается inline клавиатура для выбора подходящего варианта
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

    type_event_ids = await get_type_event_ids_by_command(command)
    schedule_events = await db_postgres.get_schedule_events_by_type_actual(
        context.session, type_event_ids)
    schedule_events = await filter_schedule_event_by_active(schedule_events)
    months = get_unique_months(schedule_events)
    message = await clean_replay_kb_and_send_typing_action(update)
    text = 'Выберите месяц'
    keyboard = await create_kbd_with_months(months)
    keyboard = adjust_kbd(keyboard, 1)
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        add_back_btn=False
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

    state = 'MONTH'
    schedule_event_ids = [item.id for item in schedule_events]
    state_data = context.user_data['reserve_user_data'][state] = {}
    state_data['schedule_event_ids'] = schedule_event_ids
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    if context.user_data.get('command', False) and query:
        await query.answer()
        await query.delete_message()
    return state


async def choice_show_or_date(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Функция отправляет пользователю список спектаклей с датами.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state DATE
    """
    query = update.callback_query

    number_of_month_str = query.data

    reserve_hl_logger.info(f'Пользователь выбрал месяц: {number_of_month_str}')
    reserve_user_data = context.user_data['reserve_user_data']
    state = context.user_data['STATE']
    schedule_event_ids = reserve_user_data[state]['schedule_event_ids']
    schedule_events = await db_postgres.get_schedule_events_by_ids(
        context.session, schedule_event_ids)

    try:
        enum_theater_events, schedule_events_filter_by_month = await (
            get_theater_and_schedule_events_by_month(context,
                                                     schedule_events,
                                                     number_of_month_str)
        )
    except ValueError as e:
        reserve_hl_logger.error(e)
        return

    text_legend = context.bot_data['texts']['text_legend']

    december = '12'
    if number_of_month_str == december:
        text = '<b>Выберите мероприятие\n</b>' + text_legend
        text = await create_event_names_text(enum_theater_events, text)

        keyboard = await create_kbd_schedule(enum_theater_events)

        state = 'SHOW'
    else:
        text = '<b>Выберите мероприятие и дату\n</b>' + text_legend
        text = await create_event_names_text(enum_theater_events, text)

        keyboard = await create_kbd_schedule_and_date(
            schedule_events_filter_by_month, enum_theater_events)

        if context.user_data['command'] == 'list_wait':
            state = 'LIST_WAIT'
        else:
            state = 'DATE'

    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='MONTH',
        size_row=2
    )
    photo = (
        context.bot_data
        .get('afisha', {})
        .get(int(number_of_month_str), False)
    )
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
            message_thread_id=update.callback_query.message.message_thread_id,
        )

    reserve_user_data['number_of_month_str'] = number_of_month_str
    schedule_event_ids = [item.id for item in schedule_events_filter_by_month]
    state_data = context.user_data['reserve_user_data'][state] = {}
    state_data['schedule_event_ids'] = schedule_event_ids

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)
    await query.delete_message()
    return state


async def choice_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю варианты
    времени и кол-во свободных мест

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state TIME
    """
    query = update.callback_query

    _, callback_data = remove_intent_id(query.data)
    theater_event_id = int(callback_data)
    reserve_user_data = context.user_data['reserve_user_data']
    number_of_month_str = reserve_user_data['number_of_month_str']

    state = context.user_data['STATE']
    schedule_event_ids = reserve_user_data[state]['schedule_event_ids']
    theater_event = await db_postgres.get_theater_event(
        context.session, theater_event_id)
    schedule_events = await db_postgres.get_schedule_events_by_ids_and_theater(
        context.session, schedule_event_ids, [theater_event_id])

    keyboard = await create_kbd_for_date_in_reserve(schedule_events)
    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='SHOW',
        size_row=2
    )

    flag_gift = False
    flag_christmas_tree = False
    flag_santa = False

    for event in schedule_events:
        if event.flag_gift:
            flag_gift = True
        if event.flag_christmas_tree:
            flag_christmas_tree = True
        if event.flag_santa:
            flag_santa = True
    full_name = get_full_name_event(theater_event.name,
                                    theater_event.flag_premier,
                                    theater_event.min_age_child,
                                    theater_event.max_age_child,
                                    theater_event.duration)
    text = (f'Вы выбрали мероприятие:\n'
            f'<b>{full_name}</b>\n'
            f'<i>Выберите удобную дату</i>\n\n')
    if flag_gift:
        text += f'{SUPPORT_DATA['Подарок'][0]} - {SUPPORT_DATA['Подарок'][1]}\n'
    if flag_christmas_tree:
        text += f'{SUPPORT_DATA['Елка'][0]} - {SUPPORT_DATA['Елка'][1]}\n'
    if flag_santa:
        text += f'{SUPPORT_DATA['Дед'][0]} - {SUPPORT_DATA['Дед'][1]}\n'

    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)

    photo = (
        context.bot_data
        .get('afisha', {})
        .get(int(number_of_month_str), False)
    )
    if update.effective_chat.type == ChatType.PRIVATE and photo:
        await query.edit_message_caption(
            caption=text,
            reply_markup=reply_markup,
        )
    else:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
        )

    if context.user_data['command'] == 'list_wait':
        state = 'LIST_WAIT'
    else:
        state = 'DATE'

    schedule_event_ids = [item.id for item in schedule_events]
    state_data = context.user_data['reserve_user_data'][state] = {}
    state_data['schedule_event_ids'] = schedule_event_ids

    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю варианты
    времени и кол-во свободных мест

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state TIME
    """
    query = update.callback_query
    _, callback_data = remove_intent_id(query.data)
    theater_event_id, selected_date = callback_data.split('|')

    schedule_events, theater_event = await get_events_for_time_hl(
        theater_event_id, selected_date, context)

    check_command_studio = check_entered_command(context, 'studio')

    if check_command_studio:
        keyboard = await create_kbd_for_time_in_studio(schedule_events)
    else:
        keyboard = await create_kbd_for_time_in_reserve(schedule_events)
    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='DATE',
        size_row=1
    )

    text = await render_text_for_choice_time(theater_event, schedule_events)
    if update.effective_chat.id == ADMIN_GROUP:
        text += 'Выберите время'
    else:
        text += ('<b>Выберите удобное время</b>\n\n'
                 '<i>Вы также можете выбрать вариант с 0 кол-вом мест '
                 'для записи в лист ожидания на данное время</i>\n\n'
                 'Кол-во свободных мест:\n')

        if check_command_studio:
            text += '⬇️<i>Время</i> | <i>Детских</i>⬇️'
        else:
            text += '⬇️<i>Время</i> | <i>Детских</i> | <i>Взрослых</i>⬇️'

    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)
    await query.delete_message()
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.callback_query.message.message_thread_id
    )

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['choose_theater_event_id'] = theater_event.id

    if context.user_data.get('command', False) == 'list':
        state = 'LIST'
    else:
        state = 'TIME'
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_option_of_reserve(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю,
    дате, времени и варианты бронирования

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state ORDER
    """
    query = update.callback_query
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

    text_select_event = await create_str_info_by_schedule_event_id(
        context, choice_event_id)

    reserve_user_data['text_select_event'] = text_select_event

    check_command_reserve = check_entered_command(context, 'reserve')
    only_child = False
    text = (f'Кол-во свободных мест: '
            f'<i>'
            f'{schedule_event.qty_adult_free_seat} взр'
            f' | '
            f'{schedule_event.qty_child_free_seat} дет'
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
        await query.answer()
        await message.edit_text(
            'Готовлю информацию для записи в лист ожидания...')
        await send_message_about_list_waiting(update, context)

        state = 'CHOOSING'
        context.user_data['STATE'] = state
        return state

    await message.edit_text('Формирую список доступных билетов...')

    text = text_select_event + text
    text += '\n<b>Выберите подходящий вариант бронирования:</b>\n'

    base_tickets_filtered = []
    for i, ticket in enumerate(base_tickets):
        check_ticket = check_available_ticket_by_free_seat(schedule_event,
                                                           theater_event,
                                                           type_event,
                                                           ticket,
                                                           only_child=only_child)
        if not ticket.flag_active or (check_command and not check_ticket):
            continue
        base_tickets_filtered.append(ticket)

    date_for_price = datetime.today()
    keyboard, text = await create_kbd_and_text_tickets_for_choice(
        context,
        text,
        base_tickets_filtered,
        schedule_event,
        theater_event,
        date_for_price
    )
    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='TIME',
        size_row=5
    )

    text += ('__________\n'
             '<i>Если вы хотите оформить несколько билетов, '
             'то каждая бронь оформляется отдельно.</i>\n'
             '__________\n'
             '<i>МНОГОДЕТНЫМ:\n'
             '1. Пришлите удостоверение многодетной семьи администратору\n'
             '2. Дождитесь ответа\n'
             '3. Оплатите билет со скидкой 10% от цены, которая указана выше</i>')

    await message.delete()
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['reserve_user_data']['date_for_price'] = date_for_price

    state = 'TICKET'
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if check_command:
        only_child = False
    check_command = check_entered_command(context, 'studio')
    if check_command:
        only_child = True

    check_ticket = check_available_ticket_by_free_seat(schedule_event,
                                                       theater_event,
                                                       type_event,
                                                       chose_base_ticket,
                                                       only_child=only_child)
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
    await send_breaf_message(update, context)

    state = 'FORMA'
    context.user_data['STATE'] = state
    return state


async def get_name_adult(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    reserve_user_data = context.user_data['reserve_user_data']

    await context.bot.edit_message_reply_markup(
        update.effective_chat.id,
        message_id=reserve_user_data['message_id']
    )
    text = update.effective_message.text

    keyboard = [add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
        add_back_btn=False)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.effective_chat.send_message(
        text='<b>Напишите номер телефона</b>',
        reply_markup=reply_markup
    )

    reserve_user_data['client_data']['name_adult'] = text
    reserve_user_data['message_id'] = message.message_id
    state = 'PHONE'
    context.user_data['STATE'] = state
    return state


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    base_ticket_id = context.user_data['reserve_user_data'][
        'chose_base_ticket_id']
    base_ticket = await db_postgres.get_base_ticket(context.session,
                                                    base_ticket_id)
    if base_ticket.quality_of_children > 0:
        keyboard = [add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=False)]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = """<b>Напишите, имя и сколько полных лет ребенку</b>
__________
Например:
Сергей 2
Юля 3
__________
<i> - Если детей несколько, напишите всех в одном сообщении
 - Один ребенок = одна строка
 - Не используйте дополнительные слова и пунктуацию, кроме тех, что указаны в примерах</i>"""
    else:
        text = 'Нажмите <b>Далее</b>'
        btn = InlineKeyboardButton(
            'Далее',
            callback_data='Далее'
        )
        keyboard = [[btn]]
        reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['reserve_user_data']['client_data']['phone'] = phone
    context.user_data['reserve_user_data']['message_id'] = message.message_id
    state = 'CHILDREN'
    context.user_data['STATE'] = state
    return state


async def get_name_children(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    reserve_user_data = context.user_data['reserve_user_data']

    await context.bot.edit_message_reply_markup(
        update.effective_chat.id,
        message_id=reserve_user_data['message_id']
    )
    await update.effective_chat.send_action(ChatAction.TYPING)

    try:
        chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
        chose_base_ticket = await db_postgres.get_base_ticket(
            context.session, chose_base_ticket_id)
    except KeyError as e:
        reserve_hl_logger.error(e)
        await update.effective_chat.send_message(
            'Произошел технический сбой.\n'
            f'Повторите, пожалуйста, бронирование еще раз\n'
            f'/{COMMAND_DICT['RESERVE'][0]}\n'
            'Приносим извинения за предоставленные неудобства.'
        )
        state = ConversationHandler.END
        context.user_data['STATE'] = state
        context.user_data['conv_hl_run'] = False
        return state

    if chose_base_ticket.quality_of_children > 0:
        text = update.effective_message.text
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
        keyboard = [add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=False)]
        reply_markup = InlineKeyboardMarkup(keyboard)

        result = await check_input_text(update.effective_message.text)
        if not result:
            keyboard = [add_btn_back_and_cancel(
                context.user_data['postfix_for_cancel'] + '|',
                add_back_btn=False)]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = await update.effective_chat.send_message(
                text=wrong_input_data_text,
                reply_markup=reply_markup,
            )
            reserve_user_data['message_id'] = message.message_id
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
        message = await update.effective_chat.send_message(text)
        ticket_ids = await create_tickets_and_people(
            update, context, TicketStatus.CREATED)

        text += '\nЗаписываю новый билет в клиентскую базу...'
        await message.edit_text(text)
        await write_client_reserve(context,
                                   update.effective_chat.id,
                                   chose_base_ticket,
                                   TicketStatus.CREATED.value)

        text += '\nУменьшаю кол-во свободных мест...'
        await message.edit_text(text)
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
            await message.edit_text(text)
            context.user_data['conv_hl_run'] = False
            await clean_context_on_end_handler(reserve_hl_logger, context)
            return ConversationHandler.END

        text += '\nПоследняя проверка...'
        try:
            await message.edit_text(text)
        except TimedOut as e:
            reserve_hl_logger.error(e)
        await processing_successful_payment(update, context)

        state = ConversationHandler.END
        context.user_data['conv_hl_run'] = False
    else:
        await create_and_send_payment(update, context)
        state = 'PAID'
    context.user_data['STATE'] = state
    return state


async def forward_photo_or_file(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await remove_button_from_last_message(update, context)

    await processing_successful_payment(update, context)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    context.user_data['conv_hl_run'] = False
    return state


async def processing_successful_notification(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await processing_successful_payment(update, context)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    context.user_data['conv_hl_run'] = False
    return state


async def conversation_timeout(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Informs the user that the operation has timed out,
    calls :meth:`remove_reply_markup` and ends the conversation.
    :return:
        int: :attr:`telegram.ext.ConversationHandler.END`.
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
        context: ContextTypes.DEFAULT_TYPE
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

    await query.edit_message_text('Загружаю данные покупателей')

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
    await query.answer()
    context.user_data['conv_hl_run'] = False
    return state


async def write_list_of_waiting(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        text='Напишите контактный номер телефона',
        reply_markup=ReplyKeyboardRemove()
    )
    state = 'PHONE_FOR_WAITING'
    context.user_data['STATE'] = state
    return state


async def get_phone_for_waiting(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    reserve_user_data = context.user_data['reserve_user_data']

    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        message = await request_phone_number(update, context)
        reserve_user_data['message_id'] = message.message_id
        return context.user_data['STATE']

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['client_data']['phone'] = phone
    text = reserve_user_data['text_select_event'] + '+7' + phone

    user = context.user_data['user']
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Лист ожидания', None))
    text = f'#Лист_ожидания\n' \
           f'Пользователь @{user.username} {user.full_name}\n' \
           f'Запросил добавление в лист ожидания\n' + text
    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=text,
        message_thread_id=thread_id
    )
    write_client_list_waiting(context)
    await update.effective_chat.send_message(
        text='Вы добавлены в лист ожидания, '
             'если место освободится, то с вами свяжутся. '
             'Если у вас есть вопросы, вы можете связаться с Администратором:\n'
             f'{context.bot_data['admin']['contacts']}'
    )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    context.user_data['conv_hl_run'] = False
    return state

import logging
import pprint
from datetime import datetime

from telegram.error import BadRequest
from telegram.ext import ContextTypes, ConversationHandler, TypeHandler
from telegram import (
    Update,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ChatType, ChatAction

from db import db_postgres
from db.db_postgres import get_schedule_theater_base_tickets
from db.enum import TicketStatus
from handlers import init_conv_hl_dialog, check_user_db
from handlers.email_hl import check_email_and_update_user
from handlers.sub_hl import (
    request_phone_number,
    send_breaf_message, send_filtered_schedule_events,
    send_message_about_list_waiting,
    remove_button_from_last_message,
    create_and_send_payment, processing_successful_payment,
    get_theater_and_schedule_events_by_month,
)
from db.db_googlesheets import (
    load_clients_data,
    decrease_free_and_increase_nonconfirm_seat,
)
from api.googlesheets import write_client_list_waiting, write_client_reserve
from utilities.utl_check import (
    check_available_seats, check_available_ticket_by_free_seat,
    check_entered_command, check_topic, check_input_text
)
from utilities.utl_func import (
    extract_phone_number_from_text, add_btn_back_and_cancel,
    set_back_context, check_phone_number,
    create_replay_markup_for_list_of_shows,
    get_full_name_event, render_text_for_choice_time,
    get_formatted_date_and_time_of_event,
    create_event_names_text, get_events_for_time_hl,
    get_type_event_ids_by_command, get_emoji, clean_context,
    add_clients_data_to_text, add_qty_visitors_to_text
)
from utilities.utl_kbd import (
    adjust_kbd,
    create_kbd_schedule_and_date, create_kbd_schedule,
    create_kbd_for_time_in_reserve, create_replay_markup,
    create_kbd_and_text_tickets_for_choice, create_kbd_for_time_in_studio
)
from settings.settings import (
    ADMIN_GROUP, COMMAND_DICT, SUPPORT_DATA, RESERVE_TIMEOUT
)
from utilities.utl_ticket import cancel_tickets

reserve_hl_logger = logging.getLogger('bot.reserve_hl')


async def choice_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю список месяцев.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state MONTH
    """
    query = update.callback_query
    if context.user_data.get('command', False) and query:
        state = context.user_data['STATE']
        await query.answer()
        await query.delete_message()
    else:
        state = await init_conv_hl_dialog(update, context)
        await check_user_db(update, context)

    if update.effective_message.is_topic_message:
        is_correct_topic = await check_topic(update, context)
        if not is_correct_topic:
            return ConversationHandler.END

    command = context.user_data['command']
    postfix_for_cancel = command
    context.user_data['postfix_for_cancel'] = postfix_for_cancel

    user = context.user_data.setdefault('user', update.effective_user)
    reserve_hl_logger.info(f'Пользователь начал выбор месяца: {user}')

    type_event_ids = await get_type_event_ids_by_command(command)
    reply_markup, text = await send_filtered_schedule_events(update,
                                                             context,
                                                             type_event_ids)

    state = 'MONTH'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
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
    await query.answer()
    await query.delete_message()

    number_of_month_str = query.data

    reserve_hl_logger.info(f'Пользователь выбрал месяц: {number_of_month_str}')
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_ids = reserve_user_data['schedule_event_ids']
    schedule_events = await db_postgres.get_schedule_events_by_ids(
        context.session, schedule_event_ids)

    enum_theater_events, schedule_events_filter_by_month = await (
        get_theater_and_schedule_events_by_month(context,
                                                 schedule_events,
                                                 number_of_month_str)
    )

    text_legend = (
        '📍 - Премьера\n'
        '👶🏼 - Рекомендованный возраст\n'
        '⏳ - Продолжительность\n'
        '\n'
    )

    december = '12'
    if number_of_month_str == december:
        text = '<b>Выберите мероприятие\n</b>' + text_legend
        text = await create_event_names_text(enum_theater_events, text)

        # TODO Сделать клавиатуру без дат, только название
        keyboard = await create_kbd_schedule(enum_theater_events)
        keyboard = adjust_kbd(keyboard, 5)
        keyboard.append(add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back='MONTH'
        ))
        reply_markup = InlineKeyboardMarkup(keyboard)

        state = 'SHOW'
        set_back_context(context, state, text, reply_markup)
    else:
        text = '<b>Выберите мероприятие и дату\n</b>' + text_legend
        text = await create_event_names_text(enum_theater_events, text)

        keyboard = await create_kbd_schedule_and_date(
            schedule_events_filter_by_month, enum_theater_events)
        reply_markup = await create_replay_markup(
            keyboard,
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back='MONTH',
            size_row=2
        )

        if context.user_data['command'] == 'list_wait':
            state = 'LIST_WAIT'
        else:
            state = 'DATE'
        set_back_context(context, state, text, reply_markup)

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

    context.user_data['STATE'] = state
    return state


async def choice_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю варианты
    времени и кол-во свободных мест

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state TIME
    """
    # TODO Переписать большую часть функции, содержит устаревший код
    query = update.callback_query
    await query.answer()

    number_of_show = int(query.data)
    reserve_user_data = context.user_data['reserve_user_data']
    dict_of_date_show = reserve_user_data['dict_of_date_show']
    dict_of_name_show_flip = reserve_user_data['dict_of_name_show_flip']
    number_of_month_str = reserve_user_data['number_of_month_str']
    dict_of_shows = context.user_data['common_data']['dict_of_shows']
    name_of_show = dict_of_name_show_flip[number_of_show]

    reply_markup = create_replay_markup_for_list_of_shows(
        dict_of_date_show,
        ver=3,
        add_cancel_btn=True,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='SHOW',
        number_of_month=number_of_month_str,
        number_of_show=number_of_show,
        dict_of_events_show=dict_of_shows
    )

    flag_gift = False
    flag_christmas_tree = False
    flag_santa = False

    for event in dict_of_shows.values():
        if name_of_show == event['name_show']:
            if event['flag_gift']:
                flag_gift = True
            if event['flag_christmas_tree']:
                flag_christmas_tree = True
            if event['flag_santa']:
                flag_santa = True

    text = (f'Вы выбрали мероприятие:\n'
            f'<b>{name_of_show}</b>\n'
            f'<i>Выберите удобную дату</i>\n\n')
    if flag_gift:
        text += f'{SUPPORT_DATA['Подарок'][0]} - {SUPPORT_DATA['Подарок'][1]}\n'
    if flag_christmas_tree:
        text += f'{SUPPORT_DATA['Елка'][0]} - {SUPPORT_DATA['Елка'][1]}\n'
    if flag_santa:
        text += f'{SUPPORT_DATA['Дед'][0]} - {SUPPORT_DATA['Дед'][1]}\n'

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
    set_back_context(context, state, text, reply_markup)
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
    await query.answer()
    try:
        await query.delete_message()
    except BadRequest as e:
        if e.message == 'Message to delete not found':
            reserve_hl_logger.error('Скорее всего нажали несколько раз')
        return

    schedule_events, theater_event = await get_events_for_time_hl(update,
                                                                  context)

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
    set_back_context(context, state, text, reply_markup)
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
    await query.answer()
    await query.edit_message_text('Загружаю данные по билетам...')

    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)

    choice_event_id = int(query.data)

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['choose_schedule_event_id'] = choice_event_id

    base_tickets, schedule_event, theater_event = await get_schedule_theater_base_tickets(
        context, choice_event_id)

    date_event, time_event = await get_formatted_date_and_time_of_event(
        schedule_event)
    full_name = get_full_name_event(theater_event.name,
                                    theater_event.flag_premier,
                                    theater_event.min_age_child,
                                    theater_event.max_age_child,
                                    theater_event.duration)

    text_emoji = await get_emoji(schedule_event)
    text_select_event = (f'Вы выбрали мероприятие:\n'
                         f'<b>{full_name}\n'
                         f'{date_event}\n'
                         f'{time_event}</b>\n')
    text_select_event += f'{text_emoji}\n' if text_emoji else ''

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
        await query.edit_message_text(
            'Готовлю информацию для записи в лист ожидания...')
        await send_message_about_list_waiting(update, context)

        state = 'CHOOSING'
        context.user_data['STATE'] = state
        return state

    await query.edit_message_text('Формирую список доступных билетов...')

    text = text_select_event + text
    text += '<b>Выберите подходящий вариант бронирования:</b>\n'

    base_tickets_filtered = []
    for i, ticket in enumerate(base_tickets):
        check_ticket = check_available_ticket_by_free_seat(schedule_event,
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

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['reserve_user_data']['date_for_price'] = date_for_price

    state = 'TICKET'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        await check_email_and_update_user(update, context)
    else:
        await query.answer()
        await query.delete_message()

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

    check_command = check_entered_command(context, 'reserve')
    if check_command:
        only_child = False
    check_command = check_entered_command(context, 'studio')
    if check_command:
        only_child = True

    check_ticket = check_available_ticket_by_free_seat(schedule_event,
                                                       chose_base_ticket,
                                                       only_child=only_child)

    if check_command and not check_ticket:
        await message.delete()
        await send_message_about_list_waiting(update, context)

        state = 'CHOOSING'
        context.user_data['STATE'] = state
        return state

    reserve_hl_logger.info('Получено разрешение на бронирование')

    result = await decrease_free_and_increase_nonconfirm_seat(context,
                                                              schedule_event_id,
                                                              chose_base_ticket_id)

    if not result:
        state = 'TICKET'

        reserve_hl_logger.error(f'Бронирование в авто-режиме не сработало')

        keyboard = [add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back='TIME')]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = ('К сожалению произошла непредвиденная ошибка\n'
                'Нажмите "Назад" и выберите время повторно.\n'
                'Если ошибка повторяется свяжитесь с Администратором:\n'
                f'{context.bot_data['admin']['contacts']}')
        await message.edit_text(
            text=text,
            reply_markup=reply_markup
        )
        context.user_data['STATE'] = state
        return state

    await message.delete()
    await send_breaf_message(update, context)

    # Нужно на случай отмены пользователем
    choose_schedule_event_ids = [schedule_event_id]
    reserve_user_data['choose_schedule_event_ids'] = choose_schedule_event_ids

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

    keyboard = [add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
        add_back_btn=False)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.effective_chat.send_message(
        text="""<b>Напишите, имя и сколько полных лет ребенку</b>
__________
Например:
Сергей 2
Юля 3
__________
<i> - Если детей несколько, напишите всех в одном сообщении
 - Один ребенок = одна строка
 - Не используйте дополнительные слова и пунктуацию, кроме тех, что указаны в примерах</i>""",
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

    text = update.effective_message.text
    wrong_input_data_text = (
        'Проверьте, что указали дату или возраст правильно\n'
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

    reserve_user_data = context.user_data['reserve_user_data']
    client_data = reserve_user_data['client_data']
    client_data['data_children'] = processed_data_on_children
    reserve_user_data['original_input_text'] = update.effective_message.text

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'отправил:',
        ],
    ))
    reserve_hl_logger.info(client_data)

    command = context.user_data.get('command', False)
    if '_admin' in command:
        studio = context.bot_data['studio']
        schedule_event_id = reserve_user_data['choose_schedule_event_id']
        price = reserve_user_data['chose_price']
        choose_schedule_event_ids = [schedule_event_id]

        ticket_ids = []
        if chose_base_ticket.flag_season_ticket:
            for v in studio['Театральный интенсив']:
                if schedule_event_id in v:
                    choose_schedule_event_ids = v
        for event_id in choose_schedule_event_ids:
            ticket = await db_postgres.create_ticket(
                context.session,
                base_ticket_id=chose_base_ticket.base_ticket_id,
                price=price,
                schedule_event_id=event_id,
                status=TicketStatus.CREATED,
            )
            ticket_ids.append(ticket.id)

        reserve_user_data['ticket_ids'] = ticket_ids
        reserve_user_data['choose_schedule_event_ids'] = choose_schedule_event_ids

        people_ids = await db_postgres.create_people(context.session,
                                                     update.effective_user.id,
                                                     client_data)
        for ticket_id in ticket_ids:
            await db_postgres.attach_user_and_people_to_ticket(context.session,
                                                               ticket_id,
                                                               update.effective_user.id,
                                                               people_ids)
        write_client_reserve(context,
                             update.effective_chat.id,
                             chose_base_ticket,
                             TicketStatus.APPROVED.value)

        await processing_successful_payment(update, context)

        state = ConversationHandler.END
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
    return state


async def processing_successful_notification(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text('Платеж успешно обработан')

    await processing_successful_payment(update, context)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
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

    await cancel_tickets(update, context)

    await clean_context(context)

    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)


async def send_clients_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)

    event_id = int(query.data)
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    theater_event = await db_postgres.get_theater_event(
        context.session, schedule_event.theater_event_id)

    full_name = get_full_name_event(theater_event.name,
                                    theater_event.flag_premier,
                                    theater_event.min_age_child,
                                    theater_event.max_age_child,
                                    theater_event.duration)
    date_event, time_event = await get_formatted_date_and_time_of_event(
        schedule_event)

    clients_data, name_column = load_clients_data(event_id)
    text = f'#Показ #event_id_{event_id}\n'
    text += (f'Список людей на\n'
             f'{full_name}\n'
             f'{date_event}\n'
             f'{time_event}\n')

    text = await add_qty_visitors_to_text(text, name_column, clients_data)

    text += await add_clients_data_to_text(text, clients_data, name_column)

    await query.edit_message_text(text)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
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
    return state

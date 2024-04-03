import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from api.googlesheets import get_quality_of_seats, write_data_for_reserve
from db import db_postgres
from db.db_googlesheets import load_show_info, load_list_show
from db.enum import TicketStatus
from handlers import init_conv_hl_dialog, check_user_db
from handlers.sub_hl import (
    get_chose_ticket_and_price, get_emoji_and_options_for_event)
from settings.settings import DICT_OF_EMOJI_FOR_BUTTON
from utilities.utl_func import add_btn_back_and_cancel, set_back_context

reserve_admin_hl_logger = logging.getLogger('bot.reserve_admin_hl')


async def event_selection_option(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    """
    init_conv_hl_dialog(update, context)
    await check_user_db(update, context)

    user = context.user_data.setdefault('user', update.effective_user)

    reserve_admin_hl_logger.info(
        f'Запущена команда бронирования администратором: {user}')

    text = 'Выбор показа по id или по параметрам?'

    keyboard = [
        [InlineKeyboardButton('по id', callback_data='id'),
         InlineKeyboardButton('по параметрам', callback_data='params')],
        add_btn_back_and_cancel(
            postfix_for_cancel='res_adm',
            add_back_btn=False
        )
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.message.message_thread_id
    )

    state = 1
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def enter_event_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    state = context.user_data['STATE']

    user = context.user_data['user']
    reserve_admin_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    text = 'Введите id события'
    reply_markup = InlineKeyboardMarkup([
        add_btn_back_and_cancel(
            postfix_for_cancel='res_adm',
            postfix_for_back=state,
            add_back_btn=True
        )
    ])
    message = await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
    )

    context.user_data['message'] = message.id

    state = 2
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_option_of_reserve(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await context.bot.delete_message(
        update.effective_chat.id,
        context.user_data['message'])
    event_id = update.effective_message.text
    message = await update.effective_chat.send_message('Загружаю данные')

    user = context.user_data['user']
    reserve_admin_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'ввел',
            event_id,
        ]
    ))

    event_info, name_column = load_show_info(int(event_id))
    list_of_tickets = context.bot_data['list_of_tickets']
    await message.edit_text('Данные загружены')

    text = ''
    keyboard = []
    list_btn_of_numbers = []
    for i, ticket in enumerate(list_of_tickets):
        text += (f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]} | {ticket.price} | '
                 f'{ticket.name}\n')
        key = ticket.base_ticket_id
        button_tmp = InlineKeyboardButton(
            text=str(i + 1),
            callback_data=str(key)
        )
        list_btn_of_numbers.append(button_tmp)

        # Позволяет управлять кол-вом кнопок в ряду
        # Максимальное кол-во кнопок в ряду равно 8
        if (i + 1) % 5 == 0:
            keyboard.append(list_btn_of_numbers)
            list_btn_of_numbers = []

    if len(list_btn_of_numbers):
        keyboard.append(list_btn_of_numbers)

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='res',
                                            postfix_for_back=1))
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text(text=text,
                            reply_markup=reply_markup)

    option, text_emoji = await get_emoji_and_options_for_event(event_info,
                                                               name_column)
    reserve_user_data = context.user_data['reserve_user_data']
    choose_event_info = reserve_user_data['choose_event_info']
    choose_event_info['option'] = option
    choose_event_info['text_emoji'] = text_emoji
    dict_of_shows: dict = load_list_show()
    show_id = int(event_info[name_column['show_id']])
    for key, item in dict_of_shows.items():
        if key == show_id:
            flag_indiv_cost = item['flag_indiv_cost']
            choose_event_info['flag_indiv_cost'] = flag_indiv_cost

    payment_data = context.user_data['reserve_admin_data']['payment_data']
    reserve_admin_hl_logger.info(f'Бронирование: {payment_data}')
    payment_data['event_id'] = event_id

    state = 'TICKET'
    context.user_data['STATE'] = state
    return state


async def start_forma_info(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    key_option_for_reserve = int(query.data)

    common_data = context.user_data['common_data']
    reserve_user_data = context.user_data['reserve_user_data']
    reserve_admin_data = context.user_data['reserve_admin_data']

    choose_event_info = reserve_user_data['choose_event_info']
    chose_ticket, price = await get_chose_ticket_and_price(
        choose_event_info,
        context,
        key_option_for_reserve,
        reserve_user_data
    )

    reserve_user_data['chose_price'] = price
    payment_data = reserve_admin_data['payment_data']
    payment_data['chose_ticket'] = chose_ticket
    event_id = payment_data['event_id']

    list_of_name_colum = [
        'qty_child_free_seat',
        'qty_adult_free_seat',
    ]
    (qty_child_free_seat_now,
     qty_adult_free_seat_now,
     ) = get_quality_of_seats(event_id,
                              list_of_name_colum)

    qty_child_free_seat_new = int(
        qty_child_free_seat_now) - int(
        chose_ticket.quality_of_children)
    qty_adult_free_seat_new = int(
        qty_adult_free_seat_now) - int(
        chose_ticket.quality_of_adult +
        chose_ticket.quality_of_add_adult)

    numbers = [
        qty_child_free_seat_new,
        qty_adult_free_seat_new,
    ]

    write_data_for_reserve(event_id, numbers, 3)

    ticket = await db_postgres.create_ticket(
        context.session,
        base_ticket_id=chose_ticket.base_ticket_id,
        price=price,
        schedule_event_id=event_id,
        status=TicketStatus.CREATED,
    )

    payment_data['ticket_id'] = ticket.id

    await query.edit_message_text(
        '<b>Напишите фамилию и имя (взрослого)</b>',
    )

    if common_data.get('dict_of_shows', False):
        common_data['dict_of_shows'].clear()
    if reserve_user_data.get('dict_of_name_show', False):
        reserve_user_data['dict_of_name_show'].clear()
    if reserve_user_data.get('dict_of_name_show_flip', False):
        reserve_user_data['dict_of_name_show_flip'].clear()
    if reserve_user_data.get('dict_of_date_show', False):
        reserve_user_data['dict_of_date_show'].clear()
    if reserve_user_data.get('dict_of_date_show', False):
        reserve_user_data['back'].clear()

    state = 'FORMA'
    context.user_data['STATE'] = state
    return state

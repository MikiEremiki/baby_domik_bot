import logging

from telegram import (
    Update,
    ReplyKeyboardRemove,
)
from telegram.ext import ContextTypes

from db.db_googlesheets import load_ticket_data, load_list_show
from utilities.googlesheets import (
    get_quality_of_seats,
    write_data_for_reserve
)

sub_hl_logger = logging.getLogger('bot.sub_hl')


async def request_phone_number(update, phone):
    await update.effective_chat.send_message(
        text=f'Возможно вы ошиблись, вы указали {phone} \n'
             'Напишите ваш номер телефона еще раз пожалуйста\n'
             'Идеальный пример из 10 цифр: 9991119090'
    )


async def send_and_del_message_to_remove_kb(update: Update):
    return await update.effective_chat.send_message(
        text='Загружаем данные',
        reply_markup=ReplyKeyboardRemove(),
        message_thread_id=update.message.message_thread_id
    )


async def write_old_seat_info(
        user,
        event_id,
        chose_ticket
):
    # Обновляем кол-во доступных мест
    list_of_name_colum = [
        'qty_child_free_seat',
        'qty_child_nonconfirm_seat',
        'qty_adult_free_seat',
        'qty_adult_nonconfirm_seat'
    ]
    (qty_child_free_seat_now,
     qty_child_nonconfirm_seat_now,
     qty_adult_free_seat_now,
     qty_adult_nonconfirm_seat_now
     ) = get_quality_of_seats(event_id,
                              list_of_name_colum)

    qty_child_free_seat_new = int(
        qty_child_free_seat_now) + int(chose_ticket.quality_of_children)
    qty_child_nonconfirm_seat_new = int(
        qty_child_nonconfirm_seat_now) - int(chose_ticket.quality_of_children)
    qty_adult_free_seat_new = int(
        qty_adult_free_seat_now) + int(chose_ticket.quality_of_adult +
                                       chose_ticket.quality_of_add_adult)
    qty_adult_nonconfirm_seat_new = int(
        qty_adult_nonconfirm_seat_now) - int(chose_ticket.quality_of_adult +
                                             chose_ticket.quality_of_add_adult)

    numbers = [
        qty_child_free_seat_new,
        qty_child_nonconfirm_seat_new,
        qty_adult_free_seat_new,
        qty_adult_nonconfirm_seat_new
    ]

    try:
        write_data_for_reserve(event_id, numbers)
    except TimeoutError:
        sub_hl_logger.error(": ".join(
            [
                f'Для пользователя {user} отклонение в '
                f'авто-режиме не сработало',
                'event_id для обновления',
                event_id,
            ]
        ))


async def update_ticket_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    context.bot_data['list_of_tickets'] = load_ticket_data()
    text = 'Билеты обновлены'
    await update.effective_chat.send_message(text)

    sub_hl_logger.info(text)
    for item in context.bot_data['list_of_tickets']:
        sub_hl_logger.info(f'{str(item)}')


async def update_show_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    context.bot_data['dict_show_data'] = load_list_show()
    text = 'Репертуар обновлен'
    await update.effective_chat.send_message(text)

    sub_hl_logger.info(text)
    for item in context.bot_data['dict_show_data']:
        sub_hl_logger.info(f'{str(item)}')


async def remove_inline_button(update: Update):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    return query

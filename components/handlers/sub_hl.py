import logging

from telegram import (
    Update,
    ReplyKeyboardRemove,
)

from utilities.googlesheets import (
    update_quality_of_seats,
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
        reply_markup=ReplyKeyboardRemove()
    )


async def write_old_seat_info(
        update: Update,
        user,
        row_in_googlesheet,
        chose_ticket
):

    # Обновляем кол-во доступных мест
    availibale_number_of_seats_now = update_quality_of_seats(
        row_in_googlesheet, 'qty_child_free_seat')
    nonconfirm_number_of_seats_now = update_quality_of_seats(
        row_in_googlesheet, 'qty_child_nonconfirm_seat')

    old_number_of_seats = int(
        availibale_number_of_seats_now) + int(
        chose_ticket.quality_of_children)
    old_nonconfirm_number_of_seats = int(
        nonconfirm_number_of_seats_now) - int(
        chose_ticket.quality_of_children)

    try:
        write_data_for_reserve(
            row_in_googlesheet,
            [old_number_of_seats, old_nonconfirm_number_of_seats]
        )

        sub_hl_logger.info(": ".join(
            [
                'Для пользователя',
                f'{user}',
                'Номер строки для обновления',
                row_in_googlesheet,
            ]
        ))
    except TimeoutError:
        await update.effective_chat.send_message(
            text=f'Для пользователя @{user.username} {user.full_name} '
                 f'отклонение в авто-режиме не сработало\n'
                 f'Номер строки для обновления:\n{row_in_googlesheet}'
        )
        sub_hl_logger.error(TimeoutError)
        sub_hl_logger.error(": ".join(
            [
                f'Для пользователя {user} отклонение в '
                f'авто-режиме не сработало',
                'Номер строки для обновления',
                row_in_googlesheet,
            ]
        ))

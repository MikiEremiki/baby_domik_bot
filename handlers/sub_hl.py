import logging

from telegram import (
    Update,
    ReplyKeyboardRemove,
)

sub_hl_logger = logging.getLogger('bot.sub_hl')


async def request_phone_number(update, phone):
    await update.effective_chat.send_message(
        text=f'Возможно вы ошиблись, вы указали {phone} \n'
             'Напишите ваш номер телефона еще раз пожалуйста\n'
             'Идеальный пример из 10 цифр: 9991119090'
    )


async def message_load_show_info(update: Update):
    return await update.effective_chat.send_message(
        text='Загружаем данные спектаклей',
        reply_markup=ReplyKeyboardRemove()
    )
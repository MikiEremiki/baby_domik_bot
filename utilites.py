import logging
import datetime

from telegram import Update, InlineKeyboardButton
from telegram.ext import ContextTypes

import googlesheets
from settings import (
    RANGE_NAME
)


def load_data():
    """

    :return:
    """
    data = googlesheets.get_data_from_spreadsheet(RANGE_NAME['База спектаклей'])
    logging.info('Данные загружены')

    dict_of_shows = {}
    dict_of_name_show = {}
    dict_of_name_show_flip = {}
    dict_of_date_show = {}
    j = 0
    for i, item in enumerate(data[1:]):
        i += 1
        dict_of_shows[i + 1] = {
            'name_of_show': item[0],
            'date': item[1],
            'time': item[2],
            'total_children_seats': item[3],
            'available_children_seats': item[4],
            'non_confirm_children_seats': item[5],
            'total_adult_seats': item[6],
            'available_adult_seats': item[7],
            'non_confirm_adult_seats': item[8],
        }

        if item[0] not in dict_of_name_show:
            j += 1
            dict_of_name_show.setdefault(item[0], j)
            dict_of_name_show_flip.setdefault(j, item[0])

        date_now = datetime.datetime.now()
        date_tmp = item[1].split()[0] + f'.{date_now.year}'
        date_tmp = datetime.datetime.strptime(date_tmp, f'%d.%m.%Y')
        if date_tmp > date_now and item[1] not in dict_of_date_show:
            dict_of_date_show.setdefault(item[1], dict_of_name_show[item[0]])

    return (
        dict_of_shows,
        dict_of_name_show,
        dict_of_name_show_flip,
        dict_of_date_show,
    )


def load_option_buy_data():
    dict_of_option_for_reserve = {}
    data = googlesheets.get_data_from_spreadsheet(RANGE_NAME['Варианты стоимости'])
    logging.info("Данные стоимости броней загружены")

    for item in data[1:]:
        dict_of_option_for_reserve[int(item[0])] = {
            'name': item[1],
            'price': int(item[2]),
            'quality_of_children': int(item[3]),
            'quality_of_adult': int(item[4]),
            'flag_individual': bool(int(item[5])),
        }

    return dict_of_option_for_reserve


def add_btn_back_and_cancel():
    """

    :return: List
    """
    button_back = InlineKeyboardButton(
        "Назад",
        callback_data='Назад'
    )
    button_cancel = InlineKeyboardButton(
        "Отменить",
        callback_data='Отменить'
    )
    return [button_back, button_cancel]


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(
        f'{update.effective_user.id}: '
        f'{update.effective_user.full_name}\n'
        f'Вызвал команду echo'
    )
    text = ' '.join([
        str(update.effective_chat.id),
        'from',
        str(update.effective_user.id)
    ])
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text
    )


async def delete_message_for_job_in_callback(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.delete_message(
        chat_id=context.job.chat_id,
        message_id=context.job.data
    )

import logging

from telegram import InlineKeyboardButton

import googlesheets


def load_data():
    """

    :return:
    """
    dict_of_shows = {}  # type: ignore
    dict_of_date_and_time = {}
    data = googlesheets.data_show()
    logging.info(f"Данные загружены")

    n = 1
    for i, item in enumerate(data[1:]):
        if item[0] not in dict_of_shows.keys():
            dict_of_shows[item[0]] = n
            dict_of_date_and_time[dict_of_shows[item[0]]] = {}
            n += 1
        if item[1] not in dict_of_date_and_time[dict_of_shows[item[0]]].keys():
            dict_of_date_and_time[dict_of_shows[item[0]]][item[1]] = {}
        if item[2] not in dict_of_date_and_time[dict_of_shows[item[0]]][item[1]].keys():
            dict_of_date_and_time[dict_of_shows[item[0]]][item[1]][item[2]] = {}
        dict_of_date_and_time[dict_of_shows[item[0]]][item[1]][item[2]] = [
            [int(item[3]),
             int(item[4]),
             int(item[5])],
            i + 2
        ]
    return dict_of_shows, dict_of_date_and_time


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

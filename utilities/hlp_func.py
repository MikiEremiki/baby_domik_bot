import logging
from typing import List

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.helpers import escape_markdown

from utilities.settings import DICT_OF_EMOJI_FOR_BUTTON
from utilities.utl_func import yrange

helper_func_logger = logging.getLogger('bot.helper_func')


def create_replay_markup_for_list_of_shows(
        dict_of_show: dict,
        num_colum=2,
        ver=1,
        add_cancel_btn=True,
        postfix_for_callback=None
):
    """
    Создает inline клавиатуру
    :param dict_of_show: Словарь со списком спектаклей
    :param num_colum: Кол-во кнопок в строке
    :param ver:
    ver = 1 для бронирования обычного спектакля
    ver = 2 для бронирования дня рождения
    :param add_cancel_btn: если True, то добавляет кнопку отмены
    :param postfix_for_callback: Добавление дополнительной приписки для
    корректного определения случая при использовании отмены
    :return: InlineKeyboardMarkup
    """
    # Определение кнопок для inline клавиатуры
    keyboard = []
    list_btn_of_numbers = []

    i = 0
    y = yrange(len(dict_of_show))
    for key, item in dict_of_show.items():
        num = next(y) + 1
        button_tmp = None
        match ver:
            case 1:
                button_tmp = InlineKeyboardButton(
                    text=key + ' ' + DICT_OF_EMOJI_FOR_BUTTON[num],
                    callback_data=str(item) + ' | ' + key
                )
            case 2:
                button_tmp = InlineKeyboardButton(
                    text=DICT_OF_EMOJI_FOR_BUTTON[num],
                    callback_data=key
                )
        list_btn_of_numbers.append(button_tmp)

        i += 1
        # Две кнопки в строке так как для узких экранов телефонов дни недели
        # обрезаются
        if i % num_colum == 0:
            i = 0
            keyboard.append(list_btn_of_numbers)
            list_btn_of_numbers = []
    if len(list_btn_of_numbers):
        keyboard.append(list_btn_of_numbers)

    if add_cancel_btn:
        callback_data = 'Отменить'
        if postfix_for_callback:
            callback_data += f'-{postfix_for_callback}'
        button_tmp = InlineKeyboardButton(
            "Отменить",
            callback_data=callback_data
        )
        keyboard.append([button_tmp])
    return InlineKeyboardMarkup(keyboard)


def create_replay_markup_with_number_btn(
        qty_btn,
        num_colum=8,
):
    """
    Создает inline клавиатуру
    :param qty_btn: диапазон кнопок
    :param num_colum: Кол-во кнопок в строке, по умолчанию 8
    :return: InlineKeyboardMarkup
    """
    # Определение кнопок для inline клавиатуры
    keyboard = []
    list_btn_of_numbers = []

    i = 0
    for num in range(qty_btn):
        button_tmp = InlineKeyboardButton(str(num+1), callback_data=str(num+1))
        list_btn_of_numbers.append(button_tmp)

        i += 1
        # Две кнопки в строке так как для узких экранов телефонов дни недели
        # обрезаются
        if i % num_colum == 0:
            i = 0
            keyboard.append(list_btn_of_numbers)
            list_btn_of_numbers = []
    if len(list_btn_of_numbers):
        keyboard.append(list_btn_of_numbers)

    return InlineKeyboardMarkup(keyboard)


def check_phone_number(phone):
    if len(phone) != 10 or phone[0] != '9':
        return True
    else:
        return False


def create_approve_and_reject_replay(
        callback_name,
        chat_id,
        message_id,
        data: List
):
    keyboard = []

    button_approve = InlineKeyboardButton(
        "Подтвердить",
        callback_data=f'confirm-{callback_name}|'
                      f'{chat_id} {message_id} '
                      f'{data[0]} {data[1]}'
    )

    button_cancel = InlineKeyboardButton(
        "Отклонить",
        callback_data=f'reject-{callback_name}|'
                      f'{chat_id} {message_id} '
                      f'{data[0]} {data[1]}'
    )
    keyboard.append([button_approve, button_cancel])
    return InlineKeyboardMarkup(keyboard)


def replace_markdown_v2(text: str) -> str:
    text = text.replace('_', '\_')
    text = text.replace('*', '\*')
    text = text.replace('[', '\[')
    text = text.replace(']', '\]')
    text = text.replace('(', '\(')
    text = text.replace(')', '\)')
    text = text.replace('~', '\~')
    text = text.replace('`', '\`')
    text = text.replace('>', '\>')
    text = text.replace('#', '\#')
    text = text.replace('+', '\+')
    text = text.replace('-', '\-')
    text = text.replace('=', '\=')
    text = text.replace('|', '\|')
    text = text.replace('{', '\{')
    text = text.replace('}', '\}')
    text = text.replace('.', '\.')
    text = text.replace('!', '\!')

    return text


def do_italic(text):
    return f'_{escape_markdown(text, 2)}_'
# TODO Сделать одну общую функцию для разного форматирования с несколькими
#  параметрами-флагами


def do_bold(text):
    return f'*{escape_markdown(text, 2)}*'

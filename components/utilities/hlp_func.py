import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.helpers import escape_markdown

from utilities.settings import DICT_OF_EMOJI_FOR_BUTTON, support_data
from utilities.utl_func import yrange, add_btn_back_and_cancel

helper_func_logger = logging.getLogger('bot.helper_func')


def create_replay_markup_for_list_of_shows(
        dict_of_show: dict,
        num_colum=2,
        ver=1,
        add_cancel_btn=True,
        postfix_for_cancel=None,
        add_back_btn=True,
        postfix_for_back=None,
        number_of_month=None,
        number_of_show=None,
        dict_of_events_show: dict = None
):
    """
    Создает inline клавиатуру
    :param number_of_month: номер месяца
    :param number_of_show: номер спектакля при загрузке всех дат из расписания
    :param dict_of_show: Словарь со списком спектаклей
    :param num_colum: Кол-во кнопок в строке
    :param ver:
    ver = 1 для бронирования обычного спектакля
    ver = 2 для бронирования дня рождения
    ver = 3 для бронирования в декабре
    :param add_cancel_btn: если True, то добавляет кнопку Отменить
    :param add_back_btn: если True, то добавляет кнопку Назад
    :param postfix_for_cancel: Добавление дополнительной приписки для
    корректного определения случая при использовании Отменить
    :param postfix_for_back: Добавление дополнительной приписки для
    корректного определения случая при использовании Назад
    :param dict_of_events_show:
    :return: InlineKeyboardMarkup
    """
    # Определение кнопок для inline клавиатуры
    keyboard = []
    list_btn_of_numbers = []

    i = 0
    y = yrange(len(dict_of_show))
    for key, item in dict_of_show.items():
        if number_of_month is not None and key[3:5] != number_of_month:
            continue
        num = next(y) + 1
        button_tmp = None
        match ver:
            case 1:
                if number_of_month:
                    filter_show_id = enum_current_show_by_month(dict_of_show,
                                                                number_of_month)
                    if item in filter_show_id.keys():
                        button_tmp = InlineKeyboardButton(
                            text=key + ' ' + DICT_OF_EMOJI_FOR_BUTTON[
                                filter_show_id[item]],
                            callback_data=str(item) + ' | ' + key
                        )
            case 2:
                button_tmp = InlineKeyboardButton(
                    text=DICT_OF_EMOJI_FOR_BUTTON[num],
                    callback_data=key
                )
            case 3:
                if number_of_month:
                    filter_show_id = enum_current_show_by_month(dict_of_show,
                                                                number_of_month)
                    if item in filter_show_id.keys() and item == number_of_show:
                        text = key
                        for event in dict_of_events_show.values():
                            if key == event['date_show']:
                                if event['flag_gift']:
                                    text += f'{support_data["Подарок"][0]}'
                                if event['flag_christmas_tree']:
                                    text += f'{support_data["Елка"][0]}'
                                if event['flag_santa']:
                                    text += f'{support_data["Дед"][0]}'
                        button_tmp = InlineKeyboardButton(
                            text=text,
                            callback_data=str(item) + ' | ' + key
                        )
                    else:
                        continue
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

    list_end_btn = []
    if add_back_btn:
        callback_data = 'Назад'
        button_tmp = InlineKeyboardButton(
            'Назад',
            callback_data=callback_data
        )
        list_end_btn.append(button_tmp)
    if add_cancel_btn:
        callback_data = 'Отменить'
        if postfix_for_callback:
            callback_data += f'-{postfix_for_callback}'
        button_tmp = InlineKeyboardButton(
            'Отменить',
            callback_data=callback_data
        )
        list_end_btn.append(button_tmp)
    if len(list_end_btn):
        keyboard.append(list_end_btn)
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
        message_id
):
    keyboard = []

    button_approve = InlineKeyboardButton(
        "Подтвердить",
        callback_data=f'confirm-{callback_name}|'
                      f'{chat_id} {message_id}'
    )

    button_cancel = InlineKeyboardButton(
        "Отклонить",
        callback_data=f'reject-{callback_name}|'
                      f'{chat_id} {message_id}'
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


def enum_current_show(dict_of_date_show: dict, num: str) -> dict:
    filter_show_id = {}
    i = 1
    for key, item in dict_of_date_show.items():
        if num is not None and key[3:5] != num:
            continue
        if item not in filter_show_id.keys():
            filter_show_id[item] = i
            i += 1

    return filter_show_id

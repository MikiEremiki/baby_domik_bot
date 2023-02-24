import logging
import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeChatAdministrators,
)
from telegram.ext import ContextTypes
from telegram.error import BadRequest

import googlesheets
from settings import (
    RANGE_NAME,
    COMMAND_DICT,
    ADMIN_GROUP_ID,
    ADMIN_CHAT_ID,
)


def load_data():
    """

    :return:
    """
    data = googlesheets.get_data_from_spreadsheet(RANGE_NAME['База спектаклей'])
    logging.info('Данные загружены')

    dict_of_shows = {}  # Все спектакли со всеми данными
    dict_of_name_show = {}  # key: str (название спектакля), item: int
    dict_of_name_show_flip = {}  # key: int, item: str (название спектакля)
    dict_of_date_show = {}  # key: str (дата спектакля), item: int (номер спектакля)
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


def load_clients_data(name, date, time):
    data_clients_data = []
    data = googlesheets.get_data_from_spreadsheet(RANGE_NAME['База клиентов_'])

    for item in data[1:]:
        if (
            item[6] == name and
            item[7] == date and
            item[8] == time
        ):
            data_clients_data.append(item)

    return data_clients_data


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


def replace_markdown_v2(text: str) -> str:
    for char in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-',
                 '=', '|', '{', '}', '.', '!']:
        formatted_text = text.replace(char, '\\' + char)
    return formatted_text


async def set_menu(bot):
    group_commands = [
        BotCommand(COMMAND_DICT['RESERVE'][0], COMMAND_DICT['RESERVE'][1]),
        BotCommand(COMMAND_DICT['LIST'][0], COMMAND_DICT['LIST'][1]),
    ]

    for chat_id in ADMIN_GROUP_ID:
        try:
            await bot.set_my_commands(
                commands=group_commands,
                scope=BotCommandScopeChatAdministrators(chat_id=chat_id)
            )
        except BadRequest:
            continue
    for chat_id in ADMIN_CHAT_ID:
        try:
            await bot.set_my_commands(
                commands=group_commands,
                scope=BotCommandScopeChat(chat_id=chat_id)
            )
        except BadRequest:
            continue

    return bot

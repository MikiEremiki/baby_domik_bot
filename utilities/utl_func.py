import logging
import datetime
from typing import Any, List, Union
import os
import re

from telegram import (
    Update,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    BotCommandScopeChatAdministrators,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler
)
from telegram.error import BadRequest

from utilities import googlesheets
from utilities.settings import (
    RANGE_NAME,
    COMMAND_DICT,
    CHAT_ID_MIKIEREMIKI,
    ADMIN_GROUP_ID,
    ADMIN_CHAT_ID,
    ADMIN_ID,
)

utilites_logger = logging.getLogger('bot.utilites')


def load_show_data() -> tuple[
    dict[int, dict[Any]],
    dict[str, int],
    dict[int, str],
    dict[str, int]
]:
    """
    Возвращает 4 словаря из гугл-таблицы с листа "База спектаклей"
    Проводит фильтрацию по дате, все прошедшие даты исключаются из выборки

    dict_of_shows -> Все спектакли со всеми данными
    dict_of_name_show -> key: str (название спектакля), item: int
    dict_of_name_show_flip -> key: int, item: str (название спектакля)
    dict_of_date_show -> key: str (дата спектакля), item: int (номер спектакля)

    :return: dict, dict, dict, dict
    """
    # TODO Переписать структуру словарей с учетом добавления отдельного листа
    #  с базой по спектаклям
    data_of_dates = googlesheets.get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_дата']
    )

    # Исключаем из загрузки в data спектакли, у которых дата уже прошла
    first_row = 2
    date_now = datetime.datetime.now().date()
    for i, item in enumerate(data_of_dates[1:]):
        date_tmp = item[0].split()[0] + f'.{date_now.year}'
        date_tmp = datetime.datetime.strptime(date_tmp, f'%d.%m.%Y').date()
        if date_tmp >= date_now:
            first_row += i
            break

    data = googlesheets.get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_'] + f'A{first_row}:I'
    )
    utilites_logger.info('Данные загружены')

    dict_of_shows = {}
    dict_of_name_show = {}
    dict_of_name_show_flip = {}
    dict_of_date_show = {}
    j = 0
    for i, item in enumerate(data):
        i += first_row - 1
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

        date_now = datetime.datetime.now().date()
        date_tmp = item[1].split()[0] + f'.{date_now.year}'
        date_tmp = datetime.datetime.strptime(date_tmp, f'%d.%m.%Y').date()

        if date_tmp >= date_now and item[1] not in dict_of_date_show:
            dict_of_date_show.setdefault(item[1], dict_of_name_show[item[0]])

    return (
        dict_of_shows,
        dict_of_name_show,
        dict_of_name_show_flip,
        dict_of_date_show,
    )


def load_list_show() -> dict[int, dict[str, Any]]:
    """
    Возвращает 1 словарь из гугл-таблицы с листа "Список спектаклей"
    Проводит фильтрацию по дате, все прошедшие даты исключаются из выборки

    dict_of_name_show -> key: str, item: Any

    :return: dict
    """

    qty_shows = len(googlesheets.get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] + f'A:A'
    ))
    data = googlesheets.get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] + f'A2:I{qty_shows}'
    )
    utilites_logger.info('Данные загружены')

    dict_of_shows = {}
    for item in data:
        id_show: int = int(item[0])
        name: str = item[1]
        flag_premiere: bool = True if item[2] == 'TRUE' else False
        min_age_child: int = int(item[3])
        flag_birthday: bool = True if item[5] == 'TRUE' else False
        max_num_child: int = int(item[6])
        max_num_adult: int = int(item[7])
        flag_repertoire: bool = True if item[8] == 'TRUE' else False

        if flag_premiere:
            text = 'ПРЕМЬЕРА. ' + item[3] + '+'
        else:
            text = item[3] + '+'
        full_name_of_show: str = '. '.join([name, text])

        dict_of_shows[id_show] = {
            'name': name,
            'flag_premiere': flag_premiere,
            'min_age_child': min_age_child,
            'birthday': {
                'flag': flag_birthday,
                'max_num_child': max_num_child,
                'max_num_adult': max_num_adult,
            },
            'flag_repertoire': flag_repertoire,
            'full_name_of_show': full_name_of_show,
        }

    return (
        dict_of_shows
    )


def load_option_buy_data() -> dict[int, dict[str, Any]]:
    dict_of_option_for_reserve = {}
    data = googlesheets.get_data_from_spreadsheet(
        RANGE_NAME['Варианты стоимости'])
    utilites_logger.info("Данные стоимости броней загружены")

    for item in data[1:]:
        if len(item) == 0:
            break
        dict_of_option_for_reserve[int(item[0])] = {
            'name': item[1],
            'price': int(item[2]),
            'quality_of_children': int(item[3]),
            'quality_of_adult': int(item[4]),
            'flag_individual': bool(int(item[5])),
        }

    return dict_of_option_for_reserve


def load_clients_data(name: str, date: str, time: str) -> List[List[str]]:
    data_clients_data = []
    first_colum = googlesheets.get_data_from_spreadsheet(
        RANGE_NAME['База клиентов']
    )
    first_row = googlesheets.get_data_from_spreadsheet(
        RANGE_NAME['База клиентов__']
    )
    sheet = (
        RANGE_NAME['База клиентов_'] +
        f'!R1C1:R{len(first_colum)}C{len(first_row[0])}'
    )
    data = googlesheets.get_data_from_spreadsheet(sheet)

    for item in data[1:]:
        if (
            item[6] == name and
            item[7] == date and
            item[8] == time
        ):
            data_clients_data.append(item)

    return data_clients_data


def add_btn_back_and_cancel() -> List[object]:
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


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    utilites_logger.info(
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


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> -1:
    utilites_logger.info(
        f'{update.effective_user.id}: '
        f'{update.effective_user.full_name}\n'
        f'Вызвал команду reset'
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text='Попробуйте выполнить новый запрос'
    )
    utilites_logger.info(
        f'Обработчик завершился на этапе {context.user_data["STATE"]}')

    context.user_data.clear()
    return ConversationHandler.END


async def delete_message_for_job_in_callback(
        context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.delete_message(
        chat_id=context.job.chat_id,
        message_id=context.job.data
    )


async def set_menu(context: ContextTypes.DEFAULT_TYPE) -> None:
    default_commands = [
        BotCommand(COMMAND_DICT['START'][0], COMMAND_DICT['START'][1]),
        BotCommand(COMMAND_DICT['RESERVE'][0], COMMAND_DICT['RESERVE'][1]),
        BotCommand(COMMAND_DICT['BD_ORDER'][0], COMMAND_DICT['BD_ORDER'][1]),
    ]
    admin_group_commands = [
        BotCommand(COMMAND_DICT['LIST'][0], COMMAND_DICT['LIST'][1]),
        BotCommand(COMMAND_DICT['LOG'][0], COMMAND_DICT['LOG'][1]),
        BotCommand(COMMAND_DICT['ECHO'][0], COMMAND_DICT['ECHO'][1]),
    ]
    admin_commands = default_commands + admin_group_commands

    for chat_id in ADMIN_GROUP_ID:
        try:
            await context.bot.set_my_commands(
                commands=admin_group_commands,
                scope=BotCommandScopeChatAdministrators(chat_id=chat_id)
            )
        except BadRequest:
            utilites_logger.error(f'Бот не состоит в группе {chat_id}')
    for chat_id in ADMIN_CHAT_ID:
        await context.bot.set_my_commands(
            commands=admin_commands,
            scope=BotCommandScopeChat(chat_id=chat_id)
        )
    await context.bot.set_my_commands(
        commands=default_commands,
        scope=BotCommandScopeDefault()
    )


async def send_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id in ADMIN_ID:
        try:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document='log.txt'
            )
            i = 1
            while os.path.exists(f'log_debug/log.txt.{i}'):
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f'log_debug/log.txt.{i}'
                )
        except FileExistsError:
            utilites_logger.info('Файл логов не найден')


async def send_message_to_admin(
        chat_id: Union[int, str],
        text: str,
        message_id: Union[int, str],
        context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=message_id
        )
    except BadRequest:
        utilites_logger.info(": ".join(
            [
                'Для пользователя',
                str(context.user_data['user'].id),
                str(context.user_data['user'].full_name),
                'сообщение на которое нужно ответить, удалено'
            ],
        ))
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
        )


def extract_phone_number_from_text(phone):
    phone = re.sub(r'[-\s)(+]', '', phone)
    return re.sub(r'^[78]{,2}(?=9)', '', phone)


def yrange(n):
    i = 0
    while i < n:
        yield i
        i += 1


def print_ud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == CHAT_ID_MIKIEREMIKI:
        print(context.application.user_data.keys())


def create_keys_for_sort(item):
    a, b = item.split()[0].split('.')
    return b + a


def load_and_concat_date_of_shows():
    list_of_date_show = load_date_show_data()
    list_of_date_show = sorted(list_of_date_show,
                               key=create_keys_for_sort)
    text_date = '\n'.join(item for item in list_of_date_show)
    return ('\n__________\nВ следующие даты проводятся спектакли, поэтому их '
            'не указывайте:'
            f'\n{text_date}')

import logging

from typing import Any, List

from utilities.googlesheets import get_data_from_spreadsheet
from utilities.utl_func import filter_by_date, get_date
from utilities.settings import RANGE_NAME
from utilities.schemas.ticket import Ticket

db_googlesheets_logger = logging.getLogger('bot.db.googlesheets')


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
    # TODO Выделить загрузку базы спектаклей в отдельную задачу и хранить ее
    #  сразу в
    #  bot_data
    data_of_dates = get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_дата']
    )

    # Исключаем из загрузки в data спектакли, у которых дата уже прошла
    first_row = filter_by_date(data_of_dates)

    data = get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_'] + f'A{first_row}:I'
    )
    db_googlesheets_logger.info('Данные загружены')

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

        date_now, date_tmp = get_date(item)
        # TODO Скорее всего тут можно упростить условие даты и не
        #  использовать его вовсе, за счёт того, что данные и так содержат
        #  уже отфильтрованные данные по дате
        if date_tmp >= date_now and item[1] not in dict_of_date_show:
            dict_of_date_show.setdefault(item[1], dict_of_name_show[item[0]])

    return (
        dict_of_shows,
        dict_of_name_show,
        dict_of_name_show_flip,
        dict_of_date_show,
    )


def load_date_show_data() -> List[str]:
    """
    Возвращает 1 словарь из гугл-таблицы с листа "База спектаклей"
    Проводит фильтрацию по дате, все прошедшие даты исключаются из выборки

    dict_of_date_show -> key: str (дата спектакля), item: int (номер спектакля)

    :return: dict
    """
    # TODO Выделить загрузку дат в отдельную задачу и хранить ее сразу в
    #  bot_data
    data_of_dates = get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_дата']
    )

    # Исключаем из загрузки в data спектакли, у которых дата уже прошла
    first_row = filter_by_date(data_of_dates)

    list_of_date_show = []
    for item in data_of_dates[first_row:]:
        if item[0] not in list_of_date_show:
            list_of_date_show.append(item[0])

    db_googlesheets_logger.info('Данные загружены')

    return list_of_date_show


def load_list_show() -> dict[int, dict[str, Any]]:
    """
    Возвращает 1 словарь из гугл-таблицы с листа "Список спектаклей"
    Проводит фильтрацию по дате, все прошедшие даты исключаются из выборки

    dict_of_name_show -> key: str, item: Any

    :return: dict
    """
    # TODO Выделить загрузку спектаклей в отдельную задачу и хранить ее сразу в
    #  bot_data
    qty_shows = len(get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] + f'A:A'
    ))
    data = get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] + f'A2:I{qty_shows}'
    )
    db_googlesheets_logger.info('Данные загружены')

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


def load_ticket_data() -> List[Ticket]:
    # TODO Выделить загрузку билетов в отдельную задачу и хранить ее сразу в
    #  bot_data
    list_of_tickets = []

    data = get_data_from_spreadsheet(
        RANGE_NAME['Варианты стоимости тест'])
    db_googlesheets_logger.info('Данные стоимости броней загружены')

    for item in data[3:]:
        if len(item) == 0:
            break
        tmp_dict = {}
        for i, value in enumerate(item):
            tmp_dict[data[1][i]] = value
        list_of_tickets.append(Ticket(**tmp_dict))

    return list_of_tickets


def load_clients_data(name: str, date: str, time: str) -> List[List[str]]:
    data_clients_data = []
    first_colum = get_data_from_spreadsheet(
        RANGE_NAME['База клиентов']
    )
    first_row = get_data_from_spreadsheet(
        RANGE_NAME['База клиентов__']
    )
    sheet = (
            RANGE_NAME['База клиентов_'] +
            f'!R1C1:R{len(first_colum)}C{len(first_row[0])}'
    )
    data = get_data_from_spreadsheet(sheet)

    for item in data[1:]:
        if (
                item[6] == name and
                item[7] == date and
                item[8] == time
        ):
            data_clients_data.append(item)

    return data_clients_data
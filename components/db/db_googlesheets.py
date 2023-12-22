import logging
import datetime

from typing import Any, List, Tuple, Dict

from pydantic import ValidationError

from utilities.googlesheets import get_data_from_spreadsheet, get_column_info
from utilities.settings import RANGE_NAME
from utilities.schemas.ticket import BaseTicket

db_googlesheets_logger = logging.getLogger('bot.db.googlesheets')


def filter_by_date(data_of_dates):
    first_row = 3
    date_now = datetime.datetime.now().date()
    for i, item in enumerate(data_of_dates[2:]):
        date_tmp = item[0].split()[0] + f'.{date_now.year}'
        date_tmp = datetime.datetime.strptime(date_tmp, f'%d.%m.%Y').date()
        if date_tmp >= date_now:
            first_row += i
            break
    return first_row


def get_date(item, dict_column_name):
    date_now = datetime.datetime.now().date()
    date_tmp = item[dict_column_name['date_show']].split()[0] + (
        f'.{date_now.year}')
    date_tmp = datetime.datetime.strptime(date_tmp, f'%d.%m.%Y').date()
    return date_now, date_tmp


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
    #  сразу в bot_data
    dict_column_name, len_column = get_column_info('База спектаклей_')
    data_of_dates = get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_'] +
        f'C[{dict_column_name['date_show']}]'
    )

    # Исключаем из загрузки в data спектакли, у которых дата уже прошла
    first_row = filter_by_date(data_of_dates)

    data = get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_'] + f'R{first_row}C1:'
                                         f'R{len(data_of_dates)}'
                                         f'C{len_column}'
    )

    db_googlesheets_logger.info('Данные загружены')

    dict_of_shows = {}
    dict_of_name_show = {}
    dict_of_name_show_flip = {}
    dict_of_date_show = {}
    j = 0
    for item in data:
        if item[dict_column_name['flag_turn_on_off']] == 'TRUE':
            dict_of_shows[int(item[dict_column_name['event_id']])] = {
                'event_type': item[dict_column_name['event_type']],
                'show_id': item[dict_column_name['show_id']],
                'name_show': item[dict_column_name['name_show']],
                'date_show': item[dict_column_name['date_show']],
                'time_show': item[dict_column_name['time_show']],
                'qty_child': item[dict_column_name['qty_child']],
                'qty_child_free_seat': item[
                    dict_column_name['qty_child_free_seat']],
                'qty_child_nonconfirm_seat': item[
                    dict_column_name['qty_child_nonconfirm_seat']],
                'qty_adult': item[dict_column_name['qty_adult']],
                'qty_adult_free_seat': item[
                    dict_column_name['qty_adult_free_seat']],
                'qty_adult_nonconfirm_seat': item[
                    dict_column_name['qty_adult_nonconfirm_seat']],
                'flag_gift': True if item[dict_column_name[
                    'flag_gift']] == 'TRUE' else False,
                'flag_christmas_tree': True if item[dict_column_name[
                    'flag_christmas_tree']] == 'TRUE' else False,
                'flag_santa': True if item[dict_column_name[
                    'flag_santa']] == 'TRUE' else False,
                'ticket_price_type': item[dict_column_name['ticket_price_type']],
            }

            if item[dict_column_name['name_show']] not in dict_of_name_show:
                j += 1
                dict_of_name_show.setdefault(
                    item[dict_column_name['name_show']],
                    j)
                dict_of_name_show_flip.setdefault(
                    j,
                    item[dict_column_name['name_show']])

            if item[dict_column_name['date_show']] not in dict_of_date_show:
                dict_of_date_show.setdefault(
                    item[dict_column_name['date_show']],
                    {dict_of_name_show[item[dict_column_name['name_show']]]}
                )
            else:
                dict_of_date_show[item[dict_column_name['date_show']]].add(
                    dict_of_name_show[item[dict_column_name['name_show']]]
                )

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
    dict_column_name, len_column = get_column_info('База спектаклей_')
    qty_shows = len(get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_'] + f'A:A'
    ))

    data_of_dates = get_data_from_spreadsheet(
        RANGE_NAME['База спектаклей_'] +
        f'R1C{dict_column_name['date_show'] + 1}:'
        f'R{qty_shows}C{dict_column_name['date_show'] + 1}'
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
    dict_column_name, len_column = get_column_info('Список спектаклей_')

    qty_shows = len(get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] + f'A:A'
    ))
    data = get_data_from_spreadsheet(
        RANGE_NAME['Список спектаклей_'] +
        f'R3C1:R{qty_shows}C{len_column}'
    )
    db_googlesheets_logger.info('Данные загружены')

    dict_of_shows = {}
    for item in data:
        show_id: int = int(item[dict_column_name['show_id']])
        name: str = item[dict_column_name['name']]
        flag_premiere: bool = True if item[dict_column_name[
            'flag_active_premiere']] == 'TRUE' else False
        min_age_child: int = int(item[dict_column_name['min_age_child']])
        max_age_child: int = int(item[dict_column_name['max_age_child']])
        show_emoji: str = item[dict_column_name['show_emoji']]
        flag_birthday: bool = True if item[dict_column_name[
            'flag_active_bd']] == 'TRUE' else False
        max_num_child: int = int(item[dict_column_name['max_num_child_bd']])
        max_num_adult: int = int(item[dict_column_name['max_num_adult_bd']])
        flag_repertoire: bool = True if item[dict_column_name[
            'flag_active_repertoire']] == 'TRUE' else False
        flag_indiv_cost: bool = True if item[dict_column_name[
            'flag_indiv_cost']] == 'TRUE' else False

        full_name: str = name
        sep = '. '
        if flag_premiere:
            full_name += sep + 'ПРЕМЬЕРА'
        if min_age_child > 0:
            full_name += sep + item[dict_column_name['min_age_child']]
        if max_age_child > 0:
            full_name += "-" + item[dict_column_name['max_age_child']] + "лет"
        else:
            full_name += '+'

        dict_of_shows[show_id] = {
            'name': name,
            'flag_premiere': flag_premiere,
            'min_age_child': min_age_child,
            'max_age_child': max_age_child,
            'show_emoji': show_emoji,
            'birthday': {
                'flag': flag_birthday,
                'max_num_child': max_num_child,
                'max_num_adult': max_num_adult,
            },
            'flag_repertoire': flag_repertoire,
            'flag_indiv_cost': flag_indiv_cost,
            'full_name': full_name,
        }

    return (
        dict_of_shows
    )


def load_ticket_data() -> List[BaseTicket]:
    # TODO Выделить загрузку билетов в отдельную задачу и хранить ее сразу в
    #  bot_data
    list_of_tickets = []

    dict_column_name, len_column = get_column_info('Варианты стоимости_')

    qty_tickets = len(get_data_from_spreadsheet(
        RANGE_NAME['Варианты стоимости_'] + f'A:A'
    ))

    data = get_data_from_spreadsheet(
        RANGE_NAME['Варианты стоимости_'] +
        f'R2C1:R{qty_tickets}C{len(dict_column_name)}'
    )
    db_googlesheets_logger.info('Данные стоимости броней загружены')

    fields_ticket = [*BaseTicket.model_fields.keys()]
    for item in data[1:]:
        tmp_dict = {}
        for value in fields_ticket:
            try:
                tmp_dict[value] = item[dict_column_name[value]]
            except KeyError as e:
                if e.args[0] != 'date_show_tmp':
                    db_googlesheets_logger.error(item)
                    db_googlesheets_logger.error(e)
        try:
            ticket = BaseTicket(**tmp_dict)
            if ticket.flag_active:
                list_of_tickets.append(ticket)
        except ValidationError as exc:
            db_googlesheets_logger.error(repr(exc.errors()[0]['type']))
            db_googlesheets_logger.error(tmp_dict)

    db_googlesheets_logger.info('Список билетов загружен')
    return list_of_tickets


def load_clients_data(
        event_id: int
) -> Tuple[List[List[str]], Dict[int | str, int]]:
    data_clients_data = []
    first_colum = get_data_from_spreadsheet(
        RANGE_NAME['База клиентов']
    )
    first_row = get_data_from_spreadsheet(
        RANGE_NAME['База клиентов__']
    )
    sheet = (
            RANGE_NAME['База клиентов_'] +
            f'R1C1:R{len(first_colum)}C{len(first_row[0])}'
    )

    dict_column_name, len_column = get_column_info('База клиентов_')

    data = get_data_from_spreadsheet(sheet)

    for item in data[1:]:
        if item[dict_column_name['event_id']] == str(event_id):
            data_clients_data.append(item)

    return data_clients_data, dict_column_name


def load_clients_wait_data(
        date_show: str
) -> Tuple[List[List[str]], Dict[int | str, int]]:
    data_clients_data = []
    first_colum = get_data_from_spreadsheet(
        RANGE_NAME['Лист ожидания']
    )

    dict_column_name, len_column = get_column_info('Лист ожидания_')

    sheet = (
            RANGE_NAME['Лист ожидания_'] +
            f'R1C1:R{len(first_colum)}C{len_column}'
    )

    data = get_data_from_spreadsheet(sheet)

    for item in data[1:]:
        if item[dict_column_name['date_show']] == date_show:
            data_clients_data.append(item)

    return data_clients_data, dict_column_name

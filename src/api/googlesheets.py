import logging
import os
from datetime import datetime
from typing import List, Any, Optional, Dict

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from telegram.ext import ContextTypes

from settings.config_loader import parse_settings
from settings.settings import RANGE_NAME
from utilities.schemas.ticket import BaseTicket

config = parse_settings()
SPREADSHEET_ID = {}
SPREADSHEET_ID.setdefault('Домик', config.sheets.sheet_id)

filename = 'credentials.json'
path = os.getenv('CONFIG_PATH')
if path is not None:
    filename = path + filename
else:
    filename = config.sheets.credentials_path
googlesheets_logger = logging.getLogger('bot.googlesheets')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def get_service_sacc(scopes):
    credentials = service_account.Credentials.from_service_account_file(
        filename=filename,
        scopes=scopes
    )

    return build('sheets', 'v4', credentials=credentials)


def get_values(
        spreadsheet_id,
        range_name,
        value_render_option='FORMATTED_VALUE'
):
    sheet = get_service_sacc(SCOPES).spreadsheets()
    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueRenderOption=value_render_option,

    ).execute()
    return result.get('values', [])


def get_data_from_spreadsheet(sheet, value_render_option='FORMATTED_VALUE'):
    try:
        values = get_values(
            SPREADSHEET_ID['Домик'],
            sheet,
            value_render_option
        )

        if not values:
            googlesheets_logger.info('No data found')
            raise ValueError

        return values
    except HttpError as err:
        googlesheets_logger.error(err)
        raise ConnectionError


def get_quality_of_seats(event_id: str, keys: List[str]):
    try:
        dict_column_name, len_column = get_column_info('База спектаклей_')

        values = get_values(
            SPREADSHEET_ID['Домик'],
            f'{RANGE_NAME['База спектаклей']}'
        )

        if not values:
            googlesheets_logger.info('No data found')
            raise ValueError

        return_data = []
        for row in values:
            if event_id == row[dict_column_name['event_id']]:
                for key in keys:
                    return_data.append(row[dict_column_name[key]])
                return return_data
        raise KeyError
    except HttpError as err:
        googlesheets_logger.error(err)
    except KeyError:
        googlesheets_logger.error(f'Показа с event_id = {event_id} не найдено')


def get_column_info(name_sheet):
    data_column_name = get_data_from_spreadsheet(
        RANGE_NAME[name_sheet] + f'2:2'
    )
    dict_column_name: Dict[int | str, int] = {}
    for i, item in enumerate(data_column_name[0]):
        if item == '':
            item = i
        dict_column_name[item] = i

    if len(dict_column_name) != len(data_column_name[0]):
        googlesheets_logger.warning(
            'dict_column_name, len(data_column_name[0]) не равны')
        googlesheets_logger.warning(
            f'{len(dict_column_name)} != {len(data_column_name[0])}')

    return dict_column_name, len(data_column_name[0])


def write_data_for_reserve(
        event_id: str,
        numbers: List[int],
        option: int = 1
) -> None:
    try:
        dict_column_name, len_column = get_column_info('База спектаклей_')

        values = get_values(
            SPREADSHEET_ID['Домик'],
            f'{RANGE_NAME['База спектаклей']}'
        )

        if not values:
            googlesheets_logger.info('No data found')
            raise ValueError

        for i, row in enumerate(values):
            if event_id == row[dict_column_name['event_id']]:
                row_event = i + 1

        sheet = get_service_sacc(SCOPES).spreadsheets()
        value_input_option = 'RAW'
        major_dimension = 'ROWS'
        data = []

        match option:
            case 1:
                col1 = dict_column_name['qty_child_free_seat'] + 1
                col2 = dict_column_name['qty_child_nonconfirm_seat'] + 1
                range_sheet = (f'{RANGE_NAME['База спектаклей_']}'
                               f'R{row_event}C{col1}:R{row_event}C{col2}')
                data.append({
                    'range': range_sheet,
                    'majorDimension': major_dimension,
                    'values': [numbers[0:2]]
                })
                col1 = dict_column_name['qty_adult_free_seat'] + 1
                col2 = dict_column_name['qty_adult_nonconfirm_seat'] + 1
                range_sheet = (f'{RANGE_NAME['База спектаклей_']}'
                               f'R{row_event}C{col1}:R{row_event}C{col2}')
                data.append({
                    'range': range_sheet,
                    'majorDimension': major_dimension,
                    'values': [numbers[2:4]]
                })
            case 2:
                col = dict_column_name['qty_child_nonconfirm_seat'] + 1
                range_sheet = (f'{RANGE_NAME['База спектаклей_']}'
                               f'R{row_event}C{col}')
                data.append({
                    'range': range_sheet,
                    'majorDimension': major_dimension,
                    'values': [[numbers[0]]]
                })
                col = dict_column_name['qty_adult_nonconfirm_seat'] + 1
                range_sheet = (f'{RANGE_NAME['База спектаклей_']}'
                               f'R{row_event}C{col}')
                data.append({
                    'range': range_sheet,
                    'majorDimension': major_dimension,
                    'values': [[numbers[1]]]
                })
            case 3:
                col = dict_column_name['qty_child_free_seat'] + 1
                range_sheet = (f'{RANGE_NAME['База спектаклей_']}'
                               f'R{row_event}C{col}')
                data.append({
                    'range': range_sheet,
                    'majorDimension': major_dimension,
                    'values': [[numbers[0]]]
                })
                col = dict_column_name['qty_adult_free_seat'] + 1
                range_sheet = (f'{RANGE_NAME['База спектаклей_']}'
                               f'R{row_event}C{col}')
                data.append({
                    'range': range_sheet,
                    'majorDimension': major_dimension,
                    'values': [[numbers[1]]]
                })

        value_range_body = {
            'valueInputOption': value_input_option,
            'data': data
        }
        request = sheet.values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID['Домик'],
            body=value_range_body
        )
        try:
            responses = request.execute()
            googlesheets_logger.info(
                f'spreadsheetId: {responses['spreadsheetId']}')
            for response in responses['responses']:
                googlesheets_logger.info(': '.join(
                    [
                        'updatedRange: ',
                        response['updatedRange']
                    ]
                ))
        except TimeoutError:
            googlesheets_logger.error(value_range_body)

    except HttpError as err:
        googlesheets_logger.error(err)


def write_client(
        client: dict,
        event_id: str,
        ticket: BaseTicket,
        price: int,
) -> Optional[int]:
    # TODO Переписать функцию, чтобы принимала весь контекст целиком и внутри
    #  вытаскивать нужные значения
    try:
        values_column = get_values(
            SPREADSHEET_ID['Домик'],
            RANGE_NAME['База клиентов']
        )

        if not values_column:
            googlesheets_logger.info('No data found')
            return

        sheet = get_service_sacc(SCOPES).spreadsheets()
        value_input_option = 'USER_ENTERED'
        response_value_render_option = 'FORMATTED_VALUE'
        values: List[Any] = [[]]

        record_id = int(values_column[-1][0]) + 1
        values[0].append(record_id)
        # TODO Добавить запись user_id
        for key, item in client.items():
            if key == 'data_children':
                values[0].append(' | '.join([i[0] for i in item]))
                values[0].append('')
                values[0].append(' | '.join([i[1] for i in item]))
            else:
                values[0].append(item)

        # Спектакль
        values[0].append(event_id)
        for j in range(4):
            values[0].append(
                f'=VLOOKUP('
                f'INDIRECT("R"&ROW()&"C"&MATCH("event_id";$2:$2;0);FALSE);'
                f'INDIRECT("\'Расписание\'!R1C1:C"&MATCH('
                f'INDIRECT("R2C"&COLUMN();FALSE);\'Расписание\'!$2:$2;0);FALSE);'
                f'MATCH(INDIRECT("R2C"&COLUMN();FALSE);\'Расписание\'!$2:$2;0);'
                f'0)'
            )
        values[0].append(datetime.now().strftime('%y%m%d %H:%M:%S'))

        # add ticket info
        values[0].append(ticket.base_ticket_id)
        values[0].append(ticket.name)
        values[0].append(price)
        values[0].append(ticket.quality_of_children)
        values[0].append(ticket.quality_of_adult +
                         ticket.quality_of_add_adult)

        values[0].append(False)
        values[0].append(False)
        values[0].append(False)
        values[0].append('')
        values[0].append('=iferror(SPLIT(L1916;" "))')

        googlesheets_logger.info(values)

        end_column_index = len(values[0])

        value_range_body = {
            'values': values,
        }

        range_sheet = (RANGE_NAME['База клиентов_'] +
                       f'R1C1:'
                       f'R1C{end_column_index}')

        execute_append_googlesheet(sheet,
                                   range_sheet,
                                   value_input_option,
                                   response_value_render_option,
                                   value_range_body)

        return record_id
    except HttpError as err:
        googlesheets_logger.error(err)
        # TODO добавить возврат списка с нулевым значением


def write_client_bd(
        context_data: dict,
) -> None:
    try:
        values_column = get_values(
            SPREADSHEET_ID['Домик'],
            RANGE_NAME['База ДР']
        )

        if not values_column:
            googlesheets_logger.info('No data found.')
            return

        first_row_for_write = len(values_column)
        last_row_for_write = first_row_for_write

        sheet = get_service_sacc(SCOPES).spreadsheets()
        value_input_option = 'USER_ENTERED'
        response_value_render_option = 'FORMATTED_VALUE'
        values = [[]]

        date = datetime.now().strftime('%y%m%d %H:%M:%S')

        bd_data = context_data['birthday_user_data']
        values[0].append(bd_data['phone'])  # 0
        values[0].append(bd_data['place'])
        values[0].append(bd_data['address'])
        values[0].append(bd_data['date'])
        values[0].append(bd_data['time'])
        values[0].append(bd_data['show_id'])
        values[0].append(bd_data['age'])
        values[0].append(bd_data['qty_child'])
        values[0].append(bd_data['qty_adult'])
        values[0].append(bd_data['format_bd'])
        values[0].append(bd_data['name_child'])
        values[0].append(bd_data['name'])
        values[0].append(date)  # 12
        values[0].extend(['FALSE', 'FALSE', 'FALSE'])
        values[0].append(context_data['user'].id)  # 16

        googlesheets_logger.info(values)

        end_column_index = len(values[0])

        value_range_body = {
            'values': values,
        }

        range_sheet = (RANGE_NAME['База ДР_'] +
                       f'R{first_row_for_write + 1}C1:' +
                       f'R{last_row_for_write + 1}C{end_column_index}')

        execute_update_googlesheet(sheet,
                                   range_sheet,
                                   value_input_option,
                                   response_value_render_option,
                                   value_range_body)

    except HttpError as err:
        googlesheets_logger.error(err)


def write_client_list_waiting(context: ContextTypes.DEFAULT_TYPE):
    try:
        values_column = get_values(
            SPREADSHEET_ID['Домик'],
            RANGE_NAME['Лист ожидания']
        )

        if not values_column:
            googlesheets_logger.info('No data found')
            return

        first_row_for_write = len(values_column)
        last_row_for_write = first_row_for_write + 1

        sheet = get_service_sacc(SCOPES).spreadsheets()
        value_input_option = 'USER_ENTERED'
        response_value_render_option = 'FORMATTED_VALUE'
        values: List[List[Any]] = [[]]

        date = datetime.now().strftime('%y%m%d %H:%M:%S')

        values[0].append(context.user_data['user'].id)
        values[0].append(context.user_data['user'].username)
        values[0].append(context.user_data['user'].full_name)
        reserve_user_data = context.user_data['reserve_user_data']
        choose_event_info = reserve_user_data['choose_event_info']
        values[0].append(reserve_user_data['client_data']['phone'])
        values[0].append(date)
        values[0].append(choose_event_info['event_id'])
        for i in range(5):
            values[0].append(
                f'=VLOOKUP('
                f'INDIRECT("R"&ROW()&"C"&MATCH("event_id";$2:$2;0);FALSE);'
                f'INDIRECT("\'Расписание\'!R1C1:C"&MATCH('
                f'INDIRECT("R2C"&COLUMN();FALSE);\'Расписание\'!$2:$2;0);FALSE);'
                f'MATCH(INDIRECT("R2C"&COLUMN();FALSE);\'Расписание\'!$2:$2;0);'
                f'0)'
            )
        values[0].append(
            '=if(INDIRECT("R"&ROW()&"C"&MATCH("flag_reserve";$2:$2;0);False);'
            '"Бронь";'
            'if(INDIRECT("R"&ROW()&"C"&MATCH("flag_call";$2:$2;0);False);'
            '"Позвонили";'
            'if(INDIRECT("R"&ROW()&"C"&COLUMN()-1;False)>0;'
            '"Позвонить";)))'
        )

        googlesheets_logger.info(values)

        end_column_index = len(values[0])

        value_range_body = {
            'values': values,
        }

        range_sheet = (RANGE_NAME['Лист ожидания_'] +
                       f'R{first_row_for_write + 1}C1:'
                       f'R{last_row_for_write + 1}C{end_column_index}')

        execute_update_googlesheet(sheet,
                                   range_sheet,
                                   value_input_option,
                                   response_value_render_option,
                                   value_range_body)

    except HttpError as err:
        googlesheets_logger.error(err)


def set_approve_order(bd_data, step=0) -> None:
    """

    :param bd_data:
    :type step: 0 - Заявка подтверждена
    1 - Предоплата
    2 - Предоплата подтверждена
    """
    try:
        values = get_values(
            SPREADSHEET_ID['Домик'],
            RANGE_NAME['База ДР_'] + 'A:E'
        )
        values_header = get_values(
            SPREADSHEET_ID['Домик'],
            RANGE_NAME['База ДР_'] + '1:1'
        )

        if not values:
            googlesheets_logger.info('No data found')
            return
        if not values_header:
            googlesheets_logger.info('No data found')
            return

        colum = 1
        for i, item in enumerate(values_header[0]):
            if item == 'Заявка подтверждена':
                colum += i

        for i, item in enumerate(values):
            if (item[0] == bd_data['phone'] and
                    item[2] == bd_data['address'] and
                    item[3] == bd_data['date'] and
                    item[4] == bd_data['time']):
                sheet = get_service_sacc(SCOPES).spreadsheets()
                value_input_option = 'USER_ENTERED'
                response_value_render_option = 'FORMATTED_VALUE'

                values = [[]]
                values[0].append(True)
                googlesheets_logger.info(values)

                value_range_body = {
                    'values': values,
                }

                range_sheet = (RANGE_NAME['База ДР_'] +
                               f'R{i + 1}C{colum + step}:' +
                               f'R{i + 2}C{colum + step}')

                execute_update_googlesheet(sheet,
                                           range_sheet,
                                           value_input_option,
                                           response_value_render_option,
                                           value_range_body)

    except HttpError as err:
        googlesheets_logger.error(err)


def execute_update_googlesheet(
        sheet,
        range_sheet,
        value_input_option,
        response_value_render_option,
        value_range_body
):
    request = sheet.values().update(
        spreadsheetId=SPREADSHEET_ID['Домик'],
        range=range_sheet,
        valueInputOption=value_input_option,
        responseValueRenderOption=response_value_render_option,
        body=value_range_body
    )
    try:
        response = request.execute()

        googlesheets_logger.info(": ".join(
            [
                'spreadsheetId: ',
                response['spreadsheetId'],
                '\n'
                'updatedRange: ',
                response['updatedRange']
            ]
        ))
    except TimeoutError as err:
        googlesheets_logger.error(err)
        googlesheets_logger.error(value_range_body)


def execute_append_googlesheet(
        sheet,
        range_sheet,
        value_input_option,
        response_value_render_option,
        value_range_body
):
    request = sheet.values().append(
        spreadsheetId=SPREADSHEET_ID['Домик'],
        range=range_sheet,
        valueInputOption=value_input_option,
        insertDataOption='INSERT_ROWS',
        includeValuesInResponse=True,
        responseValueRenderOption=response_value_render_option,
        body=value_range_body,
    )
    try:
        response = request.execute()

        googlesheets_logger.info(": ".join(
            [
                'spreadsheetId: ',
                response['spreadsheetId'],
                '\n'
                'tableRange: ',
                response['tableRange']
            ]
        ))
    except TimeoutError as err:
        googlesheets_logger.error(err)
        googlesheets_logger.error(value_range_body)

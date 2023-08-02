import logging
from datetime import datetime
from typing import List, Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utilities.settings import RANGE_NAME, SPREADSHEET_ID

googlesheets_logger = logging.getLogger('bot.googlesheets')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def get_service_sacc(scopes):
    credentials = service_account.Credentials.from_service_account_file(
        'utilities/credentials.json', scopes=scopes)

    return build('sheets', 'v4', credentials=credentials)


def get_values(spreadsheet_id, range_name):
    sheet = get_service_sacc(SCOPES).spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id,
                                range=range_name).execute()
    return result.get('values', [])


def get_data_from_spreadsheet(sheet):
    try:
        values = get_values(
            SPREADSHEET_ID['Домик'],
            sheet
        )

        if not values:
            googlesheets_logger.info('No data found')
            raise ValueError

        return values
    except HttpError as err:
        googlesheets_logger.error(err)
        raise ConnectionError


def update_quality_of_seats(row: str, qty: int):
    try:
        values = get_values(
            SPREADSHEET_ID['Домик'],
            f'База спектаклей!{row}:{row}'
        )

        if not values:
            googlesheets_logger.info('No data found')
            raise ValueError

        return values[0][qty]
    except HttpError as err:
        googlesheets_logger.error(err)


def write_data_for_reserve(row: str, numbers: List[int]) -> None:
    try:
        sheet = get_service_sacc(SCOPES).spreadsheets()
        value_input_option = 'RAW'
        values = [
            numbers,
        ]
        value_range_body = {
            'values': values,
        }

        range_sheet = ''
        if len(numbers) == 1:
            range_sheet = f'База спектаклей!F{row}'
        elif len(numbers) == 2:
            range_sheet = f'База спектаклей!E{row}:F{row}'

        request = sheet.values().update(
            spreadsheetId=SPREADSHEET_ID['Домик'],
            range=range_sheet,
            valueInputOption=value_input_option,
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
        except TimeoutError:
            googlesheets_logger.error(value_range_body)

    except HttpError as err:
        googlesheets_logger.error(err)


def write_client(
        client: dict,
        row_in_data_show: str,
        dict_reserve_option: dict
) -> None:
    try:
        values_column = get_values(
            SPREADSHEET_ID['Домик'],
            RANGE_NAME['База клиентов']
        )
        values_row = get_values(
            SPREADSHEET_ID['Домик'],
            RANGE_NAME[
                'База спектаклей_'] + f'A{row_in_data_show}:C{row_in_data_show}'
        )

        if not values_column:
            googlesheets_logger.info('No data found')
            return

        first_row_for_write = len(values_column)
        last_row_for_write = first_row_for_write + len(client['data_children'])

        sheet = get_service_sacc(SCOPES).spreadsheets()
        value_input_option = 'USER_ENTERED'
        response_value_render_option = 'FORMATTED_VALUE'
        values: List[Any] = []

        age = None
        for i in range(len(client['data_children'])):
            values.append([first_row_for_write + i])
            for key, item in client.items():
                if key == 'data_children':
                    item = item[i]
                    values[i].append(item[0])
                    if len(item[1]) < 5:
                        age = item[1]
                        # item[1] = f'=NOW()-YEAR(F{first_row_for_write + i + 1})'
                        item[1] = ''
                    values[i].append(item[1])
                else:
                    values[i].append(item)
            if age is not None:
                values[i].append(age)
            else:
                values[i].append(
                    f'=(TODAY()-E{first_row_for_write + i + 1})/365')
            values[i].extend(values_row[0])
            values[i].append(datetime.now().__str__())
            for key, value in dict_reserve_option.items():
                if key == 'flag_individual':
                    break
                values[i].append(value)
            values[i].append(bool(i))
        googlesheets_logger.info(values)

        end_column_index = len(values[0])

        value_range_body = {
            'values': values,
        }

        range_sheet = f'Клиентская база!' \
                      f'R{first_row_for_write + 1}C1:' \
                      f'R{last_row_for_write + 1}C{end_column_index}'

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
        except TimeoutError:
            googlesheets_logger.error(value_range_body)

    except HttpError as err:
        googlesheets_logger.error(err)


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

        bd_data = context_data['birthday_data']
        values[0].append(bd_data['phone'])  # 0
        values[0].append(bd_data['place'])
        values[0].append(bd_data['address'])
        values[0].append(bd_data['date'])
        values[0].append(bd_data['time'])
        values[0].append(bd_data['id_show'])
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
        except TimeoutError:
            googlesheets_logger.error(value_range_body)

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
                    item[3].split()[0] == bd_data['date'] and
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

    except HttpError as err:
        googlesheets_logger.error(err)

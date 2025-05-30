import logging
import os
from datetime import datetime
from typing import List, Any, Dict

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from telegram.ext import ContextTypes

from db import BaseTicket
from db.enum import TicketStatus
from db.models import CustomMadeEvent
from settings.config_loader import parse_settings
from settings.settings import RANGE_NAME

config = parse_settings()

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


def get_data_from_spreadsheet(
        spreadsheet_id,
        sheet,
        value_render_option='FORMATTED_VALUE'
):
    try:
        values = get_values(
            spreadsheet_id,
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


def get_column_info(spreadsheet_id, name_sheet):
    data_column_name = get_data_from_spreadsheet(
        spreadsheet_id, RANGE_NAME[name_sheet] + f'2:2')
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


def write_data_reserve(
        spreadsheet_id,
        event_id,
        numbers: List[int],
        option: int = 1
) -> None:
    try:
        dict_column_name, len_column = get_column_info(
            spreadsheet_id, 'База спектаклей_')

        values = get_values(
            spreadsheet_id,
            f'{RANGE_NAME['База спектаклей']}',
            value_render_option='UNFORMATTED_VALUE'
        )

        if not values:
            googlesheets_logger.info('No data found')
            raise ValueError

        row_event = 0
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
            spreadsheetId=spreadsheet_id,
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


async def write_client_reserve(
        spreadsheet_id,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        base_ticket: BaseTicket,
        ticket_status_value
) -> int:
    # TODO Заменить на запись в другой лист
    reserve_user_data = context.user_data['reserve_user_data']
    chose_price = reserve_user_data['chose_price']
    client_data: dict = reserve_user_data['client_data']
    ticket_ids = reserve_user_data['ticket_ids']
    event_ids = reserve_user_data['choose_schedule_event_ids']

    try:
        values_column = get_values(
            spreadsheet_id,
            RANGE_NAME['База клиентов']
        )

        if not values_column:
            googlesheets_logger.info('No data found')
            return 0

        sheet = get_service_sacc(SCOPES).spreadsheets()
        value_input_option = 'USER_ENTERED'
        response_value_render_option = 'FORMATTED_VALUE'
        values: List[Any] = []

        for i, event_id in enumerate(event_ids):
            values.append([])
            values[i].append(ticket_ids[i])
            values[i].append(chat_id)
            values[i].append(client_data['name_adult'])
            values[i].append(client_data['phone'])
            values[i].append(
                ' | '.join([i[0] for i in client_data['data_children']]))
            values[i].append('')
            values[i].append(
                ' | '.join([i[1] for i in client_data['data_children']]))

            # Спектакль
            values[i].append(event_id)
            for j in range(5):
                values[i].append(
                    f'=VLOOKUP('
                    f'INDIRECT("R"&ROW()&"C"&MATCH("event_id";$2:$2;0);FALSE);'
                    f'INDIRECT("\'Расписание\'!R1C1:C"&MATCH('
                    f'INDIRECT("R2C"&COLUMN();FALSE);\'Расписание\'!$2:$2;0);FALSE);'
                    f'MATCH(INDIRECT("R2C"&COLUMN();FALSE);\'Расписание\'!$2:$2;0);'
                    f'0)'
                )
            values[i].append(datetime.now().strftime('%y%m%d %H:%M:%S'))

            # add ticket info
            values[i].append(base_ticket.base_ticket_id)
            values[i].append(base_ticket.name)
            values[i].append(int(chose_price))
            values[i].append(base_ticket.quality_of_children)
            values[i].append(base_ticket.quality_of_adult +
                             base_ticket.quality_of_add_adult)

            (flag_exclude,
             flag_exclude_place_sum,
             flag_transfer) = get_flags_by_ticket_status(ticket_status_value)

            values[i].append(flag_exclude)
            values[i].append(flag_transfer)
            values[i].append(flag_exclude_place_sum)
            values[i].append(ticket_status_value)

        googlesheets_logger.info(values)

        end_column_index = len(values[0])

        value_range_body = {
            'values': values,
        }

        range_sheet = (RANGE_NAME['База клиентов_'] +
                       f'R1C1:R1C{end_column_index}')

        execute_append_googlesheet(spreadsheet_id,
                                   sheet,
                                   range_sheet,
                                   value_input_option,
                                   response_value_render_option,
                                   value_range_body)
        return 1
    except HttpError as err:
        googlesheets_logger.error(err)
        await context.bot.send_message(
            chat_id=context.config.bot.developer_chat_id,
            text=f'Не записался билет {ticket_ids} в клиентскую базу')
        return 0


def update_ticket_in_gspread(
        spreadsheet_id,
        ticket_id: int,
        ticket_status: str,
        option: int = 1
) -> None:
    try:
        dict_column_name, len_column = get_column_info(
            spreadsheet_id, 'База клиентов_')

        values = get_values(
            spreadsheet_id,
            f'{RANGE_NAME['База клиентов']}',
            value_render_option='UNFORMATTED_VALUE'
        )

        if not values:
            googlesheets_logger.info('No data found')
            raise ValueError

        row_event = 0
        for i, row in enumerate(values):
            if ticket_id == row[dict_column_name['ticket_id']]:
                row_event = i + 1
        if row_event <= 1:
            raise ValueError('Билет удален из гугл-таблицы')

        sheet = get_service_sacc(SCOPES).spreadsheets()
        value_input_option = 'RAW'
        major_dimension = 'ROWS'
        data = []

        match option:
            case 1:
                (flag_exclude,
                 flag_exclude_place_sum,
                 flag_transfer) = get_flags_by_ticket_status(ticket_status)

                col1 = dict_column_name['flag_exclude'] + 1
                col2 = dict_column_name['ticket_status'] + 1
                range_sheet = (f'{RANGE_NAME['База клиентов_']}'
                               f'R{row_event}C{col1}:R{row_event}C{col2}')
                data.append({
                    'range': range_sheet,
                    'majorDimension': major_dimension,
                    'values': [[
                        flag_exclude,
                        flag_transfer,
                        flag_exclude_place_sum,
                        ticket_status,
                    ]]
                })

        value_range_body = {
            'valueInputOption': value_input_option,
            'data': data
        }
        request = sheet.values().batchUpdate(
            spreadsheetId=spreadsheet_id,
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
    except ValueError as e:
        googlesheets_logger.error(e)


def get_flags_by_ticket_status(ticket_status_value):
    flag_exclude = False
    flag_transfer = False
    flag_exclude_place_sum = False
    if (
            ticket_status_value == TicketStatus.CREATED.value or
            ticket_status_value == TicketStatus.CANCELED.value or
            ticket_status_value == TicketStatus.REJECTED.value
    ):
        flag_exclude = True
        flag_transfer = False
        flag_exclude_place_sum = True
    if (
            ticket_status_value == TicketStatus.REFUNDED.value or
            ticket_status_value == TicketStatus.MIGRATED.value
    ):
        flag_exclude = True
        flag_transfer = True
        flag_exclude_place_sum = True
    return flag_exclude, flag_exclude_place_sum, flag_transfer


def write_client_cme(
        spreadsheet_id,
        custom_made_event: CustomMadeEvent
) -> None:
    dict_column_name, len_column = get_column_info(
        spreadsheet_id, 'База ДР_')

    values_column = get_values(
        spreadsheet_id,
        RANGE_NAME['База ДР']
    )

    if not values_column:
        googlesheets_logger.info('No data found.')
        return

    sheet = get_service_sacc(SCOPES).spreadsheets()
    value_input_option = 'USER_ENTERED'
    response_value_render_option = 'FORMATTED_VALUE'
    values = [[]]

    created_at = custom_made_event.created_at.strftime('%y%m%d %H:%M:%S')
    cme = custom_made_event.model_dump()
    for key, name in dict_column_name.items():
        if key in cme:
            match key:
                case 'created_at':
                    values[0].append(created_at)
                case 'status':
                    values[0].append(custom_made_event.status.value)
                case _:
                    values[0].append(cme[key])
        elif key == 'name_theater':
            values[0].append(
                '=VLOOKUP('
                'INDEX($A:$Z;ROW();MATCH("theater_event_id";$2:$2;0));'
                '\'Репертуар\'!$A$3:$F;'
                'MATCH("name";\'Репертуар\'!$2:$2;0)'
                ')'
            )
        else:
            values[0].append('')

    values[0][dict_column_name['created_at']] = created_at

    googlesheets_logger.info(values)

    end_column_index = len(values[0])

    value_range_body = {
        'values': values,
    }

    range_sheet = (RANGE_NAME['База ДР_'] +
                   f'R1C1:R1C{end_column_index}')

    execute_append_googlesheet(spreadsheet_id,
                               sheet,
                               range_sheet,
                               value_input_option,
                               response_value_render_option,
                               value_range_body)


def write_client_list_waiting(
        spreadsheet_id,
        context: ContextTypes.DEFAULT_TYPE
):
    try:
        values_column = get_values(
            spreadsheet_id,
            RANGE_NAME['Лист ожидания']
        )

        if not values_column:
            googlesheets_logger.info('No data found')
            return

        sheet = get_service_sacc(SCOPES).spreadsheets()
        value_input_option = 'USER_ENTERED'
        response_value_render_option = 'FORMATTED_VALUE'
        values: List[List[Any]] = [[]]

        date = datetime.now().strftime('%y%m%d %H:%M:%S')
        reserve_user_data = context.user_data['reserve_user_data']
        schedule_event_id = reserve_user_data['choose_schedule_event_id']

        values[0].append(context.user_data['user'].id)
        values[0].append(context.user_data['user'].username)
        values[0].append(context.user_data['user'].full_name)
        values[0].append(reserve_user_data['client_data']['phone'])
        values[0].append(date)
        values[0].append(schedule_event_id)
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
                       f'R1C1:R1C{end_column_index}')

        execute_append_googlesheet(spreadsheet_id,
                                   sheet,
                                   range_sheet,
                                   value_input_option,
                                   response_value_render_option,
                                   value_range_body)

    except HttpError as err:
        googlesheets_logger.error(err)


def update_cme_in_gspread(
        spreadsheet_id,
        cme_id,
        status
) -> None:
    dict_column_name, len_column = get_column_info(
        spreadsheet_id, 'База ДР_')
    values = get_values(
        spreadsheet_id,
        f'{RANGE_NAME['База ДР']}',
        value_render_option='UNFORMATTED_VALUE'
    )

    if not values:
        googlesheets_logger.info('No data found')
        raise ValueError

    row_cme = 0
    for i, row in enumerate(values):
        if int(cme_id) == row[dict_column_name['id']]:
            row_cme = i + 1
    if row_cme == 0:
        raise ValueError('Билет удален из гугл-таблицы')

    sheet = get_service_sacc(SCOPES).spreadsheets()
    value_input_option = 'USER_ENTERED'
    response_value_render_option = 'FORMATTED_VALUE'

    values = [[]]
    values[0].append(status)
    googlesheets_logger.info(values)

    value_range_body = {'values': values}

    col1 = dict_column_name['status'] + 1
    col2 = col1 + 1
    range_sheet = (f'{RANGE_NAME['База ДР_']}'
                   f'R{row_cme}C{col1}:R{row_cme}C{col2}')

    execute_update_googlesheet(spreadsheet_id,
                               sheet,
                               range_sheet,
                               value_input_option,
                               response_value_render_option,
                               value_range_body)


def execute_update_googlesheet(
        spreadsheet_id,
        sheet,
        range_sheet,
        value_input_option,
        response_value_render_option,
        value_range_body
):
    request = sheet.values().update(
        spreadsheetId=spreadsheet_id,
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
        spreadsheet_id,
        sheet,
        range_sheet,
        value_input_option,
        response_value_render_option,
        value_range_body
):
    request = sheet.values().append(
        spreadsheetId=spreadsheet_id,
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

import asyncio
import logging
import os
from datetime import datetime
from typing import List, Any, Dict

from google.oauth2.service_account import Credentials
import gspread.exceptions
from gspread_asyncio import (
    ClientManager,
    Spreadsheet,
    Client,
)
import requests

from db import BaseTicket
from db.enum import TicketStatus
from db.models import CustomMadeEvent
from settings.config_loader import parse_settings
from settings.settings import RANGE_NAME
from utilities.utl_date import datetime_to_sheets_date_time

config = parse_settings()

creds_file = 'credentials.json'
path = os.getenv('CONFIG_PATH')
if path is not None:
    creds_file = os.path.join(path, creds_file)
else:
    creds_file = config.sheets.credentials_path
googlesheets_logger = logging.getLogger('bot.googlesheets')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def get_creds():
    creds = Credentials.from_service_account_file(creds_file)
    scoped = creds.with_scopes(SCOPES)
    return scoped


class RetryingClientManager(ClientManager):
    def __init__(self, *args, max_retries: int = 3, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_retries = max_retries

    async def _call(self, method, *args, **kwargs):
        if "api_call_count" in kwargs:
            api_call_count = kwargs["api_call_count"]
            del kwargs["api_call_count"]
        else:
            api_call_count = 1

        method_name = getattr(method, '__name__', str(method))
        attempt = 0
        while True:
            attempt += 1
            await self.call_lock.acquire()
            try:
                for _ in range(api_call_count):
                    await self.delay()
                await self.before_gspread_call(method, args, kwargs)
                return await asyncio.to_thread(method, *args, **kwargs)
            except gspread.exceptions.APIError as e:
                code = getattr(getattr(e, 'response', None), 'status_code', None)
                if code is not None and 400 <= code <= 499 and code != 429:
                    googlesheets_logger.error(
                        f"Non-retryable client error {code} in {method_name}: {e}",
                        exc_info=True,
                    )
                    raise
                if attempt > self.max_retries:
                    googlesheets_logger.error(
                        f"Max retries ({self.max_retries}) exceeded for {method_name}: {e}",
                        exc_info=True,
                    )
                    raise
                await self.handle_gspread_error(e, method, args, kwargs, attempt=attempt)
            except requests.RequestException as e:
                if attempt > self.max_retries:
                    googlesheets_logger.error(
                        f"Max retries ({self.max_retries}) exceeded for {method_name}: {e}",
                        exc_info=True,
                    )
                    raise
                await self.handle_requests_error(e, method, args, kwargs, attempt=attempt)
            finally:
                self.call_lock.release()

    async def before_gspread_call(self, method, args, kwargs):
        method_name = getattr(method, '__name__', str(method))
        googlesheets_logger.debug(f"Calling {method_name} {args!s} {kwargs!s}")

    async def handle_requests_error(self, e, method, args, kwargs, attempt: int = 1):
        backoff = self.gspread_delay * (2 ** (attempt - 1))
        method_name = getattr(method, '__name__', str(method))
        googlesheets_logger.warning(
            f"Network error in {method_name} (attempt {attempt}/{self.max_retries}): {e}. Retrying in {backoff:.1f}s..."
        )
        await asyncio.sleep(backoff)

    async def handle_gspread_error(self, e, method, args, kwargs, attempt: int = 1):
        backoff = self.gspread_delay * (2 ** (attempt - 1))
        method_name = getattr(method, '__name__', str(method))
        code = getattr(getattr(e, 'response', None), 'status_code', None)
        googlesheets_logger.warning(
            f"Google API error in {method_name} (attempt {attempt}/{self.max_retries}, status={code}): {e}. Retrying in {backoff:.1f}s..."
        )
        await asyncio.sleep(backoff)


_agcm = RetryingClientManager(get_creds, gspread_timeout=(10.0, 60.0), max_retries=3)


async def _open_spreadsheet(spreadsheet_id: str) -> Spreadsheet:
    agc: Client = await _agcm.authorize()
    ss: Spreadsheet = await agc.open_by_key(spreadsheet_id)
    return ss


async def _get_values(
        spreadsheet_id: str,
        range_name: str,
        value_render_option: str = 'FORMATTED_VALUE'
) -> List[List[Any]]:
    ss: Spreadsheet = await _open_spreadsheet(spreadsheet_id)
    values = await ss.values_get(
        range_name, params={'valueRenderOption': value_render_option})
    return values.get('values', [])


async def _get_data_from_spreadsheet(
        spreadsheet_id: str,
        sheet: str,
        value_render_option: str = 'FORMATTED_VALUE'
) -> List[List[Any]]:
    values = await _get_values(spreadsheet_id, sheet, value_render_option)
    googlesheets_logger.info('_get_values done')
    if not values:
        googlesheets_logger.info('No data found')
        raise ValueError('No data found')
    return values


async def _get_column_info(spreadsheet_id: str, name_sheet: str):
    data_column_name = await _get_data_from_spreadsheet(
        spreadsheet_id, RANGE_NAME[name_sheet] + '2:2')
    dict_column_name: Dict[int | str, int] = {}
    for i, item in enumerate(data_column_name[0]):
        if item == '':
            item = i
        dict_column_name[item] = i

    if len(dict_column_name) != len(data_column_name[0]):
        googlesheets_logger.warning(
            'dict_column_name, len(data_column_name[0]) не равны')
        googlesheets_logger.warning(
            f"{len(dict_column_name)} != {len(data_column_name[0])}")

    return dict_column_name, len(data_column_name[0])


def _get_flags_by_ticket_status(ticket_status_value):
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


async def load_from_gspread(
        sheet_id: str,
        name_sh: str,
        value_render_option: str = 'FORMATTED_VALUE',
):
    """
    Унифицированная загрузка данных из Google Sheets по имени листа.

    Параметры:
      - sheet_id: ID таблицы
      - name_sh: ключ из RANGE_NAME (например, 'База спектаклей_', 'Список спектаклей_', ...)
      - value_render_option: формат данных из гугл-таблицы

    Возвращает кортеж (data, dict_column_name).
    """
    dict_column_name, len_col = await _get_column_info(sheet_id, name_sh)

    first_col = await _get_data_from_spreadsheet(
        sheet_id, RANGE_NAME[name_sh] + 'A:A')

    len_row = len(first_col)
    sheet_range = f"{RANGE_NAME[name_sh]}R2C1:R{len_row}C{len_col}"

    data = await _get_data_from_spreadsheet(
        sheet_id,
        sheet_range,
        value_render_option=value_render_option
    )
    return data, dict_column_name


async def write_data_reserve(
        spreadsheet_id: str,
        event_id: int,
        numbers: List[int],
        option: int = 1
) -> None:
    try:
        dict_column_name, _ = await _get_column_info(
            spreadsheet_id, 'База спектаклей_')
        values = await _get_values(
            spreadsheet_id,
            f"{RANGE_NAME['База спектаклей_']}" + 'A:AA',
            value_render_option='UNFORMATTED_VALUE'
        )
        if not values:
            googlesheets_logger.info('No data found')
            raise ValueError
        row_event = 0
        for i, row in enumerate(values):
            if event_id == row[dict_column_name['event_id']]:
                row_event = i + 1
        value_input_option = 'RAW'
        major_dimension = 'ROWS'
        data = []
        match option:
            case 1:
                col1 = dict_column_name['qty_child_free_seat'] + 1
                col2 = dict_column_name['qty_child_nonconfirm_seat'] + 1
                range_sheet = (
                    f"{RANGE_NAME['База спектаклей_']}" f"R{row_event}C{col1}:R{row_event}C{col2}")
                data.append(
                    {'range': range_sheet, 'majorDimension': major_dimension,
                     'values': [numbers[0:2]]})
                col1 = dict_column_name['qty_adult_free_seat'] + 1
                col2 = dict_column_name['qty_adult_nonconfirm_seat'] + 1
                range_sheet = (
                    f"{RANGE_NAME['База спектаклей_']}" f"R{row_event}C{col1}:R{row_event}C{col2}")
                data.append(
                    {'range': range_sheet, 'majorDimension': major_dimension,
                     'values': [numbers[2:4]]})
            case 2:
                col = dict_column_name['qty_child_nonconfirm_seat'] + 1
                range_sheet = (
                    f"{RANGE_NAME['База спектаклей_']}" f"R{row_event}C{col}")
                data.append(
                    {'range': range_sheet, 'majorDimension': major_dimension,
                     'values': [[numbers[0]]]})
                col = dict_column_name['qty_adult_nonconfirm_seat'] + 1
                range_sheet = (
                    f"{RANGE_NAME['База спектаклей_']}" f"R{row_event}C{col}")
                data.append(
                    {'range': range_sheet, 'majorDimension': major_dimension,
                     'values': [[numbers[1]]]})
            case 3:
                col = dict_column_name['qty_child_free_seat'] + 1
                range_sheet = (
                    f"{RANGE_NAME['База спектаклей_']}" f"R{row_event}C{col}")
                data.append({
                    'range': range_sheet,
                    'majorDimension': major_dimension,
                    'values': [[numbers[0]]]
                })
                col = dict_column_name['qty_adult_free_seat'] + 1
                range_sheet = (
                    f"{RANGE_NAME['База спектаклей_']}" f"R{row_event}C{col}")
                data.append({
                    'range': range_sheet,
                    'majorDimension': major_dimension,
                    'values': [[numbers[1]]]
                })

        await _write_data_to_batch_update(
            data, spreadsheet_id, value_input_option)

    except Exception as err:
        googlesheets_logger.error(
            f"Error in write_data_reserve: {err}", exc_info=True)
        raise


async def write_client_reserve(
        spreadsheet_id,
        reserve_user_data: dict,
        chat_id: int,
        base_ticket_dto: dict,
        ticket_status_value: str
) -> int:
    # TODO Заменить на запись в другой лист
    chose_price = reserve_user_data['chose_price']
    client_data: dict = reserve_user_data['client_data']
    ticket_ids = reserve_user_data['ticket_ids']
    event_ids = reserve_user_data['choose_schedule_event_ids']

    try:
        values_column = await _get_values(
            spreadsheet_id,
            RANGE_NAME['База клиентов_'] + 'A:A'
        )

        if not values_column:
            googlesheets_logger.info('No data found')
            return 0

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
            base_ticket = BaseTicket(**base_ticket_dto)
            values[i].append(base_ticket.base_ticket_id)
            values[i].append(base_ticket.name)
            values[i].append(int(chose_price))
            values[i].append(base_ticket.quality_of_children)
            values[i].append(base_ticket.quality_of_adult +
                             base_ticket.quality_of_add_adult)

            (flag_exclude,
             flag_exclude_place_sum,
             flag_transfer) = _get_flags_by_ticket_status(ticket_status_value)

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

        await _execute_append_googlesheet(spreadsheet_id,
                                          range_sheet,
                                          value_input_option,
                                          response_value_render_option,
                                          value_range_body)
        return 1
    except Exception as err:
        googlesheets_logger.error(
            f"Error in write_client_reserve: {err}", exc_info=True)
        return 0


async def _write_data_to_batch_update(
        data,
        spreadsheet_id,
        value_input_option
):
    value_range_body = {
        'valueInputOption': value_input_option,
        'data': data
    }
    ss = await _open_spreadsheet(spreadsheet_id)

    try:
        responses = await ss.values_batch_update(body=value_range_body)
        googlesheets_logger.info(
            f"spreadsheetId: {responses.get('spreadsheetId', '')}")
        for response in responses.get('responses', []):
            googlesheets_logger.info(': '.join(
                ['updatedRange: ', response.get('updatedRange', '')]))
    except TimeoutError as err:
        googlesheets_logger.error(err)
        googlesheets_logger.error(value_range_body)
        raise
    except (requests.RequestException, gspread.exceptions.APIError, Exception) as err:
        googlesheets_logger.error(
            f"Error in _write_data_to_batch_update: {err}", exc_info=True)
        raise


async def write_client_cme(
        spreadsheet_id,
        custom_made_event: CustomMadeEvent
) -> None:
    dict_column_name, _ = await _get_column_info(
        spreadsheet_id, 'База ДР_')

    values_column = await _get_values(
        spreadsheet_id,
        RANGE_NAME['База ДР_'] + 'A:A'
    )

    if not values_column:
        googlesheets_logger.info('No data found.')
        return

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

    await _execute_append_googlesheet(spreadsheet_id,
                                      range_sheet,
                                      value_input_option,
                                      response_value_render_option,
                                      value_range_body)


async def write_client_list_waiting(
        spreadsheet_id,
        context: dict
):
    try:
        value_input_option = 'USER_ENTERED'
        response_value_render_option = 'FORMATTED_VALUE'
        values: List[List[Any]] = [[]]

        date = datetime.now().strftime('%y%m%d %H:%M:%S')
        user_id = context['user_id']
        username = context['username']
        full_name = context['full_name']
        phone = context['phone']
        schedule_event_id = context['schedule_event_id']

        values[0].append(user_id)
        values[0].append(username)
        values[0].append(full_name)
        values[0].append(phone)
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

        await _execute_append_googlesheet(spreadsheet_id,
                                          range_sheet,
                                          value_input_option,
                                          response_value_render_option,
                                          value_range_body)

    except Exception as err:
        googlesheets_logger.error(
            f"Error in write_client_list_waiting: {err}", exc_info=True)
        raise


async def update_ticket_in_gspread(
        spreadsheet_id,
        ticket_id: int,
        ticket_status,
        option: int = 1
) -> None:
    try:
        dict_column_name, _ = await _get_column_info(
            spreadsheet_id, 'База клиентов_')

        values = await _get_values(
            spreadsheet_id,
            f"{RANGE_NAME['База клиентов_']}" + 'A:A',
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

        value_input_option = 'RAW'
        major_dimension = 'ROWS'
        data = []

        match option:
            case 1:
                (flag_exclude,
                 flag_exclude_place_sum,
                 flag_transfer) = _get_flags_by_ticket_status(ticket_status)

                col1 = dict_column_name['flag_exclude'] + 1
                col2 = dict_column_name['ticket_status'] + 1
                range_sheet = (f"{RANGE_NAME['База клиентов_']}"
                               f"R{row_event}C{col1}:R{row_event}C{col2}")
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

        await _write_data_to_batch_update(
            data, spreadsheet_id, value_input_option)

    except Exception as err:
        googlesheets_logger.error(
            f"Error in update_ticket_in_gspread: {err}", exc_info=True)
        raise


async def update_cme_in_gspread(
        spreadsheet_id,
        cme_id,
        status
) -> None:
    dict_column_name, _ = await _get_column_info(
        spreadsheet_id, 'База ДР_')
    values = await _get_values(
        spreadsheet_id,
        f"{RANGE_NAME['База ДР_']}" + 'A:A',
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

    value_input_option = 'USER_ENTERED'
    response_value_render_option = 'FORMATTED_VALUE'

    values_body = [[]]
    values_body[0].append(status)
    googlesheets_logger.info(values_body)

    value_range_body = {'values': values_body}

    col1 = dict_column_name['status'] + 1
    col2 = col1 + 1
    range_sheet = (f"{RANGE_NAME['База ДР_']}"
                   f"R{row_cme}C{col1}:R{row_cme}C{col2}")

    await _execute_update_googlesheet(spreadsheet_id,
                                      range_sheet,
                                      value_input_option,
                                      response_value_render_option,
                                      value_range_body)


async def _execute_update_googlesheet(
        spreadsheet_id,
        range_sheet,
        value_input_option,
        response_value_render_option,
        value_range_body
):
    sh = await _open_spreadsheet(spreadsheet_id)
    params = {
        'valueInputOption': value_input_option,
        'responseValueRenderOption': response_value_render_option,
    }
    try:
        response = await sh.values_update(
            range_sheet, params=params, body=value_range_body)
        googlesheets_logger.info(': '.join([
            'spreadsheetId: ', response.get('spreadsheetId', ''), '\n',
            'updatedRange: ', response.get('updatedRange', '')
        ]))
    except TimeoutError as err:
        googlesheets_logger.error(err)
        googlesheets_logger.error(value_range_body)
        raise
    except (requests.RequestException, gspread.exceptions.APIError, Exception) as err:
        googlesheets_logger.error(
            f"Error in _execute_update_googlesheet: {err}", exc_info=True)
        raise


async def _execute_append_googlesheet(
        spreadsheet_id,
        range_sheet,
        value_input_option,
        response_value_render_option,
        value_range_body
):
    sh = await _open_spreadsheet(spreadsheet_id)
    params = {
        'valueInputOption': value_input_option,
        'insertDataOption': 'INSERT_ROWS',
        'includeValuesInResponse': True,
        'responseValueRenderOption': response_value_render_option,
    }
    try:
        response = await sh.values_append(
            range_sheet, params=params, body=value_range_body)
        googlesheets_logger.info(': '.join([
            'spreadsheetId: ', response.get('spreadsheetId', ''), '\n',
            'tableRange: ', response.get('tableRange', '')
        ]))
    except TimeoutError as err:
        googlesheets_logger.error(err)
        googlesheets_logger.error(value_range_body)
        raise
    except (requests.RequestException, gspread.exceptions.APIError, Exception) as err:
        googlesheets_logger.error(
            f"Error in _execute_append_googlesheet: {err}", exc_info=True)
        raise


async def sync_schedule_events_to_gspread(
        spreadsheet_id: str,
        run_id: str,
        items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Выполняет выгрузку элементов расписания в Google Таблицу с проверкой конфликтов.
    """
    name_sh = 'База спектаклей_'
    dict_column_name, len_col = await _get_column_info(spreadsheet_id, name_sh)

    required_headers = [
        'event_id', 'event_type', 'theater_event_id',
        'flag_turn_on_off', 'date_show', 'time_show',
        'qty_child', 'qty_adult', 'flag_gift',
        'flag_christmas_tree', 'flag_santa', 'ticket_price_type'
    ]
    missing_headers = [h for h in required_headers if h not in dict_column_name]
    if missing_headers:
        googlesheets_logger.error(f"Missing required columns in sheet {name_sh}: {missing_headers}")
        return [
            {
                'item_id': it['item_id'],
                'event_id': it['event_id'],
                'change_ids': it['change_ids'],
                'status': 'failed',
                'details': {'error': f"Отсутствуют обязательные колонки: {missing_headers}"},
                'unsupported_fields': ['base_ticket_ids'] if 'base_ticket_ids' in it.get('fields', []) else []
            }
            for it in items
        ]

    values = await _get_values(
        spreadsheet_id,
        f"{RANGE_NAME[name_sh]}A:AA",
        value_render_option='UNFORMATTED_VALUE'
    )
    if not values:
        values = []

    existing_event_rows: Dict[int, int] = {}
    duplicate_event_ids: set = set()

    for idx, row in enumerate(values):
        row_idx = idx + 1  # 1-based index
        if row_idx < 3:
            continue
        event_id_col = dict_column_name['event_id']
        if len(row) > event_id_col:
            raw_eid = row[event_id_col]
            if raw_eid != '' and raw_eid is not None:
                try:
                    eid = int(raw_eid)
                    if eid in existing_event_rows:
                        duplicate_event_ids.add(eid)
                    else:
                        existing_event_rows[eid] = row_idx
                except (ValueError, TypeError):
                    pass

    def map_snapshot_to_sheet(snapshot: Any) -> Dict[str, Any]:
        if not snapshot or not isinstance(snapshot, dict):
            return {}
        sheets_date, sheets_time = None, None
        if snapshot.get('datetime_event'):
            sheets_date, sheets_time = datetime_to_sheets_date_time(snapshot['datetime_event'])

        mapped = {
            'event_id': int(snapshot.get('id') or snapshot.get('event_id') or 0),
            'event_type': int(snapshot.get('type_event_id', 0)),
            'theater_event_id': int(snapshot.get('theater_event_id', 0)),
            'flag_turn_on_off': bool(snapshot.get('flag_turn_in_bot', False)),
            'date_show': sheets_date,
            'time_show': sheets_time,
            'qty_child': int(snapshot.get('qty_child', 0)),
            'qty_adult': int(snapshot.get('qty_adult', 0)),
            'flag_gift': bool(snapshot.get('flag_gift', False)),
            'flag_christmas_tree': bool(snapshot.get('flag_christmas_tree', False)),
            'flag_santa': bool(snapshot.get('flag_santa', False)),
            'ticket_price_type': str(snapshot.get('ticket_price_type', '')),
        }
        if 'place_id' in dict_column_name:
            p_id = snapshot.get('place_id')
            mapped['place_id'] = int(p_id) if p_id is not None else None
        return mapped

    def compare_sheet_val(col_name: str, sheet_val: Any, target_val: Any) -> bool:
        if target_val is None:
            return sheet_val == '' or sheet_val is None
        if col_name == 'time_show':
            s_f = float(sheet_val) if sheet_val != '' and sheet_val is not None else 0.0
            t_f = float(target_val) if target_val != '' and target_val is not None else 0.0
            return abs(s_f - t_f) < 0.001
        if col_name in ('flag_turn_on_off', 'flag_gift', 'flag_christmas_tree', 'flag_santa'):
            return bool(sheet_val) == bool(target_val)
        if col_name == 'place_id':
            if sheet_val == '' or sheet_val is None:
                return target_val is None
            try:
                return int(sheet_val) == int(target_val)
            except (ValueError, TypeError):
                return False
        if col_name in ('event_id', 'event_type', 'theater_event_id', 'qty_child', 'qty_adult', 'date_show'):
            s_i = int(sheet_val) if sheet_val != '' and sheet_val is not None else 0
            t_i = int(target_val) if target_val != '' and target_val is not None else 0
            return s_i == t_i
        return str(sheet_val or '').strip() == str(target_val or '').strip()

    field_to_columns = {
        'type_event_id': ['event_type'],
        'theater_event_id': ['theater_event_id'],
        'place_id': ['place_id'] if 'place_id' in dict_column_name else [],
        'flag_turn_in_bot': ['flag_turn_on_off'],
        'datetime_event': ['date_show', 'time_show'],
        'qty_child': ['qty_child'],
        'qty_adult': ['qty_adult'],
        'flag_gift': ['flag_gift'],
        'flag_christmas_tree': ['flag_christmas_tree'],
        'flag_santa': ['flag_santa'],
        'ticket_price_type': ['ticket_price_type'],
    }

    results: List[Dict[str, Any]] = []
    batch_updates: List[Dict[str, Any]] = []
    appended_rows: List[List[Any]] = []

    for item in items:
        item_id = item['item_id']
        event_id = int(item['event_id'])
        change_ids = item['change_ids']
        operation = item['operation']
        fields = item.get('fields', [])
        unsupported = ['base_ticket_ids'] if 'base_ticket_ids' in fields else []

        if event_id in duplicate_event_ids:
            results.append({
                'item_id': item_id,
                'event_id': event_id,
                'change_ids': change_ids,
                'status': 'failed',
                'details': {'error': f"В таблице обнаружены дубликаты строк с event_id={event_id}"},
                'unsupported_fields': unsupported,
            })
            continue

        desired_mapped = map_snapshot_to_sheet(item.get('desired'))
        expected_mapped = map_snapshot_to_sheet(item.get('expected'))

        cols_to_check = []
        for f in fields:
            if f in field_to_columns:
                cols_to_check.extend(field_to_columns[f])
        cols_to_check = [c for c in cols_to_check if c in dict_column_name]
        if not cols_to_check and operation == 'update':
            results.append({
                'item_id': item_id,
                'event_id': event_id,
                'change_ids': change_ids,
                'status': 'already_equal',
                'unsupported_fields': unsupported,
            })
            continue

        if operation == 'create':
            if event_id in existing_event_rows:
                row_idx = existing_event_rows[event_id]
                row_data = values[row_idx - 1]
                all_match = True
                diffs = {}
                for col in required_headers:
                    if col in dict_column_name:
                        c_idx = dict_column_name[col]
                        val_in_sheet = row_data[c_idx] if c_idx < len(row_data) else ''
                        val_desired = desired_mapped.get(col)
                        if not compare_sheet_val(col, val_in_sheet, val_desired):
                            all_match = False
                            diffs[col] = {
                                'field': col,
                                'expected': expected_mapped.get(col),
                                'actual_in_sheet': val_in_sheet,
                                'desired': val_desired
                            }
                if all_match:
                    results.append({
                        'item_id': item_id,
                        'event_id': event_id,
                        'change_ids': change_ids,
                        'status': 'already_equal',
                        'unsupported_fields': unsupported,
                    })
                else:
                    results.append({
                        'item_id': item_id,
                        'event_id': event_id,
                        'change_ids': change_ids,
                        'status': 'conflict',
                        'details': {'conflicts': diffs},
                        'unsupported_fields': unsupported,
                    })
            else:
                new_row = [''] * len_col
                for col, val in desired_mapped.items():
                    if col in dict_column_name:
                        new_row[dict_column_name[col]] = val
                appended_rows.append(new_row)
                results.append({
                    'item_id': item_id,
                    'event_id': event_id,
                    'change_ids': change_ids,
                    'status': 'created',
                    'unsupported_fields': unsupported,
                })

        elif operation == 'update':
            if event_id not in existing_event_rows:
                results.append({
                    'item_id': item_id,
                    'event_id': event_id,
                    'change_ids': change_ids,
                    'status': 'failed',
                    'details': {'error': f"Строка с event_id={event_id} не найдена в Google Таблице"},
                    'unsupported_fields': unsupported,
                })
                continue

            row_idx = existing_event_rows[event_id]
            row_data = values[row_idx - 1]

            already_equal = True
            conflict = False
            conflict_details = {}
            cells_to_update = []

            for col in cols_to_check:
                c_idx = dict_column_name[col]
                sheet_val = row_data[c_idx] if c_idx < len(row_data) else ''
                desired_val = desired_mapped.get(col)
                expected_val = expected_mapped.get(col)

                if compare_sheet_val(col, sheet_val, desired_val):
                    continue

                already_equal = False
                if expected_val is not None and not compare_sheet_val(col, sheet_val, expected_val):
                    conflict = True
                    conflict_details[col] = {
                        'field': col,
                        'expected': expected_val,
                        'actual_in_sheet': sheet_val,
                        'desired': desired_val
                    }
                else:
                    cells_to_update.append((col, c_idx, desired_val))

            if already_equal:
                results.append({
                    'item_id': item_id,
                    'event_id': event_id,
                    'change_ids': change_ids,
                    'status': 'already_equal',
                    'unsupported_fields': unsupported,
                })
            elif conflict:
                results.append({
                    'item_id': item_id,
                    'event_id': event_id,
                    'change_ids': change_ids,
                    'status': 'conflict',
                    'details': {'conflicts': conflict_details},
                    'unsupported_fields': unsupported,
                })
            else:
                for col, c_idx, desired_val in cells_to_update:
                    col_num = c_idx + 1
                    cell_range = f"{RANGE_NAME[name_sh]}R{row_idx}C{col_num}"
                    batch_updates.append({
                        'range': cell_range,
                        'majorDimension': 'ROWS',
                        'values': [[desired_val]]
                    })
                results.append({
                    'item_id': item_id,
                    'event_id': event_id,
                    'change_ids': change_ids,
                    'status': 'updated',
                    'unsupported_fields': unsupported,
                })

    if batch_updates:
        await _write_data_to_batch_update(batch_updates, spreadsheet_id, value_input_option='USER_ENTERED')

    if appended_rows:
        append_body = {'values': appended_rows}
        range_append = f"{RANGE_NAME[name_sh]}R1C1:R1C{len_col}"
        await _execute_append_googlesheet(
            spreadsheet_id,
            range_append,
            value_input_option='USER_ENTERED',
            response_value_render_option='FORMATTED_VALUE',
            value_range_body=append_body
        )

    return results

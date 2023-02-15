from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from settings import RANGE_NAME, SPREADSHEET_ID

from pprint import pprint


SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def get_service_sacc(scopes):
    credentials = service_account.Credentials.from_service_account_file(
        'credentials.json', scopes=scopes)
    
    return build('sheets', 'v4', credentials=credentials)


def get_values(spreadsheet_id, range_name):
    sheet = get_service_sacc(SCOPES).spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id,
                                range=range_name).execute()
    return result.get('values', [])


def data_show():
    try:
        values = get_values(
            SPREADSHEET_ID['Домик'],
            RANGE_NAME['База спектаклей']
        )

        if not values:
            print('No data found.')
            return

        return values
    except HttpError as err:
        print(err)


def update_quality_of_seats(row, i):
    try:
        values = get_values(
            SPREADSHEET_ID['Домик'],
            f'База спектаклей!{row}:{row}'
        )

        if not values:
            print('No data found.')
            return

        return values[0][i]
    except HttpError as err:
        print(err)


def confirm(row, numbers):
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
            body=value_range_body)
        response = request.execute()

        pprint(response)

    except HttpError as err:
        print(err)

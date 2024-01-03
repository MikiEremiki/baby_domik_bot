import logging
from requests import Response, get

from config.settings import TIMEWEB_CLOUD_TOKEN

timeweb_hl_logger = logging.getLogger('bot.timeweb_api')

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + TIMEWEB_CLOUD_TOKEN,
}


def request_finances_info() -> Response:
    return get(
        'https://api.timeweb.cloud/api/v1/account/finances',
        headers=headers)

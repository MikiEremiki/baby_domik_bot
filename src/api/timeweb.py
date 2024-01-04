import logging
from requests import Response, get

from settings.config_loader import parse_settings

timeweb_hl_logger = logging.getLogger('bot.timeweb_api')

config = parse_settings()
headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + config.timeweb.token.get_secret_value(),
    }


def request_finances_info() -> Response:
    return get(
        'https://api.timeweb.cloud/api/v1/account/finances',
        headers=headers)

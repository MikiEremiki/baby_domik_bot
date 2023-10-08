import logging
import locale
from datetime import datetime, timedelta

from telegram.ext import ContextTypes
from telegram import Update

from components.api.timeweb import request_finances_info

timeweb_hl_logger = logging.getLogger('bot.timeweb_hl')
locale.setlocale(locale.LC_TIME, '')


async def get_balance(update: Update, _: ContextTypes.DEFAULT_TYPE):
    timeweb_hl_logger.info(f'Пользователь {update.effective_user} запросил '
                           f'баланс сервера')
    response = request_finances_info()
    try:
        finances = response.json()['finances']

        balance = finances['balance']
        currency = finances['currency']
        hours_left = finances['hours_left']
        autopay_card_info = finances['autopay_card_info']
        date_now = datetime.now()
        delta = timedelta(hours=hours_left)
        date_end = date_now + delta

        text = f'Текущий баланс - {int(balance)}{currency}\n'
        text += f'Этого хватит до {date_end.date().strftime("%a %d %b %Y")}\n'
        text += f'Привязанная карта {autopay_card_info}'
    except KeyError as e:
        timeweb_hl_logger.error(e)

        text = response.json()
        text += '\n'
        match response.status_code:
            case 400:
                text += '400 Некорректный запрос'
            case 401:
                text += '401 Не авторизован'
            case 403:
                text += '403 Запрещено'
            case 404:
                text += '404 Не найдено'
            case 429:
                text += '429 Слишком много запросов'
            case 500:
                text += '500 Внутренняя ошибка сервера'

        text += '\nПередайте это сообщение в техподдержку'

    await update.effective_chat.send_message(text)

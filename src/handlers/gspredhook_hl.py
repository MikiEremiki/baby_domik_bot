import logging
from typing import Dict

from telegram.error import BadRequest
from telegram.ext import TypeHandler, ContextTypes

from settings.settings import CHAT_ID_MIKIEREMIKI

gspredhook_hl_logger = logging.getLogger('bot.gspredhook')


async def gspreadhook_update(
        update: dict, context: 'ContextTypes.DEFAULT_TYPE'):
    text = 'Не удачная попытка записи в гугл-таблицу\nИнфа по задаче:\n'
    for k, v in dict(update).items():
        text += f'{k}: {v}\n'
    try:
        await context.bot.send_message(CHAT_ID_MIKIEREMIKI, text)
    except BadRequest as e:
        gspredhook_hl_logger.error(e)
        gspredhook_hl_logger.info(text)


GspreadhookHandler = TypeHandler(Dict, gspreadhook_update)

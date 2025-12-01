import logging

from telegram.error import BadRequest
from telegram.ext import TypeHandler, ContextTypes

from api.broker_nats import GSpreadFailedData
from settings.settings import CHAT_ID_MIKIEREMIKI

gspredhook_hl_logger = logging.getLogger('bot.gspredhook')


async def gspread_hook_update(
        update: GSpreadFailedData, context: 'ContextTypes.DEFAULT_TYPE'):
    text = 'Не удачная попытка записи в гугл-таблицу\nИнфа по задаче:\n'
    for k, v in update.data.items():
        text += f'{k}: {v}\n'
    try:
        await context.bot.send_message(CHAT_ID_MIKIEREMIKI, text)
    except BadRequest as e:
        gspredhook_hl_logger.error(e)
        gspredhook_hl_logger.info(text)


GspreadHookHandler = TypeHandler(GSpreadFailedData, gspread_hook_update)

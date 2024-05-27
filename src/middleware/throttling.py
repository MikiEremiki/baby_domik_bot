import logging

from cachetools import TTLCache
from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop, TypeHandler

logger_ttl = logging.getLogger('bot.TTL')
CACHE = TTLCache(maxsize=10_000, ttl=0.3)

def add_throttling_middleware(application):
    async def check_ttl(update: Update, _: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in CACHE:
            logger_ttl.info(
                f'User: {update.effective_user}: часто нажимает на '
                f'кнопку')
            raise ApplicationHandlerStop

        CACHE[update.effective_user.id] = True

    application.add_handler(TypeHandler(Update, check_ttl), group=-150)
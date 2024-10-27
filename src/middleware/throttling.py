import logging

from cachetools import TTLCache
from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop, TypeHandler

logger_ttl = logging.getLogger('bot.TTL')
CACHE = TTLCache(maxsize=10_000, ttl=0.3)
CACHE_QUERY = TTLCache(maxsize=10_000, ttl=5)

def add_throttling_middleware(application):
    async def check_ttl(update: Update, _: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in CACHE:
            logger_ttl.warning(f'Update пришел быстрее чем 0.3сек: {update}')
            raise ApplicationHandlerStop

        query = update.callback_query
        if query:
            query_data = query.data
            cache_query_data = CACHE_QUERY.get(update.effective_user.id, None)
            if cache_query_data == query_data:
                logger_ttl.warning(f'Update уже обработан: {update}')
                raise ApplicationHandlerStop
            CACHE_QUERY[update.effective_user.id] = query_data
        CACHE[update.effective_user.id] = True

    application.add_handler(TypeHandler(Update, check_ttl), group=-150)
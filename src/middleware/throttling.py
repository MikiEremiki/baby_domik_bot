import logging

from cachetools import TTLCache
from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop, TypeHandler

logger_ttl = logging.getLogger('bot.TTL')
ttl = 0.5
CACHE = TTLCache(maxsize=10_000, ttl=ttl)

def add_throttling_middleware(application):
    async def check_ttl(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in CACHE:
            logger_ttl.warning(f'Update пришел быстрее чем {ttl}сек: {update}')
            raise ApplicationHandlerStop
        CACHE[update.effective_user.id] = True

        last_update: Update = context.user_data.get('last_update', None)
        if last_update:
            query = update.callback_query
            last_query = last_update.callback_query
            if query and last_query:
                query_data = query.data
                last_query_data = last_query.data
                if last_query_data == query_data:
                    logger_ttl.warning(f'Update уже обработан: {update}')
                    raise ApplicationHandlerStop
        context.user_data['last_update'] = update

    application.add_handler(TypeHandler(Update, check_ttl), group=-150)
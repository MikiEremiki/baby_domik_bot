import logging

from cachetools import TTLCache
from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop, TypeHandler

logger_ttl = logging.getLogger('bot.TTL')
CACHE = TTLCache(maxsize=10_000, ttl=0.3)

def add_throttling_middleware(application):
    async def check_ttl(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in CACHE:
            logger_ttl.warning(
                f'От пользователя приходит слишком много update: {update}')
            raise ApplicationHandlerStop

        query = update.callback_query
        if query:
            last_data = context.user_data.get('last_callback_query', None)
            if last_data == query.data:
                logger_ttl.warning(
                    f'Update уже обработан: callback_data: {query.data}')

                raise ApplicationHandlerStop
            else:
                context.user_data['last_callback_query'] = query.data
                logger_ttl.info(
                    f'save last_callback_data: {query.data}: '
                    f'{update.effective_user}')

        CACHE[update.effective_user.id] = True

    application.add_handler(TypeHandler(Update, check_ttl), group=-150)
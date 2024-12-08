import logging

from cachetools import TTLCache
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ApplicationHandlerStop, TypeHandler

from settings.settings import ADMIN_GROUP_ID

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
            chat_id = update.effective_chat.id
            last_query = last_update.callback_query
            last_chat_id = last_update.effective_chat.id
            if (query and last_query) and (chat_id and last_chat_id):
                query_data = query.data
                last_query_data = last_query.data
                if last_query_data == query_data:
                    logger_ttl.warning(f'Update уже обработан: {update}')
                    if chat_id in ADMIN_GROUP_ID:
                        text = ('При необходимости повторной обработки '
                                'вызови /start в ЛС бота, иначе игнорируй '
                                'данное сообщение')
                        message_thread_id = update.message.message_thread_id
                        try:
                            await update.effective_message.reply_text(
                                text=text,
                                message_thread_id=message_thread_id,
                            )
                        except BadRequest as e:
                            logger_ttl.error(e)
                            await update.effective_chat.send_message(
                                text=text,
                                message_thread_id=message_thread_id,
                            )
                    raise ApplicationHandlerStop
        context.user_data['last_update'] = update

    application.add_handler(TypeHandler(Update, check_ttl), group=-150)
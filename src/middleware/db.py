import logging

from telegram import Update
from telegram.ext import ContextTypes, TypeHandler

from yookassa.domain.notification import WebhookNotification
from db import create_sessionmaker_and_engine

user_status_md_logger = logging.getLogger('bot.md.db')

# Хранилище активных сессий, привязанных к id(update)
# Используется для гарантированного закрытия сессий даже при ApplicationHandlerStop
active_sessions = {}


def add_db_handlers_middleware(application, config):
    sessionmaker = create_sessionmaker_and_engine(str(config.postgres.db_url))

    # Патчим application.process_update для автоматического управления сессией
    original_process_update = application.process_update

    async def patched_process_update(update, *args, **kwargs):
        async with sessionmaker() as session:
            update_id = id(update)
            active_sessions[update_id] = session
            user_status_md_logger.info(f'Сессия для {update_id} создана')
            try:
                return await original_process_update(update, *args, **kwargs)
            finally:
                active_sessions.pop(update_id, None)
                user_status_md_logger.info(f'Сессия {update_id} закрыта')
                user_status_md_logger.info(f'{active_sessions=}')

    application.process_update = patched_process_update

    async def open_session_handler(
            update: Update,
            context: 'ContextTypes.DEFAULT_TYPE'
    ):
        session = active_sessions.get(id(update))
        if session is None:
            session = sessionmaker()
            user_status_md_logger.warning('Сессия создана вручную в open_session_handler (патч не сработал?)')
        
        context.session = session

        user_status_md_logger.info('Соединение с БД установлено')

    application.add_handlers([
        TypeHandler(Update, open_session_handler),
        TypeHandler(WebhookNotification, open_session_handler)
    ], group=-100)
import logging

from telegram import Update
from telegram.ext import ContextTypes, TypeHandler

from yookassa.domain.notification import WebhookNotification
from db import create_sessionmaker_and_engine

logger_postgres = logging.getLogger('sqlalchemy.engine')

def add_db_handlers_middleware(application, config):
    sessionmaker = create_sessionmaker_and_engine(str(config.postgres.db_url))

    async def open_session_handler(
            _: Update,
            context: ContextTypes.DEFAULT_TYPE
    ):
        session = sessionmaker()
        context.session = session

        logger_postgres.info('Соединение с БД установлено')

    async def close_session_handler(
            _: Update,
            context: ContextTypes.DEFAULT_TYPE
    ):
        await context.session.close()
        logger_postgres.info('Соединение с БД закрыто')

    application.add_handlers([
        TypeHandler(Update, open_session_handler),
        TypeHandler(WebhookNotification, open_session_handler)
    ], group=-100)
    application.add_handlers([
        TypeHandler(Update, close_session_handler),
        TypeHandler(WebhookNotification, close_session_handler)
    ], group=100)
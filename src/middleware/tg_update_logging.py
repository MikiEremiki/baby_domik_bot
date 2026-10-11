import logging
from telegram import Update
from telegram.ext import ContextTypes, TypeHandler
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db import TelegramUpdate, create_sessionmaker_and_engine

tg_update_md_logger = logging.getLogger('bot.md.tg_update')


class TGUpdateLoggingMiddleware:
    def __init__(self, config):
        self.sessionmaker = create_sessionmaker_and_engine(str(config.postgres.db_url))

    async def log_update(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        if not update:
            return

        try:
            update_dict = update.to_dict()
            data = {
                "update_id": update.update_id,
                "full_update": update_dict,
            }

            if update.effective_user:
                data["user_id"] = update.effective_user.id
            if update.effective_chat:
                data["chat_id"] = update.effective_chat.id

            message = update.effective_message
            if message:
                data["text"] = message.text or message.caption

            async with self.sessionmaker() as session:
                stmt = pg_insert(TelegramUpdate).values(**data).on_conflict_do_nothing(
                    index_elements=['update_id']
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            tg_update_md_logger.error(f"Error logging telegram update: {e}", exc_info=True)


def add_tg_update_logging_middleware(application, config):
    middleware = TGUpdateLoggingMiddleware(config)
    application.add_handler(TypeHandler(Update, middleware.log_update), group=-101)

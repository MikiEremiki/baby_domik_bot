import logging
from telegram import Update
from telegram.ext import ContextTypes, TypeHandler
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db import TelegramUpdate, create_sessionmaker_and_engine

logger = logging.getLogger(__name__)


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

            fields = [
                "message",
                "edited_message",
                "channel_post",
                "edited_channel_post",
                "inline_query",
                "chosen_inline_result",
                "callback_query",
                "shipping_query",
                "pre_checkout_query",
                "poll",
                "poll_answer",
                "my_chat_member",
                "chat_member",
                "chat_join_request",
                "chat_boost",
                "removed_chat_boost",
                "message_reaction",
                "message_reaction_count",
                "business_connection",
                "business_message",
                "edited_business_message",
                "deleted_business_messages",
                "purchased_paid_media",
            ]

            for field in fields:
                val = update_dict.get(field)
                if val is not None:
                    data[field] = val

            if update.effective_user:
                data["user_id"] = update.effective_user.id
            if update.effective_chat:
                data["chat_id"] = update.effective_chat.id

            message = update.effective_message
            if message:
                data["message_id"] = message.message_id
                data["text"] = message.text or message.caption
                data["message_thread_id"] = message.message_thread_id
                if message.reply_to_message:
                    data["reply_to_message_id"] = message.reply_to_message.message_id

            async with self.sessionmaker() as session:
                stmt = pg_insert(TelegramUpdate).values(**data).on_conflict_do_nothing(
                    index_elements=['update_id']
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.error(f"Error logging telegram update: {e}", exc_info=True)


def add_tg_update_logging_middleware(application, config):
    middleware = TGUpdateLoggingMiddleware(config)
    application.add_handler(TypeHandler(Update, middleware.log_update), group=-101)

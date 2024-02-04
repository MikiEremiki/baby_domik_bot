from telegram import Update
from telegram.ext import TypeHandler, ContextTypes

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


def middleware_db_add_handlers(application, config):
    async_engine = create_async_engine(
        url=str(config.postgres.db_url),
        echo=True,
        connect_args={"options": "-c timezone=utc"},
    )
    sessionmaker = async_sessionmaker(
        async_engine,
        expire_on_commit=False
    )

    async def open_session_handler(
            _: Update,
            context: ContextTypes.DEFAULT_TYPE
    ):
        session = sessionmaker()
        context.session = session

    async def close_session_handler(
            _: Update,
            context: ContextTypes.DEFAULT_TYPE
    ):
        await context.session.close()

    application.add_handler(TypeHandler(Update, open_session_handler),
                            group=-100)
    application.add_handler(TypeHandler(Update, close_session_handler),
                            group=100)

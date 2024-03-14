from telegram import Update
from telegram.ext import TypeHandler, ContextTypes

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


def create_sessionmaker_and_engine(db_url, echo=True):
    async_engine = create_async_engine(
        url=db_url,
        echo=echo,
        connect_args={"options": "-c timezone=utc"},
    )
    return async_sessionmaker(
        async_engine,
        expire_on_commit=False
    )


def middleware_db_add_handlers(application, config):
    sessionmaker = create_sessionmaker_and_engine(str(config.postgres.db_url))

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

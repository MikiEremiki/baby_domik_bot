from db import create_sessionmaker_and_engine


async def open_session(config):
    sessionmaker = create_sessionmaker_and_engine(str(config.postgres.db_url))

    session = sessionmaker()
    return session
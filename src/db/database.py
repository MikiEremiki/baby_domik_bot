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

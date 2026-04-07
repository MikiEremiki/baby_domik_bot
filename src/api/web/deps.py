from sqlalchemy.ext.asyncio import AsyncSession
from .config import session_factory

async def get_session() -> AsyncSession:
    async with session_factory() as session:
        yield session

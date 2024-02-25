from sqlalchemy import select, exists, insert, update
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update

from db import User


class AsyncORM:
    @staticmethod
    async def create_user(update_tg: Update, session: AsyncSession):
        stmt = insert(User).values(
            user_id=update_tg.effective_user.id,
            chat_id=update_tg.effective_chat.id,
            callback_name=update_tg.effective_user.full_name,
            username=update_tg.effective_user.username,
        )
        result = await session.execute(stmt.returning(User.user_id))
        await session.commit()
        return result.scalar()

    @staticmethod
    async def get_user(update_tg: Update, session: AsyncSession):
        exists_criteria = (
            exists().where(User.user_id == update_tg.effective_user.id))
        query = select(User).where(exists_criteria)
        result = await session.execute(query)
        user = result.all()

        if user:
            return user
        else:
            return None


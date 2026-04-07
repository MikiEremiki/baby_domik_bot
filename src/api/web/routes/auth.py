import hmac
import hashlib
import time
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import settings
from ..deps import get_session
from ..logger import logger
from db.models import User, UserStatus
from db.enum import UserRole

router = APIRouter()

def validate_telegram_data(data: dict, bot_token: str) -> bool:
    received_hash = data.get('hash')
    if not received_hash:
        return False

    # Сортируем все ключи, кроме hash
    data_check_list = []
    for key, value in sorted(data.items()):
        if key != 'hash' and value is not None:
            data_check_list.append(f"{key}={value}")
    
    data_check_string = "\n".join(data_check_list)

    # Секрет = SHA256(bot_token)
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    
    # HMAC-SHA256(data_check_string, secret_key)
    calculated_hash = hmac.new(
        secret_key, 
        data_check_string.encode(), 
        hashlib.sha256
    ).hexdigest()

    # Проверка времени (auth_date не старше 24 часов)
    auth_date = int(data.get('auth_date', 0))
    if time.time() - auth_date > 86400:
        logger.warning(f"Telegram auth expired: {auth_date}")
        return False

    return calculated_hash == received_hash

@router.get('/auth/telegram/callback')
async def telegram_auth_callback(
    request: Request,
    id: int = Query(...),
    first_name: str = Query(...),
    last_name: str | None = Query(None),
    username: str | None = Query(None),
    photo_url: str | None = Query(None),
    auth_date: int = Query(...),
    hash: str = Query(...),
    session: AsyncSession = Depends(get_session)
):
    # Telegram передает id как число, но для хеша нам нужны строки
    data = {
        'id': str(id),
        'first_name': first_name,
        'auth_date': str(auth_date),
        'hash': hash
    }
    if last_name: data['last_name'] = last_name
    if username: data['username'] = username
    if photo_url: data['photo_url'] = photo_url

    if not validate_telegram_data(data, settings.bot.token.get_secret_value()):
        logger.error(f"Invalid Telegram auth attempt: {data}")
        raise HTTPException(status_code=400, detail="Invalid Telegram data")

    # Поиск или создание пользователя
    stmt = select(User).where(User.user_id == id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # Если пользователя нет, создаем
        user = User(
            user_id=id,
            chat_id=id,
            username=username,
        )
        session.add(user)
        # Также создаем статус пользователя
        user_status = UserStatus(user_id=id, role=UserRole.USER)
        session.add(user_status)
        
        await session.commit()
        logger.info(f"Created new user from web: {id} ({username})")
    else:
        # Обновляем username если изменился
        if user.username != username:
            user.username = username
            await session.commit()
        logger.info(f"User logged in from web: {id} ({username})")

    # Сохраняем в сессию
    request.session['user'] = {
        'id': id,
        'first_name': first_name,
        'username': username,
        'photo_url': photo_url
    }

    # Редирект обратно на главную
    return RedirectResponse(url='/')

@router.get('/logout')
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url='/')

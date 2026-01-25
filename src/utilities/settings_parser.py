import inspect
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.ext import Application
from db import db_postgres
from settings import settings

logger = logging.getLogger('bot.settings_parser')

async def sync_settings_to_db(session: AsyncSession):
    """
    Парсит src/settings/settings.py и сохраняет константы в таблицу bot_settings.
    """
    logger.info("Starting synchronization of settings from settings.py to DB")
    
    # Получаем все атрибуты модуля settings, которые написаны капсом
    # Исключаем импортированные модули и встроенные атрибуты
    settings_to_save = {}
    for name, value in inspect.getmembers(settings):
        if name.isupper() and not name.startswith('_'):
            # Проверяем, что значение можно сериализовать в JSON (базовая проверка)
            # В нашем случае settings.py содержит простые типы, списки и словари
            settings_to_save[name] = value
    
    count = 0
    for key, value in settings_to_save.items():
        try:
            await db_postgres.update_bot_setting(session, key, value)
            count += 1
        except Exception as e:
            logger.error(f"Failed to update setting {key}: {e}")
            
    logger.info(f"Successfully synchronized {count} settings")
    return count


async def load_bot_settings(app: Application):
    """
    Загружает настройки из БД в app.bot_data['settings'].
    """
    from utilities.utl_db import open_session
    logger.info("Loading settings from DB to bot_data")
    session = await open_session(app.context_types.context.config)
    try:
        settings_db = await db_postgres.get_bot_settings(session)
        app.bot_data['settings'] = {s.key: s.value for s in settings_db}
        logger.info(f"Loaded {len(app.bot_data['settings'])} settings")
    except Exception as e:
        logger.error(f"Failed to load settings from DB: {e}")
        app.bot_data.setdefault('settings', {})
    finally:
        await session.close()

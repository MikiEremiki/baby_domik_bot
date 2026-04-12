import asyncio
import functools
import logging

from telegram.error import TimedOut, NetworkError

retry_logger = logging.getLogger('bot.retry')


def retry_on_timeout(retries: int = 3, retry_delay: float = 2.0,
                     log_on_fail: bool = True):
    """Декоратор для retry async-функций при TimedOut/NetworkError.

    Args:
        retries: количество попыток
        retry_delay: базовая задержка между попытками (умножается на номер
            попытки)
        log_on_fail: логировать ли ошибку если все попытки исчерпаны
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retries):
                try:
                    return await func(*args, **kwargs)
                except (TimedOut, NetworkError) as e:
                    last_exception = e
                    retry_logger.warning(
                        f"TimedOut/NetworkError в {func.__name__} "
                        f"(попытка {attempt + 1}/{retries}): {e}"
                    )
                    if attempt < retries - 1:
                        await asyncio.sleep(retry_delay * (attempt + 1))
            if log_on_fail:
                retry_logger.error(
                    f"Не удалось выполнить {func.__name__} "
                    f"после {retries} попыток: {last_exception}"
                )
            return None
        return wrapper
    return decorator

import asyncio
from contextlib import asynccontextmanager

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, Defaults, AIORateLimiter
from yookassa import Configuration
from faststream import FastStream
from yookassa.domain.notification import WebhookNotificationFactory

from api.broker_nats import connect_to_nats
from db import pickle_persistence
from handlers.set_handlers import set_handlers
from log.logging_conf import setup_logs
from settings.config_loader import parse_settings
from utilities.utl_post_init import post_init

bot_logger = setup_logs()
bot_logger.info('Инициализация бота')

config = parse_settings()

application = (
    Application.builder()
    .token(config.bot.token.get_secret_value())
    .persistence(pickle_persistence)
    .defaults(Defaults(parse_mode=ParseMode.HTML))
    .get_updates_pool_timeout(3)
    .get_updates_write_timeout(7)
    .get_updates_connect_timeout(7)
    .get_updates_read_timeout(7)
    .get_updates_connection_pool_size(2)
    .rate_limiter(AIORateLimiter())

    .build()
)

Configuration.configure(config.yookassa.account_id,
                        config.yookassa.secret_key.get_secret_value())

webhook_notification_factory = WebhookNotificationFactory()
broker = connect_to_nats(application, webhook_notification_factory)


@asynccontextmanager
async def lifespan():
    set_handlers(application, config)
    await application.initialize()
    await post_init(application, config)
    bot_logger.info('=====Setup Бота произведен, переходим к запуску =====')
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    yield

    await application.updater.stop()
    await application.stop()
    bot_logger.info('Бот остановлен')
    await application.shutdown()


fast_stream = FastStream(broker, lifespan=lifespan)


if __name__ == '__main__':
    asyncio.run(fast_stream.run())

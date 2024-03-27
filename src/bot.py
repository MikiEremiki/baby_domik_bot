import asyncio
from contextlib import asynccontextmanager

from telegram.constants import ParseMode
from telegram.ext import Application, Defaults
from yookassa import Configuration
from faststream import FastStream
from yookassa.domain.notification import WebhookNotificationFactory

from api.broker_nats import connect_to_nats
from db import pickle_persistence
from handlers.set_handlers import set_handlers
from log.logging_conf import load_log_config
from utilities.utl_func import (
    set_menu, set_description, set_ticket_data, set_show_data,
    set_special_ticket_price,
)
from settings.config_loader import parse_settings


async def post_init(app: Application):
    await set_menu(app.bot)
    await set_description(app.bot)
    set_ticket_data(app)
    set_show_data(app)
    set_special_ticket_price(app)

    app.bot_data.setdefault('admin', {})
    app.bot_data['admin'].setdefault('contacts', {})
    app.bot_data.setdefault('dict_topics_name', {})
    app.bot_data.setdefault('global_on_off', True)


bot_logger = load_log_config()
bot_logger.info('Инициализация бота')

config = parse_settings()

application = (
    Application.builder()
    .token(config.bot.token.get_secret_value())
    .persistence(pickle_persistence)
    .post_init(post_init)
    .defaults(Defaults(parse_mode=ParseMode.HTML))

    .build()
)
application.bot_data.setdefault('config', config)

Configuration.configure(config.yookassa.account_id,
                        config.yookassa.secret_key.get_secret_value())

webhook_notification_factory = WebhookNotificationFactory()
broker = connect_to_nats(application, webhook_notification_factory)

@asynccontextmanager
async def lifespan():
    set_handlers(application, config)
    await application.initialize()
    await post_init(application)
    await application.start()
    await application.updater.start_polling()

    yield

    await application.updater.stop()
    await application.stop()
    bot_logger.info('Бот остановлен')
    await application.shutdown()


fast_stream = FastStream(broker, lifespan=lifespan)


if __name__ == '__main__':
    asyncio.run(fast_stream.run())

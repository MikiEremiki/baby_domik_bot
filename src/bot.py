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
from utilities.utl_func import set_menu, set_description
from settings.config_loader import parse_settings


async def post_init(app: Application):
    await set_menu(app.bot)
    await set_description(app.bot)

    app.bot_data.setdefault('texts', {})
    app.bot_data['texts']['description'] = (
        '--><a href="https://vk.com/baby_theater_domik">Наша группа ВКонтакте</a>\n\n'
        'В ней более подробно описаны:\n'
        '- <a href="https://vk.com/baby_theater_domik?w=wall-202744340_2446">Бронь билетов</a>\n'
        '- <a href="https://vk.com/baby_theater_domik?w=wall-202744340_2495">Репертуар</a>\n'
        '- Фотографии\n'
        '- Команда и жизнь театра\n'
        '- <a href="https://vk.com/wall-202744340_1239">Ответы на часто задаваемые вопросы</a>\n'
        '- <a href="https://vk.com/baby_theater_domik?w=wall-202744340_2003">Как нас найти</a>\n\n'
        '<i>Задать любые интересующие вас вопросы вы можете через сообщения группы</i>\n\n'
    )
    app.bot_data.setdefault('admin', {})
    app.bot_data['admin'].setdefault('contacts', {})
    app.bot_data.setdefault('dict_topics_name', {})
    app.bot_data.setdefault('global_on_off', True)
    app.context_types.context.config = config

    # TODO Сделать команду для настройки списков по интенсивам
    studio = {
        'Театральный интенсив': [],
    }
    app.bot_data['studio'] = studio


bot_logger = load_log_config()
bot_logger.info('Инициализация бота')

config = parse_settings()

application = (
    Application.builder()
    .token(config.bot.token.get_secret_value())
    .persistence(pickle_persistence)
    .defaults(Defaults(parse_mode=ParseMode.HTML))

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

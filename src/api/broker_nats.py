from faststream import Logger
from faststream.nats import JStream, NatsMessage, NatsBroker
from telegram.ext import Application
from yookassa.domain.notification import WebhookNotificationFactory

from settings.settings import nats_url


def connect_to_nats(app: Application,
                    webhook_notification_factory: WebhookNotificationFactory):
    broker = NatsBroker(nats_url)
    stream = JStream(name="baby_domik", max_msgs=100, max_age=60*60*24*7)

    @broker.subscriber("bot", stream=stream, durable='yookassa')
    async def nats_handler(
            data: dict,
            logger: Logger,
            nats_message: NatsMessage,
    ):
        logger.info(f'{data=}')
        notification = webhook_notification_factory.create(data)
        # print(f'{nats_message=}')
        await app.update_queue.put(notification)

    return broker

from faststream import Logger
from faststream.nats import JStream, NatsBroker, PullSub
from nats.js.api import ConsumerConfig, DeliverPolicy
from telegram.ext import Application
from yookassa.domain.notification import WebhookNotificationFactory

from settings.settings import nats_url


def connect_to_nats(app: Application,
                    webhook_notification_factory: WebhookNotificationFactory):
    broker = NatsBroker(nats_url)
    stream = JStream(name='baby_domik', max_msgs=100, max_age=60*60*24*7, declare=False)

    @broker.subscriber('bot', stream=stream, durable='yookassa')
    async def yookassa_handler(
            data: dict,
            logger: Logger,
    ):
        logger.info(f'{data=}')
        notification = webhook_notification_factory.create(data)
        await app.update_queue.put(notification)

    @broker.subscriber(
        subject='gspread_failed',
        durable='gspread_failed',
        config=ConsumerConfig(ack_wait=10),
        deliver_policy=DeliverPolicy.NEW,
        pull_sub=PullSub(),
        stream=stream,
    )
    async def gspread_handler(
            data: dict,
            logger: Logger,
    ):
        logger.info(f'{data=}')
        await app.update_queue.put(data)

    return broker

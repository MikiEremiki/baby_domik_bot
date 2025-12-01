import logging
from typing import Any, Dict

from faststream.nats import NatsBroker

from settings.settings import nats_url

sales_pub_logger = logging.getLogger('bot.sales_pub')


async def _publish_message(message: Dict[str, Any]):
    async with NatsBroker(nats_url) as broker:
        await broker.publish(message, subject='sales', stream='baby_domik')
        sales_pub_logger.info(f'Published sales task: {message}')


async def publish_sales(campaign_id: int) -> None:
    """Publish a sales campaign task to NATS.

    Payload is minimal: {"campaign_id": <id>}.
    """
    message: Dict[str, Any] = {
        'campaign_id': int(campaign_id),
    }
    await _publish_message(message)

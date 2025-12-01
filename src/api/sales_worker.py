import asyncio
import logging
from typing import Any, Dict, List, Tuple

import sqlalchemy as sa
from faststream import FastStream, Depends, Logger
from faststream.nats import JStream, NatsBroker, PullSub, NatsMessage
from nats.js.api import DeliverPolicy, ConsumerConfig
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, MessageEntity
from telegram.error import Forbidden, RetryAfter, BadRequest, TimedOut, \
    NetworkError

from db import create_sessionmaker_and_engine
from db.models import (
    SalesCampaign, SalesCampaignSchedule, SalesRecipient, ScheduleEvent,
)
from db.sales_crud import (
    iter_recipients_for_send, mark_recipient_status, get_free_places,
)
from settings.config_loader import parse_settings
from settings.settings import URL_BOT, DICT_CONVERT_WEEKDAY_NUMBER_TO_STR, \
    nats_url

sales_worker_logger = logging.getLogger('bot.sales_worker')

_settings = parse_settings()
_sessionmaker = create_sessionmaker_and_engine(str(_settings.postgres.db_url))

broker = NatsBroker(nats_url)
stream = JStream(name='baby_domik', max_msgs=100, max_age=60 * 60 * 24 * 7,
                 declare=False)
MSG_PROCESSING_TIME = 300  # allow long processing
BATCH_SIZE = 30
RATE_DELAY = 0.1  # seconds, ~10 msg/sec

_bot: Bot | None = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=_settings.bot.token.get_secret_value())
    return _bot


async def _availability_block(session: AsyncSession, campaign_id: int) -> Tuple[
    str, List[int]]:
    # Get schedules for campaign
    rows = (await session.execute(
        sa.select(SalesCampaignSchedule.schedule_event_id)
        .where(SalesCampaignSchedule.campaign_id == campaign_id)
    )).all()
    schedule_ids = [r[0] for r in rows]
    if not schedule_ids:
        return 'Внимание: не выбраны сеансы.', []

    free = await get_free_places(session, schedule_ids)
    if not free:
        return 'Кол-во свободных мест: нет данных.', schedule_ids

    # Need datetimes for ordering
    info = (await session.execute(
        sa.select(ScheduleEvent.id, ScheduleEvent.datetime_event)
        .where(ScheduleEvent.id.in_(list(map(int, schedule_ids))))
        .order_by(ScheduleEvent.datetime_event)
    )).all()

    lines = ['Кол-во свободных мест:', '⬇️Дата Время — Детских | Взрослых⬇️']
    for sid, dt in info:
        weekday = int(dt.strftime('%w'))
        date_txt = dt.strftime('%d.%m ')
        time_txt = dt.strftime('%H:%M')
        fc, fa = free.get(int(sid), (0, 0))
        lines.append(
            f"{date_txt}({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]}) {time_txt} — {fc} дет | {fa} взр")
    return '\n'.join(lines), schedule_ids


def _deserialize_entities(raw) -> List[MessageEntity]:
    try:
        return [MessageEntity(**e) for e in (raw or [])]
    except Exception:
        return []


async def _send_to_chat(bot: Bot, campaign: SalesCampaign, chat_id: int,
                        availability_block: str, reserve_text: str) -> None:
    kind = campaign.message_kind
    if kind == 'text':
        base_text = campaign.message_text or ''
        # Append availability and a plain DeepLink URL (auto-linkified).
        text = base_text + '\n\n' + availability_block + f"\n\n{reserve_text}"
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    elif kind == 'photo' and campaign.photo_file_id:
        base_caption = campaign.caption_text or ''
        caption = base_caption + '\n\n' + availability_block + f"\n\n{reserve_text}"
        await bot.send_photo(
            chat_id=chat_id,
            photo=campaign.photo_file_id,
            caption=caption,
            disable_notification=False,
            parse_mode='HTML'
        )
    elif kind == 'video' and campaign.video_file_id:
        base_caption = campaign.caption_text or ''
        caption = base_caption + '\n\n' + availability_block + f"\n\n{reserve_text}"
        await bot.send_video(
            chat_id=chat_id,
            video=campaign.video_file_id,
            caption=caption,
            disable_notification=False,
            parse_mode='HTML'
        )
    elif kind == 'animation' and campaign.animation_file_id:
        base_caption = campaign.caption_text or ''
        caption = base_caption + '\n\n' + availability_block + f"\n\n{reserve_text}"
        await bot.send_animation(
            chat_id=chat_id,
            animation=campaign.animation_file_id,
            caption=caption,
            parse_mode='HTML',
            disable_notification=False,
        )
    else:
        # fallback to text if no proper payload
        base_text = campaign.message_text or ''
        text = base_text + '\n\n' + availability_block + f"\n\n{reserve_text}"
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode='HTML',
            disable_web_page_preview=True,
        )


async def progress_sender(message: NatsMessage):
    async def in_progress_task():
        while True:
            await asyncio.sleep(5.0)
            await message.in_progress()

    task = asyncio.create_task(in_progress_task())
    yield
    task.cancel()


@broker.subscriber(
    subject='sales',
    durable='sales',
    config=ConsumerConfig(ack_wait=MSG_PROCESSING_TIME),
    deliver_policy=DeliverPolicy.NEW,
    pull_sub=PullSub(),
    stream=stream,
    dependencies=[Depends(progress_sender)]
)
async def handle_sales_task(data: Dict[str, Any], logger: Logger):
    session: AsyncSession = _sessionmaker()
    try:
        campaign_id = int(data['campaign_id'])
        logger.info(f'sales:received campaign_id={campaign_id}')

        campaign: SalesCampaign | None = await session.get(SalesCampaign,
                                                           campaign_id)
        if not campaign:
            logger.warning(f'Campaign not found: id={campaign_id}')
            return

        bot = _get_bot()
        reserve_text = (f"👉 /reserve команда для покупки билетов\n"
                        f"Выбирайте подходящий спектакль и следуйте инструкциям")

        total_sent = 0
        total_failed = 0
        total_blocked = 0

        while True:
            recipients = await iter_recipients_for_send(session, campaign_id,
                                                        batch_size=BATCH_SIZE)
            if not recipients:
                break

            # Recalculate availability before batch
            availability_block, _ = await _availability_block(session,
                                                              campaign_id)

            for r in recipients:
                try:
                    await _send_to_chat(bot, campaign, int(r.chat_id),
                                        availability_block, reserve_text)
                    await mark_recipient_status(session, r.id, 'sent')
                    total_sent += 1
                except Forbidden as e:
                    await mark_recipient_status(session, r.id, 'blocked',
                                                last_error=str(e))
                    total_blocked += 1
                except RetryAfter as e:
                    await asyncio.sleep(float(getattr(e, 'retry_after', 1)))
                    # simple retry once
                    try:
                        await _send_to_chat(bot, campaign, int(r.chat_id),
                                            availability_block, reserve_text)
                        await mark_recipient_status(session, r.id, 'sent')
                        total_sent += 1
                    except Exception as e2:
                        await mark_recipient_status(session, r.id, 'failed',
                                                    last_error=str(e2))
                        total_failed += 1
                except (BadRequest, TimedOut, NetworkError, Exception) as e:
                    await mark_recipient_status(session, r.id, 'failed',
                                                last_error=str(e))
                    total_failed += 1
                await session.flush()
                await asyncio.sleep(RATE_DELAY)

            await session.commit()

        # Mark campaign as done
        campaign.status = 'done'
        await session.commit()
        logger.info(
            f'sales:done campaign_id={campaign_id} sent={total_sent} failed={total_failed} blocked={total_blocked}')

        # Publish a summary for the bot (sales_report)
        try:
            # Try to determine the admin chat_id who created the campaign
            created_chat_id = None
            try:
                if campaign.created_by_admin_id:
                    row = (await session.execute(
                        sa.text(
                            'SELECT chat_id FROM users WHERE user_id = :uid'),
                        {'uid': int(campaign.created_by_admin_id)}
                    )).first()
                    if row and row[0]:
                        created_chat_id = int(row[0])
            except Exception as e_lookup:
                sales_worker_logger.warning(
                    'Failed to lookup creator chat_id: %s', e_lookup)

            summary = {
                'action': 'sales_done',
                'campaign_id': campaign_id,
                'status': 'done',
                'totals': {
                    'sent': total_sent,
                    'failed': total_failed,
                    'blocked': total_blocked,
                },
            }
            if created_chat_id:
                summary['chat_id'] = created_chat_id

            await broker.publish(summary, subject='sales_report',
                                 stream='baby_domik')
            logger.info('sales_report published: %s', summary)
        except Exception as e:
            logger.exception('Failed to publish sales_report: %s', e)
    except Exception as e:
        logger.exception(f'Failed to handle sales task: {e} | payload={data}')
        # mark campaign failed
        try:
            if 'campaign_id' in data:
                campaign = await session.get(SalesCampaign,
                                             int(data['campaign_id']))
                if campaign:
                    campaign.status = 'failed'
                    await session.commit()
                    try:
                        # Try include creator chat_id for targeted notification
                        created_chat_id = None
                        try:
                            if campaign and campaign.created_by_admin_id:
                                row = (await session.execute(
                                    sa.text(
                                        'SELECT chat_id FROM users WHERE user_id = :uid'),
                                    {'uid': int(campaign.created_by_admin_id)}
                                )).first()
                                if row and row[0]:
                                    created_chat_id = int(row[0])
                        except Exception as e_lookup:
                            sales_worker_logger.warning(
                                'Failed to lookup creator chat_id on failed report: %s',
                                e_lookup)

                        summary = {
                            'action': 'sales_failed',
                            'campaign_id': int(data['campaign_id']),
                            'status': 'failed',
                        }
                        if created_chat_id:
                            summary['chat_id'] = created_chat_id

                        await broker.publish(summary, subject='sales_report',
                                             stream='baby_domik')
                        sales_worker_logger.info(
                            'sales_report (failed) published: %s', summary)
                    except Exception as e2:
                        sales_worker_logger.exception(
                            'Failed to publish failed sales_report: %s', e2)
        except Exception:
            pass
    finally:
        await session.close()


fast_stream = FastStream(broker)

if __name__ == "__main__":
    asyncio.run(fast_stream.run())

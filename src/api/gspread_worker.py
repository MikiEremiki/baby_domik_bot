import asyncio
import logging
from typing import Any, Dict

from faststream import FastStream, Depends, Logger
from faststream.nats import JStream, NatsBroker, PullSub, NatsMessage
from nats.js.api import DeliverPolicy, ConsumerConfig

from api.googlesheets import (
    update_ticket_in_gspread, update_cme_in_gspread,
    write_data_reserve, write_client_reserve, write_client_list_waiting
)
from settings.settings import nats_url

gspread_worker_logger = logging.getLogger('bot.gspread_worker')

broker = NatsBroker(nats_url)
stream = JStream(name='baby_domik', max_msgs=100, max_age=60*60*24*7, declare=False)
MSG_PROCESSING_TIME = 60


async def progress_sender(message: NatsMessage):
    async def in_progress_task():
        while True:
            await asyncio.sleep(5.0)
            await message.in_progress()

    task = asyncio.create_task(in_progress_task())
    yield
    task.cancel()


@broker.subscriber(
    subject='gspread',
    durable='gspread',
    config=ConsumerConfig(ack_wait=MSG_PROCESSING_TIME),
    deliver_policy=DeliverPolicy.NEW,
    pull_sub=PullSub(),
    stream=stream,
    dependencies=[Depends(progress_sender)]
)
async def handle_gspread_task(data: Dict[str, Any], logger: Logger):
    """
    Обработчик задач записи в Google Sheets.
    Первая поддерживаемая операция: update_ticket → update_ticket_in_gspread
    """
    try:
        action = data.get('action')
        sheet_id = str(data['sheet_id'])
        status = data.get('status', None)
        option = int(data.get('option', 1))

        logger.info(f'gspread:{action} started')
        log_text = ''
        if action == 'update_ticket':
            ticket_id = int(data['ticket_id'])
            await update_ticket_in_gspread(sheet_id, ticket_id, status, option)
            log_text = f'{ticket_id=} {status=}'

        elif action == 'update_cme':
            cme_id = int(data['cme_id'])
            await update_cme_in_gspread(sheet_id, cme_id, status)
            log_text = f'{cme_id=} {status=}'

        elif action == 'write_data_reserve':
            event_id = data['event_id']
            numbers = data['numbers']
            await write_data_reserve(sheet_id, event_id, numbers, option)
            log_text = f'{event_id=} {numbers=}'

        elif action == 'write_client_list_waiting':
            context = data['context']
            await write_client_list_waiting(sheet_id, context)
            log_text = f'{context=}'

        elif action == 'write_client_reserve':
            reserve_user_data = data['reserve_user_data']
            chat_id = data['chat_id']
            base_ticket_dto = data['base_ticket_dto']
            ticket_status_value = data['ticket_status_value']

            res = await write_client_reserve(sheet_id,
                                             reserve_user_data,
                                             chat_id,
                                             base_ticket_dto,
                                             ticket_status_value)
            if res == 1:
                ticket_ids = reserve_user_data['ticket_ids']
                event_ids = reserve_user_data['choose_schedule_event_ids']
                log_text = f'{event_ids=} {ticket_ids=}'

            elif res == 0:
                message: Dict[str, Any] = {
                    'action': 'write_client_reserve',
                    'sheet_id': sheet_id,
                    'reserve_user_data': reserve_user_data,
                    'chat_id': chat_id,
                    'base_ticket_dto': base_ticket_dto,
                    'ticket_status_value': ticket_status_value,
                }
                await broker.publish(
                    message, subject='gspread_failed', stream='baby_domik')
                logger.info(f'Published gspread task: {message}')
        else:
            logger.warning(f'Unknown gspread action: {action} | payload={data}')

        logger.info(f'gspread:{action} done | ' + log_text)
    except Exception as e:
        logger.exception(f'Failed to handle gspread task: {e} | payload={data}')


fast_stream = FastStream(broker)

if __name__ == "__main__":
    asyncio.run(fast_stream.run())

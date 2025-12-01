import logging
from typing import Any, Dict, List

from faststream.nats import NatsBroker

from settings.settings import nats_url

gspread_pub_logger = logging.getLogger('bot.gspread_pub')


async def _publish_message(message: Dict[str, Any]):
    async with NatsBroker(nats_url) as broker:
        await broker.publish(message, subject='gspread', stream='baby_domik')
        gspread_pub_logger.info(f'Published gspread task: {message}')


async def publish_update_ticket(
        sheet_id: str,
        ticket_id: int,
        status: str,
        option: int = 1
) -> None:
    """
    Публикует задачу обновления статуса билета в Google Sheets в топик 'gspread'.
    """
    message: Dict[str, Any] = {
        'action': 'update_ticket',
        'sheet_id': sheet_id,
        'ticket_id': ticket_id,
        'status': status,
        'option': option,
    }
    await _publish_message(message)


async def publish_update_cme(sheet_id: str, cme_id: int, status: str) -> None:
    """
    Публикует задачу обновления статуса заказного мероприятия в Google Sheets в
    топик 'gspread'.
    """
    message: Dict[str, Any] = {
        'action': 'update_cme',
        'sheet_id': sheet_id,
        'cme_id': cme_id,
        'status': status,
    }
    await _publish_message(message)


async def publish_write_data_reserve(
        sheet_id: str,
        event_id: int,
        numbers: List[int],
        option: int = 1
) -> None:
    """
    Публикует задачу обновления свободных мест на мероприятие в Google Sheets в
    топик 'gspread'.
    """
    message: Dict[str, Any] = {
        'action': 'write_data_reserve',
        'sheet_id': sheet_id,
        'event_id': event_id,
        'numbers': numbers,
        'option': option,
    }
    await _publish_message(message)


async def publish_write_client_list_waiting(
        sheet_id: str,
        context: dict,
) -> None:
    """
    Публикует задачу обновления свободных мест на мероприятие в Google Sheets в
    топик 'gspread'.
    """
    message: Dict[str, Any] = {
        'action': 'write_client_list_waiting',
        'sheet_id': sheet_id,
        'context': context,
    }
    await _publish_message(message)



async def publish_write_client_reserve(
        sheet_id: str,
        reserve_user_data: dict,
        chat_id: int,
        base_ticket_dto: dict,
        ticket_status_value: str
) -> None:
    """
    Публикует задачу записи билета в клиентскую базу в Google Sheets в
    топик 'gspread'.
    """
    chose_price = reserve_user_data['chose_price']
    client_data: dict = reserve_user_data['client_data']
    ticket_ids = reserve_user_data['ticket_ids']
    choose_schedule_event_ids = reserve_user_data['choose_schedule_event_ids']
    data = {
        'chose_price': chose_price,
        'client_data': client_data,
        'ticket_ids': ticket_ids,
        'choose_schedule_event_ids': choose_schedule_event_ids,
    }
    message: Dict[str, Any] = {
        'action': 'write_client_reserve',
        'sheet_id': sheet_id,
        'reserve_user_data': data,
        'chat_id': chat_id,
        'base_ticket_dto': base_ticket_dto,
        'ticket_status_value': ticket_status_value,
    }
    await _publish_message(message)

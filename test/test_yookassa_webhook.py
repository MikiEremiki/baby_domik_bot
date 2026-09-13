import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from handlers.hooks import yookassa_hl


def _create_mock_update(
    source='website',
    chat_id='5473664345',
    message_id=123,
    ticket_ids='4915',
    choose_schedule_event_ids='101',
    command='reserve',
    promo_id=None
):
    update = MagicMock()
    metadata = {
        'source': source,
        'chat_id': str(chat_id),
        'message_id': message_id,
        'ticket_ids': ticket_ids,
        'choose_schedule_event_ids': choose_schedule_event_ids,
        'command': command,
    }
    if promo_id:
        metadata['promo_id'] = str(promo_id)
    update.object.metadata = metadata
    return update


def _create_mock_context():
    context = MagicMock()
    context.application.user_data = {}
    
    # Моделируем persistence из PTB v20+, где get_user_data() - асинхронный метод
    async def async_get_user_data():
        return {}
    context.application.persistence.get_user_data = async_get_user_data
    context.application.persistence.update_conversation = AsyncMock()
    
    context.config.sheets.sheet_id_domik = 'test_sheet_id'
    context.config.bot.developer_chat_id = 111
    context.bot_data = {
        'settings': {'REFUND_INFO': 'Правила возврата'},
        'dict_topics_name': {'Бронирования спектаклей': 42}
    }
    context.session = AsyncMock()
    
    mock_sent_msg = MagicMock()
    mock_sent_msg.message_id = 777
    context.bot.send_message = AsyncMock(return_value=mock_sent_msg)
    context.bot.edit_message_reply_markup = AsyncMock()
    
    return context


def test_processing_ticket_paid_website_new_user(monkeypatch):
    """
    Проверяет успешную обработку вебхука с сайта для пользователя,
    чьи данные отсутствуют в context.application.user_data.
    Убеждается в отсутствии AttributeError: 'coroutine' object has no attribute 'setdefault'.
    """
    update = _create_mock_update(source='website', chat_id='5473664345', ticket_ids='4915')
    context = _create_mock_context()
    
    # Мокаем вызовы к БД и внешним сервисам
    mock_ticket = MagicMock(base_ticket_id=1, price=1000)
    mock_base_ticket = MagicMock(name='Взрослый + ребенок')
    
    monkeypatch.setattr('handlers.hooks.yookassa_hl.create_str_info_by_schedule_event_id',
                        AsyncMock(return_value='01.01 12:00 Спектакль'))
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.get_ticket',
                        AsyncMock(return_value=mock_ticket))
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.get_base_ticket',
                        AsyncMock(return_value=mock_base_ticket))
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.update_ticket',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.publish_update_ticket',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.send_approve_reject_message_to_admin_in_webhook',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl._edit_message_reply_markup',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl._send_message',
                        AsyncMock(return_value=MagicMock(message_id=777)))

    asyncio.run(yookassa_hl.processing_ticket_paid(update, context))

    # Проверяем, что user_data для chat_id 5473664345 инициализирован
    assert 5473664345 in context.application.user_data
    user_data = context.application.user_data[5473664345]
    
    assert user_data['command'] == 'reserve'
    assert user_data['postfix_for_cancel'] == 'reserve'
    assert user_data['reserve_user_data']['ticket_ids'] == [4915]
    assert user_data['reserve_user_data']['flag_send_ticket_info'] is True
    assert '01.01 12:00 Спектакль' in user_data['common_data']['text_for_notification_massage']
    assert user_data['common_data']['message_id_buy_info'] == 777
    assert user_data['STATE'] == 'PAID'


def test_processing_ticket_paid_website_existing_user(monkeypatch):
    """
    Проверяет обработку вебхука с сайта для пользователя с уже существующим user_data.
    """
    update = _create_mock_update(source='website', chat_id='5473664345', ticket_ids='4915')
    context = _create_mock_context()
    context.application.user_data[5473664345] = {
        'custom_key': 'custom_val',
        'reserve_user_data': {
            'client_data': {'old': 'data'},
            'original_child_text': 'old_child'
        },
        'common_data': {
            'text_for_notification_massage': 'old_text'
        }
    }
    
    mock_ticket = MagicMock(base_ticket_id=1, price=1000)
    mock_base_ticket = MagicMock(name='Взрослый + ребенок')
    
    monkeypatch.setattr('handlers.hooks.yookassa_hl.create_str_info_by_schedule_event_id',
                        AsyncMock(return_value='01.01 12:00 Спектакль'))
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.get_ticket',
                        AsyncMock(return_value=mock_ticket))
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.get_base_ticket',
                        AsyncMock(return_value=mock_base_ticket))
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.update_ticket',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.publish_update_ticket',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.send_approve_reject_message_to_admin_in_webhook',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl._edit_message_reply_markup',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl._send_message',
                        AsyncMock(return_value=MagicMock(message_id=777)))

    asyncio.run(yookassa_hl.processing_ticket_paid(update, context))

    user_data = context.application.user_data[5473664345]
    assert user_data['custom_key'] == 'custom_val'
    assert 'client_data' not in user_data['reserve_user_data']
    assert 'original_child_text' not in user_data['reserve_user_data']
    assert user_data['reserve_user_data']['ticket_ids'] == [4915]
    assert '01.01 12:00 Спектакль' in user_data['common_data']['text_for_notification_massage']
    assert user_data['common_data']['message_id_buy_info'] == 777


def test_processing_ticket_paid_chat_id_zero(monkeypatch):
    """
    Проверяет, что при chat_id='0' или некорректном значении инициализация user_data безопасно пропускается.
    """
    update = _create_mock_update(source='website', chat_id='0', message_id=0, ticket_ids='4915')
    context = _create_mock_context()
    
    mock_ticket = MagicMock(base_ticket_id=1, price=1000)
    mock_base_ticket = MagicMock(name='Взрослый + ребенок')
    
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.get_ticket',
                        AsyncMock(return_value=mock_ticket))
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.get_base_ticket',
                        AsyncMock(return_value=mock_base_ticket))
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.update_ticket',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.publish_update_ticket',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.send_approve_reject_message_to_admin_in_webhook',
                        AsyncMock())

    asyncio.run(yookassa_hl.processing_ticket_paid(update, context))

    assert len(context.application.user_data) == 0


def test_processing_ticket_paid_bot_booking(monkeypatch):
    """
    Проверяет обработку вебхука для бронирования через бота (source='bot').
    """
    update = _create_mock_update(source='bot', chat_id='5473664345', ticket_ids='4915')
    context = _create_mock_context()
    context.application.user_data[5473664345] = {
        'command': 'reserve',
        'bot_data_field': 'value'
    }
    
    monkeypatch.setattr('handlers.hooks.yookassa_hl.db_postgres.update_ticket',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.publish_update_ticket',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.send_approve_reject_message_to_admin_in_webhook',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl._edit_message_reply_markup',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl._send_message',
                        AsyncMock(return_value=MagicMock(message_id=777)))

    asyncio.run(yookassa_hl.processing_ticket_paid(update, context))

    user_data = context.application.user_data[5473664345]
    assert user_data['bot_data_field'] == 'value'
    assert user_data['STATE'] == 'PAID'

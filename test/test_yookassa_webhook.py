import asyncio
from collections import defaultdict
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock
import pytest
from telegram.error import BadRequest
from telegram.ext import Application

from db.models import TicketStatus
from handlers.hooks import yookassa_hl
from handlers import sub_hl


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
        'chat_id': str(chat_id) if chat_id is not None else '',
        'message_id': message_id,
        'ticket_ids': ticket_ids,
        'choose_schedule_event_ids': choose_schedule_event_ids,
        'command': command,
    }
    if promo_id:
        metadata['promo_id'] = str(promo_id)
    update.object.metadata = metadata
    return update


def _create_mock_context(has_persistence=True):
    context = MagicMock()
    raw_user_data = defaultdict(dict)
    context.application.user_data = MappingProxyType(raw_user_data)
    
    if has_persistence:
        context.application.persistence = MagicMock()
        # Моделируем persistence из PTB v20+, где get_user_data() - асинхронный метод
        context.application.persistence.get_user_data = AsyncMock(return_value={})
        context.application.persistence.update_conversation = AsyncMock()
        context.application.mark_data_for_update_persistence = MagicMock()
    else:
        context.application.persistence = None
        context.application.mark_data_for_update_persistence = MagicMock()
    
    context.config.sheets.sheet_id_domik = 'test_sheet_id'
    context.config.bot.developer_chat_id = 111
    context.bot_data = {
        'settings': {'REFUND_INFO': 'Правила возврата'},
        'dict_topics_name': {
            'Бронирования спектаклей': 42,
            'Бронирования студия': 43,
        }
    }
    context.session = AsyncMock()
    
    mock_sent_msg = MagicMock()
    mock_sent_msg.message_id = 777
    context.bot.send_message = AsyncMock(return_value=mock_sent_msg)
    context.bot.edit_message_reply_markup = AsyncMock()
    
    return context


def test_real_application_user_data_contract():
    """
    Проверяет контракт user_data на реальном Application:
    - user_data является MappingProxyType;
    - прямой setdefault на MappingProxyType вызывает AttributeError;
    - чтение отсутствующего ключа создаёт мутабельный dict;
    - повторное чтение возвращает тот же объект словаря.
    """
    app = Application.builder().token('123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11').build()
    assert isinstance(app.user_data, MappingProxyType)
    
    with pytest.raises(AttributeError):
        app.user_data.setdefault(100, {})
    
    user_dict = app.user_data[100]
    assert isinstance(user_dict, dict)
    assert user_dict == {}
    
    assert app.user_data[100] is user_dict
    
    user_dict['key'] = 'value'
    assert app.user_data[100]['key'] == 'value'


def test_processing_ticket_paid_website_new_user(monkeypatch):
    """
    Проверяет успешную обработку вебхука с сайта для пользователя,
    чьи данные отсутствуют в context.application.user_data.
    Убеждается в отсутствии AttributeError, создании сессии, заполнении полей,
    отсутствии вызова get_user_data и вызове mark_data_for_update_persistence.
    """
    update = _create_mock_update(source='website', chat_id='5473664345', ticket_ids='4915')
    context = _create_mock_context(has_persistence=True)
    
    mock_ticket = MagicMock(base_ticket_id=1, price=1000)
    mock_base_ticket = MagicMock()
    mock_base_ticket.name = 'Взрослый + ребенок'
    
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

    assert 5473664345 in context.application.user_data
    user_data = context.application.user_data[5473664345]
    
    assert user_data['command'] == 'reserve'
    assert user_data['postfix_for_cancel'] == 'reserve'
    assert user_data['reserve_user_data']['ticket_ids'] == [4915]
    assert user_data['reserve_user_data']['flag_send_ticket_info'] is True
    assert '01.01 12:00 Спектакль' in user_data['common_data']['text_for_notification_massage']
    assert user_data['common_data']['message_id_buy_info'] == 777
    assert user_data['STATE'] == 'PAID'
    
    context.application.persistence.get_user_data.assert_not_called()
    context.application.mark_data_for_update_persistence.assert_called_once_with(user_ids=[5473664345])


def test_processing_ticket_paid_website_existing_user(monkeypatch):
    """
    Проверяет обработку вебхука с сайта для пользователя с уже существующим user_data.
    Убеждается в сохранении посторонних ключей, удалении старых client_data и пометке persistence.
    """
    update = _create_mock_update(source='website', chat_id='5473664345', ticket_ids='4915')
    context = _create_mock_context(has_persistence=True)
    context.application.user_data[5473664345].update({
        'custom_key': 'custom_val',
        'reserve_user_data': {
            'client_data': {'old': 'data'},
            'original_child_text': 'old_child'
        },
        'common_data': {
            'text_for_notification_massage': 'old_text'
        }
    })
    
    mock_ticket = MagicMock(base_ticket_id=1, price=1000)
    mock_base_ticket = MagicMock()
    mock_base_ticket.name = 'Взрослый + ребенок'
    
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
    assert user_data['STATE'] == 'PAID'
    
    context.application.mark_data_for_update_persistence.assert_called_once_with(user_ids=[5473664345])


def test_processing_ticket_paid_website_error_in_notification_still_marks_persistence(monkeypatch):
    """
    Проверяет, что при ошибке отправки уведомлений блок finally всё равно
    помечает измененные данные для сохранения в persistence.
    """
    update = _create_mock_update(source='website', chat_id='5473664345', ticket_ids='4915')
    context = _create_mock_context(has_persistence=True)
    
    mock_ticket = MagicMock(base_ticket_id=1, price=1000)
    mock_base_ticket = MagicMock()
    mock_base_ticket.name = 'Взрослый + ребенок'
    
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
    # Ошибка BadRequest перехватывается обработчиком, пометка persistence выполняется
    monkeypatch.setattr('handlers.hooks.yookassa_hl.send_approve_reject_message_to_admin_in_webhook',
                        AsyncMock(side_effect=BadRequest('Test notification error')))
    monkeypatch.setattr('handlers.hooks.yookassa_hl._edit_message_reply_markup',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl._send_message',
                        AsyncMock(return_value=MagicMock(message_id=777)))

    asyncio.run(yookassa_hl.processing_ticket_paid(update, context))

    context.application.mark_data_for_update_persistence.assert_called_once_with(user_ids=[5473664345])


def test_processing_ticket_paid_website_unhandled_exception_still_marks_persistence(monkeypatch):
    """
    Проверяет, что даже при необработанном исключении блок finally выполняет
    пометку данных в persistence.
    """
    update = _create_mock_update(source='website', chat_id='5473664345', ticket_ids='4915')
    context = _create_mock_context(has_persistence=True)
    
    monkeypatch.setattr('handlers.hooks.yookassa_hl.create_str_info_by_schedule_event_id',
                        AsyncMock(return_value='01.01 12:00 Спектакль'))
    # Ошибка при обновлении билета
    monkeypatch.setattr('handlers.hooks.yookassa_hl.publish_update_ticket',
                        AsyncMock(side_effect=RuntimeError('Critical failure')))
    monkeypatch.setattr('handlers.hooks.yookassa_hl.update_ticket_in_gspread',
                        AsyncMock(side_effect=RuntimeError('Critical failure')))

    with pytest.raises(RuntimeError):
        asyncio.run(yookassa_hl.processing_ticket_paid(update, context))

    context.application.mark_data_for_update_persistence.assert_called_once_with(user_ids=[5473664345])


@pytest.mark.parametrize('invalid_chat_id', ['0', '', 'invalid', None])
def test_processing_ticket_paid_invalid_chat_ids(monkeypatch, invalid_chat_id):
    """
    Проверяет, что при некорректных chat_id (0, пустая строка, нечисловые)
    сессия не создаётся и пометка persistence не вызывается.
    """
    update = _create_mock_update(source='website', chat_id=invalid_chat_id, message_id=0, ticket_ids='4915')
    context = _create_mock_context(has_persistence=True)
    
    mock_ticket = MagicMock(base_ticket_id=1, price=1000)
    mock_base_ticket = MagicMock()
    mock_base_ticket.name = 'Взрослый + ребенок'
    
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
    context.application.mark_data_for_update_persistence.assert_not_called()


def test_processing_ticket_paid_no_persistence(monkeypatch):
    """
    Проверяет, что при отсутствии persistence (context.application.persistence is None)
    обработка выполняется успешно без обращений к update_conversation.
    """
    update = _create_mock_update(source='website', chat_id='5473664345', ticket_ids='4915')
    context = _create_mock_context(has_persistence=False)
    
    mock_ticket = MagicMock(base_ticket_id=1, price=1000)
    mock_base_ticket = MagicMock()
    mock_base_ticket.name = 'Взрослый + ребенок'
    
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

    assert 5473664345 in context.application.user_data
    assert context.application.user_data[5473664345]['STATE'] == 'PAID'


def test_send_approve_reject_message_to_admin_real_helper_website_user(monkeypatch):
    """
    Проверяет реальный helper send_approve_reject_message_to_admin_in_webhook
    для веб-пользователя без ключа 'user' в user_data:
    - отсутствие KeyError: 'user';
    - вызов отправки сообщения админу;
    - отметка is_admin_notified=True в БД.
    """
    context = _create_mock_context()
    chat_id = 5473664345
    ticket_id = 4915
    
    context.application.user_data[chat_id].update({
        'command': 'reserve',
        'reserve_user_data': {'ticket_ids': [ticket_id]}
    })
    
    mock_ticket = MagicMock(
        id=ticket_id,
        price=1000,
        base_ticket_id=1,
        schedule_event_id=101,
        promo_id=None,
        is_admin_notified=False,
        notes='Сайт: user@example.com'
    )
    mock_schedule_event = MagicMock(theater_event_id=10)
    mock_theater_event = MagicMock()
    mock_theater_event.name = 'Тестовый спектакль'
    mock_base_ticket = MagicMock()
    mock_base_ticket.name = 'Взрослый + ребенок'
    
    mock_db_result = MagicMock()
    mock_db_result.scalars.return_value.all.return_value = []
    context.session.execute = AsyncMock(return_value=mock_db_result)
    
    monkeypatch.setattr('handlers.sub_hl.db_postgres.get_ticket',
                        AsyncMock(return_value=mock_ticket))
    monkeypatch.setattr('handlers.sub_hl.db_postgres.update_ticket',
                        AsyncMock())
    monkeypatch.setattr('handlers.sub_hl.db_postgres.get_schedule_event',
                        AsyncMock(return_value=mock_schedule_event))
    monkeypatch.setattr('handlers.sub_hl.db_postgres.get_theater_event',
                        AsyncMock(return_value=mock_theater_event))
    monkeypatch.setattr('handlers.sub_hl.db_postgres.get_base_ticket',
                        AsyncMock(return_value=mock_base_ticket))
    monkeypatch.setattr('handlers.sub_hl.get_formatted_date_and_time_of_event',
                        AsyncMock(return_value=('01.01.2026', '12:00')))
    monkeypatch.setattr('handlers.sub_hl._send_admin_message_with_retry',
                        AsyncMock())
    monkeypatch.setattr('utilities.utl_func.create_str_info_by_schedule_event_id',
                        AsyncMock(return_value='01.01 12:00 Спектакль'))

    asyncio.run(sub_hl.send_approve_reject_message_to_admin_in_webhook(
        context=context,
        chat_id=chat_id,
        message_id=0,
        ticket_ids=[ticket_id],
        thread_id=42,
        callback_name='reserve'
    ))

    sub_hl._send_admin_message_with_retry.assert_called_once()
    sub_hl.db_postgres.update_ticket.assert_called_with(context.session, ticket_id, is_admin_notified=True)
    assert context.application.user_data[chat_id]['reserve_user_data']['admin_notified'] is True


def test_get_booking_admin_text_user_none(monkeypatch):
    """
    Проверяет формирование административного текста для веб-бронирования при user=None.
    """
    context = _create_mock_context()
    ticket_id = 4915
    mock_ticket = MagicMock(
        id=ticket_id,
        price=1000,
        base_ticket_id=1,
        schedule_event_id=101,
        promo_id=None,
        notes='Сайт: test@domain.com'
    )
    mock_schedule_event = MagicMock(theater_event_id=10)
    mock_theater_event = MagicMock()
    mock_theater_event.name = 'Тестовый спектакль'
    mock_base_ticket = MagicMock()
    mock_base_ticket.name = 'Взрослый + ребенок'
    
    mock_db_result = MagicMock()
    mock_db_result.scalars.return_value.all.return_value = []
    context.session.execute = AsyncMock(return_value=mock_db_result)
    
    monkeypatch.setattr('handlers.sub_hl.db_postgres.get_ticket',
                        AsyncMock(return_value=mock_ticket))
    monkeypatch.setattr('handlers.sub_hl.db_postgres.get_schedule_event',
                        AsyncMock(return_value=mock_schedule_event))
    monkeypatch.setattr('handlers.sub_hl.db_postgres.get_theater_event',
                        AsyncMock(return_value=mock_theater_event))
    monkeypatch.setattr('handlers.sub_hl.db_postgres.get_base_ticket',
                        AsyncMock(return_value=mock_base_ticket))
    monkeypatch.setattr('handlers.sub_hl.get_formatted_date_and_time_of_event',
                        AsyncMock(return_value=('01.01.2026', '12:00')))
    monkeypatch.setattr('utilities.utl_func.create_str_info_by_schedule_event_id',
                        AsyncMock(return_value='01.01 12:00 Спектакль'))

    res_text = asyncio.run(sub_hl.get_booking_admin_text(
        context=context,
        ticket_ids=[ticket_id],
        user=None,
        user_data={}
    ))

    assert 'Покупатель: Сайт (test@domain.com)' in res_text


def test_processing_ticket_paid_bot_booking(monkeypatch):
    """
    Проверяет регрессию для бронирования через бота (source='bot').
    """
    update = _create_mock_update(source='bot', chat_id='5473664345', ticket_ids='4915')
    context = _create_mock_context()
    context.application.user_data[5473664345].update({
        'command': 'reserve',
        'bot_data_field': 'value'
    })
    
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
    context.application.mark_data_for_update_persistence.assert_called_once_with(user_ids=[5473664345])


@pytest.mark.parametrize('has_user', [True, False])
def test_processing_ticket_paid_admin_booking(monkeypatch, has_user):
    """
    Проверяет административную бронь (command='reserve_admin') с наличием и отсутствием ключа user в user_data.
    """
    update = _create_mock_update(source='website', chat_id='5473664345', command='reserve_admin', ticket_ids='4915')
    context = _create_mock_context()
    
    user_dict = context.application.user_data[5473664345]
    if has_user:
        mock_user = MagicMock(username='testadmin', full_name='Test Admin')
        user_dict['user'] = mock_user
    
    mock_ticket = MagicMock(base_ticket_id=1, price=1000, schedule_event_id=101)
    mock_base_ticket = MagicMock()
    mock_base_ticket.name = 'Взрослый + ребенок'
    
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
    monkeypatch.setattr('handlers.hooks.yookassa_hl.decrease_nonconfirm_seat',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.send_approve_message',
                        AsyncMock())
    monkeypatch.setattr('handlers.hooks.yookassa_hl.get_booking_admin_text',
                        AsyncMock(return_value='Детали брони'))
    monkeypatch.setattr('handlers.hooks.yookassa_hl._send_message',
                        AsyncMock())

    asyncio.run(yookassa_hl.processing_ticket_paid(update, context))

    yookassa_hl.db_postgres.update_ticket.assert_called_with(
        context.session, 4915, status=TicketStatus.APPROVED, promo_id=None
    )
    yookassa_hl.send_approve_message.assert_called_once_with(5473664345, context, [4915])
    context.application.mark_data_for_update_persistence.assert_called_once_with(user_ids=[5473664345])

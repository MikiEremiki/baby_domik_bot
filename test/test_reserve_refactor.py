from unittest.mock import AsyncMock, MagicMock
import asyncio

from handlers.common_hl import validate_phone_or_request
from handlers import reserve_hl
from handlers.reserve.choice import choice_mode
from handlers.reserve.input import get_phone, _update_children as input_update_children
from handlers.reserve.common import _update_children, send_msg_get_child
from handlers.reserve.payment import show_reservation_summary


def test_validate_phone_or_request_normalizes_phone(monkeypatch):
    async def fake_request_phone_number(update, context):
        raise AssertionError('request_phone_number should not be called for a valid phone')

    monkeypatch.setattr('handlers.common_hl.request_phone_number', fake_request_phone_number)

    phone, message = asyncio.run(
        validate_phone_or_request(None, None, '+7 (999) 111-22-33')
    )

    assert phone == '9991112233'
    assert message is None


def test_validate_phone_or_request_requests_contact_for_invalid_phone(monkeypatch):
    fake_message = object()

    async def fake_request_phone_number(update, context):
        return fake_message

    monkeypatch.setattr('handlers.common_hl.request_phone_number', fake_request_phone_number)

    phone, message = asyncio.run(
        validate_phone_or_request(None, None, '12345')
    )

    assert phone == None
    assert message is fake_message


def test_reserve_hl_reexports_choice_handler():
    assert reserve_hl.choice_mode is choice_mode


def test_reserve_hl_reexports_input_and_payment_handlers():
    assert reserve_hl.get_phone is get_phone
    assert reserve_hl.show_reservation_summary is show_reservation_summary
    assert input_update_children is _update_children


def test_update_children_modes(monkeypatch):
    async def run():
        mock_search = AsyncMock(return_value=[("Имя1", 3, 1)])
        mock_phone = AsyncMock(return_value=[("Имя2", 4, 2)])
        mock_my = AsyncMock(return_value=[("Имя3", 5, 3)])

        monkeypatch.setattr('handlers.reserve.common.db_postgres.search_children', mock_search)
        monkeypatch.setattr('handlers.reserve.common.db_postgres.get_children_by_phone', mock_phone)
        monkeypatch.setattr('handlers.reserve.common.db_postgres.get_children', mock_my)

        update = MagicMock()
        update.effective_user.id = 12345
        context = MagicMock()
        context.session = MagicMock()

        # 1. SEARCH_NAME
        context.user_data = {
            'command': 'reserve',
            'reserve_user_data': {
                'child_filter_mode': 'SEARCH_NAME',
                'child_search_name': 'Тест'
            }
        }
        res = await _update_children(update, context)
        assert res == [("Имя1", 3, 1)]
        mock_search.assert_awaited_with(context.session, name_query='Тест')

        # 2. SEARCH_AGE
        context.user_data = {
            'command': 'reserve',
            'reserve_user_data': {
                'child_filter_mode': 'SEARCH_AGE',
                'child_search_age': 4
            }
        }
        res = await _update_children(update, context)
        assert res == [("Имя1", 3, 1)]
        mock_search.assert_awaited_with(context.session, age_query=4)

        # 3. PHONE with results
        context.user_data = {
            'command': 'reserve',
            'reserve_user_data': {
                'child_filter_mode': 'PHONE',
                'client_data': {'phone': '9991112233'}
            }
        }
        res = await _update_children(update, context)
        assert res == [("Имя2", 4, 2)]
        mock_phone.assert_awaited_with(context.session, '9991112233')

        # 4. PHONE empty fallback to MY for non-admin
        mock_phone.return_value = []
        context.user_data = {
            'command': 'reserve',
            'reserve_user_data': {
                'child_filter_mode': 'PHONE',
                'client_data': {'phone': '9991112233'}
            }
        }
        res = await _update_children(update, context)
        assert res == [("Имя3", 5, 3)]
        assert context.user_data['reserve_user_data']['child_filter_mode'] == 'MY'
        mock_my.assert_awaited_with(context.session, 12345)

        # 5. Fallback MY
        context.user_data = {
            'command': 'reserve',
            'reserve_user_data': {
                'child_filter_mode': 'MY'
            }
        }
        res = await _update_children(update, context)
        assert res == [("Имя3", 5, 3)]

    asyncio.run(run())


def test_send_msg_get_child(monkeypatch):
    async def run():
        mock_ticket = MagicMock()
        mock_ticket.quality_of_children = 1
        mock_ticket_get = AsyncMock(return_value=mock_ticket)
        mock_update_chld = AsyncMock(return_value=[("Ребенок", 3, 10)])
        mock_back = AsyncMock()

        monkeypatch.setattr('handlers.reserve.common.db_postgres.get_base_ticket', mock_ticket_get)
        monkeypatch.setattr('handlers.reserve.common._update_children', mock_update_chld)
        monkeypatch.setattr('handlers.reserve.common.set_back_context', mock_back)
        monkeypatch.setattr('handlers.reserve.common.db_postgres.count_adult_phones', AsyncMock(return_value=1))

        update = MagicMock()
        update.effective_user.id = 555
        update.effective_chat.send_message = AsyncMock(return_value=MagicMock(message_id=99))
        context = MagicMock()
        context.session = MagicMock()
        context.user_data = {
            'command': 'reserve',
            'postfix_for_cancel': 'canc',
            'reserve_user_data': {
                'chose_base_ticket_id': 1,
            }
        }

        msg = await send_msg_get_child(update, context)
        assert msg.message_id == 99
        assert context.user_data['reserve_user_data']['children'] == [("Ребенок", 3, 10)]
        mock_ticket_get.assert_awaited_once_with(context.session, 1)
        mock_update_chld.assert_awaited_once_with(update, context)
        update.effective_chat.send_message.assert_awaited_once()
        mock_back.assert_awaited_once()

    asyncio.run(run())
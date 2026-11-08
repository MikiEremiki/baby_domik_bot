"""Unit tests for receipt API service and handlers — no real YooKassa calls."""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.receipt_service import (
    ReceiptStatus,
    ReceiptInfo,
    select_payment_receipt,
    get_ticket_receipt,
)
from api.yookassa_connect import build_ofd_url, fetch_payment_receipts
from handlers.receipt_hl import (
    format_receipt_card,
    build_receipt_card_keyboard,
    build_receipt_card_keyboard_sent,
    build_receipt_button_row,
    receipt_cmd,
    receipt_callback,
    receipt_send_callback,
)


# ---------------------------------------------------------------------------
# build_ofd_url
# ---------------------------------------------------------------------------

def test_build_ofd_url():
    url = build_ofd_url('123456789012', '098765432109', '000001')
    assert url == 'https://lk.platformaofd.ru/web/noauth/cheque?fn=123456789012&fp=098765432109&i=000001'


# ---------------------------------------------------------------------------
# select_payment_receipt
# ---------------------------------------------------------------------------

def _receipt(type_='payment', status='succeeded', **kwargs):
    r = MagicMock()
    r.type = type_
    r.status = status
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


def test_select_payment_receipt_empty():
    assert select_payment_receipt([]) is None


def test_select_payment_receipt_refund_only():
    items = [_receipt(type_='refund')]
    assert select_payment_receipt(items) is None


def test_select_payment_receipt_succeeded_preferred():
    items = [_receipt(type_='payment', status='pending'), _receipt(type_='payment', status='succeeded')]
    result = select_payment_receipt(items)
    assert result.status == 'succeeded'


def test_select_payment_receipt_pending_fallback():
    items = [_receipt(type_='payment', status='pending')]
    result = select_payment_receipt(items)
    assert result.status == 'pending'


def test_select_payment_receipt_mixed_refund_and_payment():
    items = [_receipt(type_='refund'), _receipt(type_='payment', status='succeeded')]
    result = select_payment_receipt(items)
    assert result.status == 'succeeded'


# ---------------------------------------------------------------------------
# fetch_payment_receipts
# ---------------------------------------------------------------------------

def test_fetch_payment_receipts_success():
    async def _run():
        mock_receipt = MagicMock()
        mock_receipt.type = 'payment'
        mock_result = MagicMock()
        mock_result.items = [mock_receipt]

        async def fake_to_thread(func, *args, **kwargs):
            return mock_result

        with patch('api.yookassa_connect.asyncio.to_thread', new=fake_to_thread):
            items = await fetch_payment_receipts('pay-123')
        assert len(items) == 1
        assert items[0].type == 'payment'

    asyncio.run(_run())


def test_fetch_payment_receipts_empty_items():
    async def _run():
        mock_result = MagicMock()
        mock_result.items = None

        async def fake_to_thread(func, *args, **kwargs):
            return mock_result

        with patch('api.yookassa_connect.asyncio.to_thread', new=fake_to_thread):
            items = await fetch_payment_receipts('pay-123')
        assert items == []

    asyncio.run(_run())


def test_fetch_payment_receipts_timeout():
    async def _run():
        async def fake_to_thread(func, *args, **kwargs):
            raise asyncio.TimeoutError()

        with patch('api.yookassa_connect.asyncio.to_thread', new=fake_to_thread):
            with pytest.raises(asyncio.TimeoutError):
                await fetch_payment_receipts('pay-123', timeout=0.01)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# get_ticket_receipt
# ---------------------------------------------------------------------------

def _mock_ticket(ticket_id=1, payment_id='pay-123', price=1000, status_value='Оплачен', chat_id=12345):
    t = MagicMock()
    t.id = ticket_id
    t.payment_id = payment_id
    t.price = price
    t.status = MagicMock()
    t.status.value = status_value
    if chat_id is not None:
        t.user = MagicMock()
        t.user.chat_id = chat_id
    else:
        t.user = None
    return t


def test_get_ticket_receipt_not_found():
    async def _run():
        async def fake_get_ticket(session, tid):
            return None

        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            info = await get_ticket_receipt(MagicMock(), 999)
        assert info.status == ReceiptStatus.NOT_FOUND
        assert info.ticket_id == 999

    asyncio.run(_run())


def test_get_ticket_receipt_no_payment():
    async def _run():
        async def fake_get_ticket(session, tid):
            return _mock_ticket(payment_id=None)

        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            info = await get_ticket_receipt(MagicMock(), 1)
        assert info.status == ReceiptStatus.NO_PAYMENT
        assert info.price == 1000

    asyncio.run(_run())


def test_get_ticket_receipt_api_error_timeout():
    async def _run():
        async def fake_get_ticket(session, tid):
            return _mock_ticket()

        async def fake_fetch(payment_id, timeout=10.0):
            raise asyncio.TimeoutError()

        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            with patch('api.receipt_service.fetch_payment_receipts', new=fake_fetch):
                info = await get_ticket_receipt(MagicMock(), 1)
        assert info.status == ReceiptStatus.API_ERROR

    asyncio.run(_run())


def test_get_ticket_receipt_api_error_exception():
    async def _run():
        async def fake_get_ticket(session, tid):
            return _mock_ticket()

        async def fake_fetch(payment_id, timeout=10.0):
            raise RuntimeError('SDK crash')

        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            with patch('api.receipt_service.fetch_payment_receipts', new=fake_fetch):
                info = await get_ticket_receipt(MagicMock(), 1)
        assert info.status == ReceiptStatus.API_ERROR

    asyncio.run(_run())


def test_get_ticket_receipt_pending_empty_list():
    async def _run():
        async def fake_get_ticket(session, tid):
            return _mock_ticket()

        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            with patch('api.receipt_service.fetch_payment_receipts', return_value=[]):
                info = await get_ticket_receipt(MagicMock(), 1)
        assert info.status == ReceiptStatus.PENDING

    asyncio.run(_run())


def test_get_ticket_receipt_canceled():
    async def _run():
        async def fake_get_ticket(session, tid):
            return _mock_ticket()

        canceled_receipt = _receipt(type_='payment', status='canceled')
        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            with patch('api.receipt_service.fetch_payment_receipts', return_value=[canceled_receipt]):
                info = await get_ticket_receipt(MagicMock(), 1)
        assert info.status == ReceiptStatus.CANCELED

    asyncio.run(_run())


def test_get_ticket_receipt_pending_status():
    async def _run():
        async def fake_get_ticket(session, tid):
            return _mock_ticket()

        pending_receipt = _receipt(type_='payment', status='pending')
        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            with patch('api.receipt_service.fetch_payment_receipts', return_value=[pending_receipt]):
                info = await get_ticket_receipt(MagicMock(), 1)
        assert info.status == ReceiptStatus.PENDING

    asyncio.run(_run())


def test_get_ticket_receipt_ready():
    async def _run():
        async def fake_get_ticket(session, tid):
            return _mock_ticket()

        ready_receipt = _receipt(
            type_='payment',
            status='succeeded',
            fiscal_storage_number='123456789012',
            fiscal_attribute='098765432109',
            fiscal_document_number='000001',
            fd='FD-VALUE',
            registered_at='2026-10-11T12:00:00Z',
        )
        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            with patch('api.receipt_service.fetch_payment_receipts', return_value=[ready_receipt]):
                info = await get_ticket_receipt(MagicMock(), 1)
        assert info.status == ReceiptStatus.READY
        assert info.fn == '123456789012'
        assert info.fp == '098765432109'
        assert info.fd == 'FD-VALUE'
        assert info.ofd_url == 'https://lk.platformaofd.ru/web/noauth/cheque?fn=123456789012&fp=098765432109&i=000001'
        assert info.registered_at is not None
        assert info.client_chat_id == 12345

    asyncio.run(_run())


def test_get_ticket_receipt_refund_only_canceled():
    async def _run():
        async def fake_get_ticket(session, tid):
            return _mock_ticket()

        refund_receipt = _receipt(type_='refund')
        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            with patch('api.receipt_service.fetch_payment_receipts', return_value=[refund_receipt]):
                info = await get_ticket_receipt(MagicMock(), 1)
        assert info.status == ReceiptStatus.CANCELED

    asyncio.run(_run())


def test_get_ticket_receipt_ready_no_user():
    async def _run():
        async def fake_get_ticket(session, tid):
            return _mock_ticket(chat_id=None)

        ready_receipt = _receipt(
            type_='payment',
            status='succeeded',
            fiscal_storage_number='123456789012',
            fiscal_attribute='098765432109',
            fiscal_document_number='000001',
        )
        with patch('api.receipt_service.get_ticket', new=fake_get_ticket):
            with patch('api.receipt_service.fetch_payment_receipts', return_value=[ready_receipt]):
                info = await get_ticket_receipt(MagicMock(), 1)
        assert info.status == ReceiptStatus.READY
        assert info.client_chat_id is None

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# format_receipt_card
# ---------------------------------------------------------------------------

def _receipt_info(
    status=ReceiptStatus.READY,
    ticket_id=1,
    price=1000,
    fn='123456789012',
    fd='FD-VALUE',
    fp='098765432109',
    registered_at=None,
    ofd_url=None,
    ticket_status='Оплачен',
    client_chat_id=12345,
):
    return ReceiptInfo(
        status=status,
        ticket_id=ticket_id,
        price=price,
        fn=fn,
        fd=fd,
        fp=fp,
        registered_at=registered_at,
        ofd_url=ofd_url,
        ticket_status=ticket_status,
        client_chat_id=client_chat_id,
    )


def test_format_receipt_card_ready_with_fiscal_data():
    msk = timezone(timedelta(hours=3))
    registered_at = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
    info = _receipt_info(registered_at=registered_at, ofd_url='http://example.com')
    text = format_receipt_card(info)
    assert '✅' in text
    assert 'Чек готов' in text
    assert 'Билет: <code>1</code>' in text
    assert 'Сумма: 1000 ₽' in text
    assert 'ФН: 123456789012' in text
    assert 'ФД: FD-VALUE' in text
    assert 'ФП: 098765432109' in text
    assert '11.10.2026 15:00' in text  # UTC 12:00 → MSK 15:00
    assert '(МСК)' in text


def test_format_receipt_card_pending():
    info = _receipt_info(
        status=ReceiptStatus.PENDING,
        fn=None,
        fd=None,
        fp=None,
    )
    text = format_receipt_card(info)
    assert '⏳' in text
    assert 'Чек формируется' in text
    assert 'ФН' not in text


def test_format_receipt_card_not_found():
    info = _receipt_info(
        status=ReceiptStatus.NOT_FOUND,
        ticket_id=999,
        price=None,
        ticket_status=None,
    )
    text = format_receipt_card(info)
    assert '🔍' in text
    assert 'Билет не найден' in text
    assert 'Билет: <code>999</code>' in text
    assert 'Сумма' not in text


def test_format_receipt_card_no_payment():
    info = _receipt_info(
        status=ReceiptStatus.NO_PAYMENT,
        price=500,
    )
    text = format_receipt_card(info)
    assert '💳' in text
    assert 'Оплата не найдена' in text


def test_format_receipt_card_canceled():
    info = _receipt_info(status=ReceiptStatus.CANCELED)
    text = format_receipt_card(info)
    assert '❌' in text
    assert 'Чек отменён' in text


def test_format_receipt_card_api_error():
    info = _receipt_info(status=ReceiptStatus.API_ERROR)
    text = format_receipt_card(info)
    assert '⚠️' in text
    assert 'Ошибка получения чека' in text


def test_format_receipt_card_ready_no_date():
    """READY receipt without registered_at should not show date."""
    info = _receipt_info(registered_at=None)
    text = format_receipt_card(info)
    assert 'Дата регистрации' not in text


# ---------------------------------------------------------------------------
# build_receipt_card_keyboard
# ---------------------------------------------------------------------------

def test_build_receipt_card_keyboard_ready_with_url():
    info = _receipt_info(ofd_url='http://example.com', client_chat_id=None)
    keyboard = build_receipt_card_keyboard(info)
    assert keyboard is not None
    buttons = keyboard.inline_keyboard
    assert len(buttons) == 1
    btn = buttons[0][0]
    assert btn.text == '🌐 Открыть чек ОФД'
    assert btn.url == 'http://example.com'


def test_build_receipt_card_keyboard_with_client_chat_id():
    """READY receipt with client_chat_id should include send button."""
    info = _receipt_info(ofd_url='http://example.com', client_chat_id=12345)
    keyboard = build_receipt_card_keyboard(info)
    assert keyboard is not None
    buttons = keyboard.inline_keyboard
    assert len(buttons) == 1
    assert len(buttons[0]) == 2
    btn_ofd = buttons[0][0]
    assert btn_ofd.text == '🌐 Открыть чек ОФД'
    assert btn_ofd.url == 'http://example.com'
    btn_send = buttons[0][1]
    assert btn_send.text == '📤 Отправить клиенту'
    assert btn_send.callback_data == 'receipt_send|1'


def test_build_receipt_card_keyboard_sent_to_client_flag():
    """When sent_to_client=True, send button should not appear."""
    info = _receipt_info(ofd_url='http://example.com', client_chat_id=12345)
    keyboard = build_receipt_card_keyboard(info, sent_to_client=True)
    assert keyboard is not None
    buttons = keyboard.inline_keyboard
    assert len(buttons) == 1
    assert len(buttons[0]) == 1
    assert buttons[0][0].text == '🌐 Открыть чек ОФД'


def test_build_receipt_card_keyboard_sent():
    """Sent keyboard should show OFD URL + sent confirmation button."""
    info = _receipt_info(ofd_url='http://example.com', client_chat_id=12345)
    keyboard = build_receipt_card_keyboard_sent(info)
    assert keyboard is not None
    buttons = keyboard.inline_keyboard
    assert len(buttons) == 2
    assert buttons[0][0].text == '🌐 Открыть чек ОФД'
    assert buttons[0][0].url == 'http://example.com'
    assert buttons[1][0].text == '✅ Отправлено клиенту'
    assert buttons[1][0].callback_data == 'receipt_sent|noop'


def test_build_receipt_card_keyboard_sent_not_ready():
    """Sent keyboard should return None for non-READY status."""
    info = _receipt_info(status=ReceiptStatus.PENDING, ofd_url='http://example.com')
    keyboard = build_receipt_card_keyboard_sent(info)
    assert keyboard is None


def test_build_receipt_card_keyboard_ready_no_url():
    info = _receipt_info(ofd_url=None)
    keyboard = build_receipt_card_keyboard(info)
    assert keyboard is None


def test_build_receipt_card_keyboard_pending():
    info = _receipt_info(status=ReceiptStatus.PENDING, ofd_url='http://example.com')
    keyboard = build_receipt_card_keyboard(info)
    assert keyboard is None


# ---------------------------------------------------------------------------
# build_receipt_button_row
# ---------------------------------------------------------------------------

def test_build_receipt_button_row():
    keyboard = build_receipt_button_row(42)
    buttons = keyboard.inline_keyboard
    assert len(buttons) == 1
    btn = buttons[0][0]
    assert btn.text == '🧾 Чек'
    assert btn.callback_data == 'receipt|42'


# ---------------------------------------------------------------------------
# receipt_cmd — no args shows help
# ---------------------------------------------------------------------------

def test_receipt_cmd_no_args():
    async def _run():
        update = MagicMock()
        msg = MagicMock()
        msg.message_id = 10
        msg.reply_text = AsyncMock()
        update.effective_message = msg

        context = MagicMock()
        context.args = []

        await receipt_cmd(update, context)

        # Should call reply_text with help text
        call_kwargs = update.effective_message.reply_text.call_args
        assert call_kwargs is not None
        text = call_kwargs[1]['text']
        assert '/receipt' in text

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# receipt_cmd — invalid ticket ID
# ---------------------------------------------------------------------------

def test_receipt_cmd_invalid_ticket_id():
    async def _run():
        update = MagicMock()
        msg = MagicMock()
        msg.message_id = 10
        msg.reply_text = AsyncMock()
        update.effective_message = msg

        context = MagicMock()
        context.args = ['abc']

        await receipt_cmd(update, context)

        call_kwargs = update.effective_message.reply_text.call_args
        text = call_kwargs[1]['text']
        assert 'Неверный номер' in text

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# receipt_cmd — READY status includes keyboard with OFD URL
# ---------------------------------------------------------------------------

def test_receipt_cmd_ready_with_keyboard():
    async def _run():
        update = MagicMock()
        msg = MagicMock()
        msg.message_id = 10
        msg.reply_text = AsyncMock()
        update.effective_message = msg

        context = MagicMock()
        context.args = ['42']
        context.session = MagicMock()

        msk = timezone(timedelta(hours=3))
        ready_info = ReceiptInfo(
            status=ReceiptStatus.READY,
            ticket_id=42,
            price=1000,
            fn='123',
            fp='456',
            fd='FD',
            registered_at=datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc),
            ofd_url='http://ofd.example.com',
            ticket_status='Оплачен',
            client_chat_id=12345,
        )

        with patch('handlers.receipt_hl.get_ticket_receipt', new=AsyncMock(return_value=ready_info)):
            await receipt_cmd(update, context)

        call_kwargs = update.effective_message.reply_text.call_args
        assert call_kwargs[1]['reply_markup'] is not None
        keyboard = call_kwargs[1]['reply_markup']
        btn = keyboard.inline_keyboard[0][0]
        assert btn.url == 'http://ofd.example.com'

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# receipt_cmd — PENDING status, no keyboard
# ---------------------------------------------------------------------------

def test_receipt_cmd_pending_no_keyboard():
    async def _run():
        update = MagicMock()
        msg = MagicMock()
        msg.message_id = 10
        msg.reply_text = AsyncMock()
        update.effective_message = msg

        context = MagicMock()
        context.args = ['42']
        context.session = MagicMock()

        pending_info = ReceiptInfo(
            status=ReceiptStatus.PENDING,
            ticket_id=42,
            price=1000,
        )

        with patch('handlers.receipt_hl.get_ticket_receipt', new=AsyncMock(return_value=pending_info)):
            await receipt_cmd(update, context)

        call_kwargs = update.effective_message.reply_text.call_args
        assert call_kwargs[1]['reply_markup'] is None

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# receipt_callback — admin check
# ---------------------------------------------------------------------------

def test_receipt_callback_non_admin():
    async def _run():
        update = MagicMock()
        query = MagicMock()
        query.data = 'receipt|42'
        query.message.message_id = 5
        query.answer = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 99999  # non-admin
        update.effective_chat.send_message = AsyncMock()

        context = MagicMock()
        context.session = MagicMock()

        with patch('handlers.receipt_hl.is_privileged_update', return_value=False):
            await receipt_callback(update, context)

        # Should not send any message
        assert not update.effective_chat.send_message.called

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# receipt_callback — admin, sends card
# ---------------------------------------------------------------------------

def test_receipt_callback_admin_sends_card():
    async def _run():
        update = MagicMock()
        query = MagicMock()
        query.data = 'receipt|42'
        query.message.message_id = 5
        query.answer = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 12345  # admin
        update.effective_message.message_thread_id = 100
        update.effective_chat.send_message = AsyncMock()

        context = MagicMock()
        context.session = MagicMock()

        ready_info = ReceiptInfo(
            status=ReceiptStatus.READY,
            ticket_id=42,
            price=1000,
            fn='123',
            fp='456',
            fd='FD',
            ofd_url='http://ofd.example.com',
            ticket_status='Оплачен',
            client_chat_id=12345,
        )

        with patch('handlers.receipt_hl.is_privileged_update', return_value=True):
            with patch('handlers.receipt_hl.get_ticket_receipt', new=AsyncMock(return_value=ready_info)):
                await receipt_callback(update, context)

        # Should send message with keyboard
        assert update.effective_chat.send_message.called
        call_kwargs = update.effective_chat.send_message.call_args
        assert call_kwargs[1]['reply_markup'] is not None

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# receipt_send_callback — non-admin alert
# ---------------------------------------------------------------------------

def test_receipt_send_callback_non_admin():
    async def _run():
        update = MagicMock()
        query = MagicMock()
        query.data = 'receipt_send|42'
        query.answer = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 99999  # non-admin

        context = MagicMock()
        context.session = MagicMock()

        with patch('handlers.receipt_hl.is_privileged_update', return_value=False):
            await receipt_send_callback(update, context)

        # Should answer with alert
        query.answer.assert_called_with('Только для администраторов', show_alert=True)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# receipt_send_callback — success: sends to client + edits keyboard
# ---------------------------------------------------------------------------

def test_receipt_send_callback_success():
    async def _run():
        update = MagicMock()
        query = MagicMock()
        query.data = 'receipt_send|42'
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_reply_markup = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 12345  # admin

        context = MagicMock()
        context.session = MagicMock()
        context.bot.send_message = AsyncMock()

        ready_info = ReceiptInfo(
            status=ReceiptStatus.READY,
            ticket_id=42,
            price=1000,
            fn='123',
            fp='456',
            fd='FD',
            ofd_url='http://ofd.example.com',
            ticket_status='Оплачен',
            client_chat_id=67890,
        )

        with patch('handlers.receipt_hl.is_privileged_update', return_value=True):
            with patch('handlers.receipt_hl.get_ticket_receipt', new=AsyncMock(return_value=ready_info)):
                await receipt_send_callback(update, context)

        # Should send message to client
        assert context.bot.send_message.called
        call_kwargs = context.bot.send_message.call_args
        assert call_kwargs[1]['chat_id'] == 67890
        assert 'http://ofd.example.com' in call_kwargs[1]['text']
        assert '42' in call_kwargs[1]['text']

        # Should edit keyboard to sent state
        assert query.message.edit_reply_markup.called
        edit_kwargs = query.message.edit_reply_markup.call_args
        sent_keyboard = edit_kwargs[1]['reply_markup']
        assert sent_keyboard.inline_keyboard[1][0].text == '✅ Отправлено клиенту'

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# receipt_send_callback — Forbidden: client blocked bot
# ---------------------------------------------------------------------------

def test_receipt_send_callback_forbidden():
    async def _run():
        from telegram.error import Forbidden

        update = MagicMock()
        query = MagicMock()
        query.data = 'receipt_send|42'
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.edit_reply_markup = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 12345  # admin

        context = MagicMock()
        context.session = MagicMock()
        context.bot.send_message = AsyncMock(side_effect=Forbidden('User not found'))

        ready_info = ReceiptInfo(
            status=ReceiptStatus.READY,
            ticket_id=42,
            price=1000,
            ofd_url='http://ofd.example.com',
            client_chat_id=67890,
        )

        with patch('handlers.receipt_hl.is_privileged_update', return_value=True):
            with patch('handlers.receipt_hl.get_ticket_receipt', new=AsyncMock(return_value=ready_info)):
                await receipt_send_callback(update, context)

        # Should answer with blocked alert
        # First answer() was called at the start, second with alert
        answer_calls = query.answer.call_args_list
        assert any(
            c[1].get('show_alert') and 'заблокировал' in c[1].get('', '')
            or (len(c[0]) > 0 and 'заблокировал' in c[0][0])
            for c in answer_calls
        )
        # Should NOT edit keyboard
        assert not query.message.edit_reply_markup.called

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# receipt_send_callback — not ready receipt
# ---------------------------------------------------------------------------

def test_receipt_send_callback_not_ready():
    async def _run():
        update = MagicMock()
        query = MagicMock()
        query.data = 'receipt_send|42'
        query.answer = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 12345  # admin

        context = MagicMock()
        context.session = MagicMock()
        context.bot.send_message = AsyncMock()

        pending_info = ReceiptInfo(
            status=ReceiptStatus.PENDING,
            ticket_id=42,
            client_chat_id=67890,
        )

        with patch('handlers.receipt_hl.is_privileged_update', return_value=True):
            with patch('handlers.receipt_hl.get_ticket_receipt', new=AsyncMock(return_value=pending_info)):
                await receipt_send_callback(update, context)

        # Should NOT send to client
        assert not context.bot.send_message.called

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# create_approve_and_reject_replay — regression: without extra_rows
# ---------------------------------------------------------------------------

def test_create_approve_and_reject_replay_without_extra_rows():
    """Without extra_rows, keyboard should have exactly 1 row (Approve/Reject)."""
    from utilities.utl_func import create_approve_and_reject_replay

    keyboard = create_approve_and_reject_replay('reserve', '123 456')
    rows = keyboard.inline_keyboard
    assert len(rows) == 1
    assert len(rows[0]) == 2
    assert rows[0][0].text == 'Подтвердить'
    assert rows[0][0].callback_data == 'confirm-reserve|123 456'
    assert rows[0][1].text == 'Отклонить'
    assert rows[0][1].callback_data == 'reject-reserve|123 456'


# ---------------------------------------------------------------------------
# create_approve_and_reject_replay — with extra_rows
# ---------------------------------------------------------------------------

def test_create_approve_and_reject_replay_with_extra_rows():
    """With extra_rows, keyboard should have Approve/Reject row + extra rows."""
    from telegram import InlineKeyboardButton
    from utilities.utl_func import create_approve_and_reject_replay

    extra = [
        [InlineKeyboardButton('🧾 Чек', callback_data='receipt|42')]
    ]
    keyboard = create_approve_and_reject_replay(
        'reserve', '123 456', extra_rows=extra
    )
    rows = keyboard.inline_keyboard
    assert len(rows) == 2
    # First row: Approve/Reject
    assert rows[0][0].text == 'Подтвердить'
    assert rows[0][1].text == 'Отклонить'
    # Second row: extra receipt button
    assert len(rows[1]) == 1
    assert rows[1][0].text == '🧾 Чек'
    assert rows[1][0].callback_data == 'receipt|42'


# ---------------------------------------------------------------------------
# create_approve_and_reject_replay — extra_rows=None (explicit)
# ---------------------------------------------------------------------------

def test_create_approve_and_reject_replay_extra_rows_none():
    """Explicit extra_rows=None should behave like no extra_rows."""
    from utilities.utl_func import create_approve_and_reject_replay

    keyboard = create_approve_and_reject_replay('reserve', '123 456', extra_rows=None)
    rows = keyboard.inline_keyboard
    assert len(rows) == 1

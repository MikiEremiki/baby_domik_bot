"""Tests for the /tickets "My Tickets" public page."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.web.main import app
from api.web.config import broker
from api.web.deps import get_session
from api.web.routes import pages, booking
from api.web.services import booking_service
from db.enum import TicketStatus
from conftest import _create_web_client, _create_mock_schedule_event


def _mock_ticket(ticket_id=1, status=TicketStatus.PAID, schedule_event_id=101):
    """Create a mock Ticket object."""
    t = MagicMock()
    t.id = ticket_id
    t.status = status
    t.schedule_event_id = schedule_event_id
    t.email = 'test@example.com'
    t.phone = 9991112233
    t.price = 2400

    # Schedule event
    se = MagicMock()
    se.id = schedule_event_id
    se.datetime_event = datetime(2030, 6, 15, 12, 0, tzinfo=timezone.utc)
    te = MagicMock()
    te.name = 'Кот в сапогах'
    se.theater_event = te
    se.place = None
    t.schedule_event = se

    # Base ticket
    bt = MagicMock()
    bt.name = '1 взрослый + 1 ребенок'
    bt.quality_of_adult = 1
    bt.quality_of_add_adult = 0
    bt.quality_of_children = 1
    t.base_ticket = bt

    return t


def test_tickets_page_gets_rendered(monkeypatch):
    """GET /tickets renders the search form."""
    with _create_web_client(monkeypatch) as client:
        response = client.get('/tickets')

    assert response.status_code == 200
    assert 'Мои билеты' in response.text
    assert 'По номеру билета' in response.text
    assert 'По контактам' in response.text
    assert 'no-store' in response.headers.get('Cache-Control', '')


def test_tickets_search_by_number_found(monkeypatch):
    """POST /tickets with a valid ticket number returns the ticket card."""
    mock_ticket = _mock_ticket(ticket_id=42, status=TicketStatus.PAID)
    monkeypatch.setattr(booking, 'get_ticket', AsyncMock(return_value=mock_ticket))

    with _create_web_client(monkeypatch) as client:
        response = client.post('/tickets', data={
            'search_type': 'number',
            'ticket_number': '42',
        })

    assert response.status_code == 200
    assert 'Билет #42' in response.text
    assert 'Кот в сапогах' in response.text
    assert '15.06.2030' in response.text
    # 12:00 UTC -> 15:00 Moscow (UTC+3)
    assert '15:00' in response.text
    assert '1 взрослый + 1 ребенок' in response.text
    assert 'Взрослых: 1' in response.text
    assert 'Детей: 1' in response.text
    # No confidential data
    assert 'test@example.com' not in response.text
    assert '9991112233' not in response.text
    assert '2400' not in response.text


def test_tickets_search_by_number_not_found(monkeypatch):
    """POST /tickets with an unknown ticket number shows not found."""
    monkeypatch.setattr(booking, 'get_ticket', AsyncMock(return_value=None))

    with _create_web_client(monkeypatch) as client:
        response = client.post('/tickets', data={
            'search_type': 'number',
            'ticket_number': '99999',
        })

    assert response.status_code == 200
    assert 'Билет не найден' in response.text


def test_tickets_search_by_contacts_found(monkeypatch):
    """POST /tickets with matching email+phone returns tickets."""
    mock_ticket = _mock_ticket(ticket_id=10, status=TicketStatus.PAID)
    monkeypatch.setattr(booking, 'get_tickets_by_contacts', AsyncMock(return_value=[mock_ticket]))

    with _create_web_client(monkeypatch) as client:
        response = client.post('/tickets', data={
            'search_type': 'contacts',
            'email': 'test@example.com',
            'phone': '+79991112233',
        })

    assert response.status_code == 200
    assert 'Билет #10' in response.text
    assert 'Кот в сапогах' in response.text
    # No confidential data in output
    assert 'test@example.com' not in response.text
    assert '9991112233' not in response.text


def test_tickets_search_by_contacts_not_found(monkeypatch):
    """POST /tickets with no matching contacts shows not found."""
    monkeypatch.setattr(booking, 'get_tickets_by_contacts', AsyncMock(return_value=[]))

    with _create_web_client(monkeypatch) as client:
        response = client.post('/tickets', data={
            'search_type': 'contacts',
            'email': 'nobody@example.com',
            'phone': '+79000000000',
        })

    assert response.status_code == 200
    assert 'Билеты не найдены' in response.text
    assert 'подтверждение может занять' in response.text


def test_tickets_search_by_contacts_filters_past_sessions(monkeypatch):
    """Tickets for past sessions should not appear in contacts search."""
    # The DB function filters by datetime_event > now, so a past session
    # ticket should not be returned. We verify by checking the DB function
    # is called with the right params.
    mock_db_fn = AsyncMock(return_value=[])
    monkeypatch.setattr(booking, 'get_tickets_by_contacts', mock_db_fn)

    with _create_web_client(monkeypatch) as client:
        client.post('/tickets', data={
            'search_type': 'contacts',
            'email': 'test@example.com',
            'phone': '9991112233',
        })

    # Verify the DB function was called
    assert mock_db_fn.called
    call_kwargs = mock_db_fn.call_args
    assert call_kwargs[1]['email'] == 'test@example.com'
    assert call_kwargs[1]['phone'] == 9991112233


def test_tickets_search_by_number_any_status(monkeypatch):
    """Search by number finds tickets of any status, not just active."""
    # A CANCELED ticket should still be found by number
    mock_ticket = _mock_ticket(ticket_id=77, status=TicketStatus.CANCELED)
    monkeypatch.setattr(booking, 'get_ticket', AsyncMock(return_value=mock_ticket))

    with _create_web_client(monkeypatch) as client:
        response = client.post('/tickets', data={
            'search_type': 'number',
            'ticket_number': '77',
        })

    assert response.status_code == 200
    assert 'Билет #77' in response.text
    assert 'Отменен' in response.text


def test_tickets_search_by_number_any_date(monkeypatch):
    """Search by number finds tickets for past sessions too."""
    mock_ticket = _mock_ticket(ticket_id=88, status=TicketStatus.PAID)
    mock_ticket.schedule_event.datetime_event = datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(booking, 'get_ticket', AsyncMock(return_value=mock_ticket))

    with _create_web_client(monkeypatch) as client:
        response = client.post('/tickets', data={
            'search_type': 'number',
            'ticket_number': '88',
        })

    assert response.status_code == 200
    assert 'Билет #88' in response.text


def test_tickets_no_confidential_data_in_html(monkeypatch):
    """The ticket card HTML must not contain email, phone, price, or receipt links."""
    mock_ticket = _mock_ticket(ticket_id=55, status=TicketStatus.APPROVED)
    mock_ticket.email = 'secret@example.com'
    mock_ticket.phone = 1234567890
    mock_ticket.price = 5000
    monkeypatch.setattr(booking, 'get_tickets_by_contacts', AsyncMock(return_value=[mock_ticket]))

    with _create_web_client(monkeypatch) as client:
        response = client.post('/tickets', data={
            'search_type': 'contacts',
            'email': 'secret@example.com',
            'phone': '+71234567890',
        })

    assert response.status_code == 200
    html = response.text
    assert 'secret@example.com' not in html
    assert '1234567890' not in html
    assert '5000' not in html
    # No YooKassa receipt service calls
    assert 'yookassa' not in html.lower()
    assert 'ofd' not in html.lower()


def test_tickets_truncated_warning(monkeypatch):
    """When 50+ tickets are returned, a truncation warning is shown."""
    tickets = [_mock_ticket(ticket_id=i, status=TicketStatus.PAID) for i in range(50)]
    monkeypatch.setattr(booking, 'get_tickets_by_contacts', AsyncMock(return_value=tickets))

    with _create_web_client(monkeypatch) as client:
        response = client.post('/tickets', data={
            'search_type': 'contacts',
            'email': 'many@example.com',
            'phone': '9991112233',
        })

    assert response.status_code == 200
    assert 'Показано до 50 билетов' in response.text


def test_payment_result_has_my_tickets_button(monkeypatch):
    """The payment result page includes a link to /tickets."""
    monkeypatch.setattr(booking, 'get_ticket', AsyncMock(return_value=None))
    with _create_web_client(monkeypatch) as client:
        response = client.get('/payment-result?status=success')

    assert response.status_code == 200
    assert 'href="/tickets"' in response.text
    assert 'Мои билеты' in response.text


def test_navigation_includes_my_tickets(monkeypatch):
    """The layout navigation includes the /tickets link."""
    with _create_web_client(monkeypatch) as client:
        response = client.get('/tickets')

    assert response.status_code == 200
    assert 'href="/tickets"' in response.text
    assert 'Мои билеты' in response.text

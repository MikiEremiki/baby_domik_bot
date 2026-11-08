"""Tests for format_ticket_contacts — unified ticket contacts formatter.

Covers:
- Bot buyer: Telegram user username
- Bot buyer: full_name parameter (Telegram display name)
- Website buyer: always "Неизвестен"
- Ticket without user (user=None → "Покупатель: Неизвестен")
- Ticket with phone and email
- All TicketSource values (WEBSITE, BOT, None)
"""
from unittest.mock import MagicMock

from db.enum import TicketSource
from utilities.utl_ticket import format_ticket_contacts


def _make_ticket(
    source=None,
    user=None,
    phone=None,
    email=None,
) -> MagicMock:
    """Create a mock Ticket with the given attributes."""
    ticket = MagicMock()
    ticket.source = source
    ticket.user = user
    ticket.phone = phone
    ticket.email = email
    return ticket


def _make_user(username=None) -> MagicMock:
    """Create a mock User (DB model) with the given attributes."""
    user = MagicMock()
    user.username = username
    return user


# ——— Source ———


def test_format_source_website():
    ticket = _make_ticket(source=TicketSource.WEBSITE)
    result = format_ticket_contacts(ticket)
    assert 'Источник: Сайт' in result


def test_format_source_bot():
    ticket = _make_ticket(source=TicketSource.BOT)
    result = format_ticket_contacts(ticket)
    assert 'Источник: Бот' in result


def test_format_source_none():
    ticket = _make_ticket(source=None)
    result = format_ticket_contacts(ticket)
    assert 'Источник: не указан' in result


# ——— Buyer (user) ———


def test_format_buyer_bot_with_username():
    """Bot purchase: buyer is the Telegram user username."""
    user = _make_user(username='testuser')
    ticket = _make_ticket(source=TicketSource.BOT, user=user)
    result = format_ticket_contacts(ticket)
    assert 'Покупатель: @testuser testuser' in result


def test_format_buyer_bot_with_full_name():
    """Bot purchase: full_name takes precedence over username."""
    user = _make_user(username='testuser')
    ticket = _make_ticket(source=TicketSource.BOT, user=user)
    result = format_ticket_contacts(ticket, full_name='Иван Петров')
    assert 'Покупатель: @testuser Иван Петров' in result


def test_format_buyer_bot_full_name_no_username():
    """Bot purchase: full_name used when user has no username."""
    user = _make_user(username=None)
    ticket = _make_ticket(source=TicketSource.BOT, user=user)
    result = format_ticket_contacts(ticket, full_name='Иван Петров')
    assert 'Покупатель: Иван Петров' in result
    assert '@' not in result.split('Покупатель:')[1].split('\n')[0]


def test_format_buyer_bot_full_name_fallback_to_username():
    """Bot purchase: fallback to username when full_name is None."""
    user = _make_user(username='onlyuser')
    ticket = _make_ticket(source=TicketSource.BOT, user=user)
    result = format_ticket_contacts(ticket, full_name=None)
    assert 'Покупатель: @onlyuser onlyuser' in result


def test_format_buyer_bot_without_username():
    """Bot purchase: user has no username, shows 'Неизвестен'."""
    user = _make_user(username=None)
    ticket = _make_ticket(source=TicketSource.BOT, user=user)
    result = format_ticket_contacts(ticket)
    assert 'Покупатель: Неизвестен' in result


def test_format_buyer_none():
    """No user at all shows 'Неизвестен'."""
    ticket = _make_ticket(user=None)
    result = format_ticket_contacts(ticket)
    assert 'Покупатель: Неизвестен' in result


def test_format_buyer_website_unknown():
    """Website purchase: buyer is always unknown, even if user is set."""
    user = _make_user(username='website_user')
    ticket = _make_ticket(source=TicketSource.WEBSITE, user=user)
    result = format_ticket_contacts(ticket)
    assert 'Покупатель: Неизвестен' in result


def test_format_buyer_website_no_user():
    """Website purchase without user: buyer is unknown."""
    ticket = _make_ticket(source=TicketSource.WEBSITE, user=None)
    result = format_ticket_contacts(ticket)
    assert 'Покупатель: Неизвестен' in result


def test_format_buyer_source_none():
    """Unknown source: buyer is unknown."""
    user = _make_user(username='some_user')
    ticket = _make_ticket(source=None, user=user)
    result = format_ticket_contacts(ticket)
    assert 'Покупатель: Неизвестен' in result


# ——— Phone ———


def test_format_phone_present():
    ticket = _make_ticket(phone=91234567890)
    result = format_ticket_contacts(ticket)
    assert 'Телефон: +791234567890' in result


def test_format_phone_none():
    ticket = _make_ticket(phone=None)
    result = format_ticket_contacts(ticket)
    assert 'Телефон: не указан' in result


# ——— Email ———


def test_format_email_present():
    ticket = _make_ticket(email='buyer@example.com')
    result = format_ticket_contacts(ticket)
    assert 'Email: buyer@example.com' in result


def test_format_email_none():
    ticket = _make_ticket(email=None)
    result = format_ticket_contacts(ticket)
    assert 'Email: не указан' in result


def test_format_email_empty_string():
    ticket = _make_ticket(email='')
    result = format_ticket_contacts(ticket)
    assert 'Email: не указан' in result


# ——— Full combination ———


def test_format_full_ticket_bot_with_user():
    """Full bot ticket: buyer uses full_name when provided."""
    user = _make_user(username='ivan')
    ticket = _make_ticket(
        source=TicketSource.BOT,
        user=user,
        phone=9998887766,
        email='ivan@mail.ru',
    )
    result = format_ticket_contacts(ticket, full_name='Иван Петров')
    lines = result.split('\n')
    assert len(lines) == 4
    assert lines[0] == 'Источник: Бот'
    assert lines[1] == 'Покупатель: @ivan Иван Петров'
    assert lines[2] == 'Телефон: +79998887766'
    assert lines[3] == 'Email: ivan@mail.ru'


def test_format_full_ticket_without_user():
    ticket = _make_ticket(
        source=TicketSource.WEBSITE,
        user=None,
        phone=9112223344,
        email='site-buyer@example.com',
    )
    result = format_ticket_contacts(ticket)
    lines = result.split('\n')
    assert len(lines) == 4
    assert lines[0] == 'Источник: Сайт'
    assert lines[1] == 'Покупатель: Неизвестен'
    assert lines[2] == 'Телефон: +79112223344'
    assert lines[3] == 'Email: site-buyer@example.com'


def test_format_minimal_ticket():
    """Ticket with all optional fields None."""
    ticket = _make_ticket(
        source=None,
        user=None,
        phone=None,
        email=None,
    )
    result = format_ticket_contacts(ticket)
    lines = result.split('\n')
    assert len(lines) == 4
    assert lines[0] == 'Источник: не указан'
    assert lines[1] == 'Покупатель: Неизвестен'
    assert lines[2] == 'Телефон: не указан'
    assert lines[3] == 'Email: не указан'

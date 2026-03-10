import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from handlers.common_hl import validate_phone_or_request
from handlers import reserve_hl
from handlers.reserve.choice import choice_mode
from handlers.reserve.input import get_phone
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

    assert phone is None
    assert message is fake_message


def test_reserve_hl_reexports_choice_handler():
    assert reserve_hl.choice_mode is choice_mode


def test_reserve_hl_reexports_input_and_payment_handlers():
    assert reserve_hl.get_phone is get_phone
    assert reserve_hl.show_reservation_summary is show_reservation_summary
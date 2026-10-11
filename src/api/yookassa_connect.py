import asyncio
from typing import Optional, Union

from yookassa import Receipt
from yookassa.domain import models
from settings.settings import URL_BOT


OFD_URL_TEMPLATE = 'https://lk.platformaofd.ru/web/noauth/cheque?fn={fn}&fp={fp}&i={i}'


def build_ofd_url(fn: str, fp: str, i: str) -> str:
    """Build public OFD receipt URL from fiscal data."""
    return OFD_URL_TEMPLATE.format(fn=fn, fp=fp, i=i)


async def fetch_payment_receipts(payment_id: str, timeout: float = 10.0) -> list:
    """Fetch receipts for a payment via YooKassa SDK Receipt.list.

    Returns the list of receipt items, or an empty list on error.
    TimeoutError and SDK errors are propagated to the caller.
    """
    result = await asyncio.wait_for(
        asyncio.to_thread(Receipt.list, {'payment_id': payment_id}),
        timeout=timeout,
    )
    return result.items or []


def create_param_payment(
        price: Union[str, int],
        description: str,
        email: str,
        return_url: str = URL_BOT,
        *,
        quantity: str = "1",
        payment_method_type: str = "sbp",  # "yoo_money"
        payment_mode: Optional[str] = "full_payment",
        payment_subject: str = "service",
        **kwargs,
) -> dict:
    """

    :param price:
    :param description:
    :param email:
    :param return_url:
    :param quantity:
    :param payment_method_type: takes only one method
    https://yookassa.ru/developers/payment-acceptance/integration-scenarios/manual-integration/basics#integration-options
    :param payment_mode:
    :param payment_subject:
    :param kwargs:
    :return:
    """
    return {
        "amount": models.Amount(value=price, currency="RUB"),
        "payment_method_data": {
            "type": payment_method_type
        },
        "confirmation": {
            "type": "redirect",
            "return_url": return_url
        },
        "capture": True,
        'receipt': {
            "customer": {
                'email': email
            },
            "items": [
                {
                    "description": description,
                    "quantity": quantity,
                    "amount": models.Amount(value=price, currency="RUB"),
                    "vat_code": "1",
                    "payment_mode": payment_mode,
                    "payment_subject": payment_subject,
                }
            ]
        },
        'metadata': kwargs
    }

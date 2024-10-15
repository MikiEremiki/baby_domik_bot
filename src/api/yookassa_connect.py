from typing import Optional

from yookassa.domain import models
from settings.settings import URL_BOT


def create_param_payment(
        price: [str, int],
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

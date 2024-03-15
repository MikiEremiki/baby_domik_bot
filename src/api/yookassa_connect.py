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
        payment_mode: str = "full_payment",
        payment_subject: str = "service",
        **kwargs,
) -> dict:
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

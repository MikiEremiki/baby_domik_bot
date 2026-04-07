from telegram import Message

from handlers.sub_hl import request_phone_number
from utilities.utl_text import check_phone_number, extract_phone_number_from_text


async def validate_phone_or_request(
        update,
        context,
        raw_phone: str,
) -> tuple[str | None, Message | None]:
    phone = extract_phone_number_from_text(raw_phone)
    if check_phone_number(phone):
        message = await request_phone_number(update, context)
        return None, message

    return phone, None
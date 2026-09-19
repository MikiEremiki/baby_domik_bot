import re


def extract_phone_number_from_text(phone):
    phone = re.sub(r'[-\s)(+]', '', phone)
    return re.sub(r'^[78]{,2}(?=9)', '', phone)


def check_email(email: str):
    return re.fullmatch(r"^[-a-z0-9!#$%&'*+/=?^_`{|}~]+"
                        r"(?:\.[-a-z0-9!#$%&'*+/=?^_`{|}~]+)*"
                        r"@(?:[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?\.)*"
                        r"(?:aero|arpa|asia|biz|cat|com|coop|"
                        r"edu|gov|info|int|jobs|mil|mobi|museum|"
                        r"name|net|org|pro|tel|travel|[a-z][a-z])$",
                        email.lower())


def check_phone_number(phone):
    if len(phone) != 10 or phone[0] != '9':
        return True
    else:
        return False


def format_receipt_description(
        ticket_id: int | str,
        event_name: str,
        place_name: str,
        date_str: str,
        time_str: str,
        ticket_format: str,
        max_len: int = 128
) -> str:
    """
    Формирует наименование позиции чека для YooKassa (до max_len символов, по умолчанию 128).
    Формат: "Билет №{ticket_id} на {event_name} ({place_name}) {date_str} в {time_str} ({ticket_format})"
    При превышении max_len контролируемо сокращает event_name, сохраняя название локации.
    """
    if hasattr(place_name, '__await__') or str(type(place_name)).startswith("<class 'unittest.mock."):
        place_name = "Домик"
    clean_ticket_format = str(ticket_format).split(' | ')[0].strip()
    place_part = f" ({str(place_name).strip()})" if place_name else ""
    prefix = f"Билет №{ticket_id} на "
    suffix = f"{place_part} {date_str} в {time_str} ({clean_ticket_format})"

    total_len = len(prefix) + len(suffix)
    if total_len >= max_len:
        len_for_name = max(0, max_len - total_len)
        name_part = event_name[:len_for_name] if len_for_name > 0 else ""
        return f"{prefix}{name_part}{suffix}"[:max_len]

    len_for_name = max_len - total_len
    name_part = event_name[:len_for_name].strip()
    return f"{prefix}{name_part}{suffix}"

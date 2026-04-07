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

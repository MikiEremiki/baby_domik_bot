from typing import (
    Dict,
    Optional,
)
from telegram import (
    User,
    Message,
    InlineKeyboardMarkup
)

context_user_data: Dict = {
    'STATE': str,
    'user': Optional[User],
    'message_id': Message.message_id[int | str],  # На данный момент только для удаления
    'message_id_for_admin': Message.message_id[int | str],  # На данный момент только для удаления
    'message_id_to_pin': Message.message_id[int | str],
    'text_for_notification_massage': str,
    'text_for_list_waiting': str,
    'birthday_data': {
        'place': 1 | 2,
        'address': str,
        'date': str,
        'time': str,
        'id_show': int,
        'age': int,
        'qty_child': int,
        'qty_adult': int,
        'format_bd': 1 | 2,
        'name_child': str,
        'name': str,
        'phone': str,
        # 'flag_approve_request': bool,
        # 'flag_prepayment': bool,
        # 'flag_approve_prepayment': bool,
    },
    'reserve_data': {
        'text_date': str,
        'text_time': str,
        'keyboard_date': InlineKeyboardMarkup,
        'keyboard_time': InlineKeyboardMarkup,
        'dict_of_shows': dict,
        'dict_of_name_show': dict,
        'dict_of_name_show_flip': dict,
        'key_of_name_show': int,
        'date_show': str,
        'name_show': str,
        'row_in_googlesheet': str,
    },
}

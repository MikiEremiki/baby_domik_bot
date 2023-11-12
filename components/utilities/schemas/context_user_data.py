from typing import Dict, List
from telegram import (
    User,
    Message,
    InlineKeyboardMarkup
)

from utilities.schemas.ticket import BaseTicket

context_user_data: Dict = {
    'STATE': str,
    'user': User,
    'support_data': {
        'dict_of_shows': dict,
        'message_id_buy_info': Message.message_id[int | str],
        'message_id_for_admin': Message.message_id[int | str],
        'text_for_notification_massage': str,
    },
    'birthday_data': {
        'place': 1 | 2,
        'address': str,
        'date': str,
        'time': str,
        'show_id': int,
        'age': int,
        'qty_child': int,
        'qty_adult': int,
        'format_bd': 1 | 2,
        'name_child': str,
        'name': str,
        'phone': str,
        # 'flag_approve_order': bool,
        # 'flag_prepayment': bool,
        # 'flag_approve_prepayment': bool,
    },
    'reserve_user_data': {
        'back': {
            str: {
                'text': str,  # текст для возврата назад в State str
                'keyboard': InlineKeyboardMarkup
            },
            'number_of_month_str': str,
            'afisha_media': List[Message]
        },
        'dict_of_name_show': dict,
        'dict_of_name_show_flip': dict,
        'dict_of_date_show': dict,
        'name_show': str,
        'date_show': str,
        'time_show': str,
        'text_emoji': str,
        'event_info_for_list_waiting': str,
        # Инфо о выбранном показе пользователя
        'client_data': {
            'name_adult': str,
            'phone': str,
            'data_children': List[List[str]],
        },
    },
    'reserve_admin_data': {
        int: {
            'row_in_googlesheet': str,
            'chose_ticket': BaseTicket,
        },
    },
    'birthday_user_data': {

    },
    'month_afisha': int,
}

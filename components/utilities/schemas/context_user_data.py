from typing import (
    Dict, List,
)
from telegram import (
    User,
    Message,
    InlineKeyboardMarkup
)

from utilities.schemas.ticket import BaseTicket

context_user_data: Dict = {
    'STATE': str,
    'user': User,
    'message_id': Message.message_id[int | str],
    # На данный момент только для удаления
    'message_id_for_admin': Message.message_id[int | str],
    # На данный момент только для удаления
    'text_for_notification_massage': str,
    'text_for_list_waiting': str,  # Выбранный показ пользователем
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
    'reserve_data': {
        'back': {
            'month': {
                'text': str,  # текст для возврата назад в State MONTH
                'keyboard': InlineKeyboardMarkup
            },
            'show': {
                'text': str,  # текст для возврата назад в State SHOW
                'keyboard': InlineKeyboardMarkup
            },
            'date': {
                'text': str,  # текст для возврата назад в State DATE
                'keyboard': InlineKeyboardMarkup
            },
            'time': {
                'text': str,  # текст для возврата назад в State TIME
                'keyboard': InlineKeyboardMarkup
            },
        },
        'dict_of_shows': dict,
        'dict_of_name_show': dict,
        'dict_of_name_show_flip': dict,
        'name_show': str,
        'date_show': str,
        'time_show': str,
        'row_in_googlesheet': str,
        'chose_ticket': BaseTicket,
    },
    'month_afisha': int,
    'client_data': {
        'name_adult': str,
        'phone': str,
        'data_children': List[List[str]],
    }
}

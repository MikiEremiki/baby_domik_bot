from datetime import datetime
from decimal import Decimal
from typing import Dict, List

from telegram import User, Message, InlineKeyboardMarkup

from db import ScheduleEvent, TheaterEvent, BaseTicket

context_user_data: Dict = {
    'STATE': str,
    'command': str,
    'postfix_for_cancel': str,
    'user': User,
    'common_data': {
        'dict_of_shows': dict,
        'message_id_buy_info': Message.message_id,
        'message_id_for_admin': Message.message_id,
        'text_for_notification_massage': str,
    },
    'birthday_user_data': {
        'place': 1 | 2,
        'address': str,
        'date': str,
        'time': str,
        'theater_event_id': int,
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
            str | int: {
                'text': str,  # текст для возврата назад в State str
                'keyboard': InlineKeyboardMarkup
            },
        },
        'number_of_month_str': str,
        'dict_of_name_show': dict,
        'dict_of_name_show_flip': dict,
        'dict_of_date_show': dict,
        'choose_event_info': {
            'theater_event_id': int,
            'name_show': str,
            'date_show': str,
            'time_show': str,
            'event_id': int,
            'option': str,
            'text_emoji': str,
            'flag_indiv_cost': bool,
        },
        # Инфо о выбранном показе пользователя
        'text_select_event': str,
        'client_data': {
            'name_adult': str,
            'phone': str,
            'data_children': List[List[str]],
        },
        'schedule_event_ids': List[ScheduleEvent.id],
        'chose_price': Decimal,
        'choose_schedule_event_id': ScheduleEvent.id,
        'choose_schedule_event_ids': List[ScheduleEvent.id],
        'choose_theater_event_id': TheaterEvent.id,
        'chose_base_ticket_id': BaseTicket.base_ticket_id,
        'type_ticket_price': str,
        'key_option_for_reserve': int,
        'original_input_text': str,
        'date_for_price': datetime,
        'ticket_ids': List[int],
    },
    'reserve_admin_data': {
        'ticket_id': int,
        'message_id': Message.message_id,
    },
    'month_afisha': int,
}

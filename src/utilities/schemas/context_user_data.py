from datetime import datetime
from decimal import Decimal
from typing import Dict, List

from telegram import User, Message, InlineKeyboardMarkup

from db import ScheduleEvent, TheaterEvent, BaseTicket
from db.models import CustomMadeEvent

context_user_data: Dict = {
    'conv_hl_run': bool,
    'STATE': str,
    'command': str,
    'postfix_for_cancel': str,
    'user': User,
    'common_data': {
        'dict_of_shows': dict,
        'message_id_buy_info': Message.message_id,
        'message_id_for_admin': Message.message_id,
        'text_for_notification_massage': str,
        'message_id_for_reply': int,
        'del_keyboard_message_ids': List[int],
    },
    'birthday_user_data': {
        'place': 1 | 2,
        'address': str,
        'date': str,
        'time': str,
        'age': int,
        'qty_child': int,
        'qty_adult': int,
        'name_child': str,
        'name': str,
        'phone': str,
        'custom_made_format_id': CustomMadeEvent.id,
        'theater_event_id': TheaterEvent.id,
        'note': str,
        'theater_events': List[TheaterEvent.id],
        'custom_made_event_id': CustomMadeEvent.id,
    },
    'reserve_user_data': {
        str | int: {
                'schedule_event_ids': List[ScheduleEvent.id],
            },
        'back': {
            str | int: {
                'text': str,  # текст для возврата назад в State str
                'keyboard': InlineKeyboardMarkup,
                'del_message_ids': List[int],
            },
        },
        'number_of_month_str': str,
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
        'original_child_text': str,
        'date_for_price': datetime,
        'ticket_ids': List[int],
        'flag_send_ticket_info': bool,
    },
    'reserve_admin_data': {
        'ticket_id': int,
        'message_id': Message.message_id,
    },
    'month_afisha': int,
    'reply_markup' : InlineKeyboardMarkup,
    'theater_event': dict,
    'schedule_event': dict,
}

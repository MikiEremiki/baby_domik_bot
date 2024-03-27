from typing import (
    Dict, Optional
)

from ticket import list_of_tickets

context_bot_data: Dict = {
    'global_on_off': bool,
    'list_of_tickets': list_of_tickets,
    'dict_show_data': {
        'show_id': {  # int
                'name': str,
                'flag_premiere': bool,
                'min_age_child': int,
                'max_age_child': int,
                'show_emoji': str,
                'full_name': str,
                'flag_repertoire': bool,
                'birthday': {
                    'flag': bool,
                    'max_num_child': int,
                    'max_num_adult': int,
                },
                'flag_indiv_cost': bool,
                'price_type': str,
        },
    },
    'special_ticket_price': {
        str: {
            'будни': {
                int: int,
            },
            'выходные': {
                int: int,
            },
        }
    },
    'afisha': {
        int: str,  # int - номер месяца, str - file_id картинки
    },
    'dict_topics_name': Dict[str, Optional[int]],
    'admin': {
        'name': str,
        'username': str,
        'phone': str,
        'contacts': str,
    },
    'birthday_price': {
        int: (int, str),
    },
}

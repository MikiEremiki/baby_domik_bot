from typing import (
    Dict, Optional
)

from ticket import list_of_tickets

context_bot_data: Dict = {
    'list_of_tickets': list_of_tickets,
    'dict_show_data': {
        'show_id': {  # int
                'name': str,
                'flag_premiere': bool,
                'min_age_child': int,
                'max_age_child': int,
                'emoji': str,
                'birthday': {
                    'flag': bool,
                    'max_num_child': int,
                    'max_num_adult': int,
                },
                'flag_repertoire': bool,
                'flag_indiv_cost': bool,
                'full_name': str,
        },
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
    }
}

from typing import (
    Dict, Optional, List
)

from settings.config_loader import Settings

context_bot_data: Dict = {
    'global_on_off': bool,
    'config': Settings,
    'feedback_group_id': int,
    'special_ticket_price': {
        str | int: {
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
    'cme_admin': {
        'name': str,
        'username': str,
        'phone': str,
        'contacts': str,
    },
    'texts': {
        'description': str,
    },
    'studio': {
        'name': List[List[int]]
    }
}

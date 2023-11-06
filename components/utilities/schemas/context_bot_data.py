from typing import (
    Dict, Optional
)

from ticket import list_of_tickets

context_bot_data: Dict = {
    'list_of_tickets': list_of_tickets,
    'afisha': {
        int: str,  # int - номер месяца, str - file_id картинки
    },
    'dict_topics_name': Dict[str, Optional[int, None]]
}

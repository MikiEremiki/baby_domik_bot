from typing import (
    Dict,
)

dict_of_shows: Dict

id_show: int = 1  # Начинается с 1
name: str = 'name_show'
date: str = '15.08 (Вт)'
time: str = '17:00'

# Старая версия словаря со спектаклями, используется в reserve
dict_of_shows = {
    'name_of_show': name,
    'date': date,
    'time': time,
    'total_children_seats': int,
    'available_children_seats': int,
    'non_confirm_children_seats': int,
    'total_adult_seats': int,
    'available_adult_seats': int,
    'non_confirm_adult_seats': int
}

dict_of_date_show: Dict

dict_of_date_show = {
    date: name,
}

dict_of_name_show: Dict

name: str = 'name_show'

dict_of_name_show = {
    'name_of_show': name,
}

dict_of_shows_v2: Dict[int: Dict, ...]

# id_show определено ранее
name: str = 'name_show'
flag_premiere: bool = False
min_age_child: int = 1
flag_birthday: bool = True
max_num_child: int = 8
max_num_adult: int = 10
flag_repertoire: bool = True
full_name_of_show: str = 'full_name_show'

# Новая версия словаря со спектаклями, используется в birthday
dict_of_shows_v2 = {
    id_show: {
        'name': name,
        'flag_premiere': flag_premiere,
        'min_age_child': min_age_child,
        'birthday': {
            'flag': flag_birthday,
            'max_num_child': max_num_child,
            'max_num_adult': max_num_adult,
        },
        'flag_repertoire': flag_repertoire,
        'full_name_of_show': full_name_of_show,
    },
}


class Show:
    def __init__(self) -> None:
        super().__init__()

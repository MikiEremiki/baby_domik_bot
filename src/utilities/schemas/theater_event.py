from datetime import time
from typing import Dict, Annotated

from pydantic import BaseModel, BeforeValidator

from db.enum import PriceType


def empty_str_validator(value: str) -> PriceType:
    if not value:
        return PriceType.NONE
    else:
        return PriceType(value)


PriceType = Annotated[PriceType, BeforeValidator(empty_str_validator)]

class TheaterEventDTO(BaseModel):
    theater_event_id: int
    name: str
    flag_active_premiere: bool
    min_age_child: int
    max_age_child: int
    show_emoji: str
    duration: int
    flag_active_repertoire: bool
    flag_active_bd: bool
    max_num_child_bd: int
    max_num_adult_bd: int
    flag_indiv_cost: bool
    price_type: PriceType

    def to_dto(self):
        return {
            'id': self.theater_event_id,
            'name': self.name,
            'flag_premier': self.flag_active_premiere,
            'min_age_child': self.min_age_child,
            'max_age_child': self.max_age_child,
            'show_emoji': self.show_emoji,
            'duration': time(self.duration // 60, self.duration % 60),
            'flag_active_repertoire': self.flag_active_repertoire,
            'flag_active_bd': self.flag_active_bd,
            'max_num_child_bd': self.max_num_child_bd,
            'max_num_adult_bd': self.max_num_adult_bd,
            'flag_indiv_cost': self.flag_indiv_cost,
            'price_type': self.price_type
        }


kv_name_attr_theater_event = {
    'name': 'Название спектакля',
    'min_age_child': 'Мин возраст',
    'max_age_child': 'Макс возраст',
    'show_emoji': 'Эмодзи',
    'flag_premier': 'Премьера',
    'flag_active_repertoire': 'В репертуаре',
    'flag_active_bd': 'День рождения',
    'max_num_child_bd': 'Макс кол-во детей ДР',
    'max_num_adult_bd': 'Макс кол-во взрослых ДР',
    'flag_indiv_cost': 'Индив стоимость',
    'price_type': 'Расчет стоимости',
}


dict_of_shows: Dict

show_id: int = 1  # Начинается с 1
name_show: str = 'name_show'
date_show: str = '15.08 (Вт)'
time_show: str = '17:00'

# Старая версия словаря со спектаклями, используется в reserve
dict_of_shows = {
    'event_id': int,
    'show_id': int,
    'name_show': name_show,
    'date_show': date_show,
    'time_show': time_show,
    'qty_child': int,
    'qty_child_free_seat': int,
    'qty_child_nonconfirm_seat': int,
    'qty_adult': int,
    'qty_adult_free_seat': int,
    'qty_adult_nonconfirm_seat': int,
    'ticket_price_type': str,
}

dict_of_date_show: Dict

dict_of_date_show = {
    date_show: name_show,
}

dict_of_name_show: Dict

name_show: str = 'name_show'

dict_of_name_show = {
    'name_show': name_show,
}

dict_of_shows_v2: Dict[int: Dict, ...]

# show_id определено ранее
name_show: str = 'name_show'
flag_premiere: bool = False
min_age_child: int = 1
flag_birthday: bool = True
max_num_child: int = 8
max_num_adult: int = 10
flag_repertoire: bool = True
full_name: str = 'full_name_show'

# Новая версия словаря со спектаклями, используется в birthday
dict_of_shows_v2 = {
    show_id: {
        'name': name_show,
        'flag_premiere': flag_premiere,
        'min_age_child': min_age_child,
        'birthday': {
            'flag': flag_birthday,
            'max_num_child': max_num_child,
            'max_num_adult': max_num_adult,
        },
        'flag_repertoire': flag_repertoire,
        'full_name': full_name,
    },
}

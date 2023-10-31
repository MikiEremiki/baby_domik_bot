from datetime import date, time
from typing import Dict

from pydantic import BaseModel, computed_field


class TheaterShow(BaseModel):
    show_id: int
    name: str
    min_age_child: str
    flag_active_repertoire: bool

    @computed_field
    @property
    def full_name(self) -> str:
        return '. '.join([self.name,
                          self.min_age_child])


class BirthDayEvent(BaseModel):
    flag_active_bd: bool
    max_num_child_bd: int
    max_num_adult_bd: int


class TheaterPerformance(TheaterShow):
    flag_active_premiere: bool
    birthday: BirthDayEvent

    @computed_field
    @property
    def full_name(self) -> str:
        return '. '.join([self.name,
                          'ПРЕМЬЕРА' if self.flag_premiere else None,
                          self.min_age_child])


class TheaterTraining(TheaterShow):
    pass


class PlaceEvent(BaseModel):
    place_id: int
    address: str
    qty_child: int
    qty_adult: int


class TheaterEvent(BaseModel):
    event_id: int
    event: TheaterTraining | TheaterPerformance
    event_date: date
    event_time: time
    place: PlaceEvent
    qty_child_free_seat: int
    qty_child_nonconfirm_seat: int
    qty_adult_free_seat: int
    qty_adult_nonconfirm_seat: int


if __name__ == '__main__':
    a = TheaterPerformance(
        show_id=1,
        name='AAA',
        flag_active_premiere=True,
        min_age_child='1',
        birthday=BirthDayEvent(
            flag_active_bd=True,
            max_num_child_bd=10,
            max_num_adult_bd=10
        ),
        flag_active_repertoire=True
    )
    print(vars(a))
    b = TheaterTraining(
        show_id=1,
        name='BBB',
        min_age_child='1',
        flag_active_repertoire=True
    )
    print(vars(b))

dict_of_shows: Dict

show_id: int = 1  # Начинается с 1
name: str = 'name_show'
date: str = '15.08 (Вт)'
time: str = '17:00'

# Старая версия словаря со спектаклями, используется в reserve
dict_of_shows = {
    'event_id': int,
    'show_id': int,
    'name_show': name,
    'date_show': date,
    'time_show': time,
    'qty_child': int,
    'qty_child_free_seat': int,
    'qty_child_nonconfirm_seat': int,
    'qty_adult': int,
    'qty_adult_free_seat': int,
    'qty_adult_nonconfirm_seat': int
}

dict_of_date_show: Dict

dict_of_date_show = {
    date: name,
}

dict_of_name_show: Dict

name: str = 'name_show'

dict_of_name_show = {
    'name_show': name,
}

dict_of_shows_v2: Dict[int: Dict, ...]

# show_id определено ранее
name: str = 'name_show'
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
        'name': name,
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

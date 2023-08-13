from typing import List
from datetime import datetime

from typing_extensions import Annotated

from pydantic import BaseModel, computed_field, Field
from pydantic.functional_validators import BeforeValidator


def clean_float(s: str) -> str:
    return s.replace('%', '').replace(',', '.')


def str_to_date(s: str) -> (datetime | None):
    date_now = datetime.now().date()
    s = s.split()
    if len(s):
        date_tmp = s[0] + f'.{date_now.year}'
        return datetime.strptime(date_tmp, f'%d.%m.%Y')
    else:
        return None


prepare_float = Annotated[float, BeforeValidator(clean_float)]
prepare_str_to_date = Annotated[datetime | None, BeforeValidator(str_to_date)]


class Ticket(BaseModel):
    id_ticket: int  # Идентификатор билета
    name: str  # Наименование вариантов билетов
    cost_basic: int  # Базовая стоимость
    cost_main: int  # Стоимость
    cost_privilege: int  # Стоимость для льгот
    discount_main: prepare_float  # Скидка/Наценка
    discount_privilege: prepare_float  # Скидка/Наценка по льготе
    period_start_change_price: prepare_str_to_date  # Начало периода изм цены
    period_end_change_price: prepare_str_to_date  # Конец периода изм цены
    cost_main_in_period: int  # Стоимость на время повышения
    cost_privilege_in_period: int  # Стоимость льгот на время повышения
    discount_basic_in_period: prepare_float  # Скидка/Наценка после даты
    cost_basic_in_period: int  # Базовая стоимость на время повышения
    quality_of_children: int  # Кол-во мест занимаемых по билету при посещении
    # спектакля
    price_child_for_one_ticket: int  # Сумма за 1 билет
    quality_of_adult: int  # Кол-во мест занимаемых по билету при посещении
    # спектакля
    price_adult_for_one_ticket: int  # Сумма за 1 билет
    flag_individual: bool  # Флаг для индивидуального обращения
    flag_season_ticket: bool  # Флаг абонемент
    quality_visits_by_ticket: str  # Общее кол-во посещений по билету
    ticket_category: str  # Категория билета

    date_show_tmp: datetime = Field(default=datetime.fromisoformat('2000-01-01'))

    @computed_field
    @property
    def date_show(self) -> datetime:
        return datetime.fromisoformat('2000-01-01')

    @date_show.setter
    def date_show(self, new_date: datetime) -> None:
        self.date_show_tmp = new_date

    @computed_field
    @property
    def flag_set_period_price(self) -> bool:
        if self.period_start_change_price:
            if self.period_start_change_price < self.date_show_tmp:
                if self.period_end_change_price:
                    if self.date_show_tmp < self.period_end_change_price:
                        return True
                else:
                    return True

    @computed_field
    @property
    def price(self) -> int:
        if self.flag_set_period_price:
            return self.cost_main_in_period
        else:
            return self.cost_main


list_of_tickets = List[Ticket]

id_ticket: int = 1  # Идентификатор билета

dict_of_tickets = {
    id_ticket:
        {
            'name': str,  # Наименование вариантов билетов
            'cost_basic': int,  # Базовая стоимость
            'cost_main': int,  # Стоимость
            'cost_privilege': int,  # Стоимость для льгот
            'discount_main': float,  # Скидка/Наценка
            'discount_privilege': float,  # Скидка/Наценка по льготе
            'period_start_change_price': str,  # Начало периода изменения цены
            'period_end_change_price': str,  # Конец периода изменения цены
            'cost_main_in_period': int,  # Стоимость на время повышения
            'cost_privilege_in_period': int,
            # Стоимость льгот на время повышения
            'discount_basic_in_period': float,  # Скидка/Наценка после даты
            'cost_basic_in_period': int,  # Базовая стоимость на время повышения
            'quality_of_children': int,
            # Кол-во мест занимаемых по билету при посещении спектакля
            'price_child_for_one_ticket': int,  # Сумма за 1 билет
            'quality_of_adult': int,
            # Кол-во мест занимаемых по билету при посещении спектакля
            'price_adult_for_one_ticket': int,  # Сумма за 1 билет
            'flag_individual': bool,  # Флаг для индивидуального обращения
            'flag_season_ticket': bool,  # Флаг абонемент
            'quality_visits_by_ticket': str,  # Общее кол-во посещений по билету
            'ticket_category': str,  # Категория билета
        }
}

keys_ticket = [
    'id_ticket',  # 0
    'name',  # 1
    'cost_basic',  # 2
    'cost_main',  # 3
    'cost_privilege',  # 4
    'discount_main',  # 5
    'discount_privilege',
    'period_start_change_price',
    'period_end_change_price',
    'discount_basic_in_period',
    'cost_basic_in_period',  # 10
    'cost_main_in_period',
    'cost_privilege_in_period',
    'quality_of_children',
    'price_child_for_one_ticket',
    'quality_of_adult',  # 15
    'price_adult_for_one_ticket',
    'flag_individual',
    'flag_season_ticket',
    'quality_visits_by_ticket',
    'ticket_category',  # 20
]

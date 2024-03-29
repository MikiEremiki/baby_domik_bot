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


class BaseTicketDTO(BaseModel):
    base_ticket_id: int  # Идентификатор билета
    flag_active: bool = True
    name: str  # Наименование вариантов билетов
    # cost_basic: int  # Базовая стоимость
    cost_main: int  # Стоимость
    cost_privilege: int  # Стоимость для льгот
    period_start_change_price: prepare_str_to_date = None
    # Начало периода изм цены
    period_end_change_price: prepare_str_to_date = None
    # Конец периода изм цены
    cost_main_in_period: int = None  # Стоимость на время повышения
    cost_privilege_in_period: int  # Стоимость льгот на время повышения
    # cost_basic_in_period: int  # Базовая стоимость на время повышения
    quality_of_children: int = 0  # Кол-во детск мест
    # price_child_for_one_ticket: int  # Сумма за 1 билет
    quality_of_adult: int = 0  # Кол-во взр мест
    # price_adult_for_one_ticket: int  # Сумма за 1 билет
    quality_of_add_adult: int = 0  # Кол-во доп взр мест
    # flag_individual: bool = False  # Флаг для индивидуального обращения
    # flag_season_ticket: bool  # Флаг абонемент
    quality_visits: int  # Общее кол-во посещений по билету
    # ticket_category: int  # Категория билета

    date_show_tmp: datetime = Field(
        default=datetime.fromisoformat('2000-01-01'))

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
                        return False
                else:
                    return True
            else:
                return False
        else:
            return False

    @computed_field
    @property
    def price(self) -> int:
        if self.flag_set_period_price:
            return self.cost_main_in_period
        else:
            return self.cost_main

    @price.setter
    def price(self, new_cost) -> None:
        self.cost_main = new_cost

    def __repr__(self):
        return str(self.base_ticket_id)

    def to_dto(self):
        return {
            'flag_active': self.flag_active,
            'base_ticket_id': self.base_ticket_id,
            'name': self.name,
            'cost_main': self.cost_main,
            'cost_privilege': self.cost_privilege,
            'period_start_change_price': self.period_start_change_price,
            'period_end_change_price': self.period_end_change_price,
            'cost_main_in_period': self.cost_main_in_period,
            'cost_privilege_in_period': self.cost_privilege_in_period,
            'quality_of_children': self.quality_of_children,
            'quality_of_adult': self.quality_of_adult,
            'quality_of_add_adult': self.quality_of_add_adult,
            'quality_visits': self.quality_visits,
        }


list_of_tickets = List[BaseTicketDTO]

keys_ticket = [
    'base_ticket_id',
    'flag_active',
    'name',
    'cost_basic',
    'cost_main',
    'cost_privilege',
    'discount_main',
    'discount_privilege',
    'period_start_change_price',
    'period_end_change_price',
    'discount_basic_in_period',
    'cost_basic_in_period',
    'cost_main_in_period',
    'cost_privilege_in_period',
    'quality_of_children',
    'price_child_for_one_ticket',
    'quality_of_adult',
    'price_adult_for_one_ticket',
    'flag_individual',
    'flag_season_ticket',
    'quality_visits_by_ticket',
    'ticket_category',
]


class Ticket(BaseModel):
    ticket_id: int
    base_ticket: BaseTicketDTO
    event_id: int = None
    buy_date: datetime


if __name__ == '__main__':
    ticket = BaseTicketDTO(
        base_ticket_id=101,
        name='1р+1в',
        cost_main=1000,
        cost_privilege=1000,
        cost_privilege_in_period=1000,
        quality_of_adult=1,
        quality_of_children=1,
        quality_visits=1
    )
    dict_ticket = ticket.model_dump(exclude_defaults=True)
    ticket2 = BaseTicketDTO.model_validate(dict_ticket)

    print(ticket)

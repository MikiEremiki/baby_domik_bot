from typing import List

from typing_extensions import Annotated

from pydantic import BaseModel
from pydantic.functional_validators import BeforeValidator


def clean_float(s: str) -> str:
    return s.replace('%', '').replace(',', '.')


prepare_float = Annotated[float, BeforeValidator(clean_float)]


class Ticket(BaseModel):
    id_ticket: int  # Идентификатор билета
    name: str  # Наименование вариантов билетов
    cost_basic: int  # Базовая стоимость
    cost_main: int  # Стоимость
    cost_privilege: int  # Стоимость для льгот
    discount_main: prepare_float  # Скидка/Наценка
    discount_privilege: prepare_float  # Скидка/Наценка по льготе
    period_start_change_price: str  # Начало периода изменения цены
    period_end_changes_price: str  # Конец периода изменения цены
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
            'period_end_changes_price': str,  # Конец периода изменения цены
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
    'period_end_changes_price',
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

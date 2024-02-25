import enum

import sqlalchemy as sa

from db import BaseModel


class TicketStatus(enum.Enum):
    CREATED = 'Создан'
    PAID = 'Оплачен'
    APPROVED = 'Подтвержден'
    REJECTED = 'Отклонен'
    REFUNDED = 'Возвращен'
    TRANSFERRED = 'Передан'
    POSTPONED = 'Перенесен'


class PriceType(enum.Enum):
    NONE = None
    BASE_PRICE = 'Базовая стоимость'
    OPTIONS = 'Опции'
    INDIVIDUAL = 'Индивидуальная'


class TicketPriceType(enum.Enum):
    NONE = None
    weekday = 'будни'
    weekend = 'выходные'


TicketStatusEnum = sa.Enum(
    TicketStatus,
    name="TicketStatusEnum",
    metadata=BaseModel.metadata
)
PriceTypeEnum = sa.Enum(
    PriceType,
    name="PriceTypeEnum",
    metadata=BaseModel.metadata
)
TicketPriceTypeEnum = sa.Enum(
    TicketPriceType,
    name="TicketPriceTypeEnum",
    metadata=BaseModel.metadata
)

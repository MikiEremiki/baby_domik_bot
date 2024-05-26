import enum


class TicketStatus(enum.Enum):
    CREATED = 'Создан'
    PAID = 'Оплачен'
    APPROVED = 'Подтвержден'
    REJECTED = 'Отклонен'
    REFUNDED = 'Возвращен'
    TRANSFERRED = 'Передан'
    MIGRATED = 'Перенесен'
    CANCELED = 'Отменен'


class PriceType(enum.Enum):
    NONE = None
    BASE_PRICE = 'Базовая стоимость'
    OPTIONS = 'Опции'
    INDIVIDUAL = 'Индивидуальная'


class TicketPriceType(enum.Enum):
    NONE = None
    weekday = 'будни'
    weekend = 'выходные'


class AgeType(enum.Enum):
    adult = 'взрослый'
    child = 'ребенок'


class GroupOfPeopleByDiscountType(enum.Enum):
    all = 0
    privilege = 1
    non_privilege = 2

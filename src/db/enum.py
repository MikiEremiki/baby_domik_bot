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
    # TODO Рассмотреть вариант создания доп статусов
    #  Зарезервирован/Оформлен для отслеживания, что места в базе
    #  зарезервированы. Это удобно для проверки нужно изменять кол-во мест по
    #  мероприятию или нет.
    #  Сброшен, когда билет отменяется в результате ошибок или другой
    #  внутренней логики
    #  а Отменен использовать только в случаях, отмены самим пользователем
    #  (при статусах Создан и Зарезервирован/Оформлен)


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


class CustomMadeStatus(enum.Enum):
    CREATED = 'Создан'
    APPROVED = 'Подтвержден'
    PREPAID = 'Предоплачен'
    PAID = 'Оплачен'
    REJECTED = 'Отклонен'
    REFUNDED = 'Возвращен'
    CANCELED = 'Отменен'

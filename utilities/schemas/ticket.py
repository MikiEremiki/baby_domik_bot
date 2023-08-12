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
            'cost_privilege_in_period': int,  # Стоимость льгот на время повышения
            'discount_basic_in_period': float,  # Скидка/Наценка после даты
            'cost_basic_in_period': int,  # Базовая стоимость на время повышения
            'quality_of_children': int,  # Кол-во мест занимаемых по билету при посещении спектакля
            'price_child_for_one_ticket': int,  # Сумма за 1 билет
            'quality_of_adult': int,  # Кол-во мест занимаемых по билету при посещении спектакля
            'price_adult_for_one_ticket': int,  # Сумма за 1 билет
            'flag_individual': bool,  # Флаг для индивидуального обращения
            'flag_season_ticket': bool,  # Флаг абонемент
            'quality_visits_by_ticket': str,  # Общее кол-во посещений по билету
            'ticket_category': str,  # Категория билета
        }
}










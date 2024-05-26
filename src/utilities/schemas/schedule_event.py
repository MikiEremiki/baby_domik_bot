from typing import Annotated

from pydantic import BaseModel, BeforeValidator

from db.enum import TicketPriceType
from utilities.utl_func import convert_sheets_datetime

moscow_timezone_offset = -3


def empty_str_validator(value: str) -> TicketPriceType:
    if not value:
        return TicketPriceType.NONE
    else:
        return TicketPriceType(value)

def str_to_int(s: str) -> int:
    try:
        return int(s)
    except ValueError:
        return 0

TicketPriceType = Annotated[TicketPriceType, BeforeValidator(empty_str_validator)]
prepare_str_to_int = Annotated[int, BeforeValidator(str_to_int)]


class ScheduleEventDTO(BaseModel):
    event_id: int
    event_type: int
    show_id: int
    flag_turn_on_off: bool
    date_show: int
    time_show: float
    qty_child: prepare_str_to_int
    qty_child_free_seat: prepare_str_to_int
    qty_child_nonconfirm_seat: prepare_str_to_int
    qty_adult: prepare_str_to_int
    qty_adult_free_seat: prepare_str_to_int
    qty_adult_nonconfirm_seat: prepare_str_to_int
    flag_gift: bool
    flag_christmas_tree: bool
    flag_santa: bool
    ticket_price_type: TicketPriceType

    def to_dto(self):
        return {
            "id": self.event_id,
            "type_event_id": self.event_type,
            "theater_events_id": self.show_id,
            "flag_turn_in_bot": self.flag_turn_on_off,
            "datetime_event": convert_sheets_datetime(self.date_show,
                                                      self.time_show,
                                                      moscow_timezone_offset),
            "qty_child": self.qty_child,
            "qty_child_free_seat": self.qty_child_free_seat,
            "qty_child_nonconfirm_seat": self.qty_child_nonconfirm_seat,
            "qty_adult": self.qty_adult,
            "qty_adult_free_seat": self.qty_adult_free_seat,
            "qty_adult_nonconfirm_seat": self.qty_adult_nonconfirm_seat,
            "flag_gift": self.flag_gift,
            "flag_christmas_tree": self.flag_christmas_tree,
            "flag_santa": self.flag_santa,
            "ticket_price_type": self.ticket_price_type
        }

    def get_datetime_event(self):
        return convert_sheets_datetime(self.date_show,
                                       self.time_show,
                                       moscow_timezone_offset)

    def get_date_event(self):
        return convert_sheets_datetime(self.date_show)


kv_name_attr_schedule_event = {
    'type_event_id': 'id типа мероприятия',
    'theater_events_id': 'id репертуара',
    'flag_turn_in_bot': 'Вкл/Выкл в боте',
    'datetime_event': 'Дата и время',
    'qty_child': 'Кол-во детских мест',
    'qty_adult': 'Кол-во взрослых мест',
    'flag_gift': 'Подарок',
    'flag_christmas_tree': 'Елка',
    'flag_santa': 'Дед Мороз',
    'ticket_price_type': 'Назначение стоимости',
}

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel


class PromotionDTO(BaseModel):
    id: Optional[int] = None
    name: str = ""
    code: str
    discount: int
    discount_type: str = "fixed"  # fixed | percentage
    start_date: Optional[datetime] = None
    expire_date: Optional[datetime] = None

    base_ticket_ids: Optional[List[int]] = None
    type_event_ids: Optional[List[int]] = None
    theater_event_ids: Optional[List[int]] = None
    schedule_event_ids: Optional[List[int]] = None

    for_who_discount: int = 0  # GroupOfPeopleByDiscountType.all

    flag_active: bool = True
    is_visible_as_option: bool = False
    count_of_usage: int = 0
    max_count_of_usage: int = 0
    min_purchase_sum: int = 0
    description_user: Optional[str] = None

    def to_dto(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "discount": self.discount,
            "start_date": self.start_date,
            "expire_date": self.expire_date,
            "base_ticket_ids": self.base_ticket_ids,
            "type_event_ids": self.type_event_ids,
            "theater_event_ids": self.theater_event_ids,
            "schedule_event_ids": self.schedule_event_ids,
            "for_who_discount": self.for_who_discount,
            "flag_active": self.flag_active,
            "is_visible_as_option": self.is_visible_as_option,
            "count_of_usage": self.count_of_usage,
            "max_count_of_usage": self.max_count_of_usage,
            "min_purchase_sum": self.min_purchase_sum,
            "description_user": self.description_user,
            "discount_type": self.discount_type,
        }

from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import ForeignKey, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import BaseModel, BaseModelTimed
from db.enum_types import TicketStatus, TicketPriceType, PriceType


class User(BaseModelTimed):
    __tablename__ = 'users'

    user_id: Mapped[int] = mapped_column(BigInteger,
                                         primary_key=True,
                                         autoincrement=False)
    chat_id: Mapped[int]

    callback_name: Mapped[str]
    callback_phone: Mapped[Optional[str]]
    username: Mapped[Optional[str]]

    children: Mapped[List['Child']] = relationship(back_populates='users')
    tickets: Mapped[List['Ticket']] = relationship(back_populates='users')


class Child(BaseModel):
    __tablename__ = 'children'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    age: Mapped[float]
    birthdate: Mapped[Optional[date]]

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.user_id', ondelete='CASCADE')
    )
    users: Mapped['User'] = relationship(back_populates='children')


class Ticket(BaseModelTimed):
    __tablename__ = 'tickets'

    id: Mapped[int] = mapped_column(primary_key=True)

    base_ticket_id: Mapped[int]
    price: Mapped[int]
    exclude: Mapped[bool] = mapped_column(default=False)
    status: Mapped[TicketStatus]

    child_id: Mapped[List['Child']] = mapped_column(ForeignKey('children.id'))
    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.user_id', ondelete='CASCADE')
    )
    theater_event_id: Mapped[int] = mapped_column(
        ForeignKey('theater_events.id', ondelete='CASCADE')
    )
    schedule_event_id: Mapped[int]
    notes: Mapped[Optional[str]]

    users: Mapped['User'] = relationship(back_populates='tickets')
    theater_events: Mapped['TheaterEvent'] = relationship(
        back_populates='tickets')


class TypeEvent(BaseModel):
    __tablename__ = 'type_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    name_alias: Mapped[str]
    base_price_gift: Mapped[Optional[int]]
    notes: Mapped[Optional[str]]


class TheaterEvent(BaseModel):
    __tablename__ = 'theater_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    flag_premier: Mapped[bool] = mapped_column(default=False)
    min_age_child: Mapped[int]
    max_age_child: Mapped[Optional[int]]
    show_emoji: Mapped[Optional[str]]
    flag_active_repertoire: Mapped[bool] = mapped_column(default=False)
    flag_active_bd: Mapped[bool] = mapped_column(default=False)
    max_num_child_bd: Mapped[int] = mapped_column(default=8)
    max_num_adult_bd: Mapped[int] = mapped_column(default=10)
    flag_indiv_cost: Mapped[bool] = mapped_column(default=False)
    price_type: Mapped[PriceType] = mapped_column(default=PriceType.NONE)


class ScheduleEvent(BaseModelTimed):
    __tablename__ = 'schedule_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[int]

    type_id: Mapped[int] = mapped_column(
        ForeignKey('type_events.id', ondelete='CASCADE')
    )
    theater_events_id: Mapped[int] = mapped_column(
        ForeignKey('theater_events.id', ondelete='CASCADE')
    )
    flag_turn_in_bot: Mapped[bool] = mapped_column(default=False)
    datetime_event: Mapped[datetime]

    qty_child: Mapped[int]
    qty_child_free_seat: Mapped[int]
    qty_child_nonconfirm_seat: Mapped[int]
    qty_adult: Mapped[int]
    qty_adult_free_seat: Mapped[int]
    qty_adult_nonconfirm_seat: Mapped[int]

    flag_gift: Mapped[bool] = mapped_column(default=False)
    flag_christmas_tree: Mapped[bool] = mapped_column(default=False)
    flag_santa: Mapped[bool] = mapped_column(default=False)

    ticket_price_type: Mapped[TicketPriceType] = mapped_column(
        default=TicketPriceType.NONE)

    tickets: Mapped[List['Ticket']] = relationship(
        back_populates='schedule_events')

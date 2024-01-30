from datetime import datetime, date
import enum
from typing import Optional, List

from sqlalchemy import ForeignKey, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel, BaseModelTimed


class User(BaseModelTimed):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(BigInteger,
                                    primary_key=True,
                                    autoincrement=False)

    name: Mapped[str]
    phone: Mapped[Optional[str]]
    username: Mapped[str]

    children: Mapped[List['Child']] = relationship(back_populates='users')
    tickets: Mapped[List['Ticket']] = relationship(back_populates='users')


class Child(BaseModel):
    __tablename__ = 'children'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[Optional[str]]
    age: Mapped[float]
    birthdate: Mapped[date]

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE')
    )
    users: Mapped['User'] = relationship(back_populates='children')


class TypeEvent(BaseModel):
    __tablename__ = 'type_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    name_alias: Mapped[str]
    price_for_gift: Mapped[int]

    notes: Mapped[Optional[str]]


class TheaterEvent(BaseModel):
    __tablename__ = 'theater_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    flag_premier: Mapped[bool] = mapped_column(default=False)
    min_age_child: Mapped[int]
    max_age_child: Mapped[int]
    show_emoji: Mapped[str]
    # full_name: Mapped[bool]
    flag_active_repertoire: Mapped[bool]
    flag_active_bd: Mapped[bool]
    max_num_child_bd: Mapped[int]
    max_num_adult_bd: Mapped[int]
    flag_indiv_cost: Mapped[bool] = mapped_column(default=False)
    event_type: Mapped[int]


class TicketStatusEnum(enum.Enum):
    PAID = 'paid'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    REFUNDED = 'refunded'
    TRANSFERRED = 'transferred'
    POSTPONED = 'postponed'


class Ticket(BaseModelTimed):
    __tablename__ = 'tickets'

    id: Mapped[int] = mapped_column(primary_key=True)

    base_ticket_id: Mapped[int]
    price: Mapped[int]
    exclude: Mapped[bool]
    status: Mapped[TicketStatusEnum]

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE')
    )
    users: Mapped['User'] = relationship(
        back_populates='tickets')

    theater_event_id: Mapped[int] = mapped_column(
        ForeignKey('theater_events.id', ondelete='CASCADE')
    )
    theater_events: Mapped['TheaterEvent'] = relationship(
        back_populates='tickets')

    notes: Mapped[Optional[str]]


class ScheduleEvent(BaseModelTimed):
    __tablename__ = 'schedule_events'

    id: Mapped[int] = mapped_column(primary_key=True)

    type_id: Mapped[int] = mapped_column(
        ForeignKey('type_events.id', ondelete='CASCADE')
    )
    theater_events_id: Mapped[int] = mapped_column(
        ForeignKey('theater_events.id', ondelete='CASCADE')
    )
    flag_turn_in_bot: Mapped[bool] = mapped_column(default=False)
    date_event: Mapped[datetime]

    tickets: Mapped[List['Ticket']] = relationship(
        back_populates='theater_events')

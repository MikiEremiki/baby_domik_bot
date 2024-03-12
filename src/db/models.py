from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import ForeignKey, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import BaseModel, BaseModelTimed
from db.enum import TicketStatus, TicketPriceType, PriceType, AgeType


class User(BaseModelTimed):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False, name='user_id')
    chat_id: Mapped[int] = mapped_column(BigInteger)

    username: Mapped[Optional[str]]
    email: Mapped[Optional[str]]

    people: Mapped[List['Person']] = relationship(lazy='selectin')
    tickets: Mapped[List['Ticket']] = relationship(
        back_populates='users', secondary='users_tickets', lazy='selectin')


class Person(BaseModelTimed):
    __tablename__ = 'people'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[Optional[str]]
    age_type: Mapped[AgeType]

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'))

    children: Mapped[List['Person']] = relationship(lazy='selectin')
    adults: Mapped[List['Person']] = relationship(lazy='selectin')
    tickets: Mapped[List['Ticket']] = relationship(
        back_populates='people', secondary='people_tickets', lazy='selectin')


class Child(BaseModel):
    __tablename__ = 'children'

    id: Mapped[int] = mapped_column(primary_key=True)
    age: Mapped[Optional[float]]
    birthdate: Mapped[Optional[date]]

    person_id: Mapped[int] = mapped_column(
        ForeignKey('people.id', ondelete='CASCADE'))


class Adult(BaseModel):
    __tablename__ = 'adults'

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[Optional[str]]

    person_id: Mapped[int] = mapped_column(
        ForeignKey('people.id', ondelete='CASCADE'))


class UserTicket(BaseModelTimed):
    __tablename__ = 'users_tickets'

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id'), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey('tickets.id'), primary_key=True)


class PersonTicket(BaseModelTimed):
    __tablename__ = 'people_tickets'

    person_id: Mapped[int] = mapped_column(
        ForeignKey('people.id'), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey('tickets.id'), primary_key=True)


class Ticket(BaseModelTimed):
    __tablename__ = 'tickets'

    id: Mapped[int] = mapped_column(primary_key=True)

    base_ticket_id: Mapped[int]
    price: Mapped[int]
    exclude: Mapped[bool] = mapped_column(default=False)
    status: Mapped[TicketStatus]
    notes: Mapped[Optional[str]]

    payment_id: Mapped[Optional[str]]
    idempotency_id: Mapped[Optional[str]]

    schedule_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('schedule_events.id'))

    users: Mapped['User'] = relationship(
        secondary='users_tickets', back_populates='tickets', lazy='selectin')
    people: Mapped[List['Person']] = relationship(
        secondary='people_tickets', back_populates='tickets', lazy='selectin')


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

    schedule_events: Mapped[List['ScheduleEvent']] = relationship(
        lazy='selectin')


class ScheduleEvent(BaseModelTimed):
    __tablename__ = 'schedule_events'

    id: Mapped[int] = mapped_column(primary_key=True)

    type_event_id: Mapped[int] = mapped_column(ForeignKey('type_events.id'))
    theater_events_id: Mapped[int] = mapped_column(ForeignKey('theater_events.id'))
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

    tickets: Mapped[List['Ticket']] = relationship(lazy='selectin')

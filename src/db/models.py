from typing import Optional, List

from sqlalchemy import ForeignKey, String, BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel, BaseModelTimed


class User(BaseModelTimed):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(BigInteger,
                                    primary_key=True,
                                    autoincrement=False,
                                    unique=True)

    callback_name: Mapped[str] = mapped_column(String)
    callback_phone: Mapped[Optional[str]] = mapped_column(String)

    children: Mapped[List['Child']] = relationship(
        back_populates='users',
        cascade='all, delete-orphan',
    )
    tickets: Mapped[List['Ticket']] = relationship(
        back_populates='users',
        cascade='all, delete-orphan'
    )

    def __repr__(self) -> str:
        return (f'Customer(user_id={self.id}, '
                f'name={self.callback_name}, '
                f'phone={self.callback_phone})')


class Child(BaseModel):
    __tablename__ = 'children'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)

    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    users: Mapped['User'] = relationship(back_populates='children')


class TheaterEvent(BaseModel):
    __tablename__ = 'theater_events'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    tickets: Mapped[List['Ticket']] = relationship(
        back_populates='theater_events')


class Ticket(BaseModelTimed):
    __tablename__ = 'tickets'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    users: Mapped['User'] = relationship(back_populates='tickets')
    theater_event_id: Mapped[int] = mapped_column(
        ForeignKey('theater_events.id'))
    theater_events: Mapped['TheaterEvent'] = relationship(
        back_populates='tickets')

from datetime import datetime, date, time
from typing import Optional, List

from sqlalchemy import ForeignKey, BigInteger, Numeric, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import BaseModel, BaseModelTimed
from db.enum import (
    TicketStatus, TicketPriceType, PriceType, AgeType,
    GroupOfPeopleByDiscountType, CustomMadeStatus,
    UserRole, PromotionDiscountType)


class User(BaseModelTimed):
    __tablename__ = 'users'

    user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False, name='user_id')
    chat_id: Mapped[int] = mapped_column(BigInteger)

    username: Mapped[Optional[str]]
    email: Mapped[Optional[str]]
    agreement_received: Mapped[Optional[date]]
    is_privilege: Mapped[Optional[bool]]

    people: Mapped[List['Person']] = relationship(lazy='selectin')
    tickets: Mapped[List['Ticket']] = relationship(
        back_populates='user', secondary='users_tickets', lazy='selectin')
    custom_made_events: Mapped[List['CustomMadeEvent']] = relationship(
        lazy='selectin')

    status: Mapped[Optional['UserStatus']] = relationship(
        back_populates='user', uselist=False, lazy='selectin')


class Person(BaseModelTimed):
    __tablename__ = 'people'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[Optional[str]]
    age_type: Mapped[AgeType]

    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'))

    child: Mapped['Child'] = relationship(lazy='selectin')
    adult: Mapped['Adult'] = relationship(lazy='selectin')
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
        ForeignKey('users.user_id'), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey('tickets.id'), primary_key=True)


class PersonTicket(BaseModelTimed):
    __tablename__ = 'people_tickets'

    person_id: Mapped[int] = mapped_column(
        ForeignKey('people.id'), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey('tickets.id'), primary_key=True)


class BaseTicket(BaseModelTimed):
    __tablename__ = 'base_tickets'

    base_ticket_id: Mapped[int] = mapped_column(primary_key=True,
                                                autoincrement=False)

    flag_active: Mapped[bool] = mapped_column(default=False)
    flag_individual: Mapped[Optional[bool]] = mapped_column(default=False)
    flag_season_ticket: Mapped[Optional[bool]] = mapped_column(default=False)
    name: Mapped[str]
    cost_main: Mapped[float] = mapped_column(Numeric)
    cost_privilege: Mapped[float] = mapped_column(Numeric)
    period_start_change_price: Mapped[Optional[datetime]]
    period_end_change_price: Mapped[Optional[datetime]]
    cost_main_in_period: Mapped[float] = mapped_column(Numeric)
    cost_privilege_in_period: Mapped[float] = mapped_column(Numeric)
    quality_of_children: Mapped[int]
    quality_of_adult: Mapped[int]
    quality_of_add_adult: Mapped[int]
    quality_visits: Mapped[int]

    type_events: Mapped[List['TypeEvent']] = relationship(
        back_populates='base_tickets',
        secondary='base_tickets_type_events',
        lazy='selectin')
    theater_events: Mapped[List['TheaterEvent']] = relationship(
        back_populates='base_tickets',
        secondary='base_tickets_theater_events',
        lazy='selectin')
    schedule_events: Mapped[List['ScheduleEvent']] = relationship(
        back_populates='base_tickets',
        secondary='base_tickets_schedule_events',
        lazy='selectin')

    def get_price_from_date(self, _date: date = date.today()):
        flag_set_period_price = False
        date_gt_start = False
        date_le_end = False
        if isinstance(self.period_start_change_price, date):
            # Для варианта расчета по наступлению даты
            # s_date = datetime.fromtimestamp(
            #    self.period_start_change_price.timestamp())
            # Для варианта расчета по дате мероприятия
            s_date = self.period_start_change_price
            date_gt_start = _date >= s_date
        if isinstance(self.period_end_change_price, date):
            # e_date = datetime.fromtimestamp(
            #     self.period_end_change_price.timestamp())
            e_date = self.period_end_change_price
            date_le_end = _date <= e_date

        check_1 = date_gt_start and date_le_end
        check_2 = date_gt_start and not date_le_end
        check_3 = not date_gt_start and date_le_end

        if check_1 or check_2 or check_3:
            flag_set_period_price = True

        if flag_set_period_price:
            price_main = self.cost_main_in_period
            price_privilege = self.cost_privilege_in_period
        else:
            price_main = self.cost_main
            price_privilege = self.cost_privilege
        return price_main, price_privilege

    def to_dto(self):
        return {
            'base_ticket_id': self.base_ticket_id,
            'flag_active': self.flag_active,
            'flag_individual': self.flag_individual,
            'flag_season_ticket': self.flag_season_ticket,
            'name': self.name,
            'cost_main': self.cost_main,
            'cost_privilege': self.cost_privilege,
            'period_start_change_price': self.period_start_change_price,
            'period_end_change_price': self.period_end_change_price,
            'cost_main_in_period': self.cost_main_in_period,
            'cost_privilege_in_period': self.cost_privilege_in_period,
            'quality_of_children': self.quality_of_children,
            'quality_of_adult': self.quality_of_adult,
            'quality_of_add_adult': self.quality_of_add_adult,
            'quality_visits': self.quality_visits,
        }


class Ticket(BaseModelTimed):
    __tablename__ = 'tickets'

    id: Mapped[int] = mapped_column(primary_key=True)

    base_ticket_id: Mapped[int] = mapped_column(
        ForeignKey('base_tickets.base_ticket_id'))
    price: Mapped[int]
    status: Mapped[TicketStatus]
    notes: Mapped[Optional[str]]
    reminded_1d_at: Mapped[Optional[datetime]]

    payment_id: Mapped[Optional[str]] = mapped_column(unique=True)
    idempotency_id: Mapped[Optional[str]] = mapped_column(unique=True)

    schedule_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('schedule_events.id'))
    promo_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('promotions.id'))

    user: Mapped['User'] = relationship(
        secondary='users_tickets', back_populates='tickets', lazy='selectin')
    people: Mapped[List['Person']] = relationship(
        secondary='people_tickets', back_populates='tickets', lazy='selectin')
    custom_made_event: Mapped[Optional['CustomMadeEvent']] = relationship(
        lazy='selectin')


class TypeEvent(BaseModel):
    __tablename__ = 'type_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    name_alias: Mapped[str]
    base_price_gift: Mapped[Optional[int]]
    notes: Mapped[Optional[str]]

    schedule_events: Mapped[List['ScheduleEvent']] = relationship(
        lazy='selectin')
    base_tickets: Mapped[List['BaseTicket']] = relationship(
        secondary='base_tickets_type_events',
        back_populates='type_events',
        lazy='selectin')


class BaseTicketTypeEvent(BaseModelTimed):
    __tablename__ = 'base_tickets_type_events'

    base_ticket_id: Mapped[int] = mapped_column(
        ForeignKey('base_tickets.base_ticket_id'), primary_key=True)
    type_event_id: Mapped[int] = mapped_column(
        ForeignKey('type_events.id'), primary_key=True)


class TheaterEvent(BaseModel):
    __tablename__ = 'theater_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    flag_premier: Mapped[bool] = mapped_column(default=False)
    min_age_child: Mapped[int] = mapped_column(default=0)
    max_age_child: Mapped[Optional[int]]
    show_emoji: Mapped[Optional[str]]
    duration: Mapped[Optional[time]]
    flag_active_repertoire: Mapped[bool] = mapped_column(default=False)
    flag_active_bd: Mapped[bool] = mapped_column(default=False)
    max_num_child_bd: Mapped[int] = mapped_column(default=8)
    max_num_adult_bd: Mapped[int] = mapped_column(default=10)
    flag_indiv_cost: Mapped[bool] = mapped_column(default=False)
    price_type: Mapped[PriceType] = mapped_column(default=PriceType.NONE)
    note: Mapped[Optional[str]]

    schedule_events: Mapped[List['ScheduleEvent']] = relationship(
        lazy='selectin')
    base_tickets: Mapped[List['BaseTicket']] = relationship(
        secondary='base_tickets_theater_events',
        back_populates='theater_events',
        lazy='selectin')


class BaseTicketTheaterEvent(BaseModelTimed):
    __tablename__ = 'base_tickets_theater_events'

    base_ticket_id: Mapped[int] = mapped_column(
        ForeignKey('base_tickets.base_ticket_id'), primary_key=True)
    theater_event_id: Mapped[int] = mapped_column(
        ForeignKey('theater_events.id'), primary_key=True)


class ScheduleEvent(BaseModelTimed):
    __tablename__ = 'schedule_events'

    id: Mapped[int] = mapped_column(primary_key=True)

    type_event_id: Mapped[int] = mapped_column(ForeignKey('type_events.id'))
    theater_event_id: Mapped[int] = mapped_column(
        ForeignKey('theater_events.id'))
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
    base_tickets: Mapped[List['BaseTicket']] = relationship(
        secondary='base_tickets_schedule_events',
        back_populates='schedule_events',
        lazy='selectin')


class BaseTicketScheduleEvent(BaseModelTimed):
    __tablename__ = 'base_tickets_schedule_events'

    base_ticket_id: Mapped[int] = mapped_column(
        ForeignKey('base_tickets.base_ticket_id'), primary_key=True)
    schedule_event_id: Mapped[int] = mapped_column(
        ForeignKey('schedule_events.id'), primary_key=True)


class Promotion(BaseModelTimed):
    __tablename__ = 'promotions'

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str]
    code: Mapped[str] = mapped_column(unique=True)
    discount: Mapped[int]
    start_date: Mapped[Optional[datetime]]
    expire_date: Mapped[Optional[datetime]]

    base_ticket_ids: Mapped[Optional[List[int]]] = mapped_column(
        ForeignKey('base_tickets.base_ticket_id'))
    type_event_ids: Mapped[Optional[List[int]]] = mapped_column(
        ForeignKey('type_events.id'))
    theater_event_ids: Mapped[Optional[List[int]]] = mapped_column(
        ForeignKey('theater_events.id'))
    schedule_event_ids: Mapped[Optional[List[int]]] = mapped_column(
        ForeignKey('schedule_events.id'))

    for_who_discount: Mapped[GroupOfPeopleByDiscountType]
    discount_type: Mapped[PromotionDiscountType] = mapped_column(
        default=PromotionDiscountType.fixed)

    flag_active: Mapped[bool] = mapped_column(default=True)
    is_visible_as_option: Mapped[bool] = mapped_column(default=False)
    count_of_usage: Mapped[int] = mapped_column(default=0)
    max_count_of_usage: Mapped[int] = mapped_column(default=0)
    min_purchase_sum: Mapped[int] = mapped_column(default=0)
    description_user: Mapped[Optional[str]]

    tickets: Mapped[List['Ticket']] = relationship(lazy='selectin')


class CustomMadeFormat(BaseModelTimed):
    __tablename__ = 'custom_made_formats'

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str]
    price: Mapped[int]
    flag_outside: Mapped[bool]


class CustomMadeEvent(BaseModelTimed):
    __tablename__ = 'custom_made_events'

    id: Mapped[int] = mapped_column(primary_key=True)

    place: Mapped[int]
    address: Mapped[str]
    date: Mapped[str]
    time: Mapped[str]
    age: Mapped[Optional[float]]
    qty_child: Mapped[int]
    qty_adult: Mapped[int]
    name_child: Mapped[str]
    name: Mapped[str]
    phone: Mapped[str]
    note: Mapped[Optional[str]]

    status: Mapped[CustomMadeStatus]

    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('users.user_id', ondelete='CASCADE'))
    custom_made_format_id: Mapped[int] = mapped_column(
        ForeignKey('custom_made_formats.id'))
    theater_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('theater_events.id'))
    ticket_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('tickets.id'))



class SalesCampaign(BaseModelTimed):
    __tablename__ = 'sales_campaigns'

    id: Mapped[int] = mapped_column(primary_key=True)

    created_by_admin_id: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str]
    theater_event_id: Mapped[int] = mapped_column(ForeignKey('theater_events.id'))
    title: Mapped[Optional[str]]
    status: Mapped[str] = mapped_column(default='draft')  # draft|running|done|canceled|failed

    # Message payload (no media groups)
    message_kind: Mapped[Optional[str]]  # text|photo|video|animation
    message_text: Mapped[Optional[str]]
    message_entities: Mapped[Optional[dict]] = mapped_column(JSON)
    caption_text: Mapped[Optional[str]]
    caption_entities: Mapped[Optional[dict]] = mapped_column(JSON)
    photo_file_id: Mapped[Optional[str]]
    video_file_id: Mapped[Optional[str]]
    animation_file_id: Mapped[Optional[str]]

    extra_payload: Mapped[Optional[dict]] = mapped_column(JSON)

    theater_event: Mapped['TheaterEvent'] = relationship(lazy='selectin')
    schedules: Mapped[List['SalesCampaignSchedule']] = relationship(
        back_populates='campaign', lazy='selectin')
    recipients: Mapped[List['SalesRecipient']] = relationship(
        back_populates='campaign', lazy='selectin')


class SalesCampaignSchedule(BaseModelTimed):
    __tablename__ = 'sales_campaign_schedules'

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey('sales_campaigns.id', ondelete='CASCADE'))
    schedule_event_id: Mapped[int] = mapped_column(
        ForeignKey('schedule_events.id', ondelete='CASCADE'))

    __table_args__ = (
        UniqueConstraint('campaign_id', 'schedule_event_id'),
    )

    campaign: Mapped['SalesCampaign'] = relationship(back_populates='schedules', lazy='selectin')
    schedule_event: Mapped['ScheduleEvent'] = relationship(lazy='selectin')


class SalesRecipient(BaseModelTimed):
    __tablename__ = 'sales_recipients'

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey('sales_campaigns.id', ondelete='CASCADE'))
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(default='pending')  # pending|sent|failed|blocked|no_chat
    last_error: Mapped[Optional[str]]

    __table_args__ = (
        UniqueConstraint('campaign_id', 'chat_id'),
    )

    campaign: Mapped['SalesCampaign'] = relationship(back_populates='recipients', lazy='selectin')


class TelegramUpdate(BaseModelTimed):
    __tablename__ = 'tg_updates'

    id: Mapped[int] = mapped_column(primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, unique=True)

    message: Mapped[Optional[dict]] = mapped_column(JSON)
    edited_message: Mapped[Optional[dict]] = mapped_column(JSON)
    channel_post: Mapped[Optional[dict]] = mapped_column(JSON)
    edited_channel_post: Mapped[Optional[dict]] = mapped_column(JSON)
    inline_query: Mapped[Optional[dict]] = mapped_column(JSON)
    chosen_inline_result: Mapped[Optional[dict]] = mapped_column(JSON)
    callback_query: Mapped[Optional[dict]] = mapped_column(JSON)
    shipping_query: Mapped[Optional[dict]] = mapped_column(JSON)
    pre_checkout_query: Mapped[Optional[dict]] = mapped_column(JSON)
    poll: Mapped[Optional[dict]] = mapped_column(JSON)
    poll_answer: Mapped[Optional[dict]] = mapped_column(JSON)
    my_chat_member: Mapped[Optional[dict]] = mapped_column(JSON)
    chat_member: Mapped[Optional[dict]] = mapped_column(JSON)
    chat_join_request: Mapped[Optional[dict]] = mapped_column(JSON)
    chat_boost: Mapped[Optional[dict]] = mapped_column(JSON)
    removed_chat_boost: Mapped[Optional[dict]] = mapped_column(JSON)
    message_reaction: Mapped[Optional[dict]] = mapped_column(JSON)
    message_reaction_count: Mapped[Optional[dict]] = mapped_column(JSON)
    business_connection: Mapped[Optional[dict]] = mapped_column(JSON)
    business_message: Mapped[Optional[dict]] = mapped_column(JSON)
    edited_business_message: Mapped[Optional[dict]] = mapped_column(JSON)
    deleted_business_messages: Mapped[Optional[dict]] = mapped_column(JSON)
    purchased_paid_media: Mapped[Optional[dict]] = mapped_column(JSON)

    full_update: Mapped[dict] = mapped_column(JSON)

    user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    text: Mapped[Optional[str]]
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    reply_to_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    message_thread_id: Mapped[Optional[int]] = mapped_column(BigInteger)


class BotSettings(BaseModelTimed):
    __tablename__ = 'bot_settings'

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True)
    value: Mapped[Optional[dict | list | str | int | float | bool]] = mapped_column(JSON)


class UserStatus(BaseModelTimed):
    __tablename__ = 'user_statuses'

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), primary_key=True)

    role: Mapped[UserRole] = mapped_column(default=UserRole.USER)
    is_blocked_by_user: Mapped[bool] = mapped_column(default=False)
    is_blacklisted: Mapped[bool] = mapped_column(default=False)

    is_blocked_by_admin: Mapped[bool] = mapped_column(default=False)
    blocked_by_admin_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    user: Mapped['User'] = relationship(back_populates='status', lazy='selectin')

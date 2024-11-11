from datetime import date, datetime
from typing import Collection, List

from sqlalchemy import select, func, DATE, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db import (
    User, Person, Adult, TheaterEvent, Ticket, Child,
    ScheduleEvent, BaseTicket, Promotion, TypeEvent)
from db.enum import (
    PriceType, TicketStatus, TicketPriceType, AgeType, CustomMadeStatus)
from db.models import CustomMadeFormat, CustomMadeEvent


async def attach_user_and_people_to_ticket(
        session: AsyncSession,
        ticket_id,
        user_id,
        people_ids
):
    result = await (session.execute(
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(selectinload(Ticket.people))
    ))
    ticket = result.scalar_one()
    for person_id in people_ids:
        person: Person = await session.get(Person, person_id)
        if person:
            ticket.people.append(person)

    user = await session.get(User, user_id)
    ticket.user = user
    await session.commit()


async def update_base_tickets_from_googlesheets(session: AsyncSession, tickets):
    for _ticket in tickets:
        dto_model = _ticket.to_dto()
        await session.merge(BaseTicket(**dto_model))
    await session.commit()


async def update_theater_events_from_googlesheets(
        session: AsyncSession, theater_events):
    for _event in theater_events:
        dto_model = _event.to_dto()
        await session.merge(TheaterEvent(**dto_model))
    await session.commit()


async def update_custom_made_format_from_googlesheets(
        session: AsyncSession, custom_made_formats):
    for _format in custom_made_formats:
        dto_model = _format.to_dto()
        await session.merge(CustomMadeFormat(**dto_model))
    await session.commit()


async def update_schedule_events_from_googlesheets(
        session: AsyncSession, schedule_events):
    for _event in schedule_events:
        dto_model = _event.to_dto()
        await session.merge(ScheduleEvent(**dto_model))
    await session.commit()


async def get_email(session: AsyncSession, user_id):
    user = await session.get(User, user_id)
    if user.email:
        return user.email
    else:
        return None


async def create_people(
        session: AsyncSession,
        user_id,
        client_data,
):
    session.autoflush = False

    people_ids = []
    name_adult = client_data['name_adult']
    phone = client_data['phone']
    data_children = client_data['data_children']
    user: User = await session.get(User, user_id)
    query = (
        select(Person)
        .where(
            Person.name == name_adult,
            Person.age_type == AgeType.adult,
            Person.user_id == user_id,
        )
    )
    res = await session.execute(query)
    res = res.scalars().all()
    if res:
        person = res[0]
        adult = person.adult
        adult.phone = phone
    else:
        person = Person(name=name_adult, age_type=AgeType.adult)
        session.add(person)
        user.people.append(person)
        adult = Adult(phone=phone)
        session.add(adult)
        person.adult = adult
        await session.flush()
    people_ids.append(adult.person_id)

    for item in data_children:
        name_child = item[0]
        age = item[1].replace(',', '.')
        query = (
            select(Person)
            .where(
                Person.name == name_child,
                Person.age_type == AgeType.child,
                Person.user_id == user_id,
            )
        )
        res = await session.execute(query)
        res = res.scalars().all()
        if res:
            person = res[0]
            child = person.child
            child.age = float(age)
        else:
            person = Person(name=name_child, age_type=AgeType.child)
            session.add(person)
            user.people.append(person)
            child = Child(age=age)
            session.add(child)
            person.child = child
            await session.flush()
        people_ids.append(child.person_id)

    await session.commit()
    return people_ids


async def create_user(
        session: AsyncSession,
        user_id,
        chat_id,
        *,
        username=None,
        email=None,
        agreement_received=None,
        is_privilege=None,
):
    user = User(
        user_id=user_id,
        chat_id=chat_id,
        username=username,
        email=email,
        agreement_received=agreement_received,
        is_privilege=is_privilege,
    )
    session.add(user)
    await session.commit()
    return user


async def create_person(session: AsyncSession, user_id, name, age_type):
    user: User = await session.get(User, user_id)
    person = Person(name=name, age_type=age_type)
    user.people.append(person)

    await session.commit()
    return person


async def create_adult(session: AsyncSession, user_id, name, phone):
    person = await create_person(session, user_id, name, AgeType.adult)
    await session.refresh(person)
    adult = Adult(phone=phone)
    person.adult = adult

    await session.commit()
    return adult


async def create_child(
        session: AsyncSession,
        user_id,
        name,
        age=None,
        birthdate=None,
):
    person = await create_person(session, user_id, name, AgeType.child)
    await session.refresh(person)
    child = Child(age=age, birthdate=birthdate)
    person.child = child

    await session.commit()
    return child


async def create_base_ticket(
        session: AsyncSession,
        base_ticket_id,
        flag_active,
        name,
        cost_main,
        cost_privilege,
        period_start_change_price,
        period_end_change_price,
        cost_main_in_period,
        cost_privilege_in_period,
        quality_of_children,
        quality_of_adult,
        quality_of_add_adult,
        quality_visits,
):
    base_ticket = BaseTicket(
        base_ticket_id=base_ticket_id,
        flag_active=flag_active,
        name=name,
        cost_main=cost_main,
        cost_privilege=cost_privilege,
        period_start_change_price=period_start_change_price,
        period_end_change_price=period_end_change_price,
        cost_main_in_period=cost_main_in_period,
        cost_privilege_in_period=cost_privilege_in_period,
        quality_of_children=quality_of_children,
        quality_of_adult=quality_of_adult,
        quality_of_add_adult=quality_of_add_adult,
        quality_visits=quality_visits,
    )
    session.add(base_ticket)
    await session.commit()
    return base_ticket


async def create_ticket(
        session: AsyncSession,
        base_ticket_id,
        price,
        schedule_event_id,
        promo_id=None,
        status=TicketStatus.CREATED,
        notes=None,
        payment_id=None,
        idempotency_id=None,
):
    ticket = Ticket(
        base_ticket_id=base_ticket_id,
        price=price,
        schedule_event_id=schedule_event_id,
        promo_id=promo_id,
        status=status,
        notes=notes,
        payment_id=payment_id,
        idempotency_id=idempotency_id,
    )
    session.add(ticket)
    await session.commit()
    return ticket


async def create_type_event(
        session: AsyncSession,
        name,
        name_alias,
        base_price_gift=None,
        notes=None,
        type_event_id=None,
):
    type_event = TypeEvent(
        id=type_event_id,
        name=name,
        name_alias=name_alias,
        base_price_gift=base_price_gift,
        notes=notes,
    )
    session.add(type_event)
    await session.commit()
    return type_event


async def create_theater_event(
        session: AsyncSession,
        name,
        min_age_child=0,
        show_emoji='',
        duration=None,
        max_age_child=0,
        flag_premier=False,
        flag_active_repertoire=False,
        flag_active_bd=False,
        max_num_child_bd=8,
        max_num_adult_bd=10,
        flag_indiv_cost=False,
        price_type=PriceType.NONE,
        theater_event_id=None,
):
    theater_event = TheaterEvent(
        id=theater_event_id,
        name=name,
        min_age_child=min_age_child,
        show_emoji=show_emoji,
        duration=duration,
        max_age_child=max_age_child,
        flag_premier=flag_premier,
        flag_active_repertoire=flag_active_repertoire,
        flag_active_bd=flag_active_bd,
        max_num_child_bd=max_num_child_bd,
        max_num_adult_bd=max_num_adult_bd,
        flag_indiv_cost=flag_indiv_cost,
        price_type=price_type
    )
    session.add(theater_event)
    await session.commit()
    return theater_event


async def create_schedule_event(
        session: AsyncSession,
        type_event_id,
        theater_event_id,
        flag_turn_in_bot,
        datetime_event,
        qty_child=0,
        qty_child_free_seat=0,
        qty_child_nonconfirm_seat=0,
        qty_adult=0,
        qty_adult_free_seat=0,
        qty_adult_nonconfirm_seat=0,
        flag_gift=False,
        flag_christmas_tree=False,
        flag_santa=False,
        ticket_price_type=TicketPriceType.NONE,
        schedule_event_id=None,
):
    schedule_event = ScheduleEvent(
        id=schedule_event_id,
        type_event_id=type_event_id,
        theater_event_id=theater_event_id,
        flag_turn_in_bot=flag_turn_in_bot,
        datetime_event=datetime_event,
        qty_child=qty_child,
        qty_child_free_seat=qty_child_free_seat,
        qty_child_nonconfirm_seat=qty_child_nonconfirm_seat,
        qty_adult=qty_adult,
        qty_adult_free_seat=qty_adult_free_seat,
        qty_adult_nonconfirm_seat=qty_adult_nonconfirm_seat,
        flag_gift=flag_gift,
        flag_christmas_tree=flag_christmas_tree,
        flag_santa=flag_santa,
        ticket_price_type=ticket_price_type,
    )
    session.add(schedule_event)
    await session.commit()
    return schedule_event


async def create_promotion(
        session: AsyncSession,
        name,
        code,
        discount,
        for_who_discount,
        *,
        start_date=None,
        expire_date=None,
        base_ticket_ids=None,
        type_event_ids=None,
        theater_event_ids=None,
        schedule_event_ids=None,
        flag_active=True,
        count_of_usage=0,
        max_count_of_usage=0,
):
    promo = Promotion(
        name=name,
        code=code,
        discount=discount,
        start_date=start_date,
        expire_date=expire_date,
        base_ticket_ids=base_ticket_ids,
        type_event_ids=type_event_ids,
        theater_event_ids=theater_event_ids,
        schedule_event_ids=schedule_event_ids,
        for_who_discount=for_who_discount,
        flag_active=flag_active,
        count_of_usage=count_of_usage,
        max_count_of_usage=max_count_of_usage,
    )
    session.add(promo)
    await session.commit()
    return promo


async def create_custom_made_event(
        session: AsyncSession,
        place,
        address,
        date,
        time,
        age,
        qty_child,
        qty_adult,
        name_child,
        name,
        phone,
        user_id,
        custom_made_format_id,
        theater_event_id,
        *,
        note=None,
        status=CustomMadeStatus.CREATED,
        ticket_id=None,
):
    custom_made_event = CustomMadeEvent(
        place=place,
        address=address,
        date=date,
        time=time,
        age=age,
        qty_child=qty_child,
        qty_adult=qty_adult,
        name_child=name_child,
        name=name,
        phone=phone,
        note=note,
        status=status,
        user_id=user_id,
        custom_made_format_id=custom_made_format_id,
        theater_event_id=theater_event_id,
        ticket_id=ticket_id,
    )
    session.add(custom_made_event)
    await session.commit()
    return custom_made_event


async def get_user(session: AsyncSession,
                   user_id: int):
    return await session.get(User, user_id)


async def get_persons(session: AsyncSession,
                      user_id: int):
    return await session.get(Person, user_id)


async def get_base_ticket(session: AsyncSession,
                          base_ticket_id: int):
    return await session.get(BaseTicket, base_ticket_id)


async def get_ticket(session: AsyncSession,
                     ticket_id: int):
    return await session.get(Ticket, ticket_id)


async def get_type_event(session: AsyncSession,
                         type_event_id: int):
    return await session.get(TypeEvent, type_event_id)


async def get_theater_event(session: AsyncSession,
                            theater_event_id: int):
    return await session.get(TheaterEvent, theater_event_id)


async def get_schedule_event(session: AsyncSession,
                             schedule_event_id: int):
    return await session.get(ScheduleEvent, schedule_event_id)


async def get_users_by_ids(session: AsyncSession,
                           user_id: Collection[int]):
    query = select(User).where(
        User.user_id.in_(user_id))
    result = await session.execute(query)
    return result.scalars().all()


async def get_persons_by_ids(session: AsyncSession,
                             user_id: Collection[int]):
    query = select(Person).where(
        Person.user_id.in_(user_id))
    result = await session.execute(query)
    return result.scalars().all()


async def get_base_tickets_by_ids(session: AsyncSession,
                                  base_ticket_id: Collection[int]):
    query = select(BaseTicket).where(
        BaseTicket.base_ticket_id.in_(base_ticket_id))
    result = await session.execute(query)
    return result.scalars().all()


async def get_tickets_by_ids(session: AsyncSession,
                             ticket_id: Collection[int]):
    query = select(Ticket).where(
        Ticket.id.in_(ticket_id))
    result = await session.execute(query)
    return result.scalars().all()


async def get_theater_events_by_ids(session: AsyncSession,
                                    theater_event_ids: Collection[int]):
    query = select(TheaterEvent).where(
        TheaterEvent.id.in_(theater_event_ids))
    result = await session.execute(query)
    return result.scalars().all()


async def get_schedule_events_by_ids(session: AsyncSession,
                                     schedule_event_ids: Collection[int]):
    query = select(ScheduleEvent).where(
        ScheduleEvent.id.in_(schedule_event_ids)
    ).order_by(ScheduleEvent.datetime_event)
    result = await session.execute(query)
    return result.scalars().all()


async def get_promotion(session: AsyncSession,
                        promotion_id: int):
    return await session.get(ScheduleEvent, promotion_id)


async def get_custom_made_format(session: AsyncSession,
                                 custom_made_format_id: int):
    return await session.get(CustomMadeFormat, custom_made_format_id)


async def get_custom_made_event(session: AsyncSession,
                                 custom_made_event_id: int):
    return await session.get(CustomMadeEvent, custom_made_event_id)


async def get_all_tickets_by_status(session: AsyncSession,
                                    status: TicketStatus):
    query = select(Ticket).where(Ticket.status == status)
    result = await session.execute(query)
    return result.scalars().all()


async def get_all_base_tickets(session: AsyncSession):
    query = select(BaseTicket).order_by(BaseTicket.base_ticket_id)
    result = await session.execute(query)
    return result.scalars().all()


async def get_all_theater_events(session: AsyncSession):
    query = select(TheaterEvent)
    result = await session.execute(query)
    return result.scalars().all()


async def get_all_schedule_events(session: AsyncSession):
    query = select(ScheduleEvent)
    result = await session.execute(query)
    return result.scalars().all()


async def get_all_promotions(session: AsyncSession):
    query = select(Promotion)
    result = await session.execute(query)
    return result.scalars().all()


async def get_all_custom_made_format(session: AsyncSession):
    query = select(CustomMadeFormat)
    result = await session.execute(query)
    return result.scalars().all()


async def get_base_tickets_by_event_or_all(
        schedule_event,
        theater_event,
        type_event,
        session
):
    if schedule_event.base_tickets:
        base_tickets = schedule_event.base_tickets
    elif theater_event.base_tickets:
        base_tickets = theater_event.base_tickets
    elif type_event.base_tickets:
        base_tickets = type_event.base_tickets
    else:
        base_tickets = await get_all_base_tickets(session)
        sorted(base_tickets, key=lambda x: x.base_ticket_id)
    base_tickets = sorted(base_tickets, key=lambda x: x.base_ticket_id)
    return base_tickets


async def get_schedule_events_by_theater_event_ids(
        session: AsyncSession, theater_event_ids: List[int]):
    query = select(ScheduleEvent).where(
        ScheduleEvent.theater_event_id.in_(theater_event_ids))
    result = await session.execute(query)
    return result.scalars().all()


async def get_schedule_events_by_type(
        session: AsyncSession, type_event_id: List[int]):
    query = select(ScheduleEvent).where(
        ScheduleEvent.type_event_id.in_(type_event_id))
    result = await session.execute(query)
    return result.scalars().all()


async def get_schedule_events_by_type_actual(
        session: AsyncSession, type_event_id: List[int]):
    query = select(ScheduleEvent).where(
        ScheduleEvent.type_event_id.in_(type_event_id),
        ScheduleEvent.datetime_event >= datetime.now()
    ).order_by(ScheduleEvent.datetime_event)
    result = await session.execute(query)
    return result.scalars().all()


async def get_schedule_events_by_theater_ids_actual(
        session: AsyncSession, theater_event_ids: List[int]):
    query = select(ScheduleEvent).where(
        ScheduleEvent.theater_event_id.in_(theater_event_ids),
        ScheduleEvent.datetime_event >= datetime.now()
    ).order_by(ScheduleEvent.datetime_event)
    result = await session.execute(query)
    return result.scalars().all()


async def get_schedule_events_by_ids_and_theater(
        session: AsyncSession,
        schedule_event_ids: List[int],
        theater_event_ids: List[int],
):
    query = select(ScheduleEvent).where(
        ScheduleEvent.id.in_(schedule_event_ids),
        ScheduleEvent.theater_event_id.in_(theater_event_ids),
    ).order_by(ScheduleEvent.datetime_event)
    result = await session.execute(query)
    return result.scalars().all()


async def get_actual_schedule_events_by_date(
        session: AsyncSession, date_event: date):
    query = select(ScheduleEvent).where(
        and_(func.cast(ScheduleEvent.datetime_event, DATE) == date_event))
    result = await session.execute(query)
    return result.scalars().all()


async def get_schedule_theater_base_tickets(context, choice_event_id):
    schedule_event = await get_schedule_event(context.session,
                                              choice_event_id)
    theater_event = await get_theater_event(context.session,
                                            schedule_event.theater_event_id)
    type_event = await get_type_event(context.session,
                                      schedule_event.type_event_id)
    base_tickets = await get_base_tickets_by_event_or_all(schedule_event,
                                                          theater_event,
                                                          type_event,
                                                          context.session)
    return base_tickets, schedule_event, theater_event, type_event


async def get_theater_events_on_cme(session: AsyncSession):
    query = select(TheaterEvent).where(TheaterEvent.flag_active_bd)
    result = await session.execute(query)
    return result.scalars().all()


async def update_user(
        session: AsyncSession,
        user_id,
        **kwargs
):
    user = await session.get(User, user_id)
    for key, value in kwargs.items():
        setattr(user, key, value)
    await session.commit()
    return user


async def update_base_ticket(
        session: AsyncSession,
        base_ticket_id,
        **kwargs
):
    ticket = await session.get(BaseTicket, base_ticket_id)
    for key, value in kwargs.items():
        setattr(ticket, key, value)
    await session.commit()
    return ticket


async def update_ticket(
        session: AsyncSession,
        ticket_id,
        **kwargs
):
    ticket = await session.get(Ticket, ticket_id)
    for key, value in kwargs.items():
        setattr(ticket, key, value)
    await session.commit()
    return ticket


async def update_type_event(
        session: AsyncSession,
        type_event_id,
        **kwargs
):
    type_event = await session.get(TheaterEvent, type_event_id)
    for key, value in kwargs.items():
        setattr(type_event, key, value)
    await session.commit()
    return type_event


async def update_theater_event(
        session: AsyncSession,
        theater_event_id,
        **kwargs
):
    theater_event = await session.get(TheaterEvent, theater_event_id)
    for key, value in kwargs.items():
        setattr(theater_event, key, value)
    await session.commit()
    return theater_event


async def update_schedule_event(
        session: AsyncSession,
        schedule_event_id,
        **kwargs
):
    schedule_event = await session.get(ScheduleEvent, schedule_event_id)
    for key, value in kwargs.items():
        setattr(schedule_event, key, value)
    await session.commit()
    return schedule_event


async def update_promotion(
        session: AsyncSession,
        promotion_id,
        **kwargs
):
    promotion = await session.get(Promotion, promotion_id)
    for key, value in kwargs.items():
        setattr(promotion, key, value)
    await session.commit()
    return promotion


async def update_custom_made_event(
        session: AsyncSession,
        custom_made_event_id,
        **kwargs
):
    cme = await session.get(CustomMadeEvent, custom_made_event_id)
    for key, value in kwargs.items():
        setattr(cme, key, value)
    await session.commit()
    return cme


async def del_ticket(
        session: AsyncSession,
        ticket_id,
):
    result = await session.get(Ticket, ticket_id)
    await session.delete(result)
    await session.commit()
    return result


async def del_theater_event(session: AsyncSession, theater_event_id: int):
    result = await session.get(TheaterEvent, theater_event_id)
    await session.delete(result)
    await session.commit()
    return result


async def del_schedule_event(session: AsyncSession, schedule_event_id: int):
    result = await session.get(ScheduleEvent, schedule_event_id)
    await session.delete(result)
    await session.commit()
    return result


async def del_promotion(session: AsyncSession, promotion_id: int):
    result = await session.get(Promotion, promotion_id)
    await session.delete(result)
    await session.commit()
    return result

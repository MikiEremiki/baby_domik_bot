from sqlalchemy import select, exists, insert, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import (User, Person, Adult, TheaterEvent, Ticket, Child,
                ScheduleEvent, BaseTicket)
from db.enum import PriceType, TicketStatus, TicketPriceType, AgeType


async def add_people_to_ticket(
        session: AsyncSession,
        ticket_id,
        people_ids
):
    ticket = await session.get(Ticket, ticket_id)
    for person_id in people_ids:
        person = await session.get(Person, person_id)
        ticket.people.append(person)
    await session.commit()
    return ticket


async def add_user_to_ticket(session: AsyncSession, ticket_id, user_id):
    ticket = await session.get(Ticket, ticket_id)
    user = await session.get(User, user_id)
    ticket.users = user
    await session.commit()
    return ticket


async def attach_user_and_people_to_ticket(
        session: AsyncSession,
        ticket_id,
        user_id,
        people
):
    await add_people_to_ticket(session, ticket_id, people)
    await add_user_to_ticket(session, ticket_id, user_id)


async def update_base_tickets(session: AsyncSession, tickets):
    for _ticket in tickets:
        # ticket = await session.get(BaseTicket, _ticket.base_ticket_id)
        dto_model = _ticket.to_dto()
        await session.merge(BaseTicket(**dto_model))
    await session.commit()


async def create_people(
        session: AsyncSession,
        user_id,
        client_data,
):
    people_ids = []
    name_adult = client_data['name_adult']
    phone = client_data['phone']
    data_children = client_data['data_children']
    adult = await create_adult(session, user_id, name_adult, phone)
    people_ids.append(adult.person_id)
    for item in data_children:
        name_child = item[0]
        age = item[1].replace(',', '.')
        child = await create_child(session, user_id, name_child, age)
        people_ids.append(child.person_id)

    await session.commit()
    return people_ids


async def create_user(
        session: AsyncSession,
        user_id,
        chat_id,
        username=None,
        email=None,
):
    user = User(
        id=user_id,
        chat_id=chat_id,
        username=username,
        email=email,
    )
    session.add(user)
    await session.commit()
    return user


async def create_person(session: AsyncSession, user_id, name, age_type):
    user = await session.get(User, user_id)
    person = Person(name=name, age_type=age_type)
    user.people.append(person)

    await session.commit()
    return person


async def create_adult(session: AsyncSession, user_id, name, phone):
    person = await create_person(session, user_id, name, AgeType.adult)
    await session.refresh(person)
    adult = Adult(phone=phone)
    person.adult.append(adult)

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
    person.child.append(child)

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
        status=TicketStatus.CREATED,
        notes=None,
        payment_id=None,
        idempotency_id=None,
):
    ticket = Ticket(
        base_ticket_id=base_ticket_id,
        price=price,
        schedule_event_id=schedule_event_id,
        status=status,
        notes=notes,
        payment_id=payment_id,
        idempotency_id=idempotency_id,
    )
    session.add(ticket)
    await session.commit()
    return ticket


async def create_theater_event(
        session: AsyncSession,
        name,
        min_age_child,
        show_emoji='',
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
    return theater_event.id


async def create_schedule_event(
        session: AsyncSession,
        type_event_id,
        theater_events_id,
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
        theater_events_id=theater_events_id,
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
    return schedule_event.id


async def get_user(session: AsyncSession, user_id: int):
    query = select(User).where(User.user_id == user_id)
    result = await session.execute(query)
    user = result.all()

    if user:
        return user
    else:
        return None

async def get_persons(session: AsyncSession, user_id: int):
    query = select(Person).where(exists().where(Person.user_id == user_id))
    result = await session.execute(query)
    persons = result.all()

    if persons:
        return persons
    else:
        return None


async def get_base_ticket(session: AsyncSession, base_ticket_id: int):
    return await session.get(BaseTicket, base_ticket_id)


async def get_ticket(session: AsyncSession, ticket_id: int):
    return await session.get(Ticket, ticket_id)


async def get_theater_event(session: AsyncSession, theater_event_id: int):
    return await session.get(TheaterEvent, theater_event_id)


async def get_schedule_event(session: AsyncSession, schedule_event_id: int):
    return await session.get(ScheduleEvent, schedule_event_id)


async def get_all_theater_events(session: AsyncSession):
    query = select(TheaterEvent)
    result = await session.execute(query)
    return result.all()


async def get_all_schedule_events(session: AsyncSession):
    query = select(ScheduleEvent)
    result = await session.execute(query)
    return result.all()


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

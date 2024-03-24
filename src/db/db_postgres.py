from sqlalchemy import select, exists, insert, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import User, Person, Adult, TheaterEvent, Ticket, Child, ScheduleEvent
from db.enum import PriceType, TicketStatus, TicketPriceType, AgeType


async def create_person(session: AsyncSession, user_id, name, age_type):
    user = await session.get(User, user_id)
    person = Person(name=name, age_type=age_type)
    user.people.append(person)

    await session.commit()
    return person

async def get_persons(session: AsyncSession, user_id: int):
    query = select(Person).where(exists().where(Person.user_id == user_id))
    result = await session.execute(query)
    persons = result.all()

    if persons:
        return persons
    else:
        return None


async def create_adult(session: AsyncSession, user_id, name, phone):
    person = await create_person(session, user_id, name, AgeType.adult)
    await session.refresh(person)
    adult = Adult(phone=phone)
    person.adults.append(adult)

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
    person.children.append(child)

    await session.commit()
    return child


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


async def add_people_ticket(
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


async def add_user_ticket(session: AsyncSession, ticket_id, user_id):
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
    await add_people_ticket(session, ticket_id, people)
    await add_user_ticket(session, ticket_id, user_id)


async def create_user(
        session: AsyncSession,
        user_id,
        chat_id,
        username=None,
        email=None,
):
    stmt = insert(User).values(
        id=user_id,
        chat_id=chat_id,
        username=username,
        email=email,
    )
    result = await session.execute(stmt.returning(User.id))
    await session.commit()
    return result.scalar()


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


async def get_user(session: AsyncSession, user_id: int):
    exists_criteria = (
        exists().where(User.id == user_id))
    query = select(User).where(exists_criteria)
    result = await session.execute(query)
    user = result.all()

    if user:
        return user
    else:
        return None


async def create_theater_event(
        session: AsyncSession,
        name,
        min_age_child,
        show_emoji,
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
    if not theater_event_id:
        stmt = insert(TheaterEvent).values(
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
            price_type=price_type,
        )
    else:
        stmt = insert(TheaterEvent).values(
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
            price_type=price_type,
        )
    result = await session.execute(stmt.returning(TheaterEvent.id))
    await session.commit()
    return result.scalar()


async def get_theater_event(session: AsyncSession, theater_event_id: int):
    return await session.get(TheaterEvent, theater_event_id)


async def del_theater_event(session: AsyncSession, theater_event_id: int):
    query = (
        delete(TheaterEvent)
        .where(TheaterEvent.id == theater_event_id)
    )
    return await session.execute(query)


async def get_all_theater_events(session: AsyncSession):
    query = select(TheaterEvent)
    result = await session.execute(query)
    return result.all()


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
    stmt = insert(Ticket).values(
        base_ticket_id=base_ticket_id,
        price=price,
        schedule_event_id=schedule_event_id,
        status=status,
        notes=notes,
        payment_id=payment_id,
        idempotency_id=idempotency_id,
    )
    result = await session.execute(stmt.returning(Ticket.id))
    await session.commit()
    return result.scalar()


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


async def get_ticket(
        session: AsyncSession,
        ticket_id,
):
    return await session.get(Ticket, ticket_id)


async def delete_ticket(
        session: AsyncSession,
        ticket_id,
):
    ticket = await get_ticket(session, ticket_id)
    return await session.delete(ticket)


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
    if not schedule_event_id:
        stmt = insert(ScheduleEvent).values(
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
    else:
        stmt = insert(ScheduleEvent).values(
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
    result = await session.execute(stmt.returning(ScheduleEvent.id))
    await session.commit()
    return result.scalar()


async def update_schedule_event(
        session: AsyncSession,
        schedule_event_id,
        **kwargs
):
    event = await session.get(ScheduleEvent, schedule_event_id)
    for key, value in kwargs.items():
        setattr(event, key, value)
    await session.commit()
    return event


async def get_schedule_event(session: AsyncSession, schedule_event_id: int):
    return await session.get(ScheduleEvent, schedule_event_id)


async def del_schedule_event(session: AsyncSession, schedule_event_id: int):
    query = (
        delete(ScheduleEvent)
        .where(ScheduleEvent.id == schedule_event_id)
    )
    return await session.execute(query)


async def get_all_schedule_events(session: AsyncSession):
    query = select(ScheduleEvent)
    result = await session.execute(query)
    return result.all()

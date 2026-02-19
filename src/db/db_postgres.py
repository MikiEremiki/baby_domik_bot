from datetime import date, datetime
from typing import Collection, List

from sqlalchemy import select, func, DATE, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, Mapped

from db import (
    User, Person, Adult, TheaterEvent, Ticket, Child,
    ScheduleEvent, BaseTicket, Promotion, TypeEvent, BotSettings, UserStatus,
    FeedbackTopic, FeedbackMessage)
from db.enum import (
    PriceType, TicketStatus, TicketPriceType, AgeType, CustomMadeStatus, UserRole)
from db.models import CustomMadeFormat, CustomMadeEvent, PersonTicket


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
        person: Person | None = await session.get(Person, person_id)
        if person:
            ticket.people.append(person)

    user: User | None = await session.get(User, user_id)
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


async def get_phone(session: AsyncSession, user_id):
    """
    Возвращает последний сохраненный телефон взрослого пользователя, если он есть.
    Формат хранения: 10 цифр без префикса +7.
    """
    # Ищем любой последний (по person_id) телефон взрослого, связанного с пользователем
    result = await session.execute(
        select(Adult.phone)
        .join(Person, Adult.person_id == Person.id)
        .where(Person.user_id == user_id, Adult.phone.is_not(None))
        .order_by(Adult.person_id.desc())
    )
    phone = result.scalars().first()
    return phone or None


async def get_adult_name(session: AsyncSession, user_id):
    """
    Возвращает последнее введенное имя взрослого пользователя, если оно есть.
    """
    result = await session.execute(
        select(Person.name)
        .where(
            Person.user_id == user_id,
            Person.name.is_not(None),
            Person.age_type == AgeType.adult
        )
        .order_by(Person.id.desc())
    )
    adult_name = result.scalars().first()
    return adult_name or None


async def get_child(session: AsyncSession, user_id):
    """
    Возвращает последнее введенное имя ребенка, если оно есть.
    """
    result = await session.execute(
        select(Person.name, Child.age)
        .join(Child, Person.id == Child.person_id)
        .where(
            Person.user_id == user_id,
            Person.name.is_not(None),
            Person.age_type == AgeType.child
        )
        .order_by(Person.id.desc())
    )
    child = result.first()
    return child or None


async def get_children(session: AsyncSession, user_id):
    """
    Возвращает всех детей пользователя.
    """
    result = await session.execute(
        select(Person.name, Child.age, Person.id)
        .join(Child, Person.id == Child.person_id)
        .where(
            Person.user_id == user_id,
            Person.name.is_not(None),
            Person.age_type == AgeType.child
        )
        .order_by(Person.name)
    )
    children = result.all()
    return children


async def create_people(
        session: AsyncSession,
        user_id,
        client_data,
):
    # TODO Исправить ошибку при вводе одинаковых имен
    session.autoflush = False

    people_ids = []
    name_adult = client_data['name_adult']
    phone = client_data['phone']
    data_children = client_data['data_children']
    user: User | None = await session.get(User, user_id)

    if user is None:
        raise ValueError(f"User with ID {user_id} does not exist")

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
    user: User | None = await session.get(User, user_id)

    if user is None:
        raise ValueError(f"User with ID {user_id} does not exist")

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
        note=None,
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
        price_type=price_type,
        note=note
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


async def get_person(session: AsyncSession,
                      person_id: int):
    return await session.get(Person, person_id)


async def get_base_ticket(session: AsyncSession,
                          base_ticket_id: int):
    return await session.get(BaseTicket, base_ticket_id)


async def get_ticket(session: AsyncSession,
                     ticket_id: int):
    return await session.get(Ticket, ticket_id)


async def get_type_event(session: AsyncSession,
                         type_event_id: Mapped[int]):
    return await session.get(TypeEvent, type_event_id)


async def get_theater_event(session: AsyncSession,
                            theater_event_id: Mapped[int]):
    return await session.get(TheaterEvent, theater_event_id)


async def get_schedule_event(session: AsyncSession,
                             schedule_event_id: Mapped[int]):
    return await session.get(ScheduleEvent, schedule_event_id)


async def get_users_by_ids(session: AsyncSession,
                           user_id: Collection[int]):
    query = select(User).where(
        User.user_id.in_(user_id))
    result = await session.execute(query)
    return result.scalars().all()


async def get_persons_by_user_ids(session: AsyncSession,
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
    query = select(Promotion).where(Promotion.id == promotion_id).options(
        selectinload(Promotion.type_events),
        selectinload(Promotion.theater_events),
        selectinload(Promotion.base_tickets),
        selectinload(Promotion.schedule_events)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


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


async def get_all_type_events(session: AsyncSession):
    query = select(TypeEvent)
    result = await session.execute(query)
    return result.scalars().all()


async def get_all_schedule_events(session: AsyncSession):
    query = select(ScheduleEvent)
    result = await session.execute(query)
    return result.scalars().all()


async def get_all_schedule_events_actual(session: AsyncSession):
    query = select(ScheduleEvent).where(
        ScheduleEvent.datetime_event >= datetime.now()
    ).options(selectinload(ScheduleEvent.theater_event)).order_by(ScheduleEvent.datetime_event)
    result = await session.execute(query)
    return result.scalars().all()


async def get_promotion_by_code(session: AsyncSession,
                               code: str):
    query = select(Promotion).where(Promotion.code == code).options(
        selectinload(Promotion.type_events),
        selectinload(Promotion.theater_events),
        selectinload(Promotion.base_tickets),
        selectinload(Promotion.schedule_events)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_active_promotions_as_options(session: AsyncSession):
    query = select(Promotion).where(
        Promotion.flag_active == True,
        Promotion.is_visible_as_option == True
    )
    result = await session.execute(query)
    return result.scalars().all()


async def increment_promotion_usage(session: AsyncSession, promotion_id: int):
    promo = await session.get(Promotion, promotion_id)
    if promo:
        promo.count_of_usage = (promo.count_of_usage or 0) + 1
        await session.commit()


async def update_promotions_from_googlesheets(session: AsyncSession, promotions):
    # Обновляем только простые поля промоакций, ограничения по связям не загружаем из таблиц
    allowed_fields = {
        'id', 'name', 'code', 'discount', 'start_date', 'expire_date',
        'for_who_discount', 'flag_active', 'is_visible_as_option',
        'count_of_usage', 'max_count_of_usage', 'min_purchase_sum',
        'description_user', 'requires_verification', 'verification_text',
        'discount_type'
    }
    for _promotion in promotions:
        dto_model = {k: v for k, v in _promotion.to_dto().items() if k in allowed_fields}
        await session.merge(Promotion(**dto_model))
    await session.commit()


async def get_all_promotions(session: AsyncSession):
    query = select(Promotion).order_by(Promotion.id)
    result = await session.execute(query)
    return result.scalars().all()


async def create_promotion(session: AsyncSession, promotion_data: dict):
    # Извлекаем списки ID для связей Many-to-Many
    type_event_ids = promotion_data.pop('type_event_ids', []) or []
    theater_event_ids = promotion_data.pop('theater_event_ids', []) or []
    base_ticket_ids = promotion_data.pop('base_ticket_ids', []) or []
    schedule_event_ids = promotion_data.pop('schedule_event_ids', []) or []

    promotion = Promotion(**promotion_data)

    if type_event_ids:
        res = await session.execute(select(TypeEvent).where(TypeEvent.id.in_(type_event_ids)))
        promotion.type_events = list(res.scalars().all())
    if theater_event_ids:
        res = await session.execute(select(TheaterEvent).where(TheaterEvent.id.in_(theater_event_ids)))
        promotion.theater_events = list(res.scalars().all())
    if base_ticket_ids:
        res = await session.execute(select(BaseTicket).where(BaseTicket.base_ticket_id.in_(base_ticket_ids)))
        promotion.base_tickets = list(res.scalars().all())
    if schedule_event_ids:
        res = await session.execute(select(ScheduleEvent).where(ScheduleEvent.id.in_(schedule_event_ids)))
        promotion.schedule_events = list(res.scalars().all())

    session.add(promotion)
    await session.commit()
    await session.refresh(promotion)
    return promotion


async def update_promotion(session: AsyncSession, promotion_id: int, promotion_data: dict):
    # Используем selectinload для загрузки связей
    query = select(Promotion).where(Promotion.id == promotion_id).options(
        selectinload(Promotion.type_events),
        selectinload(Promotion.theater_events),
        selectinload(Promotion.base_tickets),
        selectinload(Promotion.schedule_events)
    )
    result = await session.execute(query)
    promotion = result.scalar_one_or_none()

    if promotion:
        if 'code' in promotion_data:
            promotion_data['code'] = promotion_data['code'].strip().upper()

        # Обработка связей M2M
        if 'type_event_ids' in promotion_data:
            ids = promotion_data.pop('type_event_ids') or []
            res = await session.execute(select(TypeEvent).where(TypeEvent.id.in_(ids)))
            promotion.type_events = list(res.scalars().all())

        if 'theater_event_ids' in promotion_data:
            ids = promotion_data.pop('theater_event_ids') or []
            res = await session.execute(select(TheaterEvent).where(TheaterEvent.id.in_(ids)))
            promotion.theater_events = list(res.scalars().all())

        if 'base_ticket_ids' in promotion_data:
            ids = promotion_data.pop('base_ticket_ids') or []
            res = await session.execute(select(BaseTicket).where(BaseTicket.base_ticket_id.in_(ids)))
            promotion.base_tickets = list(res.scalars().all())

        if 'schedule_event_ids' in promotion_data:
            ids = promotion_data.pop('schedule_event_ids') or []
            res = await session.execute(select(ScheduleEvent).where(ScheduleEvent.id.in_(ids)))
            promotion.schedule_events = list(res.scalars().all())

        for key, value in promotion_data.items():
            setattr(promotion, key, value)
        await session.commit()
        await session.refresh(promotion)
    return promotion


async def toggle_promotion_active(session: AsyncSession, promotion_id: int):
    promotion = await session.get(Promotion, promotion_id)
    if promotion:
        promotion.flag_active = not promotion.flag_active
        await session.commit()
        await session.refresh(promotion)
    return promotion


async def toggle_promotion_visible(session: AsyncSession, promotion_id: int):
    promotion = await session.get(Promotion, promotion_id)
    if promotion:
        promotion.is_visible_as_option = not promotion.is_visible_as_option
        await session.commit()
        await session.refresh(promotion)
    return promotion


async def get_person_ticket_by_ticket_id(session: AsyncSession, ticket_id: int):
    result = await session.execute(
        select(PersonTicket).where(PersonTicket.ticket_id == ticket_id)
    )
    return result.scalars().first()


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


async def get_last_schedule_update_time(session: AsyncSession) -> datetime:
    """Возвращает время последнего изменения любого события в расписании."""
    stmt = select(func.max(ScheduleEvent.updated_at))
    result = await session.execute(stmt)
    return result.scalar() or datetime.min


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
    type_event = await session.get(TypeEvent, type_event_id)
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


# ===== Helpers for Person/Adult/Child updates and deletion =====
async def update_person(
        session: AsyncSession,
        person_id: int,
        **kwargs
):
    person = await session.get(Person, person_id)
    for key, value in kwargs.items():
        setattr(person, key, value)
    await session.commit()
    return person


async def update_adult_by_person_id(
        session: AsyncSession,
        person_id: int,
        **kwargs
):
    # Find Adult by person_id; create if missing
    result = await session.execute(
        select(Adult).where(Adult.person_id == person_id))
    adult = result.scalar_one_or_none()
    if adult is None:
        adult = Adult(person_id=person_id)
        session.add(adult)
        await session.flush()
    for key, value in kwargs.items():
        setattr(adult, key, value)
    await session.commit()
    return adult


async def update_child_by_person_id(
        session: AsyncSession,
        person_id: int,
        **kwargs
):
    result = await session.execute(
        select(Child).where(Child.person_id == person_id))
    child = result.scalar_one_or_none()
    if child is None:
        child = Child(person_id=person_id)
        session.add(child)
        await session.flush()
    for key, value in kwargs.items():
        setattr(child, key, value)
    await session.commit()
    return child


async def delete_person(
        session: AsyncSession,
        person_id: int,
):
    person = await session.get(Person, person_id)
    await session.delete(person)
    await session.commit()
    return person


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


async def update_bot_setting(session: AsyncSession, key, value):
    stmt = select(BotSettings).where(BotSettings.key == key)
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = BotSettings(key=key, value=value)
        session.add(setting)
    await session.commit()


async def get_bot_settings(session: AsyncSession):
    stmt = select(BotSettings)
    result = await session.execute(stmt)
    return result.scalars().all()

async def get_or_create_user_status(session: AsyncSession, user_id: int) -> UserStatus:
    status = await session.get(UserStatus, user_id)
    if status is None:
        status = UserStatus(user_id=user_id, role=UserRole.USER)
        session.add(status)
        await session.flush()
    return status


async def update_user_status(session: AsyncSession, user_id: int, **kwargs) -> UserStatus:
    status = await get_or_create_user_status(session, user_id)
    for key, value in kwargs.items():
        if hasattr(status, key):
            setattr(status, key, value)
    await session.commit()
    return status


async def get_feedback_topic_by_user_id(session: AsyncSession, user_id: int):
    query = select(FeedbackTopic).where(FeedbackTopic.user_id == user_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_feedback_topic_by_topic_id(session: AsyncSession, topic_id: int):
    query = select(FeedbackTopic).where(FeedbackTopic.topic_id == topic_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def create_feedback_topic(session: AsyncSession, user_id: int, topic_id: int):
    feedback_topic = FeedbackTopic(user_id=user_id, topic_id=topic_id)
    session.add(feedback_topic)
    await session.commit()
    return feedback_topic


async def update_feedback_topic(session: AsyncSession, user_id: int, topic_id: int):
    feedback_topic = await get_feedback_topic_by_user_id(session, user_id)
    if feedback_topic:
        feedback_topic.topic_id = topic_id
        await session.commit()
    return feedback_topic


async def del_feedback_topic_by_topic_id(session: AsyncSession, topic_id: int):
    query = delete(FeedbackTopic).where(FeedbackTopic.topic_id == topic_id)
    await session.execute(query)
    await session.commit()


async def create_feedback_message(session: AsyncSession, user_id: int, user_message_id: int, admin_message_id: int):
    feedback_message = FeedbackMessage(
        user_id=user_id,
        user_message_id=user_message_id,
        admin_message_id=admin_message_id
    )
    session.add(feedback_message)
    await session.commit()
    return feedback_message


async def get_feedback_message_by_admin_id(session: AsyncSession, admin_message_id: int):
    query = select(FeedbackMessage).where(FeedbackMessage.admin_message_id == admin_message_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_feedback_message_by_user_message_id(session: AsyncSession, user_message_id: int):
    query = select(FeedbackMessage).where(FeedbackMessage.user_message_id == user_message_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()

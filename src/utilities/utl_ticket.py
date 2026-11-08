import logging
from telegram.ext import ContextTypes

from db import BaseTicket, ScheduleEvent, TheaterEvent, db_postgres
from db.enum import PriceType, TicketStatus, TicketSource
from db.models import Ticket
from utilities.utl_context import clean_context_on_end_handler
from utilities.utl_googlesheets import write_to_return_seats_for_sale

utl_ticket_logger = logging.getLogger('bot.utl_ticket')


def format_ticket_contacts(ticket: 'Ticket', full_name: str | None = None) -> str:
    """Форматирует контакты и источник билета в единый блок текста.

    Возвращает строку с разделением на строки (\n):
        Источник: …
        Покупатель: …
        Телефон: …
        Email: …

    Используется во всех админских выводах: уведомления, /list,
    действие «Покупатель», диалог переноса.

    :param ticket: билет из БД
    :param full_name: отображаемое имя Telegram-пользователя (update.effective_user.full_name),
        используется для покупателя из бота, если доступно.
    """
    lines: list[str] = []

    # Источник
    if ticket.source == TicketSource.WEBSITE:
        lines.append('Источник: Сайт')
    elif ticket.source == TicketSource.BOT:
        lines.append('Источник: Бот')
    else:
        lines.append('Источник: не указан')

    # Покупатель
    user = ticket.user
    if ticket.source == TicketSource.BOT and user is not None:
        # Покупка через бота: покупатель — Telegram-пользователь
        username_part = f'@{user.username} ' if user.username else ''
        display_name = full_name or user.username or 'Неизвестен'
        lines.append(f'Покупатель: {username_part}{display_name}')
    elif ticket.source == TicketSource.WEBSITE:
        # Покупка с сайта: покупатель неизвестен
        lines.append('Покупатель: Неизвестен')
    else:
        lines.append('Покупатель: Неизвестен')

    # Телефон
    if ticket.phone is not None:
        lines.append(f'Телефон: +7{ticket.phone}')
    else:
        lines.append('Телефон: не указан')

    # Email
    if ticket.email:
        lines.append(f'Email: {ticket.email}')
    else:
        lines.append('Email: не указан')

    return '\n'.join(lines)


async def get_spec_ticket_price(context: ContextTypes.DEFAULT_TYPE,
                                ticket: BaseTicket,
                                schedule_event: ScheduleEvent,
                                theater_event: TheaterEvent):
    reserve_user_data = context.user_data['reserve_user_data']

    option = get_option(schedule_event, theater_event)

    # Переопределил дату определения цены по дате спектакля
    date_for_price = schedule_event.datetime_event
    price, price_privilege = ticket.get_price_from_date(date_for_price)
    key = ticket.base_ticket_id
    type_ticket_price = await set_type_ticket_price(schedule_event)

    reserve_user_data['type_ticket_price'] = type_ticket_price
    if theater_event.flag_indiv_cost:
        # Пытаемся получить индивидуальную стоимость из БД
        special_price = await db_postgres.get_special_ticket_price(
            context.session,
            option=option,
            base_ticket_id=key,
            type_ticket_price=type_ticket_price
        )
        if special_price is not None:
            price = special_price
        else:
            utl_ticket_logger.error(
                f'{key=} - данному билету не назначена индив. цена')
            utl_ticket_logger.error(theater_event.model_dump())
            if key // 100 != 4:
                text = f'{key=} - данному билету не назначена индив. цена\n'
                text += f'{type_ticket_price=}\n'
                text += f'{theater_event.id=}\n'
                text += f'{schedule_event.id=}\n'
                text += f'{schedule_event.type_event_id=}\n'
                await context.bot.send_message(
                    chat_id=context.config.bot.developer_chat_id,
                    text=text,
                )
    return price, price_privilege


async def set_type_ticket_price(schedule_event: ScheduleEvent,
                                date_for_price=None):
    type_ticket_price = schedule_event.ticket_price_type.value
    if not type_ticket_price:
        if not date_for_price:
            date_for_price = schedule_event.datetime_event.date()
        if date_for_price.weekday() in range(5):
            type_ticket_price = 'будни'
        else:
            type_ticket_price = 'выходные'

    return type_ticket_price


def get_option(
        schedule_event: ScheduleEvent,
        theater_event: TheaterEvent
) -> str:
    option = ''
    if schedule_event.flag_gift:
        option = 'Подарок'
    if schedule_event.flag_christmas_tree:
        option = 'Ёлка'

    if not option:
        price_type = theater_event.price_type
        if price_type == PriceType.INDIVIDUAL:
            option = theater_event.id
        else:
            option = price_type.value
    return option


async def get_ticket_and_price(context, base_ticket_id):
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    theater_event_id = reserve_user_data['choose_theater_event_id']

    schedule_event = await db_postgres.get_schedule_event(
        context.session, schedule_event_id)
    theater_event = await db_postgres.get_theater_event(
        context.session, theater_event_id)

    ticket = await db_postgres.get_base_ticket(context.session, base_ticket_id)
    price, price_privilege = await get_spec_ticket_price(
        context, ticket, schedule_event, theater_event)
    return ticket, price


async def cancel_tickets_db_and_gspread(update, context):
    reserve_user_data = context.user_data.get('reserve_user_data', {})
    ticket_ids = reserve_user_data.get('ticket_ids')
    changed_seat = reserve_user_data.get('changed_seat', False)

    # Если билеты созданы или места были списаны — гарантированно возвращаем
    if ticket_ids or changed_seat:
        try:
            effective_chat = getattr(update, 'effective_chat', None)
            if effective_chat and 'common_data' in context.user_data:
                msg_id = context.user_data['common_data'].get(
                    'message_id_buy_info')
                if msg_id:
                    await context.bot.edit_message_reply_markup(
                        chat_id=effective_chat.id,
                        message_id=msg_id
                    )
        except Exception as e:
            utl_ticket_logger.error(f"Error editing reply markup: {e}")

        await write_to_return_seats_for_sale(context)


async def create_tickets_and_people(
        update,
        context,
        ticket_status
):
    reserve_user_data = context.user_data['reserve_user_data']
    client_data = reserve_user_data['client_data']

    ticket_ids = await create_tickets(context, ticket_status)

    people_ids = await db_postgres.create_people(context.session,
                                                 update.effective_user.id,
                                                 client_data)
    for ticket_id in ticket_ids:
        await db_postgres.attach_user_and_people_to_ticket(context.session,
                                                           ticket_id,
                                                           update.effective_user.id,
                                                           people_ids)

    return ticket_ids


async def create_tickets(context, ticket_status):
    ticket_ids = []

    reserve_user_data = context.user_data['reserve_user_data']
    choose_schedule_event_ids = reserve_user_data['choose_schedule_event_ids']
    # Берем цену со скидкой, если она есть
    chose_price = reserve_user_data.get('discounted_price', reserve_user_data['chose_price'])
    promo_id = reserve_user_data.get('applied_promo_id')
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    # Email и телефон покупателя из контекста бронирования
    buyer_email = reserve_user_data.get('buyer_email')
    client_data = reserve_user_data.get('client_data', {})
    buyer_phone_str = client_data.get('phone')
    try:
        buyer_phone = int(buyer_phone_str) if buyer_phone_str else None
    except (ValueError, TypeError):
        buyer_phone = None

    for event_id in choose_schedule_event_ids:
        ticket = await db_postgres.create_ticket(
            context.session,
            base_ticket_id=chose_base_ticket.base_ticket_id,
            price=chose_price,
            schedule_event_id=event_id,
            status=ticket_status,
            promo_id=promo_id,
            source=TicketSource.BOT,
            email=buyer_email,
            phone=buyer_phone,
        )
        ticket_ids.append(ticket.id)

    reserve_user_data['ticket_ids'] = ticket_ids
    return ticket_ids


async def check_and_set_privilege(session, ticket_id, ticket=None):
    if not ticket:
        ticket = await db_postgres.get_ticket(session, ticket_id)
    if not ticket or ticket.status != TicketStatus.APPROVED:
        return

    base_ticket = await db_postgres.get_base_ticket(session, ticket.base_ticket_id)
    if not base_ticket:
        return

    # Проверка по промокоду (если есть промокод, требующий верификации)
    is_privilege_by_promo = False
    if ticket.promo_id:
        promotion = await db_postgres.get_promotion(session, ticket.promo_id)
        if promotion and promotion.requires_verification:
            is_privilege_by_promo = True

    if is_privilege_by_promo:
        user = ticket.user
        if not isinstance(user, list):
            users = [user]
        else:
            users = user

        for u in users:
            if u and not u.is_privilege:
                await db_postgres.update_user(session, u.user_id, is_privilege=True)
                utl_ticket_logger.info(
                    f"User {u.user_id} status updated to privilege "
                    f"because of ticket {ticket_id}"
                )
            elif not u:
                raise AttributeError("'NoneType' object has no attribute 'is_privilege'")


async def cancel_ticket_db_when_end_handler(update, context, text):
    reserve_user_data = context.user_data['reserve_user_data']
    ticket_ids = reserve_user_data['ticket_ids']

    for ticket_id in ticket_ids:
        await db_postgres.update_ticket(
            context.session, ticket_id, status=TicketStatus.CANCELED)

    await context.bot.send_message(
        text=text,
        chat_id=update.effective_chat.id,
    )
    await clean_context_on_end_handler(utl_ticket_logger, context)


async def parse_and_create_custom_ticket(
        context: 'ContextTypes.DEFAULT_TYPE',
        text_input: str,
) -> 'tuple[BaseTicket | None, str | None]':
    """Парсит три числа (дети, взрослые, стоимость) и создаёт кастомный базовый билет.

    Возвращает (custom_ticket, None) при успехе или (None, error_text) при ошибке формата.
    """
    parts = text_input.strip().split()
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None, ('<b>Неверный формат!</b><br><br>'
                      'Введите три числа через пробел: '
                      '<code>кол-во детей</code> <code>кол-во взрослых</code> <code>стоимость</code><br>'
                      'Например: <code>8 1 15000</code>')

    qty_child = int(parts[0])
    qty_adult = int(parts[1])
    cost = int(parts[2])

    custom_ticket = await db_postgres.get_or_create_custom_base_ticket(
        context.session,
        quality_of_children=qty_child,
        quality_of_adult=qty_adult,
        cost=cost
    )
    return custom_ticket, None


def apply_custom_ticket_to_reserve(
        context: 'ContextTypes.DEFAULT_TYPE',
        custom_ticket: 'BaseTicket',
        cost: int,
) -> None:
    """Применяет кастомный билет к reserve_user_data (цена, base_ticket_id, schedule_event_ids)."""
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    reserve_user_data['chose_price'] = cost
    reserve_user_data['chose_base_ticket_id'] = custom_ticket.base_ticket_id
    reserve_user_data['choose_schedule_event_ids'] = [schedule_event_id]

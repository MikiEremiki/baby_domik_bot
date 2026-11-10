"""Buyer card and buyer tickets for /tickets_admin."""
from __future__ import annotations

from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db import db_postgres
from db.models import User, Ticket, Person
from utilities.utl_func import (
    set_back_context, create_str_info_by_schedule_event_id,
)
from utilities.utl_kbd import add_btn_back_and_cancel
from sulguk import transform_html

from .constants import BUYER_CARD, BUYER_TICKETS, MENU, TICKET_CARD
from .ticket_list import show_user_tickets


def _get_thread_id(update: Update) -> int | None:
    """Извлекает message_thread_id из update для отправки в тему форума."""
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.message_thread_id
    if update.effective_message:
        return update.effective_message.message_thread_id
    return None


async def show_buyer_card(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
) -> int:
    """Карточка покупателя билета — формат как в update_ticket."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        await update.effective_chat.send_message(
            'Билет не найден.', message_thread_id=_get_thread_id(update))
        return MENU

    # Мероприятие — через стандартный хелпер
    text_select_event = await create_str_info_by_schedule_event_id(
        context, ticket.schedule_event_id)

    # Базовый билет (вариант бронирования)
    base_ticket = await db_postgres.get_base_ticket(context.session, ticket.base_ticket_id)
    base_name = base_ticket.name if base_ticket else '—'
    price = int(ticket.price) if ticket.price else ''

    # Участники — сначала взрослые, потом дети
    people_lines: list[str] = []
    for person in ticket.people:
        if person.age_type.value == 'взрослый':
            phone = person.adult.phone if person.adult else None
            if phone:
                people_lines.append(f'{person.name}<br>+7{phone}')
            else:
                people_lines.append(person.name)
    for person in ticket.people:
        if person.age_type.value != 'взрослый':
            age = person.child.age if person.child else None
            if age is not None:
                people_lines.append(f'{person.name} {age}')
            else:
                people_lines.append(person.name)

    people_str = '<br>'.join(people_lines)

    text = f'<b>Номер билета <code>{ticket_id}</code></b><br><br>'
    text += f'{text_select_event}<br>Вариант бронирования:<br>'
    text += f'{base_name} {price}руб<br>'
    text += f'Статус: {ticket.status.value}<br><br>'
    text += 'На кого оформлен:<br>'
    text += people_str

    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton('Билеты покупателя', callback_data=f'ta:buyer_tickets:{ticket_id}')],
        add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='TICKET_CARD',
            add_back_btn=True,
        ),
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    thread_id = _get_thread_id(update)
    res = transform_html(text)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=res.text, entities=res.entities,
                reply_markup=reply_markup, parse_mode=None)
        except BadRequest:
            await update.effective_chat.send_message(
                text=res.text, entities=res.entities,
                reply_markup=reply_markup, parse_mode=None,
                message_thread_id=thread_id)
    else:
        await update.effective_chat.send_message(
            text=res.text, entities=res.entities,
            reply_markup=reply_markup, parse_mode=None,
            message_thread_id=thread_id)

    await set_back_context(context, BUYER_CARD, res.text, reply_markup)
    context.user_data['STATE'] = BUYER_CARD
    return BUYER_CARD


async def show_buyer_tickets(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
) -> int:
    """Все билеты связанного пользователя."""
    result = await context.session.execute(
        select(Ticket)
        .options(
            selectinload(Ticket.people).selectinload(Person.adult),
            selectinload(Ticket.people).selectinload(Person.child),
            selectinload(Ticket.user).selectinload(User.tickets),
        )
        .where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        await update.effective_chat.send_message(
            'Билет не найден.', message_thread_id=_get_thread_id(update))
        return MENU

    if not ticket.user:
        text = 'Билет не привязан к Telegram-профилю'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='TICKET_CARD',
            add_back_btn=True,
        )
        reply_markup = InlineKeyboardMarkup([keyboard])
        res = transform_html(text)
        thread_id = _get_thread_id(update)
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=res.text, entities=res.entities,
                    reply_markup=reply_markup, parse_mode=None)
            except BadRequest:
                await update.effective_chat.send_message(
                    text=res.text, entities=res.entities,
                    reply_markup=reply_markup, parse_mode=None,
                    message_thread_id=thread_id)
        else:
            await update.effective_chat.send_message(
                text=res.text, entities=res.entities,
                reply_markup=reply_markup, parse_mode=None,
                message_thread_id=thread_id)
        await set_back_context(context, BUYER_TICKETS, res.text, reply_markup)
        context.user_data['STATE'] = BUYER_TICKETS
        return BUYER_TICKETS

    return await show_user_tickets(update, context, ticket.user)

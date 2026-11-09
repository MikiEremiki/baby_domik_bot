"""Text input handlers for /tickets_admin."""
from __future__ import annotations

from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from db import db_postgres
from db.models import User, Ticket, Person
from utilities.utl_func import set_back_context
from utilities.utl_text import (
    extract_phone_number_from_text, check_phone_number, check_email,
)
from utilities.utl_kbd import add_btn_back_and_cancel
from db.db_googlesheets import update_free_seat

from .constants import (
    SEARCH_USER, SEARCH_TICKET_ID, SEARCH_CONTACT_PHONE, SEARCH_CONTACT_EMAIL,
    INPUT_EMAIL, INPUT_PHONE, INPUT_NOTES, INPUT_BASE_TICKET, MENU, TICKET_CARD,
)
from .display import show_ticket_card
from .ticket_list import show_compact_ticket_list


async def handle_search_user(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Поиск пользователя по user_id или @username."""
    text = update.effective_message.text.strip()
    clean = text.lstrip('@')

    user = None
    if clean.isdigit():
        stmt = select(User).options(
            selectinload(User.tickets)
        ).where(User.user_id == int(clean))
        result = await context.session.execute(stmt)
        user = result.scalar_one_or_none()
    else:
        stmt = select(User).options(
            selectinload(User.tickets)
        ).where(User.username == clean)
        result = await context.session.execute(stmt)
        user = result.scalar_one_or_none()

    if not user:
        text_err = 'Пользователь не найден. Попробуйте ещё раз:'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            add_back_btn=False,
        )
        await update.effective_chat.send_message(
            text=text_err, reply_markup=InlineKeyboardMarkup([keyboard]))
        return SEARCH_USER

    return await show_compact_ticket_list(update, context, user.tickets, f'Билеты: {clean}')


async def handle_search_ticket_id(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Поиск билета по ID."""
    try:
        ticket_id = int(update.effective_message.text.strip())
    except ValueError:
        text_err = 'Введите числовой ID билета:'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            add_back_btn=False,
        )
        await update.effective_chat.send_message(
            text=text_err, reply_markup=InlineKeyboardMarkup([keyboard]))
        return SEARCH_TICKET_ID

    return await show_ticket_card(update, context, ticket_id, edit=False)


async def handle_search_contact_phone(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Ввод телефона для поиска контактов."""
    text = update.effective_message.text.strip()
    phone = None
    if text:
        phone = extract_phone_number_from_text(text)
        if not check_phone_number(phone):
            await update.effective_chat.send_message(
                'Неверный формат телефона (10 цифр, начинается с 9).\n\nВведите телефон для поиска (или оставьте пустым):')
            return SEARCH_CONTACT_PHONE
    context.user_data['tickets_admin']['search_contact_phone'] = phone
    # Переходим к вводу email
    text = 'Введите email для поиска (или оставьте пустым):'
    keyboard = add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='MENU',
        add_back_btn=True,
    )
    reply_markup = InlineKeyboardMarkup([keyboard])
    await update.effective_chat.send_message(
        text=text, reply_markup=reply_markup)
    await set_back_context(context, SEARCH_CONTACT_EMAIL, text, reply_markup)
    context.user_data['STATE'] = SEARCH_CONTACT_EMAIL
    return SEARCH_CONTACT_EMAIL


async def handle_search_contact_email(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Ввод email для поиска контактов и выполнение поиска."""
    text = update.effective_message.text.strip()
    email = None
    if text:
        if not check_email(text):
            await update.effective_chat.send_message(
                'Неверный формат email.\n\nВведите email для поиска (или оставьте пустым):')
            return SEARCH_CONTACT_EMAIL
        email = text

    phone = context.user_data['tickets_admin'].get('search_contact_phone')
    if not phone and not email:
        await update.effective_chat.send_message(
            'Укажите хотя бы один параметр поиска.\n\nВведите телефон (10 цифр без +7) и/или email:')
        context.user_data['STATE'] = SEARCH_CONTACT_PHONE
        return SEARCH_CONTACT_PHONE

    # Поиск билетов по phone и/или email
    conditions = []
    if phone:
        conditions.append(Ticket.phone == int(phone))
    if email:
        conditions.append(Ticket.email == email)
    stmt = select(Ticket).where(or_(*conditions))
    result = await context.session.execute(stmt)
    tickets = list(result.scalars().all())

    if not tickets:
        text_err = 'Билеты не найдены по указанным контактам.'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='MENU',
            add_back_btn=True,
        )
        await update.effective_chat.send_message(
            text=text_err, reply_markup=InlineKeyboardMarkup([keyboard]))
        return MENU

    search_desc = []
    if phone:
        search_desc.append(f'телефон +7{phone}')
    if email:
        search_desc.append(f'email {email}')
    return await show_compact_ticket_list(update, context, tickets, f'Поиск: {", ".join(search_desc)}')


async def handle_email_input(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Ввод нового email."""
    email = update.effective_message.text.strip()
    if not check_email(email):
        await update.effective_chat.send_message('Неверный формат email. Попробуйте ещё раз:')
        return INPUT_EMAIL

    ticket_id = context.user_data['tickets_admin'].get('ticket_id')
    await db_postgres.update_ticket(context.session, ticket_id, email=email)
    await update.effective_chat.send_message('Email обновлён.')
    return await show_ticket_card(update, context, ticket_id)


async def handle_phone_input(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Ввод нового телефона."""
    phone = update.effective_message.text.strip()
    phone = extract_phone_number_from_text(phone)
    if not check_phone_number(phone):
        await update.effective_chat.send_message(
            'Введите российский номер (10 цифр, начинается с 9).')
        return INPUT_PHONE

    ticket_id = context.user_data['tickets_admin'].get('ticket_id')
    await db_postgres.update_ticket(context.session, ticket_id, phone=int(phone))
    await update.effective_chat.send_message('Телефон обновлён.')
    return await show_ticket_card(update, context, ticket_id)


async def handle_notes_input(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Ввод примечания — дополнить или перезаписать."""
    new_text = update.effective_message.text.strip()
    ticket_id = context.user_data['tickets_admin'].get('ticket_id')
    mode = context.user_data['tickets_admin'].get('notes_mode', 'replace')

    if mode == 'append':
        # Дополняем существующее примечание
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        current = ticket.notes or ''
        if current:
            notes = f'{current}\n{new_text}'
        else:
            notes = new_text
    else:
        # Перезаписываем
        notes = new_text

    await db_postgres.update_ticket(context.session, ticket_id, notes=notes)
    await update.effective_chat.send_message('Примечание обновлено.')
    return await show_ticket_card(update, context, ticket_id)


async def handle_base_ticket_input(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Смена типа (базового) билета."""
    try:
        new_base_ticket_id = int(update.effective_message.text.strip())
    except ValueError:
        await update.effective_chat.send_message('Введите номер базового билета:')
        return INPUT_BASE_TICKET

    ticket_id = context.user_data['tickets_admin'].get('ticket_id')
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    new_base = await db_postgres.get_base_ticket(context.session, new_base_ticket_id)
    if not new_base:
        await update.effective_chat.send_message('Базовый билет не найден.')
        return INPUT_BASE_TICKET

    await db_postgres.update_ticket(context.session, ticket_id, base_ticket_id=new_base_ticket_id)
    if ticket.schedule_event_id:
        await update_free_seat(context, ticket.schedule_event_id)
    await update.effective_chat.send_message('Тип билета обновлён.')
    return await show_ticket_card(update, context, ticket_id)

"""Conversation handler for /tickets_admin — админское меню управления билетом."""
from __future__ import annotations

import logging
from typing import List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ConversationHandler, CommandHandler, ContextTypes, MessageHandler,
    CallbackQueryHandler,
)
from telegram.error import BadRequest

from db import db_postgres
from db.enum import TicketStatus
from handlers import init_conv_hl_dialog
from utilities.utl_func import get_formatted_date_and_time_of_event
from utilities.utl_kbd import add_btn_back_and_cancel
from utilities.utl_text import (
    extract_phone_number_from_text, check_phone_number, check_email,
)
from utilities.utl_ticket import format_ticket_contacts
from conv_hl import (
    cancel_callback_handler,
    F_text_and_no_command, common_fallbacks,
)
from api.gspread_pub import publish_update_ticket
from api.googlesheets import update_ticket_in_gspread
from db.db_googlesheets import (
    decrease_nonconfirm_seat,
    increase_free_seat,
    increase_free_and_decrease_nonconfirm_seat,
    update_free_seat,
)
from settings.settings import COMMAND_DICT

tickets_admin_logger = logging.getLogger('bot.tickets_admin_conv')

# ── States ──────────────────────────────────────────────────────────────────

MENU = 'MENU'               # стартовое меню: «По пользователю» / «По билету»
SEARCH_USER = 'SEARCH_USER' # ожидание user_id / @username
TICKET_LIST = 'TICKET_LIST' # список билетов пользователя
TICKET_CARD = 'TICKET_CARD' # карточка билета с кнопками действий
STATUS_PICK = 'STATUS_PICK' # выбор статуса кнопками
INPUT_EMAIL = 'INPUT_EMAIL' # ввод нового email
INPUT_PHONE = 'INPUT_PHONE' # ввод нового телефона
INPUT_NOTES = 'INPUT_NOTES' # ввод примечания
INPUT_BASE_TICKET = 'INPUT_BASE_TICKET'  # смена типа билета
BUYER_CARD = 'BUYER_CARD'   # карточка покупателя
BUYER_TICKETS = 'BUYER_TICKETS'  # билеты покупателя
SEARCH_TICKET_ID = 'SEARCH_TICKET_ID'  # ожидание ID билета (из меню)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _ticket_card_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления в карточке билета."""
    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton('Статус', callback_data=f'ta:status:{ticket_id}')],
        [InlineKeyboardButton('Email', callback_data=f'ta:email:{ticket_id}')],
        [InlineKeyboardButton('Телефон', callback_data=f'ta:phone:{ticket_id}')],
        [InlineKeyboardButton('Примечание', callback_data=f'ta:notes:{ticket_id}')],
        [InlineKeyboardButton('Базовый', callback_data=f'ta:base:{ticket_id}')],
        [InlineKeyboardButton('Покупатель', callback_data=f'ta:buyer:{ticket_id}')],
        [InlineKeyboardButton('Билеты покупателя', callback_data=f'ta:buyer_tickets:{ticket_id}')],
        add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='MENU',
            add_back_btn=True,
        ),
    ]
    return InlineKeyboardMarkup(keyboard)


def _status_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора статуса."""
    rows: List[List[InlineKeyboardButton]] = []
    current_row: List[InlineKeyboardButton] = []
    for status in TicketStatus:
        current_row.append(InlineKeyboardButton(
            status.value, callback_data=f'ta:set_status:{status.value}'))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append(add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='TICKET_CARD',
        add_back_btn=True,
    ))
    return InlineKeyboardMarkup(rows)


def _email_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Кнопки для редактирования email."""
    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton('Очистить', callback_data=f'ta:clear_email:{ticket_id}')],
        add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='TICKET_CARD',
            add_back_btn=True,
        ),
    ]
    return InlineKeyboardMarkup(keyboard)


async def _format_ticket_card(session, ticket) -> str:
    """Формирует текст карточки билета."""
    schedule_event = await db_postgres.get_schedule_event(
        session, ticket.schedule_event_id)
    if schedule_event:
        theater_event = await db_postgres.get_theater_event(
            session, schedule_event.theater_event_id)
        date_event, time_event = await get_formatted_date_and_time_of_event(
            schedule_event)
        event_line = f'{theater_event.name if theater_event else "—"}\n{date_event} в {time_event}'
    else:
        event_line = '—'

    base_ticket = await db_postgres.get_base_ticket(session, ticket.base_ticket_id)
    contacts_block = format_ticket_contacts(ticket)

    child_lines = []
    for person in ticket.people:
        if hasattr(person, 'child') and person.child is not None and hasattr(person.child, 'age'):
            child_lines.append(f'{person.name} {person.child.age}')

    text = (
        f'<b>Билет #{ticket.id}</b>\n\n'
        f'{event_line}\n\n'
        f'Тип: {base_ticket.name if base_ticket else "—"}\n'
        f'Стоимость: {int(ticket.price)} руб\n'
        f'Статус: {ticket.status.value}\n'
        f'Примечание: {ticket.notes or "—"}\n\n'
        f'{contacts_block}'
    )
    if child_lines:
        text += f'\nДети: {" | ".join(child_lines)}'

    if ticket.user:
        text += f'\n\nПривязан к профилю: {ticket.user.user_id}'
    else:
        text += '\n\nБилет не привязан к Telegram-профилю'

    return text


async def _show_ticket_card(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
    edit: bool = True,
) -> int:
    """Показывает карточку билета с кнопками управления."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        await update.effective_chat.send_message('Такого билета нет.')
        return MENU

    context.user_data['tickets_admin'] = context.user_data.setdefault(
        'tickets_admin', {})
    context.user_data['tickets_admin']['ticket_id'] = ticket_id

    text = await _format_ticket_card(context.session, ticket)
    keyboard = _ticket_card_keyboard(ticket_id)

    if update.callback_query and edit:
        try:
            await update.callback_query.edit_message_text(
                text=text, reply_markup=keyboard, parse_mode='HTML')
        except BadRequest:
            await update.effective_chat.send_message(
                text=text, reply_markup=keyboard, parse_mode='HTML')
    else:
        await update.effective_chat.send_message(
            text=text, reply_markup=keyboard, parse_mode='HTML')

    context.user_data['STATE'] = TICKET_CARD
    return TICKET_CARD


# ── Entry point ─────────────────────────────────────────────────────────────

async def enter_tickets_admin(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Стартовая точка /tickets_admin."""
    await init_conv_hl_dialog(update, context)
    context.user_data['postfix_for_cancel'] = 'tickets_admin'
    context.user_data['tickets_admin'] = {}

    # Прямой вызов: /tickets_admin <id>
    if context.args:
        try:
            ticket_id = int(context.args[0])
            return await _show_ticket_card(update, context, ticket_id, edit=False)
        except ValueError:
            pass

    text = '<b>Меню управления билетом</b>\n\nВыберите способ поиска:'
    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton('По пользователю', callback_data='ta:search_user')],
        [InlineKeyboardButton('По билету', callback_data='ta:search_ticket')],
        add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            add_back_btn=False,
        ),
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_chat.send_message(
        text=text, reply_markup=reply_markup, parse_mode='HTML')
    context.user_data['STATE'] = MENU
    return MENU


# ── Menu callbacks ──────────────────────────────────────────────────────────

async def tickets_admin_callback(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Обработчик callback-кнопок меню /tickets_admin."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(':')
    action = parts[1] if len(parts) > 1 else ''

    # ── Стартовое меню ──
    if action == 'search_user':
        text = 'Введите user_id или @username пользователя:'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            add_back_btn=False,
        )
        await query.edit_message_text(
            text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        context.user_data['STATE'] = SEARCH_USER
        return SEARCH_USER

    if action == 'search_ticket':
        text = 'Введите ID билета:'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            add_back_btn=False,
        )
        await query.edit_message_text(
            text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        context.user_data['STATE'] = SEARCH_TICKET_ID
        return SEARCH_TICKET_ID

    # ── Карточка билета: переход к действию ──
    if action == 'status':
        ticket_id = int(parts[2])
        text = 'Выберите новый статус:'
        await query.edit_message_text(
            text=text, reply_markup=_status_keyboard(), parse_mode='HTML')
        context.user_data['STATE'] = STATUS_PICK
        return STATUS_PICK

    if action == 'email':
        ticket_id = int(parts[2])
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        current = ticket.email if ticket else '—'
        text = f'Текущий email: {current}\n\nВведите новый email:'
        await query.edit_message_text(
            text=text, reply_markup=_email_keyboard(ticket_id), parse_mode='HTML')
        context.user_data['STATE'] = INPUT_EMAIL
        return INPUT_EMAIL

    if action == 'phone':
        ticket_id = int(parts[2])
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        current = f'+7{ticket.phone}' if ticket and ticket.phone else '—'
        text = f'Текущий телефон: {current}\n\nВведите новый телефон (10 цифр без +7):'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='TICKET_CARD',
            add_back_btn=True,
        )
        await query.edit_message_text(
            text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        context.user_data['STATE'] = INPUT_PHONE
        return INPUT_PHONE

    if action == 'notes':
        ticket_id = int(parts[2])
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        current = ticket.notes or '—'
        text = f'Текущее примечание: {current}\n\nВведите новое примечание:'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='TICKET_CARD',
            add_back_btn=True,
        )
        await query.edit_message_text(
            text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        context.user_data['STATE'] = INPUT_NOTES
        return INPUT_NOTES

    if action == 'base':
        ticket_id = int(parts[2])
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        base_ticket = await db_postgres.get_base_ticket(
            context.session, ticket.base_ticket_id) if ticket else None
        current = f'{base_ticket.base_ticket_id} ({base_ticket.name})' if base_ticket else '—'
        text = f'Текущий базовый билет: {current}\n\nВведите номер нового базового билета:'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='TICKET_CARD',
            add_back_btn=True,
        )
        await query.edit_message_text(
            text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        context.user_data['STATE'] = INPUT_BASE_TICKET
        return INPUT_BASE_TICKET

    if action == 'buyer':
        ticket_id = int(parts[2])
        return await _show_buyer_card(update, context, ticket_id)

    if action == 'buyer_tickets':
        ticket_id = int(parts[2])
        return await _show_buyer_tickets(update, context, ticket_id)

    # ── Установка статуса ──
    if action == 'set_status':
        status_value = ':'.join(parts[2:])  # восстанавливаем значение статуса
        ticket_id = context.user_data['tickets_admin'].get('ticket_id')
        if not ticket_id:
            await query.answer('Ошибка: билет не выбран', show_alert=True)
            return TICKET_CARD
        return await _set_ticket_status(query, context, ticket_id, status_value)

    # ── Очистка email ──
    if action == 'clear_email':
        ticket_id = int(parts[2])
        await db_postgres.update_ticket(context.session, ticket_id, email=None)
        await query.answer('Email очищен')
        return await _show_ticket_card(update, context, ticket_id)

    return context.user_data.get('STATE', MENU)


# ── Text input handlers ─────────────────────────────────────────────────────

async def handle_search_user(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Поиск пользователя по user_id или @username."""
    text = update.effective_message.text.strip()
    # Убираем @ если есть
    clean = text.lstrip('@')

    user = None
    if clean.isdigit():
        user = await db_postgres.get_user(context.session, int(clean))
    else:
        from sqlalchemy import select
        from db.models import User
        stmt = select(User).where(User.username == clean)
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

    return await _show_user_tickets(update, context, user)


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

    return await _show_ticket_card(update, context, ticket_id)


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
    return await _show_ticket_card(update, context, ticket_id)


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
    return await _show_ticket_card(update, context, ticket_id)


async def handle_notes_input(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Ввод нового примечания."""
    notes = update.effective_message.text.strip()
    ticket_id = context.user_data['tickets_admin'].get('ticket_id')
    await db_postgres.update_ticket(context.session, ticket_id, notes=notes)
    await update.effective_chat.send_message('Примечание обновлено.')
    return await _show_ticket_card(update, context, ticket_id)


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
    return await _show_ticket_card(update, context, ticket_id)


# ── Status change ───────────────────────────────────────────────────────────

async def _set_ticket_status(
    query,
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
    status_value: str,
) -> int:
    """Устанавливает новый статус билета с синхронизацией мест и Google Sheets."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        await query.answer('Билет не найден', show_alert=True)
        return TICKET_CARD

    try:
        new_status = TicketStatus(status_value)
    except ValueError:
        await query.answer('Неверный статус', show_alert=True)
        return TICKET_CARD

    old_status = ticket.status
    schedule_event_id = ticket.schedule_event_id

    # Синхронизация свободных мест
    if old_status == TicketStatus.CREATED:
        if new_status in (TicketStatus.CANCELED, TicketStatus.APPROVED, TicketStatus.REJECTED):
            if new_status == TicketStatus.APPROVED:
                await decrease_nonconfirm_seat(context, schedule_event_id)
            else:
                await increase_free_and_decrease_nonconfirm_seat(context, schedule_event_id)
    elif old_status == TicketStatus.PAID:
        if new_status == TicketStatus.APPROVED:
            await decrease_nonconfirm_seat(context, schedule_event_id)
        elif new_status in (TicketStatus.REJECTED, TicketStatus.REFUNDED):
            await increase_free_and_decrease_nonconfirm_seat(context, schedule_event_id)
    elif old_status in (TicketStatus.APPROVED, TicketStatus.RESERVED):
        if new_status in (TicketStatus.REJECTED, TicketStatus.REFUNDED,
                          TicketStatus.TRANSFERRED, TicketStatus.MIGRATED,
                          TicketStatus.CANCELED):
            await increase_free_seat(context, schedule_event_id)

    # Обновление в БД
    await db_postgres.update_ticket(context.session, ticket_id, status=new_status)

    # Google Sheets
    sheet_id_domik = context.config.sheets.sheet_id_domik
    try:
        await publish_update_ticket(sheet_id_domik, ticket_id, str(new_status.value))
    except Exception as e:
        tickets_admin_logger.exception(f'Gspread publish failed, fallback: {e}')
        await update_ticket_in_gspread(sheet_id_domik, ticket_id, new_status.value)

    await query.answer(f'Статус: {new_status.value}')
    return await _show_ticket_card(query, context, ticket_id)


# ── Buyer card ──────────────────────────────────────────────────────────────

async def _show_buyer_card(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
) -> int:
    """Карточка покупателя билета."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        await update.effective_chat.send_message('Билет не найден.')
        return MENU

    contacts_block = format_ticket_contacts(ticket, update.effective_user.full_name)

    child_lines = []
    for person in ticket.people:
        if hasattr(person, 'child') and person.child is not None and hasattr(person.child, 'age'):
            child_lines.append(f'{person.name} {person.child.age}')

    text = '<b>Покупатель</b>\n\n'
    text += contacts_block
    if child_lines:
        text += f'\nДети: {" | ".join(child_lines)}'

    keyboard = add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='TICKET_CARD',
        add_back_btn=True,
    )
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        except BadRequest:
            await update.effective_chat.send_message(
                text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
    else:
        await update.effective_chat.send_message(
            text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')

    context.user_data['STATE'] = BUYER_CARD
    return BUYER_CARD


# ── Buyer tickets ───────────────────────────────────────────────────────────

async def _show_buyer_tickets(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
) -> int:
    """Все билеты связанного пользователя."""
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        await update.effective_chat.send_message('Билет не найден.')
        return MENU

    if not ticket.user:
        text = 'Билет не привязан к Telegram-профилю'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='TICKET_CARD',
            add_back_btn=True,
        )
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
            except BadRequest:
                await update.effective_chat.send_message(
                    text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        else:
            await update.effective_chat.send_message(
                text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        context.user_data['STATE'] = BUYER_TICKETS
        return BUYER_TICKETS

    return await _show_user_tickets(update, context, ticket.user)


async def _show_user_tickets(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    user,
) -> int:
    """Список билетов пользователя с кнопками для перехода к карточке."""
    tickets = user.tickets if user else []
    if not tickets:
        text = f'У пользователя {user.user_id if user else "—"} нет билетов.'
        keyboard = add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            postfix_for_back='MENU',
            add_back_btn=True,
        )
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
            except BadRequest:
                await update.effective_chat.send_message(
                    text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        else:
            await update.effective_chat.send_message(
                text=text, reply_markup=InlineKeyboardMarkup([keyboard]), parse_mode='HTML')
        context.user_data['STATE'] = TICKET_LIST
        return TICKET_LIST

    username_part = f'@{user.username} ' if user.username else ''
    display = username_part + (user.username or str(user.user_id))
    text = f'<b>Билеты: {display}</b>\n\n'

    keyboard: List[List[InlineKeyboardButton]] = []
    for t in tickets:
        btn_text = f'#{t.id} — {t.status.value}'
        keyboard.append([InlineKeyboardButton(
            btn_text, callback_data=f'ta:ticket:{t.id}')])
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel='tickets_admin',
        postfix_for_back='MENU',
        add_back_btn=True,
    ))

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        except BadRequest:
            await update.effective_chat.send_message(
                text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.effective_chat.send_message(
            text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    context.user_data['STATE'] = TICKET_LIST
    return TICKET_LIST


# ── Back handler for tickets_admin ──────────────────────────────────────────

async def tickets_admin_back(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Назад в tickets_admin — возвращает в карточку билета или меню."""
    query = update.callback_query
    await query.answer()
    target = query.data.split('-')[1] if '-' in query.data else 'MENU'

    if target == 'MENU':
        return await enter_tickets_admin(update, context)
    elif target == 'TICKET_CARD':
        ticket_id = context.user_data['tickets_admin'].get('ticket_id')
        if ticket_id:
            return await _show_ticket_card(update, context, ticket_id)
        return await enter_tickets_admin(update, context)
    return context.user_data.get('STATE', MENU)


# ── State machine ───────────────────────────────────────────────────────────

states = {
    MENU: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
    ],
    SEARCH_USER: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_search_user),
    ],
    SEARCH_TICKET_ID: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_search_ticket_id),
    ],
    TICKET_LIST: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
    ],
    TICKET_CARD: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
    ],
    STATUS_PICK: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
    ],
    INPUT_EMAIL: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
        MessageHandler(F_text_and_no_command, handle_email_input),
    ],
    INPUT_PHONE: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_phone_input),
    ],
    INPUT_NOTES: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_notes_input),
    ],
    INPUT_BASE_TICKET: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_base_ticket_input),
    ],
    BUYER_CARD: [
        cancel_callback_handler,
    ],
    BUYER_TICKETS: [
        cancel_callback_handler,
    ],
}

# Кнопка «Назад» в tickets_admin
states[MENU].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[SEARCH_USER].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[SEARCH_TICKET_ID].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[TICKET_LIST].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[TICKET_CARD].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[STATUS_PICK].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[INPUT_EMAIL].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[INPUT_PHONE].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[INPUT_NOTES].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[INPUT_BASE_TICKET].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[BUYER_CARD].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))
states[BUYER_TICKETS].append(CallbackQueryHandler(tickets_admin_back, pattern='^Назад'))


tickets_admin_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['TICKETS_ADMIN'][0], enter_tickets_admin),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='tickets_admin',
    persistent=True,
    allow_reentry=True,
)

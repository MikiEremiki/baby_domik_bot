import logging
from typing import List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from db import db_postgres
from db.enum import AgeType, TicketStatus
from handlers import init_conv_hl_dialog
from handlers.sub_hl import request_phone_number
from utilities.utl_func import (
    create_str_info_by_schedule_event_id, extract_command
)
from utilities.utl_text import extract_phone_number_from_text, check_phone_number

profile_logger = logging.getLogger('bot.profile')

MENU = 1
ADD_TYPE = 2
ADD_ADULT_NAME = 3
ADD_ADULT_PHONE = 4
ADD_CHILD_NAME = 5
ADD_CHILD_AGE = 6
PERSON_MENU = 7
EDIT_NAME = 8
EDIT_ADULT_PHONE = 9
EDIT_CHILD_AGE = 10
CONFIRM_DELETE = 11


adult_button = InlineKeyboardButton('➕ Взрослый', callback_data='add_adult')
child_button = InlineKeyboardButton('➕ Ребенок', callback_data='add_child')
back_button = InlineKeyboardButton('⬅️ Назад', callback_data='profile:back')
cancel_button = InlineKeyboardButton('❌ Отмена', callback_data='Отменить-settings')

# Pagination size for tickets list
PAGE_SIZE_TICKETS = 5


def _profile_keyboard(persons) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton('🎟 Мои билеты', callback_data='profile:tickets')]]
    for p in persons:
        age_type = 'adult' if p.age_type == AgeType.adult else 'child'
        if age_type == 'adult':
            phone = getattr(getattr(p, 'adult', None), 'phone', None)
            caption = f"👤 {p.name or ''}" + (f" +7{phone}" if phone else '')
        else:
            age = getattr(getattr(p, 'child', None), 'age', None)
            age_str = f" {age}" if age is not None else ''
            caption = f"🧒 {p.name or ''}{age_str}"
        keyboard.append([
            InlineKeyboardButton(
                caption, callback_data=f'profile:menu:{p.id}:{age_type}')
        ])
    keyboard.append(
        [adult_button, child_button])
    keyboard.append(
        [cancel_button])
    return InlineKeyboardMarkup(keyboard)


def _person_menu_keyboard(person_id: int,
                          age_type: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(
            '✏️ Имя', callback_data=f'profile:edit_name:{person_id}:{age_type}')],
    ]
    if age_type == 'adult':
        keyboard.append([InlineKeyboardButton(
            '📞 Телефон', callback_data=f'profile:edit_phone:{person_id}:{age_type}')])
    else:
        keyboard.append([InlineKeyboardButton(
            '🎂 Возраст', callback_data=f'profile:edit_age:{person_id}:{age_type}')])
    keyboard.append([InlineKeyboardButton(
        '🗑 Удалить', callback_data=f'profile:del:{person_id}:{age_type}')])
    keyboard.append([back_button])
    return InlineKeyboardMarkup(keyboard)


async def start_profile(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    await init_conv_hl_dialog(update, context)
    try:
        await update.effective_chat.send_action(ChatAction.TYPING)
    except Exception as e:
        profile_logger.debug(e)

    if (context.args and
            context.config.bot.developer_chat_id == update.effective_chat.id):
        user_id = context.args[0]
        context.user_data['common_data']['profile_user_id'] = user_id
    else:
        user_id = update.effective_user.id
    user = await db_postgres.get_user(context.session, user_id)
    if not user:
        await db_postgres.create_user(
            context.session,
            user_id,
            update.effective_chat.id,
            username=update.effective_user.username,
        )
        user = await db_postgres.get_user(context.session, user_id)
    persons = user.people if user else []

    adults: List[str] = []
    children: List[str] = []
    for p in persons:
        if p.age_type == AgeType.adult:
            phone = getattr(getattr(p, 'adult', None), 'phone', None)
            adults.append(
                f"{p.name or ''} +7{phone}" if phone else f"{p.name or ''}")
        else:
            age = getattr(getattr(p, 'child', None), 'age', None)
            children.append(f"{p.name or ''} {age if age is not None else ''}")

    text = '<b>Профиль пользователя</b>\n\n'
    if adults:
        text += 'Взрослые:\n' + '\n'.join(adults) + '\n\n'
    if children:
        text += 'Дети:\n' + '\n'.join(children) + '\n\n'
    if not (adults or children):
        text += 'Пока нет добавленных людей.\n\n'
    text += 'Выберите участника для изменения или удаления, либо добавьте нового:'

    reply_markup = _profile_keyboard(persons)
    # Edit message if invoked via callback, else send new message
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=text,
                                                          reply_markup=reply_markup)
        except Exception as e:
            profile_logger.debug(e)
            await update.effective_chat.send_message(text=text,
                                                     reply_markup=reply_markup)
    else:
        await update.effective_chat.send_message(text=text,
                                                 reply_markup=reply_markup)
    context.user_data['STATE'] = MENU
    return MENU


async def select_add_type(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == 'add_adult':
        await query.edit_message_text('Введите имя взрослого:')
        context.user_data['STATE'] = ADD_ADULT_NAME
        return ADD_ADULT_NAME
    if data == 'add_child':
        await query.edit_message_text('Введите имя ребенка:')
        context.user_data['STATE'] = ADD_CHILD_NAME
        return ADD_CHILD_NAME


async def add_adult_name(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text(
            'Имя не должно быть пустым. Введите имя взрослого:')
        return ADD_ADULT_NAME
    context.user_data.setdefault('profile', {})['adult_name'] = name
    await update.message.reply_text('Введите телефон (10 цифр без +7):')
    context.user_data['STATE'] = ADD_ADULT_PHONE
    return ADD_ADULT_PHONE


async def add_adult_phone(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    reserve_user_data = context.user_data['reserve_user_data']

    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        message = await request_phone_number(update, context)
        reserve_user_data['message_id'] = message.message_id
        return context.user_data['STATE']

    name = context.user_data.get('profile', {}).get('adult_name')
    user_id = update.effective_user.id
    await db_postgres.create_adult(context.session, user_id, name, phone)
    await update.message.reply_text(
        'Взрослый добавлен. Возвращаюсь в профиль...')
    return await start_profile(update, context)


async def add_child_name(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text(
            'Имя не должно быть пустым. Введите имя ребенка:')
        return ADD_CHILD_NAME
    context.user_data.setdefault('profile', {})['child_name'] = name
    await update.message.reply_text('Введите возраст ребенка (например 4.5):')
    context.user_data['STATE'] = ADD_CHILD_AGE
    return ADD_CHILD_AGE


async def add_child_age(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    text = update.message.text.replace(',', '.').strip()
    try:
        age = float(text)
    except ValueError:
        await update.message.reply_text(
            'Возраст должен быть числом, например 4 или 4.5. Повторите ввод:')
        return ADD_CHILD_AGE
    name = context.user_data.get('profile', {}).get('child_name')
    user_id = update.effective_user.id
    await db_postgres.create_child(context.session, user_id, name, age=age)
    await update.message.reply_text(
        'Ребенок добавлен. Возвращаюсь в профиль...')
    return await start_profile(update, context)


async def profile_callback(update: Update,
                           context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(':')
    action = parts[1] if len(parts) > 1 else ''
    # profile:menu:<person_id>:<age_type>
    if action == 'tickets':
        return await show_tickets(update, context)
    if action == 'menu':
        person_id = int(parts[2])
        age_type = parts[3]
        text = 'Управление участником'
        await query.edit_message_text(
            text=text,
            reply_markup=_person_menu_keyboard(person_id, age_type)
        )
        context.user_data['STATE'] = PERSON_MENU
        return PERSON_MENU
    if action == 'back':
        return await start_profile(update, context)
    if action == 'edit_name':
        person_id = int(parts[2])
        age_type = parts[3]
        context.user_data.setdefault('profile', {})['edit_person'] = {
            'person_id': person_id,
            'age_type': age_type,
        }
        await query.edit_message_text('Введите новое имя:')
        context.user_data['STATE'] = EDIT_NAME
        return EDIT_NAME
    if action == 'edit_phone':
        person_id = int(parts[2])
        context.user_data.setdefault('profile', {})['edit_person'] = {
            'person_id': person_id,
            'age_type': 'adult',
        }
        await query.edit_message_text('Введите телефон (10 цифр без +7):')
        context.user_data['STATE'] = EDIT_ADULT_PHONE
        return EDIT_ADULT_PHONE
    if action == 'edit_age':
        person_id = int(parts[2])
        context.user_data.setdefault('profile', {})['edit_person'] = {
            'person_id': person_id,
            'age_type': 'child',
        }
        await query.edit_message_text('Введите возраст ребенка (например 4.5):')
        context.user_data['STATE'] = EDIT_CHILD_AGE
        return EDIT_CHILD_AGE
    if action == 'del':
        person_id = int(parts[2])
        age_type = parts[3]
        keyboard = [
            [InlineKeyboardButton('✅ Да, удалить',
                                  callback_data=f'profile:confirm_del:{person_id}')],
            [InlineKeyboardButton('⬅️ Назад',
                                  callback_data=f'profile:menu:{person_id}:{age_type}')],
        ]
        await query.edit_message_text(
            'Вы уверены, что хотите удалить участника? Действие необратимо.',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data['STATE'] = CONFIRM_DELETE
        return CONFIRM_DELETE
    if action == 'confirm_del':
        person_id = int(parts[2])
        await db_postgres.delete_person(context.session, person_id)
        await query.edit_message_text('Удалено. Обновляю профиль...')
        return await start_profile(update, context)


async def set_new_name(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    new_name = update.message.text.strip()
    if not new_name:
        await update.message.reply_text(
            'Имя не должно быть пустым. Введите новое имя:')
        return EDIT_NAME
    edit_person = context.user_data.get('profile', {}).get('edit_person')
    if not edit_person:
        await update.message.reply_text(
            'Не удалось определить участника. Возвращаюсь в профиль.')
        return await start_profile(update, context)
    person_id = edit_person['person_id']
    await db_postgres.update_person(context.session, person_id, name=new_name)
    await update.message.reply_text('Имя обновлено. Возвращаюсь в профиль...')
    return await start_profile(update, context)


async def set_new_adult_phone(update: Update,
                              context: 'ContextTypes.DEFAULT_TYPE'):
    reserve_user_data = context.user_data['reserve_user_data']

    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        message = await request_phone_number(update, context)
        reserve_user_data['message_id'] = message.message_id
        return context.user_data['STATE']
    edit_person = context.user_data.get('profile', {}).get('edit_person')
    if not edit_person:
        await update.message.reply_text(
            'Не удалось определить участника. Возвращаюсь в профиль.')
        return await start_profile(update, context)
    person_id = edit_person['person_id']
    await db_postgres.update_adult_by_person_id(context.session, person_id,
                                                phone=phone)
    await update.message.reply_text(
        'Телефон обновлен. Возвращаюсь в профиль...')
    return await start_profile(update, context)


async def set_new_child_age(update: Update,
                            context: 'ContextTypes.DEFAULT_TYPE'):
    text = update.message.text.replace(',', '.').strip()
    try:
        age = float(text)
    except ValueError:
        await update.message.reply_text(
            'Возраст должен быть числом, например 4 или 4.5. Повторите ввод:')
        return EDIT_CHILD_AGE
    edit_person = context.user_data.get('profile', {}).get('edit_person')
    if not edit_person:
        await update.message.reply_text(
            'Не удалось определить участника. Возвращаюсь в профиль.')
        return await start_profile(update, context)
    person_id = edit_person['person_id']
    await db_postgres.update_child_by_person_id(context.session, person_id,
                                                age=age)
    await update.message.reply_text(
        'Возраст обновлен. Возвращаюсь в профиль...')
    return await start_profile(update, context)


# Sort tickets by event datetime if available (upcoming first)
async def _get_dt(t, session):
   if t.schedule_event_id:
       se = await db_postgres.get_schedule_event(session,
                                                 t.schedule_event_id)
       return se.datetime_event if se else None
   return None


async def show_tickets(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """Show list of user's purchased tickets with pagination (PAID or APPROVED)."""
    command = context.user_data.get('command', None)
    if not command:
        command = extract_command(update.effective_message.text)
    if command == 'tickets':
        await init_conv_hl_dialog(update, context)
    elif command == 'profile':
        query = update.callback_query
        await query.answer()

    # Determine requested page from callback data if present
    page = 0
    if update.callback_query:
        try:
            parts = update.callback_query.data.split(':')
            if len(parts) > 2:
                page = int(parts[2])
        except Exception as e:
            profile_logger.debug(f"Bad page index in callback: {e}")
            page = 0

    try:
        await update.effective_chat.send_action(ChatAction.TYPING)
    except Exception as e:
        profile_logger.debug(e)

    is_admin_chat = context.config.bot.developer_chat_id == update.effective_chat.id
    if context.args and is_admin_chat:
        user_id = context.args[0]
    elif is_admin_chat and context.user_data.get('profile_user_id', False):
        user_id = context.user_data['profile_user_id']
    else:
        user_id = update.effective_user.id
    user = await db_postgres.get_user(context.session, user_id)

    tickets = []
    if user:
        try:
            tickets = [
                t for t in user.tickets
                if t.status in (TicketStatus.PAID, TicketStatus.APPROVED)
            ]
        except Exception as e:
            profile_logger.error(e)
            tickets = []

    if not tickets:
        keyboard: List[List[InlineKeyboardButton]] = []
        if command == 'profile':
            keyboard.append([back_button, cancel_button])
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = (
            '<b>Мои билеты</b>\n\n'
            'У вас нет купленных билетов.\n\n'
            'Вы можете забронировать билеты командой /reserve'
        )

        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=text, reply_markup=reply_markup)
            except Exception as e:
                profile_logger.debug(e)
                await update.effective_chat.send_message(
                    text=text, reply_markup=reply_markup)
        else:
            await update.effective_chat.send_message(
                text=text, reply_markup=reply_markup)
        context.user_data['STATE'] = MENU
        return MENU

    # Build list [(datetime|None, ticket)] and sort by datetime (None last)
    dt_list: List[tuple] = []
    for t in tickets:
        try:
            dt = await _get_dt(t, context.session)
        except Exception as e:
            profile_logger.debug(e)
            dt = None
        dt_list.append((dt, t))

    dt_list.sort(key=lambda x: (x[0] is None, x[0]))

    total = len(dt_list)
    page_size = PAGE_SIZE_TICKETS
    pages = (total + page_size - 1) // page_size
    if pages == 0:
        pages = 1
    if page < 0:
        page = 0
    if page > pages - 1:
        page = pages - 1

    start = page * page_size
    end = min(total, start + page_size)

    parts = [
        '<b>Мои билеты</b>',
        f'Страница {page + 1}/{pages} • Показаны {start + 1}-{end} из {total}',
    ]

    for dt, ticket in dt_list[start:end]:
        try:
            if ticket.schedule_event_id:
                text_event = await create_str_info_by_schedule_event_id(context, ticket.schedule_event_id)
            else:
                text_event = 'Индивидуальное мероприятие'
            base_ticket = await db_postgres.get_base_ticket(context.session, ticket.base_ticket_id)
            parts.append(
                '\n'.join([
                    f'Билет <code>{ticket.id}</code>',
                    text_event,
                    f'Стоимость: {base_ticket.name if base_ticket else ""} {int(ticket.price)}руб',
                    f'Статус: {ticket.status.value}',
                ])
            )
        except Exception as e:
            profile_logger.error(e)

    text = '\n\n'.join(parts)

    # Build pagination keyboard
    keyboard: List[List[InlineKeyboardButton]] = []
    nav_row: List[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton('◀️ Предыдущая', callback_data=f'profile:tickets:{page - 1}'))
    if page < pages - 1:
        nav_row.append(InlineKeyboardButton('Следующая ▶️', callback_data=f'profile:tickets:{page + 1}'))
    if nav_row:
        keyboard.append(nav_row)

    if command == 'profile':
        keyboard.append([back_button, cancel_button])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
        except Exception as e:
            profile_logger.debug(e)
            await update.effective_chat.send_message(text=text, reply_markup=reply_markup)
    else:
        await update.effective_chat.send_message(text=text, reply_markup=reply_markup)

    context.user_data['STATE'] = MENU
    if context.user_data.get('profile_user_id', False):
        context.user_data.pop('profile_user_id')
    return MENU

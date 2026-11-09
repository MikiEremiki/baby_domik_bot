import logging
from typing import List

from sulguk import transform_html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from db import db_postgres
from db.enum import AgeType
from handlers import init_conv_hl_dialog
from handlers.sub_hl import request_phone_number
from utilities.utl_func import set_back_context
from utilities.utl_kbd import add_btn_back_and_cancel
from utilities.utl_text import extract_phone_number_from_text, check_phone_number

# Re-export tickets-related symbols from tickets_user for backward compatibility
from handlers.tickets_user import (  # noqa: F401
    TICKETS_MENU, PAGE_SIZE_TICKETS,
    show_tickets, tickets_callback,
)

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
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel='tickets',
        add_back_btn=False,
    ))
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
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_back='MENU',
        add_cancel_btn=False,
    ))
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

    text = '<b>Профиль пользователя</b><br><br>'
    if adults:
        text += 'Взрослые:<br>' + '<br>'.join(adults) + '<br><br>'
    if children:
        text += 'Дети:<br>' + '<br>'.join(children) + '<br><br>'
    if not (adults or children):
        text += 'Пока нет добавленных людей.<br><br>'
    text += 'Выберите участника для изменения или удаления, либо добавьте нового:'

    reply_markup = _profile_keyboard(persons)
    res = transform_html(text)
    # Edit message if invoked via callback, else send new message
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=res.text, entities=res.entities, reply_markup=reply_markup, parse_mode=None)
        except Exception as e:
            profile_logger.debug(e)
            await update.effective_chat.send_message(
                res.text, entities=res.entities, reply_markup=reply_markup, parse_mode=None)
    else:
        await update.effective_chat.send_message(
            res.text, entities=res.entities, reply_markup=reply_markup, parse_mode=None)
    await set_back_context(context, MENU, text, reply_markup)
    context.user_data['STATE'] = MENU
    return MENU


async def select_add_type(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == 'add_adult':
        res = transform_html('Введите имя взрослого:')
        await query.edit_message_text(res.text, entities=res.entities, parse_mode=None)
        context.user_data['STATE'] = ADD_ADULT_NAME
        return ADD_ADULT_NAME
    if data == 'add_child':
        res = transform_html('Введите имя ребенка:')
        await query.edit_message_text(res.text, entities=res.entities, parse_mode=None)
        context.user_data['STATE'] = ADD_CHILD_NAME
        return ADD_CHILD_NAME


async def add_adult_name(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    name = update.message.text.strip()
    if not name:
        res = transform_html('Имя не должно быть пустым. Введите имя взрослого:')
        await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
        return ADD_ADULT_NAME
    context.user_data.setdefault('profile', {})['adult_name'] = name
    res = transform_html('Введите телефон (10 цифр без +7):')
    await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
    context.user_data['STATE'] = ADD_ADULT_PHONE
    return ADD_ADULT_PHONE


async def add_adult_phone(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    reserve_user_data = context.user_data['reserve_user_data']

    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if not check_phone_number(phone):
        message = await request_phone_number(update, context)
        reserve_user_data['message_id'] = message.message_id
        return context.user_data['STATE']

    name = context.user_data.get('profile', {}).get('adult_name')
    user_id = update.effective_user.id
    await db_postgres.create_adult(context.session, user_id, name, phone)
    res = transform_html('Взрослый добавлен. Возвращаюсь в профиль...')
    await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
    return await start_profile(update, context)


async def add_child_name(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    name = update.message.text.strip()
    if not name:
        res = transform_html('Имя не должно быть пустым. Введите имя ребенка:')
        await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
        return ADD_CHILD_NAME
    context.user_data.setdefault('profile', {})['child_name'] = name
    res = transform_html('Введите возраст ребенка (например 4.5):')
    await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
    context.user_data['STATE'] = ADD_CHILD_AGE
    return ADD_CHILD_AGE


async def add_child_age(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    text = update.message.text.replace(',', '.').strip()
    try:
        age = float(text)
    except ValueError:
        res = transform_html('Возраст должен быть числом, например 4 или 4.5. Повторите ввод:')
        await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
        return ADD_CHILD_AGE
    name = context.user_data.get('profile', {}).get('child_name')
    user_id = update.effective_user.id
    await db_postgres.create_child(context.session, user_id, name, age=age)
    res = transform_html('Ребенок добавлен. Возвращаюсь в профиль...')
    await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
    return await start_profile(update, context)


async def profile_callback(update: Update,
                           context: 'ContextTypes.DEFAULT_TYPE'):
    """Dispatch profile callbacks to specific handlers."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(':')
    action = parts[1] if len(parts) > 1 else ''

    if action == 'tickets':
        return await show_tickets(update, context)
    if action == 'menu':
        return await _cb_person_menu(query, context, int(parts[2]), parts[3])
    if action == 'back':
        return await start_profile(update, context)
    if action == 'edit_name':
        return await _cb_edit_name(query, context, int(parts[2]), parts[3])
    if action == 'edit_phone':
        return await _cb_edit_phone(query, context, int(parts[2]))
    if action == 'edit_age':
        return await _cb_edit_age(query, context, int(parts[2]))
    if action == 'del':
        return await _cb_delete_confirm(query, context, int(parts[2]), parts[3])
    if action == 'confirm_del':
        return await _cb_confirm_delete(update, context, int(parts[2]))
    return MENU


async def _cb_person_menu(
    query, context: 'ContextTypes.DEFAULT_TYPE', person_id: int, age_type: str,
) -> int:
    """Show person management menu."""
    text = 'Управление участником'
    res = transform_html(text)
    reply_markup = _person_menu_keyboard(person_id, age_type)
    await query.edit_message_text(
        text=res.text, entities=res.entities,
        reply_markup=reply_markup, parse_mode=None
    )
    await set_back_context(context, PERSON_MENU, text, reply_markup)
    context.user_data['STATE'] = PERSON_MENU
    return PERSON_MENU


async def _cb_edit_name(
    query, context: 'ContextTypes.DEFAULT_TYPE', person_id: int, age_type: str,
) -> int:
    """Prompt for new name."""
    context.user_data.setdefault('profile', {})['edit_person'] = {
        'person_id': person_id,
        'age_type': age_type,
    }
    res = transform_html('Введите новое имя:')
    await query.edit_message_text(res.text, entities=res.entities, parse_mode=None)
    context.user_data['STATE'] = EDIT_NAME
    return EDIT_NAME


async def _cb_edit_phone(
    query, context: 'ContextTypes.DEFAULT_TYPE', person_id: int,
) -> int:
    """Prompt for new phone."""
    context.user_data.setdefault('profile', {})['edit_person'] = {
        'person_id': person_id,
        'age_type': 'adult',
    }
    res = transform_html('Введите телефон (10 цифр без +7):')
    await query.edit_message_text(res.text, entities=res.entities, parse_mode=None)
    context.user_data['STATE'] = EDIT_ADULT_PHONE
    return EDIT_ADULT_PHONE


async def _cb_edit_age(
    query, context: 'ContextTypes.DEFAULT_TYPE', person_id: int,
) -> int:
    """Prompt for new child age."""
    context.user_data.setdefault('profile', {})['edit_person'] = {
        'person_id': person_id,
        'age_type': 'child',
    }
    res = transform_html('Введите возраст ребенка (например 4.5):')
    await query.edit_message_text(res.text, entities=res.entities, parse_mode=None)
    context.user_data['STATE'] = EDIT_CHILD_AGE
    return EDIT_CHILD_AGE


async def _cb_delete_confirm(
    query, context: 'ContextTypes.DEFAULT_TYPE', person_id: int, age_type: str,
) -> int:
    """Show delete confirmation dialog."""
    keyboard = [
        [InlineKeyboardButton('✅ Да, удалить',
                              callback_data=f'profile:confirm_del:{person_id}')],
        add_btn_back_and_cancel(
            postfix_for_back='PERSON_MENU',
            add_cancel_btn=False,
        ),
    ]
    res = transform_html('Вы уверены, что хотите удалить участника? Действие необратимо.')
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        res.text, entities=res.entities,
        reply_markup=reply_markup, parse_mode=None
    )
    await set_back_context(context, CONFIRM_DELETE, res.text, reply_markup)
    context.user_data['STATE'] = CONFIRM_DELETE
    return CONFIRM_DELETE


async def _cb_confirm_delete(
    update: Update, context: 'ContextTypes.DEFAULT_TYPE', person_id: int,
) -> int:
    """Confirm and execute person deletion."""
    await db_postgres.delete_person(context.session, person_id)
    res = transform_html('Удалено. Обновляю профиль...')
    await update.callback_query.edit_message_text(res.text, entities=res.entities, parse_mode=None)
    return await start_profile(update, context)


async def set_new_name(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    new_name = update.message.text.strip()
    if not new_name:
        res = transform_html('Имя не должно быть пустым. Введите новое имя:')
        await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
        return EDIT_NAME
    edit_person = context.user_data.get('profile', {}).get('edit_person')
    if not edit_person:
        res = transform_html('Не удалось определить участника. Возвращаюсь в профиль.')
        await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
        return await start_profile(update, context)
    person_id = edit_person['person_id']
    await db_postgres.update_person(context.session, person_id, name=new_name)
    res = transform_html('Имя обновлено. Возвращаюсь в профиль...')
    await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
    return await start_profile(update, context)


async def set_new_adult_phone(update: Update,
                              context: 'ContextTypes.DEFAULT_TYPE'):
    reserve_user_data = context.user_data['reserve_user_data']

    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if not check_phone_number(phone):
        message = await request_phone_number(update, context)
        reserve_user_data['message_id'] = message.message_id
        return context.user_data['STATE']
    edit_person = context.user_data.get('profile', {}).get('edit_person')
    if not edit_person:
        res = transform_html('Не удалось определить участника. Возвращаюсь в профиль.')
        await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
        return await start_profile(update, context)
    person_id = edit_person['person_id']
    await db_postgres.update_adult_by_person_id(context.session, person_id,
                                                phone=phone)
    res = transform_html('Телефон обновлен. Возвращаюсь в профиль...')
    await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
    return await start_profile(update, context)


async def set_new_child_age(update: Update,
                            context: 'ContextTypes.DEFAULT_TYPE'):
    text = update.message.text.replace(',', '.').strip()
    try:
        age = float(text)
    except ValueError:
        res = transform_html('Возраст должен быть числом, например 4 или 4.5. Повторите ввод:')
        await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
        return EDIT_CHILD_AGE
    edit_person = context.user_data.get('profile', {}).get('edit_person')
    if not edit_person:
        res = transform_html('Не удалось определить участника. Возвращаюсь в профиль.')
        await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
        return await start_profile(update, context)
    person_id = edit_person['person_id']
    await db_postgres.update_child_by_person_id(context.session, person_id,
                                                age=age)
    res = transform_html('Возраст обновлен. Возвращаюсь в профиль...')
    await update.message.reply_text(res.text, entities=res.entities, parse_mode=None)
    return await start_profile(update, context)

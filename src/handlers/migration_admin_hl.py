import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from db import db_postgres
from db.enum import AgeType
from handlers import init_conv_hl_dialog
from utilities.utl_kbd import add_btn_back_and_cancel
from utilities.utl_func import (
    set_back_context, get_back_context, get_formatted_date_and_time_of_event
)
from utilities.utl_ticket import format_ticket_contacts

transfer_admin_hl_logger = logging.getLogger('bot.transfer_admin_hl')


async def enter_ticket_id(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    await init_conv_hl_dialog(update, context)

    command = context.user_data['command']
    postfix_for_cancel = command
    context.user_data['postfix_for_cancel'] = postfix_for_cancel

    user = context.user_data.setdefault('user', update.effective_user)

    transfer_admin_hl_logger.info(
        f'Запущена команда переноса администратором: {user}')

    text = 'Введите id билета'

    keyboard = [
        add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            add_back_btn=False
        )
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.effective_message.message_thread_id
    )

    context.user_data['reserve_admin_data']['message_id'] = message.message_id
    state = 0
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def get_ticket_by_id(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    try:
        await context.bot.edit_message_reply_markup(
            update.effective_chat.id,
            context.user_data['reserve_admin_data']['message_id']
        )
    except BadRequest as e:
        transfer_admin_hl_logger.error(e)
        state = context.user_data['STATE']
        dict_back = context.user_data['reserve_user_data']['back'][state]
        del_message_ids = dict_back['del_message_ids']
        if del_message_ids:
            await context.bot.edit_message_reply_markup(
                update.effective_chat.id,
                del_message_ids[0]
            )

    client_data = context.user_data['reserve_user_data']['client_data']
    ticket_id = int(update.effective_message.text)
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if ticket:
        user = ticket.user
        base_ticket = await db_postgres.get_base_ticket(
            context.session, ticket.base_ticket_id)
        schedule_event = await db_postgres.get_schedule_event(
            context.session, ticket.schedule_event_id)
        theater_event = await db_postgres.get_theater_event(
            context.session, schedule_event.theater_event_id
        )

        contacts_block = format_ticket_contacts(ticket)

        # Извлекаем name_adult и data_children из ticket.people, phone — из ticket.phone
        name_adult = ''
        child_str = ''
        client_data['data_children'] = []
        for person in ticket.people:
            if person.age_type == AgeType.adult and person.adult:
                if not name_adult:
                    name_adult = person.name or ''
            elif person.age_type == AgeType.child and person.child:
                age_str = str(person.child.age) if person.child.age is not None else '0'
                child_str += f'{person.name} {person.child.age}\n'
                client_data['data_children'].append(
                    [person.name, age_str])

        if not client_data['data_children']:
            client_data['data_children'] = [['0', '0']]

        client_data['name_adult'] = name_adult
        client_data['phone'] = ticket.phone

        date_event, time_event = await get_formatted_date_and_time_of_event(
            schedule_event)
        text = (
            f'Событие: {theater_event.name}\n'
            f'{date_event} в {time_event}\n\n'
            f'Привязан к профилю: {user.user_id if user else "Нет привязки"}\n'
            f'Билет: {base_ticket.name}\n'
            f'Стоимость: {ticket.price}\n'
            f'Статус: {ticket.status.value}\n'
            f'{contacts_block}\n'
        )
        if child_str:
            text += f'Дети: {child_str}'
        text += f'Примечание: {ticket.notes}\n'
        keyboard = [
            [
                InlineKeyboardButton('Перенести', callback_data='migration'),
            ],
            [*add_btn_back_and_cancel(
                postfix_for_cancel=context.user_data['postfix_for_cancel'],
                postfix_for_back=0
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_chat.send_message(text=text,
                                                 reply_markup=reply_markup)

        context.user_data['reserve_admin_data']['ticket_id'] = ticket_id
        context.user_data['reserve_user_data']['original_child_text'] = child_str
        state = 1
        await set_back_context(context, state, text, reply_markup)
        return state
    else:
        state = 0
        text = 'Такого билета нет\n\n'
        text_back, reply_markup, _ = await get_back_context(context, state)
        message = await update.effective_chat.send_message(
            text=text + text_back, reply_markup=reply_markup)
        context.user_data['reserve_admin_data']['message_id'] = message.message_id
        return state


async def migration_ticket(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    text = 'Выбор показа по id или по параметрам?'

    keyboard = [
        [InlineKeyboardButton('по id', callback_data='id'),
         InlineKeyboardButton('по параметрам', callback_data='params')],
        add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            add_back_btn=False
        )
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text=text, reply_markup=reply_markup)

    state = 1
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    await query.answer()
    return state

import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from db import db_postgres
from handlers import init_conv_hl_dialog
from utilities.utl_func import (
    add_btn_back_and_cancel, set_back_context, get_back_context,
    get_formatted_date_and_time_of_event)

transfer_admin_hl_logger = logging.getLogger('bot.transfer_admin_hl')


async def enter_ticket_id(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
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
        message_thread_id=update.message.message_thread_id
    )

    context.user_data['reserve_admin_data']['message_id'] = message.message_id
    state = 0
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def get_ticket_by_id(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    try:
        await context.bot.edit_message_reply_markup(
            update.effective_chat.id,
            context.user_data['reserve_admin_data']['message_id']
        )
    except BadRequest as e:
        state = context.user_data['STATE']
        dict_back = context.user_data['reserve_user_data']['back'][state]
        del_message_ids = dict_back['del_message_ids']
        if del_message_ids:
            await context.bot.edit_message_reply_markup(
                update.effective_chat.id,
                del_message_ids[0]
            )
    client_data = context.user_data['reserve_user_data']['client_data']
    ticket_id = int(update.message.text)
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if ticket:
        user = ticket.user
        people = ticket.people
        base_ticket = await db_postgres.get_base_ticket(
            context.session, ticket.base_ticket_id)
        schedule_event = await db_postgres.get_schedule_event(
            context.session, ticket.schedule_event_id)
        theater_event = await db_postgres.get_theater_event(
            context.session, schedule_event.theater_event_id
        )
        adult_str = ''
        child_str = ''
        client_data['data_children'] = []
        for person in people:
            if hasattr(person.adult, 'phone'):
                adult_str = f'{person.name}\n+7{person.adult.phone}\n'
                client_data['name_adult'] = person.name
                client_data['phone'] = person.adult.phone
            elif hasattr(person.child, 'age'):
                child_str += f'{person.name} {person.child.age}\n'
                client_data['data_children'].append(
                    [person.name, str(person.child.age)])
        people_str = adult_str + child_str
        date_event, time_event = await get_formatted_date_and_time_of_event(
            schedule_event)
        text = (
            f'Событие: {theater_event.name}\n'
            f'{date_event} в {time_event}\n\n'
            f'Привязан к профилю: {user.user_id}\n'
            f'Билет: {base_ticket.name}\n'
            f'Стоимость: {ticket.price}\n'
            f'Статус: {ticket.status.value}\n'
            f'{people_str}'
            f'Примечание: {ticket.notes}\n'
        )
        keyboard = [
            [
                InlineKeyboardButton('Перенести', callback_data='migration'),
                InlineKeyboardButton('Изменить', callback_data='update'),
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
        context: ContextTypes.DEFAULT_TYPE
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

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
    )

    state = 1
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def update_ticket(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    pass

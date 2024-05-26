import logging

from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update
from telegram.constants import ChatAction

from db.db_googlesheets import load_clients_wait_data
from utilities.utl_func import get_events_for_time_hl, \
    get_formatted_date_and_time_of_event, get_full_name_event

list_wait_hl_logger = logging.getLogger('bot.list_wait_hl')


async def send_clients_wait_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    schedule_events, theater_event = await get_events_for_time_hl(update,
                                                                  context)
    event_ids = []
    for schedule_event in schedule_events:
        event_ids.append(schedule_event.id)

    await update.effective_chat.send_action(ChatAction.TYPING)

    full_name = get_full_name_event(theater_event.name,
                                    theater_event.flag_premier,
                                    theater_event.min_age_child,
                                    theater_event.max_age_child,
                                    theater_event.duration)
    date_event, time_event = await get_formatted_date_and_time_of_event(
        schedule_events[0])

    clients_data, name_column = load_clients_wait_data(event_ids)
    text = f'#Лист_ожидания\n'
    text += (f'Список людей на\n'
             f'{full_name}\n'
             f'{date_event}\n')

    for i, item in enumerate(clients_data):
        text += '\n__________\n'
        text += str(i + 1) + '| '
        text += '<b>' + item[name_column['callback_name']] + '</b>'
        text += '\n+7' + item[name_column['callback_phone']]
        text += '\nЖелаемое время: '
        text += item[name_column['time_show']] + ' '

    photo = update.effective_message.photo
    if photo:
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            message_thread_id=update.effective_message.message_thread_id
        )
    else:
        await query.edit_message_text(
            text=text,
        )
    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state

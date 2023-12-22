import logging

from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update
from telegram.constants import ParseMode, ChatAction

from db.db_googlesheets import (
    load_clients_wait_data,
)

list_wait_hl_logger = logging.getLogger('bot.list_wait_hl')


async def send_clients_wait_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    key_of_name_show, date_show = query.data.split(' | ')
    key_of_name_show = int(key_of_name_show)

    reserve_user_data = context.user_data['reserve_user_data']
    dict_of_name_show_flip = reserve_user_data['dict_of_name_show_flip']
    name_show: str = dict_of_name_show_flip[key_of_name_show]

    await update.effective_chat.send_action(ChatAction.TYPING)

    clients_data, name_column = load_clients_wait_data(date_show)
    text = f'#Лист_ожидания\n'
    text += f'Список людей на\n{name_show}\n{date_show}'

    for i, item in enumerate(clients_data):
        text += '\n__________\n'
        text += str(i + 1) + '| '
        text += '<b>' + item[name_column['callback_name']] + '</b>'
        text += '\n+7' + item[name_column['callback_phone']]
        # text += '\nДата записи: '
        # text += item[name_column['timestamp']] + ' '
        text += '\nЖелаемое время спектакля: '
        text += item[name_column['time_show']] + ' '

    photo = update.effective_message.photo
    if photo:
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            parse_mode=ParseMode.HTML,
            message_thread_id=update.effective_message.message_thread_id
        )
    else:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML
        )
    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state

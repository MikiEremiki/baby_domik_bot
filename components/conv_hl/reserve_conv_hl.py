from typing import Dict, List

from telegram.ext import (
    BaseHandler,
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters,
)

from handlers import reserve_hl, main_hl
from utilities.settings import COMMAND_DICT, RESERVE_TIMEOUT
from utilities.utl_func import reset

states:  Dict[object, List[BaseHandler]] = {
    'MONTH': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(reserve_hl.choice_show_or_date),
    ],
    'SHOW': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(reserve_hl.choice_date),
    ],
    'DATE': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-SHOW'),
        CallbackQueryHandler(reserve_hl.choice_time),
    ],
    'TIME': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-DATE'),
        CallbackQueryHandler(reserve_hl.choice_option_of_reserve),
    ],
    'ORDER': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TIME'),
        CallbackQueryHandler(reserve_hl.check_and_send_buy_info),
    ],
    'PAID': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        MessageHandler(
            filters.PHOTO | filters.ATTACHMENT,
            reserve_hl.forward_photo_or_file
        ),
    ],
    'FORMA': [
        MessageHandler(filters.TEXT, reserve_hl.get_name_adult),
    ],
    'PHONE': [
        MessageHandler(filters.TEXT, reserve_hl.get_phone),
    ],
    'CHILDREN': [
        MessageHandler(filters.TEXT, reserve_hl.get_name_children),
    ],
    'LIST': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад'),
        CallbackQueryHandler(reserve_hl.send_clients_data),
    ],
    'CHOOSING': [
        MessageHandler(
            filters.Regex('^(Выбрать другое время)$'),
            reserve_hl.choice_month
        ),
        MessageHandler(
            filters.Regex('^(Записаться в лист ожидания)$'),
            reserve_hl.write_list_of_waiting
        ),
    ],
    'PHONE_FOR_WAITING': [
        MessageHandler(filters.TEXT, reserve_hl.get_phone_for_waiting),
    ],
}

for key in states.keys():
    states[key].append(CommandHandler('reset', reset))
states[ConversationHandler.TIMEOUT] = [reserve_hl.TIMEOUT_HANDLER]

reserve_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['RESERVE'][0], reserve_hl.choice_month),
        CommandHandler(COMMAND_DICT['LIST'][0], reserve_hl.choice_month),
    ],
    states=states,
    fallbacks=[CommandHandler('help', main_hl.help_command)],
    conversation_timeout=RESERVE_TIMEOUT * 60,
    name="reserve",
    persistent=True,
    allow_reentry=True
)

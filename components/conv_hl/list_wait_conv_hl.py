from typing import Dict, List

from telegram.ext import (
    BaseHandler,
    ConversationHandler, CommandHandler, CallbackQueryHandler,
)

from handlers import reserve_hl, main_hl, list_wait_hl
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
    'LIST_WAIT': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад'),
        CallbackQueryHandler(list_wait_hl.send_clients_wait_data),
    ]
}

for key in states.keys():
    states[key].append(CommandHandler('reset', reset))
states[ConversationHandler.TIMEOUT] = [reserve_hl.TIMEOUT_HANDLER]

list_wait_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['LIST_WAIT'][0], reserve_hl.choice_month),
    ],
    states=states,
    fallbacks=[CommandHandler('help', main_hl.help_command)],
    conversation_timeout=RESERVE_TIMEOUT * 60,
    name='list_wait',
    persistent=True,
    allow_reentry=True
)

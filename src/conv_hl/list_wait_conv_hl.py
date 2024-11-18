from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
)

from custom_filters import filter_admin
from handlers import reserve_hl, main_hl, list_wait_hl
from settings.settings import COMMAND_DICT, RESERVE_TIMEOUT

cancel_callback_handler = CallbackQueryHandler(main_hl.cancel,
                                               pattern='^Отменить')
states = {
    'MONTH': [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.choice_show_or_date),
    ],
    'SHOW': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(reserve_hl.choice_date),
    ],
    'LIST_WAIT': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад'),
        CallbackQueryHandler(list_wait_hl.send_clients_wait_data),
    ]
}

for key in states.keys():
    states[key].append(CommandHandler('reset', main_hl.reset))
states[ConversationHandler.TIMEOUT] = [reserve_hl.TIMEOUT_HANDLER]

list_wait_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['LIST_WAIT'][0],
                       reserve_hl.choice_month,
                       filter_admin),
    ],
    states=states,
    fallbacks=[CommandHandler('help', main_hl.help_command)],
    conversation_timeout=RESERVE_TIMEOUT * 60,
    name='list_wait',
    persistent=True,
    allow_reentry=True
)

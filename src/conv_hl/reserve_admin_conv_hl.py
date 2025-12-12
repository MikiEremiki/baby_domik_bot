from telegram.ext import (
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler,
)

from custom_filters import filter_admin
from handlers import reserve_hl, reserve_admin_hl
from conv_hl import (
    handlers_event_selection, handlers_client_data_selection,
    cancel_callback_handler, back_callback_handler,
    F_text_and_no_command, common_fallbacks
)
from settings.settings import COMMAND_DICT, RESERVE_TIMEOUT

states = {
    1: [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.choice_month, pattern='params'),
        CallbackQueryHandler(reserve_admin_hl.enter_event_id, pattern='id'),
    ],
    2: [
        cancel_callback_handler,
        back_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_admin_hl.choice_option_of_reserve),
    ],
    'TICKET': [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(reserve_admin_hl.start_forma_info,
                             pattern='^TICKET'),
    ],
}

for key in handlers_event_selection.keys():
    states[key] = handlers_event_selection[key]
for key in handlers_client_data_selection.keys():
    states[key] = handlers_client_data_selection[key]

reserve_admin_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['RESERVE_ADMIN'][0],
                       reserve_admin_hl.event_selection_option,
                       filter_admin),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='reserve_admin',
    persistent=True,
    allow_reentry=True
)

from typing import Dict, List

from telegram.ext import (
    BaseHandler,
    ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler,
)

from handlers import support_hl, main_hl
from conv_hl import F_text_and_no_command, cancel_callback_handler
from settings.settings import COMMAND_DICT, RESERVE_TIMEOUT

states:  Dict[object, List[BaseHandler]] = {
    1: [
        cancel_callback_handler,
        CallbackQueryHandler(support_hl.choice_db_settings),
    ],
    2: [
        cancel_callback_handler,
        CallbackQueryHandler(support_hl.theater_event_settings,
                             '^theater_event'),
        CallbackQueryHandler(support_hl.schedule_event_settings,
                             '^schedule_event'),
    ],
    3: [
        cancel_callback_handler,
        CallbackQueryHandler(support_hl.theater_event_select,
                             '^theater_event_select$'),
        CallbackQueryHandler(support_hl.theater_event_preview,
                             '^theater_event_create$'),
        CallbackQueryHandler(support_hl.schedule_event_select,
                             '^schedule_event_select$'),
        CallbackQueryHandler(support_hl.schedule_event_preview,
                             '^schedule_event_create$'),
    ],
    41: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, support_hl.theater_event_check),
        CallbackQueryHandler(support_hl.theater_event_create),
    ],
    42: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, support_hl.schedule_event_check),
        CallbackQueryHandler(support_hl.schedule_event_create),
    ],
}

for key in states.keys():
    states[key].append(CommandHandler('reset', main_hl.reset))
states[ConversationHandler.TIMEOUT] = [support_hl.TIMEOUT_HANDLER]

support_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler('settings', support_hl.start_settings),
    ],
    states=states,
    fallbacks=[CommandHandler('help', main_hl.help_command)],
    conversation_timeout=RESERVE_TIMEOUT * 60,
    name='support',
    persistent=True,
    allow_reentry=True
)

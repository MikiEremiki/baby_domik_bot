from typing import Dict, List

from telegram.ext import (
    BaseHandler,
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters,
)


from handlers import reserve_hl, main_hl, reserve_admin_hl
from settings.settings import COMMAND_DICT, RESERVE_TIMEOUT

from conv_hl import base_handlers

F_text_and_no_command = filters.TEXT & ~filters.COMMAND
cancel_callback_handler = CallbackQueryHandler(main_hl.cancel,
                                               pattern='^Отменить')
back_callback_handler = CallbackQueryHandler(main_hl.back, pattern='^Назад')
states:  Dict[object, List[BaseHandler]] = {
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
        CallbackQueryHandler(reserve_admin_hl.start_forma_info),
    ],
    'FORMA': [
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_name_adult),
    ],
    'PHONE': [
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_phone),
    ],
    'CHILDREN': [
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_name_children),
    ],
}

for key in base_handlers.keys():
    states[key] = base_handlers[key]

for key in states.keys():
    states[key].append(CommandHandler('reset', main_hl.reset))
states[ConversationHandler.TIMEOUT] = [reserve_hl.TIMEOUT_HANDLER]

reserve_admin_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['RESERVE_ADMIN'][0],
                       reserve_admin_hl.choice_option_enter),
    ],
    states=states,
    fallbacks=[CommandHandler('help', main_hl.help_command)],
    conversation_timeout=RESERVE_TIMEOUT * 60,
    name='reserve_admin',
    persistent=True,
    allow_reentry=True
)

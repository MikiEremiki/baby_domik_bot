from telegram.ext import (
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters,
)

from custom_filters import filter_admin
from handlers import reserve_hl, main_hl, reserve_admin_hl, migration_admin_hl
from settings.settings import COMMAND_DICT, RESERVE_TIMEOUT

from conv_hl import handlers_event_selection, handlers_client_data_selection

F_text_and_no_command = filters.TEXT & ~filters.COMMAND
cancel_callback_handler = CallbackQueryHandler(main_hl.cancel,
                                               pattern='^Отменить')
back_callback_handler = CallbackQueryHandler(main_hl.back, pattern='^Назад')
states = {
    0: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command,
                       migration_admin_hl.get_ticket_by_id),
    ],
    1: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(migration_admin_hl.migration_ticket, pattern='migration'),
        CallbackQueryHandler(migration_admin_hl.update_ticket, pattern='update'),
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
}

for key in handlers_event_selection.keys():
    states[key] = handlers_event_selection[key]
for key in handlers_client_data_selection.keys():
    states[key] = handlers_client_data_selection[key]

for key in states.keys():
    states[key].append(CommandHandler('reset', main_hl.reset))
states[ConversationHandler.TIMEOUT] = [reserve_hl.TIMEOUT_HANDLER]

migration_admin_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['MIGRATION_ADMIN'][0],
                       migration_admin_hl.enter_ticket_id,
                       filter_admin),
    ],
    states=states,
    fallbacks=[CommandHandler('help', main_hl.help_command)],
    conversation_timeout=RESERVE_TIMEOUT * 60,
    name='migration_admin',
    persistent=True,
    allow_reentry=True
)

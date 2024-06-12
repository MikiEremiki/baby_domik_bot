from typing import Dict, List

from telegram.ext import (
    BaseHandler,
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters,
)
from telegram.ext.filters import Text

from handlers import reserve_hl, main_hl, offer_hl, ticket_hl
from conv_hl import (
    handlers_event_selection, handlers_client_data_selection,
    cancel_callback_handler, back_callback_handler,
    F_text_and_no_command
)
from settings.settings import COMMAND_DICT, RESERVE_TIMEOUT

states: Dict[object, List[BaseHandler]] = {
    'TICKET': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TIME'),
        CallbackQueryHandler(ticket_hl.get_ticket),
    ],
    'OFFER': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TICKET'),
        MessageHandler(Text(('Принимаю',)),
                       offer_hl.get_agreement),
    ],
    'EMAIL': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TICKET'),
        CallbackQueryHandler(reserve_hl.get_email, pattern='email_confirm'),
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_email),
    ],
    'PAID': [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.processing_successful_notification,
                             pattern='Next'),
        MessageHandler(
            filters.PHOTO | filters.ATTACHMENT,
            reserve_hl.forward_photo_or_file
        ),
    ],
    'LIST': [
        cancel_callback_handler,
        back_callback_handler,
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
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_phone_for_waiting),
    ],
}

for key in handlers_event_selection.keys():
    states[key] = handlers_event_selection[key]
for key in handlers_client_data_selection.keys():
    states[key] = handlers_client_data_selection[key]

for key in states.keys():
    states[key].append(CommandHandler('reset', main_hl.reset))
states[ConversationHandler.TIMEOUT] = [reserve_hl.TIMEOUT_HANDLER]

reserve_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['RESERVE'][0], reserve_hl.choice_month),
        CommandHandler(COMMAND_DICT['LIST'][0], reserve_hl.choice_month),
    ],
    states=states,
    fallbacks=[CommandHandler('help', main_hl.help_command)],
    conversation_timeout=RESERVE_TIMEOUT * 60,
    name='reserve',
    persistent=True,
    allow_reentry=True
)

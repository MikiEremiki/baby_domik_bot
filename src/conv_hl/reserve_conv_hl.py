from typing import Dict, List

from telegram.ext import (
    BaseHandler,
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters,
)
from telegram.ext.filters import Text

from handlers import reserve_hl, main_hl
from conv_hl import base_handlers
from settings.settings import COMMAND_DICT, RESERVE_TIMEOUT

F_text_and_no_command = filters.TEXT & ~filters.COMMAND
cancel_callback_handler = CallbackQueryHandler(main_hl.cancel, '^Отменить')
back_callback_handler = CallbackQueryHandler(main_hl.back, '^Назад')
states:  Dict[object, List[BaseHandler]] = {
    'TICKET': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TIME'),
        CallbackQueryHandler(reserve_hl.get_ticket),
    ],
    'OFFER': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TICKET'),
        MessageHandler(Text(('Принимаю',)),
                       reserve_hl.get_offer),
    ],
    'EMAIL': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TICKET'),
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_email),
    ],
    'FORMA': [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_name_adult),
    ],
    'PHONE': [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_phone),
    ],
    'CHILDREN': [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_name_children),
    ],
    'ORDER': [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_hl.check_and_send_buy_info),
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

for key in base_handlers.keys():
    states[key] = base_handlers[key]

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

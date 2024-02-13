from typing import Dict, List

from telegram.ext import (
    BaseHandler,
    CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler,
    filters,
)

from handlers import birthday_hl, main_hl
from settings.settings import COMMAND_DICT

F_text_and_no_command = filters.TEXT & ~filters.COMMAND
states:  Dict[object, List[BaseHandler]] = {
    'PLACE': [
        CallbackQueryHandler(birthday_hl.ask_date, pattern='^1$'),
        CallbackQueryHandler(birthday_hl.ask_address, pattern='^2$'),
    ],
    'ADDRESS': [
        MessageHandler(F_text_and_no_command,
                       birthday_hl.get_address),
    ],
    'DATE': [
        MessageHandler(F_text_and_no_command,
                       birthday_hl.get_date),
    ],
    'TIME': [
        MessageHandler(F_text_and_no_command,
                       birthday_hl.get_time),
    ],
    'CHOOSE': [
        CallbackQueryHandler(birthday_hl.get_show),
    ],
    'AGE': [
        CallbackQueryHandler(birthday_hl.get_age),
    ],
    'QTY_CHILD': [
        CallbackQueryHandler(birthday_hl.get_qty_child),
    ],
    'QTY_ADULT': [
        CallbackQueryHandler(birthday_hl.get_qty_adult),
    ],
    'FORMAT_BD': [
        CallbackQueryHandler(birthday_hl.get_format_bd),
    ],
    'NAME_CHILD': [
        MessageHandler(F_text_and_no_command,
                       birthday_hl.get_name_child),
    ],
    'NAME': [
        MessageHandler(F_text_and_no_command,
                       birthday_hl.get_name),
    ],
    'PHONE': [
        MessageHandler(F_text_and_no_command,
                       birthday_hl.get_phone),
    ],
}

for key in states.keys():
    states[key].append(CommandHandler('reset', main_hl.reset))
states[ConversationHandler.TIMEOUT] = [birthday_hl.TIMEOUT_HANDLER]

birthday_conv_hl = ConversationHandler(
        entry_points=[
            CommandHandler(COMMAND_DICT['BD_ORDER'][0],
                           birthday_hl.choice_place),
        ],
        states=states,
        fallbacks=[CommandHandler('help', main_hl.help_command)],
        conversation_timeout=30*60,  # 30 мин
        name='bd_order',
        persistent=True,
        allow_reentry=True
    )

birthday_paid_conv_hl = ConversationHandler(
        entry_points=[
            CommandHandler(COMMAND_DICT['BD_PAID'][0],
                           birthday_hl.paid_info),
        ],
        states={
            'PAID': [
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
                MessageHandler(
                    filters.PHOTO | filters.ATTACHMENT,
                    birthday_hl.forward_photo_or_file
                ),
            ],
            ConversationHandler.TIMEOUT: [birthday_hl.TIMEOUT_HANDLER]
        },
        fallbacks=[CommandHandler('help', main_hl.help_command)],
        conversation_timeout=30*60,  # 30 мин
        name='bd_paid',
        persistent=True,
        allow_reentry=True
    )

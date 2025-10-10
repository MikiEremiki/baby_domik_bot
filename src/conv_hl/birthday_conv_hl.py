from telegram.ext import (
    CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler,
    filters,
)

from handlers import birthday_hl
from conv_hl import (
    cancel_callback_handler, back_callback_handler,
    F_text_and_no_command, common_fallbacks
)
from settings.settings import COMMAND_DICT

states = {
    'PLACE': [
        CallbackQueryHandler(birthday_hl.ask_date, pattern='^0$'),
        CallbackQueryHandler(birthday_hl.ask_address, pattern='^1$'),
    ],
    'ADDRESS': [
        MessageHandler(F_text_and_no_command, birthday_hl.get_address),
    ],
    'DATE': [
        MessageHandler(F_text_and_no_command, birthday_hl.get_date),
    ],
    'TIME': [
        MessageHandler(F_text_and_no_command, birthday_hl.get_time),
    ],
    'CHOOSE': [
        CallbackQueryHandler(birthday_hl.get_show, pattern='^CHOOSE'),
    ],
    'AGE': [
        CallbackQueryHandler(birthday_hl.get_age, pattern='^AGE'),
    ],
    'FORMAT_BD': [
        CallbackQueryHandler(birthday_hl.get_format_bd, pattern='^FORMAT_BD'),
    ],
    'QTY_CHILD': [
        CallbackQueryHandler(birthday_hl.get_qty_child, pattern='^QTY_CHILD'),
    ],
    'QTY_ADULT': [
        CallbackQueryHandler(birthday_hl.get_qty_adult, pattern='^QTY_ADULT'),
    ],
    'NAME_CHILD': [
        MessageHandler(F_text_and_no_command, birthday_hl.get_name_child),
    ],
    'NAME': [
        MessageHandler(F_text_and_no_command, birthday_hl.get_name),
    ],
    'PHONE': [
        MessageHandler(F_text_and_no_command, birthday_hl.get_phone),
    ],
    'NOTE': [
        CallbackQueryHandler(birthday_hl.get_note, pattern='Next'),
        MessageHandler(F_text_and_no_command, birthday_hl.get_note),
    ],
    'CONFIRM': [
        CallbackQueryHandler(birthday_hl.get_confirm, pattern='confirm'),
    ],
}

for key in states.keys():
    states[key].insert(0, cancel_callback_handler)
    if key != 'PLACE':
        states[key].insert(1, back_callback_handler)
states[ConversationHandler.TIMEOUT] = [birthday_hl.TIMEOUT_HANDLER]

birthday_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['BD_ORDER'][0],
                       birthday_hl.choice_place),
    ],
    states=states,
    fallbacks=common_fallbacks,
    conversation_timeout=30 * 60,  # 30 мин
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
            cancel_callback_handler,
            MessageHandler(
                filters.PHOTO | filters.ATTACHMENT,
                birthday_hl.forward_photo_or_file
            ),
        ],
        ConversationHandler.TIMEOUT: [birthday_hl.TIMEOUT_HANDLER]
    },
    fallbacks=common_fallbacks,
    # conversation_timeout=30 * 60,  # 30 мин
    name='bd_paid',
    persistent=True,
    allow_reentry=True
)

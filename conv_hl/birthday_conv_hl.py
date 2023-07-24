from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from handlers import birthday_hl, main_hl
from utilities.settings import COMMAND_DICT


birthday_conv_hl = ConversationHandler(
        entry_points=[
            CommandHandler(COMMAND_DICT['BD_REQUEST'][0],
                           birthday_hl.choice_place),
        ],
        states={
            'PLACE': [
                CallbackQueryHandler(birthday_hl.ask_date, pattern='^1$'),
                CallbackQueryHandler(birthday_hl.ask_address, pattern='^2$'),
            ],
            'ADDRESS': [
                MessageHandler(filters.TEXT, birthday_hl.get_address),
            ],
            'DATE': [
                MessageHandler(filters.TEXT, birthday_hl.get_date),
            ],
            'TIME': [
                MessageHandler(filters.TEXT, birthday_hl.get_time),
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
                MessageHandler(filters.TEXT, birthday_hl.get_name_child),
            ],
            'NAME': [
                MessageHandler(filters.TEXT, birthday_hl.get_name),
            ],
            'PHONE': [
                MessageHandler(filters.TEXT, birthday_hl.get_phone),
            ],
            ConversationHandler.TIMEOUT: [birthday_hl.TIMEOUT_HANDLER]
        },
        fallbacks=[CommandHandler('help', main_hl.help_command)],
        conversation_timeout=30*60,  # 30 мин
        name='bd_request',
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

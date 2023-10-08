from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from handlers import birthday_hl, main_hl
from utilities.settings import COMMAND_DICT
from utilities.utl_func import reset


birthday_conv_hl = ConversationHandler(
        entry_points=[
            CommandHandler(COMMAND_DICT['BD_ORDER'][0],
                           birthday_hl.choice_place),
        ],
        states={
            'PLACE': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(birthday_hl.ask_date, pattern='^1$'),
                CallbackQueryHandler(birthday_hl.ask_address, pattern='^2$'),
            ],
            'ADDRESS': [
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, birthday_hl.get_address),
            ],
            'DATE': [
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, birthday_hl.get_date),
            ],
            'TIME': [
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, birthday_hl.get_time),
            ],
            'CHOOSE': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(birthday_hl.get_show),
            ],
            'AGE': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(birthday_hl.get_age),
            ],
            'QTY_CHILD': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(birthday_hl.get_qty_child),
            ],
            'QTY_ADULT': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(birthday_hl.get_qty_adult),
            ],
            'FORMAT_BD': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(birthday_hl.get_format_bd),
            ],
            'NAME_CHILD': [
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, birthday_hl.get_name_child),
            ],
            'NAME': [
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, birthday_hl.get_name),
            ],
            'PHONE': [
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, birthday_hl.get_phone),
            ],
            ConversationHandler.TIMEOUT: [birthday_hl.TIMEOUT_HANDLER]
        },
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

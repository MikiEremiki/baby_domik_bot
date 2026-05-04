from telegram.ext import (
    CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler,
    filters,
)

from custom_filters import filter_admin
from handlers import afisha_hl
from conv_hl import cancel_callback_handler, common_fallbacks
from settings.settings import COMMAND_DICT

afisha_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['AFISHA'][0],
                       afisha_hl.load_afisha,
                       filter_admin),
    ],
    states={
        1: [
            cancel_callback_handler,
            CallbackQueryHandler(afisha_hl.set_month, pattern="^([1-9]|1[0-2])$"),
        ],
        2: [
            cancel_callback_handler,
            CallbackQueryHandler(afisha_hl.view_afisha, pattern='view_afisha'),
            CallbackQueryHandler(afisha_hl.request_update_afisha, pattern='update_afisha'),
            CallbackQueryHandler(afisha_hl.delete_afisha_action, pattern='delete_afisha'),
            MessageHandler(filters.PHOTO, afisha_hl.upload_afisha),
        ],
        3: [
            cancel_callback_handler,
            MessageHandler(filters.PHOTO, afisha_hl.upload_afisha),
        ]
    },
    fallbacks=common_fallbacks,
    name='afisha',
    persistent=True,
    allow_reentry=True
)

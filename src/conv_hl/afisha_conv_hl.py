from telegram.ext import (
    CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler,
    filters,
)

from handlers import afisha_hl, main_hl
from conv_hl import cancel_callback_handler
from settings.settings import COMMAND_DICT, ADMIN_ID

afisha_conv_hl = ConversationHandler(
        entry_points=[
            CommandHandler(COMMAND_DICT['AFISHA'][0],
                afisha_hl.load_afisha,
                filters=filters.User(ADMIN_ID)),
        ],
        states={
            1: [
                cancel_callback_handler,
                CallbackQueryHandler(afisha_hl.show_data, pattern='show_data'),
                CallbackQueryHandler(afisha_hl.set_month),
            ],
            2: [
                cancel_callback_handler,
                CallbackQueryHandler(afisha_hl.skip, pattern='skip'),
                MessageHandler(filters.PHOTO, afisha_hl.check),
            ],
        },
        fallbacks=[CommandHandler('help', main_hl.help_command)],
        name='afisha',
        persistent=True,
        allow_reentry=True
    )

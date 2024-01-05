from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from handlers import afisha_hl, main_hl
from settings.settings import COMMAND_DICT, ADMIN_ID

afisha_conv_hl = ConversationHandler(
        entry_points=[
            CommandHandler(
                COMMAND_DICT['AFISHA'][0],
                afisha_hl.load_afisha,
                filters=filters.User(ADMIN_ID)
                ),
        ],
        states={
            1: [
                CallbackQueryHandler(afisha_hl.set_month),
            ],
            2: [
                MessageHandler(filters.PHOTO, afisha_hl.check),
            ],
        },
        fallbacks=[CommandHandler('help', main_hl.help_command)],
        name='afisha',
        persistent=True,
        allow_reentry=True
    )

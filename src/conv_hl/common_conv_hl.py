from warnings import filterwarnings

from telegram.ext import CallbackQueryHandler, CommandHandler, filters
from telegram.warnings import PTBUserWarning

from handlers import main_hl

F_text_and_no_command = filters.TEXT & ~filters.COMMAND
cancel_callback_handler = CallbackQueryHandler(main_hl.cancel, '^Отменить')
back_callback_handler = CallbackQueryHandler(main_hl.back, '^Назад')

common_fallbacks = [
    CommandHandler('start', main_hl.start),
    CommandHandler('reset', main_hl.reset),
]

filterwarnings(
    action='ignore',
    message=r'.*CallbackQueryHandler',
    category=PTBUserWarning,
)

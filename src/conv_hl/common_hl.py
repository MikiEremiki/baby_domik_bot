from warnings import filterwarnings

from telegram.ext import CallbackQueryHandler, filters
from telegram.warnings import PTBUserWarning

from handlers import main_hl, reserve_hl

F_text_and_no_command = filters.TEXT & ~filters.COMMAND
cancel_callback_handler = CallbackQueryHandler(main_hl.cancel, '^Отменить')
back_callback_handler = CallbackQueryHandler(main_hl.back, '^Назад')

base_handlers = {
    'MONTH': [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.choice_show_or_date),
    ],
    'SHOW': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(reserve_hl.choice_date),
    ],
    'DATE': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-SHOW'),
        CallbackQueryHandler(reserve_hl.choice_time),
    ],
    'TIME': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-DATE'),
        CallbackQueryHandler(reserve_hl.choice_option_of_reserve),
    ],
}

filterwarnings(action="ignore",
               message=r".*CallbackQueryHandler",
               category=PTBUserWarning)

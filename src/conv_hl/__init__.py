from warnings import filterwarnings

from telegram.warnings import PTBUserWarning
from telegram.ext import CallbackQueryHandler

from handlers import main_hl, reserve_hl

base_handlers = {
    'MONTH': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(reserve_hl.choice_show_or_date),
    ],
    'SHOW': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(reserve_hl.choice_date),
    ],
    'DATE': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-SHOW'),
        CallbackQueryHandler(reserve_hl.choice_time),
    ],
    'TIME': [
        CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-DATE'),
        CallbackQueryHandler(reserve_hl.choice_option_of_reserve),
    ],
}

filterwarnings(action="ignore",
               message=r".*CallbackQueryHandler",
               category=PTBUserWarning)

from warnings import filterwarnings

from telegram.ext import (
    filters,
    CallbackQueryHandler, MessageHandler, CommandHandler
)
from telegram.warnings import PTBUserWarning

from handlers import main_hl, reserve_hl

F_text_and_no_command = filters.TEXT & ~filters.COMMAND
cancel_callback_handler = CallbackQueryHandler(main_hl.cancel, '^Отменить')
back_callback_handler = CallbackQueryHandler(main_hl.back, '^Назад')

handlers_event_selection  = {
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

handlers_client_data_selection = {
    'FORMA': [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_name_adult),
    ],
    'PHONE': [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_phone),
    ],
    'CHILDREN': [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_hl.get_name_children),
        CallbackQueryHandler(reserve_hl.get_name_children, pattern='^Далее'),
    ],
}

common_fallbacks=[
        CommandHandler('start', main_hl.start),
        CommandHandler('help', main_hl.help_command),
        CommandHandler('reset', main_hl.reset),
    ],

filterwarnings(action="ignore",
               message=r".*CallbackQueryHandler",
               category=PTBUserWarning)

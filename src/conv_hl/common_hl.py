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
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MODE'),
        CallbackQueryHandler(reserve_hl.choice_show, pattern='^MONTH'),
        CallbackQueryHandler(reserve_hl.choice_month_rep_continue, pattern='^MONTH_REP'),
    ],
    'SHOW': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MODE'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-REP_GROUP'),
        CallbackQueryHandler(reserve_hl.choice_show, pattern='^SHOW_PAGE'),
        CallbackQueryHandler(reserve_hl.choice_date, pattern='^SHOW'),
    ],
    'DATE': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-SHOW'),
        CallbackQueryHandler(reserve_hl.choice_time, pattern='^DATE'),
    ],
    'TIME': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-DATE'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-SHOW'),
        CallbackQueryHandler(reserve_hl.choice_option_of_reserve, pattern='^TIME'),
    ],
}

handlers_client_data_selection = {
    'FORMA': [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.adult_confirm, pattern=r'.*adult_confirm'),
        MessageHandler(F_text_and_no_command, reserve_hl.get_adult),
    ],
    'PHONE': [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.phone_confirm, pattern=r'.*phone_confirm'),
        MessageHandler(F_text_and_no_command, reserve_hl.get_phone),
    ],
    'CHILDREN': [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.child_confirm, pattern=r'.*child_confirm'),
        MessageHandler(F_text_and_no_command, reserve_hl.get_children),
        CallbackQueryHandler(reserve_hl.get_children, pattern=r'^Далее'),
    ],
}

common_fallbacks=[
        CommandHandler('start', main_hl.start),
        CommandHandler('help', main_hl.help_command),
        CommandHandler('reset', main_hl.reset),
    ]

filterwarnings(action='ignore',
               message=r'.*CallbackQueryHandler',
               category=PTBUserWarning)

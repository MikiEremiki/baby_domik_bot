from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
)

from custom_filters import filter_list_cmd
from handlers import reserve_hl, main_hl, list_wait_hl
from conv_hl import cancel_callback_handler, common_fallbacks
from settings.settings import COMMAND_DICT

states = {
    'MONTH': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MODE'),
        CallbackQueryHandler(reserve_hl.choice_show, pattern='^MONTH'),
    ],
    'SHOW': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MODE'),
        CallbackQueryHandler(reserve_hl.choice_show, pattern='^SHOW_PAGE'),
        CallbackQueryHandler(reserve_hl.choice_date, pattern='^SHOW'),
    ],
    'LIST_WAIT': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад'),
        CallbackQueryHandler(list_wait_hl.send_clients_wait_data,
                             pattern='^LIST_WAIT'),
    ],
}

list_wait_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['LIST_WAIT'][0],
                       reserve_hl.choice_month,
                       filter_list_cmd),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='list_wait',
    persistent=True,
    allow_reentry=True
)

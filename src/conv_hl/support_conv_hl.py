from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler,
)

from custom_filters import filter_admin
from handlers import support_hl
from handlers.sub_hl import (
    update_base_ticket_data, update_theater_event_data,
    update_special_ticket_price, update_schedule_event_data,
    update_custom_made_format_data
)
from conv_hl import (
    F_text_and_no_command, cancel_callback_handler, back_callback_handler,
    common_fallbacks
)
from settings.settings import COMMAND_DICT, RESERVE_TIMEOUT

states = {
    1: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(support_hl.get_updates_option, '^update_data$'),
        CallbackQueryHandler(support_hl.choice_db_settings, '^db$'),
    ],
    'updates': [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(update_base_ticket_data, COMMAND_DICT['UP_BT_DATA'][0]),
        CallbackQueryHandler(update_theater_event_data, COMMAND_DICT['UP_TE_DATA'][0]),
        CallbackQueryHandler(update_schedule_event_data, COMMAND_DICT['UP_SE_DATA'][0]),
        CallbackQueryHandler(update_special_ticket_price, COMMAND_DICT['UP_SPEC_PRICE'][0]),
        CallbackQueryHandler(update_custom_made_format_data, COMMAND_DICT['UP_CMF_DATA'][0]),
        # CallbackQueryHandler(update_ticket_data, COMMAND_DICT['UP_TICKET_DATA'][0]),
    ],
    2: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(support_hl.get_settings, pattern='^db|$'),
    ],
    3: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(support_hl.theater_event_select,
                             '^theater_event_select$'),
        CallbackQueryHandler(support_hl.theater_event_preview,
                             '^theater_event_create$'),
        CallbackQueryHandler(support_hl.schedule_event_select,
                             '^schedule_event_select$'),
        CallbackQueryHandler(support_hl.schedule_event_preview,
                             '^schedule_event_create$'),
    ],
    41: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, support_hl.theater_event_check),
        CallbackQueryHandler(support_hl.theater_event_create, '^accept$'),
    ],
    42: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, support_hl.schedule_event_check),
        CallbackQueryHandler(support_hl.schedule_event_create, '^accept$'),
    ],
    ConversationHandler.TIMEOUT: [support_hl.TIMEOUT_HANDLER]
}


support_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler('settings',
                       support_hl.start_settings,
                       filter_admin),
    ],
    states=states,
    fallbacks=common_fallbacks,
    # conversation_timeout=RESERVE_TIMEOUT * 60,
    name='support',
    persistent=True,
    allow_reentry=True
)

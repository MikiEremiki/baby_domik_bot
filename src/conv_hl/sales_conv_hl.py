from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters,
)

from custom_filters import filter_admin
from conv_hl import (
    cancel_callback_handler, back_callback_handler, common_fallbacks,
)
from handlers import sales_hl
from settings.settings import COMMAND_DICT

states = {
    sales_hl.MENU: [
        cancel_callback_handler,
        back_callback_handler,
    ],
    sales_hl.PICK_TYPE: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_type, pattern='^sales:type'),
    ],
    sales_hl.PICK_THEATER: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_theater, pattern='^sales:theater'),
    ],
    sales_hl.PICK_SCOPE: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_scope, pattern='^sales:scope'),
    ],
    sales_hl.PICK_SCHEDULES: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_schedules, pattern='^sales:schedule_page'),
        CallbackQueryHandler(sales_hl.pick_schedules, pattern='^sales:schedule'),
    ],
    sales_hl.PICK_AUDIENCE_THEATER: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_audience_theater, pattern='^sales:aud_theater'),
    ],
    sales_hl.BUILD_AUDIENCE: [
        cancel_callback_handler,
        back_callback_handler,
        MessageHandler(filters.TEXT & ~filters.COMMAND, sales_hl.input_dev_chat_ids),
        CallbackQueryHandler(sales_hl.ask_message, pattern='^sales:next_message'),
    ],
    sales_hl.GET_MESSAGE: [
        cancel_callback_handler,
        back_callback_handler,
        MessageHandler(filters.TEXT & ~filters.COMMAND, sales_hl.handle_admin_message),
        MessageHandler(filters.PHOTO, sales_hl.handle_admin_message),
        MessageHandler(filters.VIDEO, sales_hl.handle_admin_message),
        MessageHandler(filters.ANIMATION, sales_hl.handle_admin_message),
    ],
    sales_hl.PREVIEW: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.preview_action, pattern='^sales:preview'),
    ],
}

sales_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT.get('SALES', ['sales'])[0], sales_hl.start_sales, filter_admin),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='sales',
    persistent=True,
    allow_reentry=True,
)

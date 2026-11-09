from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters,
)

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
    sales_hl.PICK_ATTACH_THEATER: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_attach_theater, pattern='^sales:attach_theater'),
    ],
    sales_hl.PICK_FILTERS: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_filters, pattern='^sales:filters'),
    ],
    sales_hl.PICK_FILTER_STATUS: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_filter_status, pattern='^sales:f_status'),
    ],
    sales_hl.PICK_FILTER_TYPE_EVENT: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_filter_type_event, pattern='^sales:f_type_event'),
    ],
    sales_hl.PICK_FILTER_THEATER_EVENT: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_filter_theater_event, pattern='^sales:f_theater_event'),
    ],
    sales_hl.PICK_FILTER_SCHEDULE_EVENT: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_filter_schedule_event, pattern='^sales:f_schedule_page'),
        CallbackQueryHandler(sales_hl.pick_filter_schedule_event, pattern='^sales:f_schedule'),
    ],
    sales_hl.PICK_FILTER_BASE_TICKET: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_filter_base_ticket, pattern='^sales:f_base_ticket'),
    ],
    sales_hl.PICK_TICKET_IDS: [
        cancel_callback_handler,
        back_callback_handler,
        MessageHandler(filters.TEXT & ~filters.COMMAND, sales_hl.pick_ticket_ids),
    ],
    sales_hl.PICK_FILTER_CHILD_AGE_MIN: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_filter_child_age_min, pattern='^sales:f_child_age_min'),
    ],
    sales_hl.PICK_FILTER_CHILD_AGE_MAX: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_filter_child_age_max, pattern='^sales:f_child_age_max'),
    ],
    sales_hl.BUILD_AUDIENCE: [
        cancel_callback_handler,
        back_callback_handler,
        MessageHandler(filters.TEXT & ~filters.COMMAND, sales_hl.input_dev_chat_ids),
        CallbackQueryHandler(sales_hl.ask_message, pattern='^sales:next_message'),
    ],
    sales_hl.PREVIEW: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.preview_action, pattern='^sales:preview'),
    ],
    # SEASON_TICKET_HOLDERS states
    sales_hl.PICK_SEASON_START: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_season_start, pattern='^sales:season_start'),
        MessageHandler(filters.TEXT & ~filters.COMMAND, sales_hl.pick_season_start),
    ],
    sales_hl.PICK_SEASON_END: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_season_end, pattern='^sales:season_end'),
        MessageHandler(filters.TEXT & ~filters.COMMAND, sales_hl.pick_season_end),
    ],
    sales_hl.PICK_SEASON_THEATERS: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_season_theaters, pattern='^sales:season_theater_page'),
        CallbackQueryHandler(sales_hl.pick_season_theaters, pattern='^sales:season_theater'),
    ],
    sales_hl.PICK_SEASON_AGE_MIN: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_season_age_min, pattern='^sales:season_age_min'),
    ],
    sales_hl.PICK_SEASON_AGE_MAX: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_season_age_max, pattern='^sales:season_age_max'),
    ],
    sales_hl.PICK_SEASON_STATUSES: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.pick_season_statuses, pattern='^sales:season_status'),
    ],
    # GET_MESSAGE — text only (media collected in GET_MEDIA)
    sales_hl.GET_MESSAGE: [
        cancel_callback_handler,
        CallbackQueryHandler(sales_hl.back_to_pick_filters, pattern='^Назад-PICK_FILTERS$'),
        CallbackQueryHandler(sales_hl.back_to_attach_theater, pattern='^Назад-PICK_ATTACH_THEATER$'),
        back_callback_handler,
        MessageHandler(filters.TEXT & ~filters.COMMAND, sales_hl.handle_admin_message),
    ],
    # GET_MEDIA — collect media files
    sales_hl.GET_MEDIA: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.handle_media_action, pattern='^sales:media'),
        MessageHandler(filters.PHOTO, sales_hl.handle_media_input),
        MessageHandler(filters.VIDEO, sales_hl.handle_media_input),
        MessageHandler(filters.ANIMATION, sales_hl.handle_media_input),
        MessageHandler(filters.TEXT & ~filters.COMMAND, sales_hl.handle_media_text),
    ],
    # LENGTH_FIX — caption too long
    sales_hl.LENGTH_FIX: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(sales_hl.handle_length_action, pattern='^sales:length'),
    ],
}

sales_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT.get('SALES', ['sales'])[0], sales_hl.start_sales),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='sales',
    persistent=True,
    allow_reentry=True,
)

from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters,
)

from conv_hl import (
    back_callback_handler, cancel_callback_handler, common_fallbacks,
)
from handlers.sales_hl import start_sales, pick_type
from handlers.sales.states import (
    MENU, PICK_EXISTING_CAMPAIGN, CAMPAIGN_ACTION_MENU, PICK_TYPE,
    PICK_THEATER, PICK_SCOPE, PICK_SCHEDULES, PICK_AUDIENCE_THEATER,
    BUILD_AUDIENCE, GET_MESSAGE, PREVIEW, GET_MEDIA, LENGTH_FIX,
    PICK_ATTACH_THEATER, PICK_FILTERS, PICK_FILTER_STATUS,
    PICK_FILTER_TYPE_EVENT, PICK_FILTER_THEATER_EVENT,
    PICK_FILTER_SCHEDULE_EVENT, PICK_FILTER_BASE_TICKET, PICK_TICKET_IDS,
    PICK_FILTER_CHILD_AGE_MIN, PICK_FILTER_CHILD_AGE_MAX,
    PICK_SEASON_START, PICK_SEASON_END, PICK_SEASON_THEATERS,
    PICK_SEASON_AGE_MIN, PICK_SEASON_AGE_MAX, PICK_SEASON_STATUSES,
)
from handlers.sales.campaign import (
    pick_existing_campaign, handle_campaign_action, back_to_campaign_action,
)
from handlers.sales.was_this_year import (
    pick_theater, pick_scope, pick_schedules, pick_audience_theater,
)
from handlers.sales.ticket_holders import (
    pick_filters, back_to_pick_filters,
    pick_filter_status, pick_filter_type_event, pick_filter_theater_event,
    pick_filter_schedule_event, pick_filter_base_ticket,
    pick_filter_child_age_min, pick_filter_child_age_max,
    pick_ticket_ids,
)
from handlers.sales.season_ticket_holders import (
    pick_season_start, pick_season_end, pick_season_theaters,
    pick_season_age_min, pick_season_age_max, pick_season_statuses,
    back_to_attach_theater,
)
from handlers.sales.shared_steps import pick_attach_theater
from handlers.sales.media import (
    input_dev_chat_ids, handle_media_action, handle_media_input, handle_media_text,
)
from handlers.sales.message import ask_message, handle_admin_message, handle_keep_text, back_from_get_message
from handlers.sales.preview import preview_action
from handlers.sales.length_fix import handle_length_action
from settings.settings import COMMAND_DICT

# Shared handler for "Back" from action:continue flow — returns to campaign action menu
_campaign_back_handler = CallbackQueryHandler(
    back_to_campaign_action, pattern='^Назад-campaign_action_back$'
)

states = {
    MENU: [
        cancel_callback_handler,
        back_callback_handler,
    ],
    PICK_EXISTING_CAMPAIGN: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_existing_campaign, pattern='^sales:existing'),
    ],
    CAMPAIGN_ACTION_MENU: [
        cancel_callback_handler,
        CallbackQueryHandler(handle_campaign_action, pattern='^sales:action'),
        CallbackQueryHandler(handle_campaign_action, pattern='^Назад-campaign_action_back'),
        back_callback_handler,
    ],
    PICK_TYPE: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_type, pattern='^sales:type'),
    ],
    PICK_THEATER: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_theater, pattern='^sales:theater'),
    ],
    PICK_SCOPE: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_scope, pattern='^sales:scope'),
    ],
    PICK_SCHEDULES: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_schedules, pattern='^sales:schedule_page'),
        CallbackQueryHandler(pick_schedules, pattern='^sales:schedule'),
    ],
    PICK_AUDIENCE_THEATER: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_audience_theater, pattern='^sales:aud_theater'),
    ],
    PICK_ATTACH_THEATER: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_attach_theater, pattern='^sales:attach_theater'),
    ],
    PICK_FILTERS: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_filters, pattern='^sales:filters'),
    ],
    PICK_FILTER_STATUS: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_filter_status, pattern='^sales:f_status'),
    ],
    PICK_FILTER_TYPE_EVENT: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_filter_type_event, pattern='^sales:f_type_event'),
    ],
    PICK_FILTER_THEATER_EVENT: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_filter_theater_event, pattern='^sales:f_theater_event'),
    ],
    PICK_FILTER_SCHEDULE_EVENT: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_filter_schedule_event, pattern='^sales:f_schedule_page'),
        CallbackQueryHandler(pick_filter_schedule_event, pattern='^sales:f_schedule'),
    ],
    PICK_FILTER_BASE_TICKET: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_filter_base_ticket, pattern='^sales:f_base_ticket'),
    ],
    PICK_TICKET_IDS: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        MessageHandler(filters.TEXT & ~filters.COMMAND, pick_ticket_ids),
    ],
    PICK_FILTER_CHILD_AGE_MIN: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_filter_child_age_min, pattern='^sales:f_child_age_min'),
    ],
    PICK_FILTER_CHILD_AGE_MAX: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_filter_child_age_max, pattern='^sales:f_child_age_max'),
    ],
    BUILD_AUDIENCE: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        MessageHandler(filters.TEXT & ~filters.COMMAND, input_dev_chat_ids),
        CallbackQueryHandler(ask_message, pattern='^sales:next_message'),
    ],
    PREVIEW: [
        cancel_callback_handler,
        _campaign_back_handler,
        CallbackQueryHandler(preview_action, pattern='^sales:preview'),
        CallbackQueryHandler(preview_action, pattern='^run$'),
        CallbackQueryHandler(preview_action, pattern='^Назад-preview_back'),
        back_callback_handler,
    ],
    # SEASON_TICKET_HOLDERS states
    PICK_SEASON_START: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_season_start, pattern='^sales:season_start'),
        MessageHandler(filters.TEXT & ~filters.COMMAND, pick_season_start),
    ],
    PICK_SEASON_END: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_season_end, pattern='^sales:season_end'),
        MessageHandler(filters.TEXT & ~filters.COMMAND, pick_season_end),
    ],
    PICK_SEASON_THEATERS: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_season_theaters, pattern='^sales:season_theater_page'),
        CallbackQueryHandler(pick_season_theaters, pattern='^sales:season_theater'),
    ],
    PICK_SEASON_AGE_MIN: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_season_age_min, pattern='^sales:season_age_min'),
    ],
    PICK_SEASON_AGE_MAX: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_season_age_max, pattern='^sales:season_age_max'),
    ],
    PICK_SEASON_STATUSES: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(pick_season_statuses, pattern='^sales:season_status'),
    ],
    # GET_MESSAGE — text only (media collected in GET_MEDIA)
    GET_MESSAGE: [
        cancel_callback_handler,
        _campaign_back_handler,
        CallbackQueryHandler(back_from_get_message, pattern='^Назад'),
        CallbackQueryHandler(handle_keep_text, pattern='^keep_text$'),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_message),
    ],
    # GET_MEDIA — collect media files
    GET_MEDIA: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(handle_media_action, pattern='^sales:media'),
        MessageHandler(filters.PHOTO, handle_media_input),
        MessageHandler(filters.VIDEO, handle_media_input),
        MessageHandler(filters.ANIMATION, handle_media_input),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_media_text),
    ],
    # LENGTH_FIX — caption too long
    LENGTH_FIX: [
        cancel_callback_handler,
        _campaign_back_handler,
        back_callback_handler,
        CallbackQueryHandler(handle_length_action, pattern='^sales:length'),
    ],
}

sales_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT.get('SALES', ['sales'])[0], start_sales),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='sales',
    persistent=True,
    allow_reentry=True,
)

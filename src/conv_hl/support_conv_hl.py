from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler,
)

from custom_filters import filter_admin
from handlers import support_hl, promotion_hl, schedule_hl
from handlers.sub_hl import (
    update_base_ticket_data, update_theater_event_data,
    update_special_ticket_price, update_schedule_event_data,
    update_custom_made_format_data, update_promotion_data
)
from conv_hl import (
    F_text_and_no_command, cancel_callback_handler, back_callback_handler,
    common_fallbacks
)
from settings.settings import COMMAND_DICT

states = {
    1: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(support_hl.get_updates_option, '^update_data$'),
        CallbackQueryHandler(support_hl.choice_db_settings, '^db$'),
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
    ],
    'updates': [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(update_base_ticket_data, COMMAND_DICT['UP_BT_DATA'][0]),
        CallbackQueryHandler(update_theater_event_data, COMMAND_DICT['UP_TE_DATA'][0]),
        CallbackQueryHandler(update_schedule_event_data, COMMAND_DICT['UP_SE_DATA'][0]),
        CallbackQueryHandler(update_special_ticket_price, COMMAND_DICT['UP_SPEC_PRICE'][0]),
        CallbackQueryHandler(update_custom_made_format_data, COMMAND_DICT['UP_CMF_DATA'][0]),
        CallbackQueryHandler(update_promotion_data, COMMAND_DICT['UP_PROM_DATA'][0]),
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        # CallbackQueryHandler(update_ticket_data, COMMAND_DICT['UP_TICKET_DATA'][0]),
    ],
    2: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(support_hl.get_settings, pattern='^db|$'),
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
    ],
    3: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(support_hl.theater_event_select,
                             r'^theater_event_select(_[pf]_.*)?$'),
        CallbackQueryHandler(support_hl.theater_event_preview,
                             '^theater_event_create$'),
        CallbackQueryHandler(support_hl.theater_event_update_start,
                             r'^theater_event_edit_(\d+)$'),

        CallbackQueryHandler(support_hl.schedule_event_select,
                             r'^schedule_event_select(_[pf]_.*)?$'),
        CallbackQueryHandler(schedule_hl.schedule_create_start,
                             '^schedule_event_create$'),
        CallbackQueryHandler(schedule_hl.schedule_update_start,
                             r'^schedule_event_edit_(\d+)$'),

        CallbackQueryHandler(support_hl.promotion_select,
                             r'^promotion_select(_[pf]_.*)?$'),
        CallbackQueryHandler(support_hl.base_ticket_select,
                             r'^base_ticket_select(_[pf]_.*)?$'),
        CallbackQueryHandler(support_hl.base_ticket_update_start,
                             r'^base_ticket_edit_(\d+)$'),

        CallbackQueryHandler(support_hl.event_type_select,
                             r'^event_type_select(_p_.*)?$'),
        CallbackQueryHandler(support_hl.event_type_update_start,
                             r'^event_type_edit_(\d+)$'),
        CallbackQueryHandler(promotion_hl.promotion_create_start,
                             '^promotion_create$'),
        CallbackQueryHandler(promotion_hl.promotion_update_start,
                             '^promotion_update$'),
        CallbackQueryHandler(promotion_hl.handle_promotion_to_update,
                             r'^upd_prom_(\d+)$'),
        CallbackQueryHandler(promotion_hl.promotion_delete_start,
                             '^promotion_delete$'),
        CallbackQueryHandler(promotion_hl.handle_promotion_delete,
                             r'^del_prom_(\d+)$'),
        CallbackQueryHandler(promotion_hl.confirm_promotion_delete,
                             r'^confirm_del_prom_(\d+)$'),
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
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
    43: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, support_hl.promotion_check),
        CallbackQueryHandler(support_hl.promotion_create, '^accept$'),
    ],
    50: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_name),
    ],
    51: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.generate_prom_code, '^generate_code$'),
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_code),
    ],
    52: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        CallbackQueryHandler(promotion_hl.handle_prom_type, '^percentage$|^fixed$'),
    ],
    53: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_value),
    ],
    54: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_min_sum),
    ],
    55: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        CallbackQueryHandler(promotion_hl.handle_prom_visible, '^yes$|^no$'),
    ],
    56: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        CallbackQueryHandler(promotion_hl.handle_prom_verify, '^yes$|^no$'),
    ],
    57: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        CallbackQueryHandler(promotion_hl.handle_prom_vtext, '^skip$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_vtext),
    ],
    58: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        CallbackQueryHandler(promotion_hl.handle_prom_start, '^skip$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_start),
    ],
    59: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        CallbackQueryHandler(promotion_hl.handle_prom_expire, '^skip$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_expire),
    ],
    60: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_max_usage),
    ],
    61: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        CallbackQueryHandler(promotion_hl.handle_prom_desc, '^skip$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_desc),
    ],
    67: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.ask_promotion_summary, '^skip_to_confirm$'),
        MessageHandler(F_text_and_no_command, promotion_hl.handle_prom_max_usage_user),
    ],
    63: [  # PROM_RESTRICT_TYPE
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.handle_restrict_type_cb, r'^prm_rt_.*$'),
    ],
    64: [  # PROM_RESTRICT_THEATER
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.handle_restrict_theater_cb, r'^prm_rth_.*$'),
    ],
    65: [  # PROM_RESTRICT_TICKET
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.handle_restrict_ticket_cb, r'^prm_rbt_.*$'),
    ],
    66: [  # PROM_RESTRICT_SCHEDULE
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.handle_restrict_schedule_cb, r'^prm_rse_.*$'),
    ],
    # ===== Schedule wizard states =====
    70: [  # SCH_TYPE
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(schedule_hl.handle_type_selected, r'^sch_tp_\d+$'),
    ],
    71: [  # SCH_THEATER
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(schedule_hl.handle_theater_cb, r'^sch_th_.*$'),
    ],
    72: [  # SCH_DATETIME
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(schedule_hl.handle_datetime_btn, r'^sch_dt_.*$'),
        MessageHandler(F_text_and_no_command, schedule_hl.handle_datetime),
    ],
    73: [  # SCH_QTY_CHILD
        back_callback_handler,
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, schedule_hl.handle_qty_child),
    ],
    74: [  # SCH_QTY_ADULT
        back_callback_handler,
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, schedule_hl.handle_qty_adult),
    ],
    75: [  # SCH_PRICE_TYPE
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(schedule_hl.handle_price_type, r'^sch_pt_.*$'),
    ],
    76: [  # SCH_FLAGS
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(schedule_hl.handle_flags, r'^sch_(fg|ft|fs|next_bt|flags_done)$'),
    ],
    77: [  # SCH_BT_SELECT
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(schedule_hl.handle_base_tickets_cb, r'^sch_bt_.*$'),
    ],
    78: [  # SCH_CONFIRM
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(schedule_hl.edit_type_start, r'^sch_edit_type$'),
        CallbackQueryHandler(schedule_hl.edit_theater_start, r'^sch_edit_theater$'),
        CallbackQueryHandler(schedule_hl.edit_datetime_start, r'^sch_edit_datetime$'),
        CallbackQueryHandler(schedule_hl.edit_qty_child_start, r'^sch_edit_qty_child$'),
        CallbackQueryHandler(schedule_hl.edit_qty_adult_start, r'^sch_edit_qty_adult$'),
        CallbackQueryHandler(schedule_hl.edit_price_type_start, r'^sch_edit_price_type$'),
        CallbackQueryHandler(schedule_hl.edit_flags_start, r'^sch_edit_flags$'),
        CallbackQueryHandler(schedule_hl.edit_bt_start, r'^sch_edit_bt$'),
        CallbackQueryHandler(schedule_hl.edit_turn_start, r'^sch_edit_turn$'),
        CallbackQueryHandler(schedule_hl.handle_confirm_save, r'^sch_accept$'),
    ],
    62: [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(promotion_hl.handle_prom_name_start, '^prom_edit_name$'),
        CallbackQueryHandler(promotion_hl.handle_prom_code_start, '^prom_edit_code$'),
        CallbackQueryHandler(promotion_hl.ask_prom_type, '^prom_edit_type$'),
        CallbackQueryHandler(promotion_hl.handle_prom_min_sum_start, '^prom_edit_min_sum$'),
        CallbackQueryHandler(promotion_hl.handle_prom_visible_start, '^prom_edit_visible$'),
        CallbackQueryHandler(promotion_hl.handle_prom_verify_start, '^prom_edit_verify$'),
        CallbackQueryHandler(promotion_hl.handle_prom_vtext_start, '^prom_edit_vtext$'),
        CallbackQueryHandler(promotion_hl.handle_prom_start_start, '^prom_edit_start_date$'),
        CallbackQueryHandler(promotion_hl.handle_prom_expire_start, '^prom_edit_expire_date$'),
        CallbackQueryHandler(promotion_hl.handle_prom_max_usage_start, '^prom_edit_max_usage$'),
        CallbackQueryHandler(promotion_hl.handle_prom_max_usage_user_start, '^prom_edit_max_usage_user$'),
        CallbackQueryHandler(promotion_hl.handle_prom_desc_start, '^prom_edit_desc$'),
        # Restrictions menu
        CallbackQueryHandler(promotion_hl.open_restrict_type, '^prom_restrict_type$'),
        CallbackQueryHandler(promotion_hl.open_restrict_theater, '^prom_restrict_theater$'),
        CallbackQueryHandler(promotion_hl.open_restrict_ticket, '^prom_restrict_ticket$'),
        CallbackQueryHandler(promotion_hl.open_restrict_schedule, '^prom_restrict_schedule$'),
        CallbackQueryHandler(promotion_hl.handle_promotion_delete, r'^del_prom_(\d+)$'),
        CallbackQueryHandler(promotion_hl.promotion_confirm_save, '^accept$'),
    ],
}


support_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler('settings',
                       support_hl.start_settings,
                       filter_admin),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='support',
    persistent=True,
    allow_reentry=True
)

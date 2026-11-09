from telegram.ext import (
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters,
)

from handlers import reserve_hl, reserve_admin_hl, main_hl
from conv_hl import (
    handlers_event_selection, handlers_client_data_selection,
    cancel_callback_handler, back_callback_handler,
    F_text_and_no_command, common_fallbacks
)
from settings.settings import COMMAND_DICT

states = {
    1: [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.choice_month, pattern='params'),
        CallbackQueryHandler(reserve_admin_hl.enter_event_id, pattern='id'),
    ],
    2: [
        cancel_callback_handler,
        back_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_admin_hl.choice_option_of_reserve),
    ],
    'TICKET': [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(reserve_admin_hl.start_forma_info,
                             pattern='^TICKET'),
    ],
    'CUSTOM_TICKET_PARAMS': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TICKET'),
        MessageHandler(F_text_and_no_command,
                       reserve_admin_hl.handle_custom_ticket_params),
    ],
    'EMAIL': [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(reserve_admin_hl.email_confirm, pattern=r'.*email_confirm'),
        MessageHandler(F_text_and_no_command, reserve_admin_hl.get_email_admin),
    ],
    'CONFIRM_RESERVATION': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-CHILDREN'),
        CallbackQueryHandler(reserve_hl.confirm_go_pay, pattern='^PAY$'),
        CallbackQueryHandler(reserve_hl.confirm_admin_reserved, pattern='^RESERVE_WITHOUT_PAY$'),
        CallbackQueryHandler(reserve_hl.confirm_admin_without_payment, pattern='^CONFIRM_WITHOUT_PAY$'),
        CallbackQueryHandler(reserve_hl.reset_promo, pattern='^RESET_PROMO$'),
        CallbackQueryHandler(reserve_hl.ask_promo_code, pattern='^PROMO$'),
        CallbackQueryHandler(reserve_hl.apply_option_promo, pattern='^PROMO_OPTION'),
    ],
    'PROMOCODE_INPUT': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-CONFIRM_RESERVATION'),
        MessageHandler(F_text_and_no_command, reserve_hl.handle_promo_code_input),
    ],
    'PAID': [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.confirm_payment, pattern='^confirm_payment$'),
        CallbackQueryHandler(reserve_hl.processing_successful_notification, pattern='Next'),
        MessageHandler(
            filters.PHOTO | filters.Document.ALL,
            reserve_hl.forward_photo_or_file
        ),
    ],
    'WAIT_RECEIPT': [
        cancel_callback_handler,
        MessageHandler(
            filters.PHOTO | filters.Document.ALL,
            reserve_hl.handle_receipt_file
        ),
    ],
    'WAIT_DOCUMENT': [
        cancel_callback_handler,
        MessageHandler(
            filters.PHOTO | filters.Document.ALL,
            reserve_hl.handle_certificate_file
        ),
    ],
}

for key in handlers_event_selection.keys():
    states[key] = handlers_event_selection[key]
for key in handlers_client_data_selection.keys():
    states[key] = handlers_client_data_selection[key]

reserve_admin_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['RESERVE_ADMIN'][0],
                       reserve_admin_hl.event_selection_option),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='reserve_admin',
    persistent=True,
    allow_reentry=True
)

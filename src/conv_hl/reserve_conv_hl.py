from telegram.ext import (
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters,
)
from telegram.ext.filters import Text

from custom_filters.admin import filter_list_cmd
from handlers import reserve_hl, main_hl, offer_hl, ticket_hl
from conv_hl import (
    handlers_event_selection, handlers_client_data_selection,
    cancel_callback_handler, back_callback_handler,
    F_text_and_no_command, common_fallbacks
)
from settings.settings import COMMAND_DICT

states = {
    'TICKET': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TIME'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-DATE'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-SHOW'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MODE'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-REP_GROUP'),
        CallbackQueryHandler(ticket_hl.get_ticket, pattern='^TICKET'),
        CallbackQueryHandler(reserve_hl.write_list_of_waiting, pattern=r'^CHOOSING\|WAIT'),
    ],
    'OFFER': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TICKET'),
        MessageHandler(Text(('Принимаю',)), offer_hl.get_agreement),
    ],
    'EMAIL': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TICKET'),
        CallbackQueryHandler(reserve_hl.get_email, pattern='email_confirm'),
        MessageHandler(F_text_and_no_command, reserve_hl.get_email),
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
    'LIST': [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(reserve_hl.send_clients_data, pattern='^LIST'),
    ],
    'CHOOSING': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-TIME'),
        CallbackQueryHandler(reserve_hl.choice_mode, pattern=r'^CHOOSING\|OTHER_TIME'),
        CallbackQueryHandler(reserve_hl.write_list_of_waiting, pattern=r'^CHOOSING\|WAIT'),
    ],
    'MODE': [
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.choice_month, pattern=r'^MODE\|DATE'),
        CallbackQueryHandler(reserve_hl.choice_show_by_repertoire, pattern=r'^MODE\|REPERTOIRE'),
    ],
    'REP_GROUP': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern=r'^Назад-MODE'),
        CallbackQueryHandler(reserve_hl.choice_show_by_repertoire, pattern=r'^REP_GROUP'),
    ],
    'PHONE_FOR_WAITING': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern=r'^Назад-TICKET'),
        CallbackQueryHandler(reserve_hl.phone_confirm, pattern=r'.*phone_confirm'),
        MessageHandler(F_text_and_no_command, reserve_hl.get_phone_for_waiting),
    ],
    'CONFIRM_RESERVATION': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-CHILDREN'),
        CallbackQueryHandler(reserve_hl.confirm_go_pay, pattern='^PAY$'),
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
}

for key in handlers_event_selection.keys():
    states[key] = handlers_event_selection[key]
for key in handlers_client_data_selection.keys():
    states[key] = handlers_client_data_selection[key]


reserve_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['RESERVE'][0], reserve_hl.choice_mode),
        CommandHandler(COMMAND_DICT['LIST'][0],
                       reserve_hl.choice_mode,
                       filter_list_cmd),
        CallbackQueryHandler(reserve_hl.processing_successful_notification, pattern='Next'),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='reserve',
    persistent=True,
    allow_reentry=True
)

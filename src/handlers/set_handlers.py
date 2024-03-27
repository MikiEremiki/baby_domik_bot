import logging

from telegram.ext import (
    CommandHandler, CallbackQueryHandler, MessageHandler, filters,
)

from handlers.webhook_hl import WebhookHandler
from handlers import main_hl
from handlers.error_hl import error_handler
from handlers.timeweb_hl import get_balance
from handlers.sub_hl import (
    update_ticket_data, update_show_data, update_admin_info, update_bd_price,
    update_special_ticket_price
)
from conv_hl import (
    reserve_conv_hl, reserve_admin_conv_hl, list_wait_conv_hl, birthday_conv_hl,
    birthday_paid_conv_hl, afisha_conv_hl, support_conv_hl
)
from middleware import add_middleware_glob_on_off, add_middleware_db_handlers
from utilities.utl_func import (
    echo, send_log,
    get_location, get_contact, request_contact_location,
    print_ud, clean_ud, clean_bd,
    create_or_connect_topic, del_topic, update_config,
)
from settings.settings import ADMIN_ID, COMMAND_DICT

set_handlers_logger = logging.getLogger('bot.set_handlers')


def set_handlers(application, config):
    add_middleware_db_handlers(application, config)
    add_middleware_glob_on_off(application, config)

    application.add_handlers([
        CommandHandler(COMMAND_DICT['START'][0], main_hl.start),
        CommandHandler('reset', main_hl.reset),
        CommandHandler('send', main_hl.send_approve_msg),
        CommandHandler('echo', echo),
    ])

    application.add_handlers([
        CallbackQueryHandler(main_hl.confirm_reserve, '^confirm-reserve'),
        CallbackQueryHandler(main_hl.reject_reserve, '^reject-reserve'),
        CallbackQueryHandler(main_hl.confirm_birthday, '^confirm-birthday'),
        CallbackQueryHandler(main_hl.reject_birthday, '^reject-birthday'),
    ])

    conversation_handlers = [
        reserve_conv_hl,
        reserve_admin_conv_hl,
        list_wait_conv_hl,
        birthday_conv_hl,
        birthday_paid_conv_hl,
        afisha_conv_hl,
        support_conv_hl,
    ]
    application.add_handlers(conversation_handlers)

    filter_admin = filters.User(ADMIN_ID)
    application.add_handlers([
        CommandHandler('clean_ud', clean_ud, filter_admin),
        CommandHandler('print_ud', print_ud, filter_admin),
        CommandHandler('clean_bd', clean_bd, filter_admin),
        CommandHandler('update_config', update_config, filter_admin),
        CommandHandler(COMMAND_DICT['LOG'][0], send_log, filter_admin),
        CommandHandler(COMMAND_DICT['CB_TW'][0], get_balance, filter_admin),
        CommandHandler(COMMAND_DICT['TOPIC_DEL'][0], del_topic, filter_admin),
        CommandHandler(COMMAND_DICT['TOPIC_START'][0], create_or_connect_topic,
                       filter_admin),
        CommandHandler(COMMAND_DICT['GLOB_ON_OFF'][0], main_hl.global_on_off,
                       filter_admin),
        CommandHandler(COMMAND_DICT['UP_T_DATA'][0], update_ticket_data,
                       filter_admin),
        CommandHandler(COMMAND_DICT['UP_S_DATA'][0], update_show_data,
                       filter_admin),
        CommandHandler(COMMAND_DICT['UP_BD_PRICE'][0], update_bd_price,
                       filter_admin),
        CommandHandler(COMMAND_DICT['UP_SPEC_PRICE'][0],
                       update_special_ticket_price,
                       filter_admin),
        CommandHandler(COMMAND_DICT['ADM_INFO'][0],
                       update_admin_info,
                       filter_admin),
    ])

    application.add_handler(
        CommandHandler('rcl', request_contact_location))
    application.add_handler(MessageHandler(filters.LOCATION, get_location))
    application.add_handler(MessageHandler(filters.CONTACT, get_contact))

    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.TEXT |
                                    filters.ATTACHMENT |
                                    filters.VIDEO |
                                    filters.PHOTO |
                                    filters.FORWARDED |
                                    filters.Document.IMAGE |
                                    filters.Document.PDF),
        main_hl.feedback_send_msg),
    )
    application.add_handler(MessageHandler(filters.REPLY,
                                           main_hl.feedback_reply_msg))

    application.add_handler(WebhookHandler)

    application.add_error_handler(error_handler)

    set_handlers_logger.info('Всё готово к поллингу')
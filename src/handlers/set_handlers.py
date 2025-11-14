import logging

from telegram.ext import (
    CommandHandler, CallbackQueryHandler, MessageHandler, filters,
)

from handlers import main_hl, reserve_hl
from custom_filters import filter_admin, filter_to_send_msg, REPLY_IN_TOPIC_FROM_BOT
from handlers.sub_hl import (
    update_admin_info, update_bd_price, update_cme_admin_info)
from handlers.webhook_hl import WebhookHandler
from handlers.gspredhook_hl import GspreadhookHandler
from handlers.error_hl import error_handler
from handlers.timeweb_hl import get_balance
from conv_hl import (
    reserve_conv_hl, reserve_admin_conv_hl, list_wait_conv_hl, birthday_conv_hl,
    afisha_conv_hl, support_conv_hl, migration_admin_conv_hl,
)
from middleware import (
    add_glob_on_off_middleware,
    add_db_handlers_middleware,
    add_check_run_conv_hl_middleware
)
from utilities.utl_func import (
    echo, send_log, send_postgres_log,
    get_location, get_contact, request_contact_location,
    print_ud, clean_ud, clean_bd,
    create_or_connect_topic, del_topic, update_config,
)
from settings.settings import COMMAND_DICT

set_handlers_logger = logging.getLogger('bot.set_handlers')


def set_handlers(application, config):
    add_db_handlers_middleware(application, config)
    add_glob_on_off_middleware(application, config)
    add_check_run_conv_hl_middleware(application)

    application.add_handlers([
        CallbackQueryHandler(main_hl.confirm_reserve, '^confirm-reserve'),
        CallbackQueryHandler(main_hl.reject_reserve, '^reject-reserve'),
        CallbackQueryHandler(main_hl.confirm_reserve, '^confirm-studio'),
        CallbackQueryHandler(main_hl.reject_reserve, '^reject-studio'),
        CallbackQueryHandler(main_hl.confirm_birthday, '^confirm-birthday'),
        CallbackQueryHandler(main_hl.reject_birthday, '^reject-birthday'),
    ])

    conversation_handlers = [
        reserve_conv_hl,
        reserve_admin_conv_hl,
        list_wait_conv_hl,
        birthday_conv_hl,
        afisha_conv_hl,
        support_conv_hl,
        migration_admin_conv_hl,
    ]
    application.add_handlers(conversation_handlers)

    application.add_handlers([
        CommandHandler(COMMAND_DICT['START'][0], main_hl.start),
        CommandHandler('reset', main_hl.reset),
        CommandHandler('echo', echo),
    ])

    application.add_handler(
        CallbackQueryHandler(reserve_hl.processing_successful_notification,
                             pattern='Next'))

    application.add_handlers([
        CommandHandler('clean_ud', clean_ud, filter_admin),
        CommandHandler('print_ud', print_ud, filter_admin),
        CommandHandler('clean_bd', clean_bd, filter_admin),
        CommandHandler('update_config', update_config, filter_admin),
        CommandHandler('send_approve_msg',
                       main_hl.send_approve_msg,
                       filter_admin),
        CommandHandler('update_ticket',
                       main_hl.update_ticket,
                       filter_admin),
        CommandHandler('send_msg',
                       main_hl.send_msg,
                       filter_to_send_msg),
        CommandHandler(COMMAND_DICT['LOG'][0], send_log, filter_admin),
        CommandHandler('postgres_log', send_postgres_log, filter_admin),
        CommandHandler(COMMAND_DICT['CB_TW'][0], get_balance, filter_admin),
        CommandHandler(COMMAND_DICT['TOPIC_DEL'][0], del_topic, filter_admin),
        CommandHandler(COMMAND_DICT['TOPIC'][0],
                       create_or_connect_topic,
                       filter_admin),
        CommandHandler(COMMAND_DICT['GLOB_ON_OFF'][0],
                       main_hl.global_on_off,
                       filter_admin),
        CommandHandler(COMMAND_DICT['UP_BD_PRICE'][0],
                       update_bd_price,
                       filter_admin),
        CommandHandler(COMMAND_DICT['ADM_INFO'][0],
                       update_admin_info,
                       filter_admin),
        CommandHandler(COMMAND_DICT['ADM_CME_INFO'][0],
                       update_cme_admin_info,
                       filter_admin),
        CommandHandler('cancel_old_created_tickets',
                       main_hl.manual_cancel_old_created_tickets,
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
    application.add_handler(MessageHandler(
        REPLY_IN_TOPIC_FROM_BOT,
        main_hl.feedback_reply_msg))

    application.add_handler(WebhookHandler)
    application.add_handler(GspreadhookHandler)

    application.add_error_handler(error_handler)

    set_handlers_logger.info('Всё готово к поллингу')

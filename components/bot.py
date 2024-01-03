from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PicklePersistence,
    filters,
    MessageHandler
)

from log.logging_conf import load_log_config
from handlers import main_hl
from handlers.error_hl import error_handler
from handlers.sub_hl import (
    update_ticket_data, update_show_data, update_admin_info
)
from handlers.timeweb_hl import get_balance
from conv_hl.reserve_conv_hl import reserve_conv_hl
from conv_hl.list_wait_conv_hl import list_wait_conv_hl
from conv_hl.birthday_conv_hl import birthday_conv_hl, birthday_paid_conv_hl
from conv_hl.afisha_conv_hl import afisha_conv_hl
from config.settings import API_TOKEN, ADMIN_ID, COMMAND_DICT
from utilities.utl_func import (
    echo, reset, send_log,
    set_menu, set_description, set_ticket_data, set_show_data,
    get_location, get_contact, request_contact_location,
    print_ud, clean_ud, clean_bd,
    create_or_connect_topic, del_topic,
)


async def post_init(application: Application):
    await set_menu(application.bot)
    await set_description(application.bot)
    set_ticket_data(application)
    set_show_data(application)

    application.bot_data.setdefault('admin', {})
    application.bot_data['admin'].setdefault('contacts', {})


def bot():
    bot_logger = load_log_config()
    bot_logger.info('Инициализация бота')

    # TODO Предусмотреть создание папки, на случай если ее нет
    persistence = PicklePersistence(filepath="components/db/conversationbot")
    application = (
        Application.builder()
        .token(API_TOKEN)
        .persistence(persistence)
        .post_init(post_init)

        .build()
    )

    application.add_handler(CommandHandler(COMMAND_DICT['START'][0],
                                           main_hl.start))

    application.add_handler(CallbackQueryHandler(main_hl.confirm_reserve,
                                                 pattern='^confirm-reserve'))
    application.add_handler(CallbackQueryHandler(main_hl.reject_reserve,
                                                 pattern='^reject-reserve'))
    application.add_handler(CallbackQueryHandler(main_hl.confirm_birthday,
                                                 pattern='^confirm-birthday'))
    application.add_handler(CallbackQueryHandler(main_hl.reject_birthday,
                                                 pattern='^reject-birthday'))

    application.add_handler(reserve_conv_hl)
    application.add_handler(list_wait_conv_hl)
    application.add_handler(birthday_conv_hl)
    application.add_handler(birthday_paid_conv_hl)
    application.add_handler(afisha_conv_hl)

    application.add_handler(CommandHandler('echo', echo))
    application.add_handler(CommandHandler('reset', reset))

    application.add_handler(CommandHandler('print_ud', print_ud))
    application.add_handler(CommandHandler('clean_ud', clean_ud))
    application.add_handler(CommandHandler('clean_bd', clean_bd))
    application.add_handler(CommandHandler(
        COMMAND_DICT['UP_T_DATA'][0],
        update_ticket_data,
        filters=filters.User(ADMIN_ID)))
    application.add_handler(CommandHandler(
        COMMAND_DICT['UP_S_DATA'][0],
        update_show_data,
        filters=filters.User(ADMIN_ID)))
    application.add_handler(CommandHandler(
        COMMAND_DICT['LOG'][0],
        send_log,
        filters=filters.User(ADMIN_ID)))
    application.add_handler(CommandHandler(
        COMMAND_DICT['CB_TW'][0],
        get_balance,
        filters=filters.User(ADMIN_ID)))
    application.add_handler(CommandHandler(
        COMMAND_DICT['TOPIC_START'][0],
        create_or_connect_topic,
        filters=filters.User(ADMIN_ID)))
    application.add_handler(CommandHandler(
        COMMAND_DICT['TOPIC_DEL'][0],
        del_topic,
        filters=filters.User(ADMIN_ID)))
    application.add_handler(CommandHandler(
        COMMAND_DICT['ADM_INFO'][0],
        update_admin_info,
        filters=filters.User(ADMIN_ID)))

    application.add_handler(CommandHandler('rcl',
                                           request_contact_location))
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

    application.add_error_handler(error_handler)

    bot_logger.info('Всё готово к поллингу')

    application.run_polling()

    bot_logger.info('Бот остановлен')


if __name__ == '__main__':
    bot()

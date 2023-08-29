from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PicklePersistence,
    filters,
    MessageHandler
)

from handlers import main_hl
from conv_hl.reserve_conv_hl import reserve_conv_hl
from conv_hl.birthday_conv_hl import birthday_conv_hl, birthday_paid_conv_hl
from conv_hl.afisha_conv_hl import afisha_conv_hl
from log.logging_conf import load_log_config
from handlers.timeweb_hl import get_balance
from utilities.settings import ADMIN_CHAT_ID
from utilities.settings import API_TOKEN, COMMAND_DICT
from utilities.utl_func import (
    echo,
    reset,
    send_log,
    set_menu,
    print_ud,
    set_description
)


def bot():
    bot_logger = load_log_config()
    bot_logger.info('Инициализация бота')

    # TODO Предусмотреть создание папки, на случай если ее нет
    persistence = PicklePersistence(filepath="db/conversationbot")
    application = (
        Application.builder()
        .token(API_TOKEN)
        .persistence(persistence)

        .build()
    )

    # TODO Переписать через специальный метод к Application.post_init
    application.job_queue.run_once(set_menu, 0)
    application.job_queue.run_once(set_description, 0)

    application.add_handler(CommandHandler(COMMAND_DICT['START'][0],
                                           main_hl.start))

    application.add_handler(reserve_conv_hl)
    application.add_handler(birthday_conv_hl)
    application.add_handler(birthday_paid_conv_hl)
    application.add_handler(afisha_conv_hl)

    application.add_handler(CallbackQueryHandler(main_hl.confirm_reserve,
                                                 pattern='^confirm-reserve'))
    application.add_handler(CallbackQueryHandler(main_hl.reject_reserve,
                                                 pattern='^reject-reserve'))
    application.add_handler(CallbackQueryHandler(main_hl.confirm_birthday,
                                                 pattern='^confirm-birthday'))
    application.add_handler(CallbackQueryHandler(main_hl.reject_birthday,
                                                 pattern='^reject-birthday'))

    application.add_handler(CommandHandler('echo', echo))
    application.add_handler(CommandHandler('reset', reset))

    application.add_handler(CommandHandler('print_ud', print_ud))
    application.add_handler(CommandHandler(
        'log',
        send_log,
        filters=filters.Chat(chat_id=ADMIN_CHAT_ID)
    ))
    application.add_handler(
        CommandHandler(
            COMMAND_DICT['CB_TW'][0],
            get_balance,
            filters=filters.Chat(chat_id=ADMIN_CHAT_ID)
        )
    )

    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.TEXT |
                                    filters.ATTACHMENT |
                                    filters.VIDEO |
                                    filters.PHOTO |
                                    filters.FORWARDED |
                                    filters.Document.IMAGE |
                                    filters.Document.PDF),
        main_hl.feedback_send_msg)
    )

    bot_logger.info('Всё готово к поллингу')

    application.run_polling()

    bot_logger.info('Бот остановлен')


if __name__ == '__main__':
    bot()

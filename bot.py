from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PicklePersistence
)

from handlers import main_hl
from conv_hl.reserve_conv_hl import reserve_conv_hl
from conv_hl.birthday_conv_hl import birthday_conv_hl, birthday_paid_conv_hl
from log.logging_conf import load_log_config
from utilities.utl_func import echo, reset, send_log, set_menu, print_ud
from utilities.settings import (
    API_TOKEN,
    COMMAND_DICT,
)


def bot():
    bot_logger = load_log_config()
    bot_logger.info('Инициализация бота')

    persistence = PicklePersistence(filepath="db/conversationbot")
    application = (
        Application.builder()
        .token(API_TOKEN)
        .persistence(persistence)

        .build()
    )

    application.job_queue.run_once(set_menu, 0)

    application.add_handler(CommandHandler(COMMAND_DICT['START'][0],
                                           main_hl.start))

    application.add_handler(reserve_conv_hl)
    application.add_handler(birthday_conv_hl)
    application.add_handler(birthday_paid_conv_hl)

    application.add_handler(CallbackQueryHandler(main_hl.confirm_reserve,
                                                 pattern='^confirm-reserve'))
    application.add_handler(CallbackQueryHandler(main_hl.reject_reserve,
                                                 pattern='^reject-reserve'))
    application.add_handler(CallbackQueryHandler(main_hl.confirm_birthday,
                                                 pattern='^confirm-birthday'))
    application.add_handler(CallbackQueryHandler(main_hl.reject_birthday,
                                                 pattern='^reject-birthday'))

    application.add_handler(CommandHandler('echo', echo))
    application.add_handler(CommandHandler('log', send_log))
    application.add_handler(CommandHandler('reset', reset))
    application.add_handler(CommandHandler('print_ud', print_ud))

    bot_logger.info('Всё готово к поллингу')

    application.run_polling()

    bot_logger.info('Бот остановлен')


if __name__ == '__main__':
    bot()

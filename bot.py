from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PicklePersistence
)

import handlers.main_hl as hl
from conv_hl.reserve_conv_hl import reserve_conv_hl
from conv_hl.birthday_conv_hl import birthday_conv_hl
from log_debug.logging_conf import load_log_config
from utilities.utilities import echo, send_log, set_menu
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

    application.add_handler(CommandHandler(COMMAND_DICT['START'][0], hl.start))

    application.add_handler(reserve_conv_hl)
    application.add_handler(CallbackQueryHandler(hl.confirm, pattern='^Разрешить'))
    application.add_handler(CallbackQueryHandler(hl.reject, pattern='^Отклонить'))

    application.add_handler(CommandHandler('echo', echo))
    application.add_handler(CommandHandler('log', send_log))

    bot_logger.info('Всё готово к поллингу')

    application.run_polling()

    bot_logger.info('Бот остановлен')


if __name__ == '__main__':
    bot()

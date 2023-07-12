from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    PicklePersistence
)

import handlers as hl
from log_debug.logging_conf import load_log_config
from utilites import echo, send_log, set_menu
from settings import (
    API_TOKEN,
    COMMAND_DICT,
)


def bot():
    bot_logger = load_log_config()
    bot_logger.info('Инициализация бота')

    persistence = PicklePersistence(filepath="conversationbot")
    application = (
        Application.builder()
        .token(API_TOKEN)
        .persistence(persistence)

        .build()
    )

    application.job_queue.run_once(set_menu, 0)

    application.add_handler(CommandHandler(COMMAND_DICT['START'][0], hl.start))
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler(COMMAND_DICT['RESERVE'][0], hl.choice_show),
            CommandHandler(COMMAND_DICT['LIST'][0], hl.choice_show),
        ],
        states={
            'DATE': [
                CallbackQueryHandler(hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(hl.choice_time),
            ],
            'TIME': [
                CallbackQueryHandler(hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(hl.back_date, pattern='^Назад$'),
                CallbackQueryHandler(hl.choice_option_of_reserve),
            ],
            'ORDER': [
                CallbackQueryHandler(hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(hl.back_time, pattern='^Назад$'),
                CallbackQueryHandler(hl.check_and_send_buy_info),
            ],
            'PAID': [
                CallbackQueryHandler(hl.cancel, pattern='^Отменить'),
                MessageHandler(
                    filters.PHOTO | filters.ATTACHMENT,
                    hl.forward_photo_or_file
                ),
            ],
            'FORMA': [
                MessageHandler(filters.TEXT, hl.get_name_adult),
            ],
            'PHONE': [
                MessageHandler(filters.TEXT, hl.get_phone),
            ],
            'CHILDREN': [
                MessageHandler(filters.TEXT, hl.get_name_children),
            ],
            'LIST': [
                CallbackQueryHandler(hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(hl.back_date, pattern='^Назад$'),
                CallbackQueryHandler(hl.send_clients_data),
            ],
            'CHOOSING': [
                MessageHandler(
                    filters.Regex('^(Выбрать другое время)$'),
                    hl.choice_show
                ),
                MessageHandler(
                    filters.Regex('^(Записаться в лист ожидания)$'),
                    hl.write_list_of_waiting
                ),
            ],
            'PHONE_FOR_WAITING': [
                MessageHandler(filters.TEXT, hl.get_phone_for_waiting),
            ],
            ConversationHandler.TIMEOUT: [hl.TIMEOUT_HANDLER]
        },
        fallbacks=[CommandHandler('help', hl.help_command)],
        conversation_timeout=15*60,  # 15 мин
        name="my_conversation",
        persistent=True,
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(hl.confirm, pattern='^Разрешить'))
    application.add_handler(CallbackQueryHandler(hl.reject, pattern='^Отклонить'))

    application.add_handler(CommandHandler('echo', echo))
    application.add_handler(CommandHandler('log', send_log))

    bot_logger.info('Всё готово к поллингу')

    application.run_polling()

    bot_logger.info('Бот остановлен')


if __name__ == '__main__':
    bot()

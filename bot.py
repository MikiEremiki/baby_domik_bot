import logging

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters
)

from warnings import filterwarnings
from telegram.warnings import PTBUserWarning

import handlers as hl
from utilites import echo
from settings import (
    API_TOKEN,
    COMMAND_DICT,
)

# Отключено предупреждение, для ConversationHandler
filterwarnings(
    action="ignore",
    message=r".*CallbackQueryHandler",
    category=PTBUserWarning
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def bot():
    application = Application.builder().token(API_TOKEN)

    # Для решения проблемы ошибки telegram.error.NetworkError:
    # httpx.LocalProtocolError: Invalid input ConnectionInputs.SEND_HEADERS
    # in state ConnectionState.CLOSED используем вместо h2 -> h1.1
    application = application.http_version('1.1')
    application = application.get_updates_http_version('1.1')

    application = application.build()

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
              CallbackQueryHandler(hl.send_clients_data)
            ],
            ConversationHandler.TIMEOUT: [hl.TIMEOUT_HANDLER]
        },
        fallbacks=[CommandHandler('help', hl.help_command)],
        conversation_timeout=15*60  # 15 мин
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(hl.confirm, pattern='^Разрешить'))
    application.add_handler(CallbackQueryHandler(hl.reject, pattern='^Отклонить'))

    application.add_handler(CommandHandler('echo', echo))

    application.run_polling()


if __name__ == '__main__':
    bot()

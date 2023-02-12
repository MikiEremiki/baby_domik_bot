import logging

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
)

from warnings import filterwarnings
from telegram.warnings import PTBUserWarning

import handlers as hl
from settings import API_TOKEN

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
    """

    :return:
    """
    application = Application.builder().token(API_TOKEN).build()

    application.add_handler(CommandHandler('start', hl.start))
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('choice', hl.choice_show)],
        states={
            'DATE': [
                CallbackQueryHandler(hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(hl.choice_time),
            ],
            'TIME': [
                CallbackQueryHandler(hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(hl.back_date, pattern='^Назад$'),
                CallbackQueryHandler(hl.choice_number_of_seats),
            ],
            'ORDER': [
                CallbackQueryHandler(hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(hl.back_time, pattern='^Назад$'),
                CallbackQueryHandler(hl.send_qr_code),
            ],
            'PAID': [
                CallbackQueryHandler(hl.cancel, pattern='^Отменить'),
                CallbackQueryHandler(hl.approve, pattern='^Подтвердить'),
            ],
        },
        fallbacks=[CommandHandler('help', hl.help_command)],
    )
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(hl.reject, pattern='^Отклонить'))
    application.add_handler(CallbackQueryHandler(hl.confirm, pattern='^Разрешить'))

    application.run_polling()


if __name__ == '__main__':
    bot()

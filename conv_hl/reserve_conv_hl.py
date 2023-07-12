from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from handlers import reserve_hl, main_hl
from settings import COMMAND_DICT


reserve_conv_hl = ConversationHandler(
        entry_points=[
            CommandHandler(COMMAND_DICT['RESERVE'][0], reserve_hl.choice_show),
            CommandHandler(COMMAND_DICT['LIST'][0], reserve_hl.choice_show),
        ],
        states={
            'DATE': [
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(reserve_hl.choice_time),
            ],
            'TIME': [
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(main_hl.back_date, pattern='^Назад$'),
                CallbackQueryHandler(reserve_hl.choice_option_of_reserve),
            ],
            'ORDER': [
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(main_hl.back_time, pattern='^Назад$'),
                CallbackQueryHandler(reserve_hl.check_and_send_buy_info),
            ],
            'PAID': [
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
                MessageHandler(
                    filters.PHOTO | filters.ATTACHMENT,
                    reserve_hl.forward_photo_or_file
                ),
            ],
            'FORMA': [
                MessageHandler(filters.TEXT, reserve_hl.get_name_adult),
            ],
            'PHONE': [
                MessageHandler(filters.TEXT, reserve_hl.get_phone),
            ],
            'CHILDREN': [
                MessageHandler(filters.TEXT, reserve_hl.get_name_children),
            ],
            'LIST': [
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить$'),
                CallbackQueryHandler(main_hl.back_date, pattern='^Назад$'),
                CallbackQueryHandler(reserve_hl.send_clients_data),
            ],
            'CHOOSING': [
                MessageHandler(
                    filters.Regex('^(Выбрать другое время)$'),
                    reserve_hl.choice_show
                ),
                MessageHandler(
                    filters.Regex('^(Записаться в лист ожидания)$'),
                    reserve_hl.write_list_of_waiting
                ),
            ],
            'PHONE_FOR_WAITING': [
                MessageHandler(filters.TEXT, reserve_hl.get_phone_for_waiting),
            ],
            ConversationHandler.TIMEOUT: [reserve_hl.TIMEOUT_HANDLER]
        },
        fallbacks=[CommandHandler('help', main_hl.help_command)],
        conversation_timeout=15*60,  # 15 мин
        name="my_conversation",
        persistent=True,
        # allow_reentry=True
    )

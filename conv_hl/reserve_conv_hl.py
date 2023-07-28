from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from handlers import reserve_hl, main_hl
from utilities.settings import COMMAND_DICT
from utilities.utl_func import reset


reserve_conv_hl = ConversationHandler(
        entry_points=[
            CommandHandler(COMMAND_DICT['RESERVE'][0], reserve_hl.choice_show),
            CommandHandler(COMMAND_DICT['LIST'][0], reserve_hl.choice_show),
        ],
        states={
            'DATE': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
                CallbackQueryHandler(reserve_hl.choice_time),
            ],
            'TIME': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
                CallbackQueryHandler(main_hl.back_date, pattern='^Назад'),
                CallbackQueryHandler(reserve_hl.choice_option_of_reserve),
            ],
            'ORDER': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
                CallbackQueryHandler(main_hl.back_time, pattern='^Назад'),
                CallbackQueryHandler(reserve_hl.check_and_send_buy_info),
            ],
            'PAID': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
                MessageHandler(
                    filters.PHOTO | filters.ATTACHMENT,
                    reserve_hl.forward_photo_or_file
                ),
            ],
            'FORMA': [
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, reserve_hl.get_name_adult),
            ],
            'PHONE': [
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, reserve_hl.get_phone),
            ],
            'CHILDREN': [
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, reserve_hl.get_name_children),
            ],
            'LIST': [
                CommandHandler('reset', reset),
                CallbackQueryHandler(main_hl.cancel, pattern='^Отменить'),
                CallbackQueryHandler(main_hl.back_date, pattern='^Назад'),
                CallbackQueryHandler(reserve_hl.send_clients_data),
            ],
            'CHOOSING': [
                CommandHandler('reset', reset),
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
                CommandHandler('reset', reset),
                MessageHandler(filters.TEXT, reserve_hl.get_phone_for_waiting),
            ],
            ConversationHandler.TIMEOUT: [reserve_hl.TIMEOUT_HANDLER]
        },
        fallbacks=[CommandHandler('help', main_hl.help_command)],
        conversation_timeout=15*60,  # 15 мин
        name="reserve",
        persistent=True,
        allow_reentry=True
    )

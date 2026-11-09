from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler, CommandHandler, ContextTypes, MessageHandler,
    CallbackQueryHandler,
)

from db import db_postgres
from handlers import reserve_hl, reserve_admin_hl, migration_admin_hl
from handlers.reserve_admin_hl import execute_ticket_migration
from conv_hl import (
    handlers_event_selection, handlers_client_data_selection,
    cancel_callback_handler, back_callback_handler,
    F_text_and_no_command, common_fallbacks
)
from utilities.utl_func import clean_context_on_end_handler
from utilities.utl_kbd import add_btn_back_and_cancel
from utilities.utl_ticket import (
    get_ticket_and_price,
    parse_and_create_custom_ticket,
    apply_custom_ticket_to_reserve,
)
from settings.settings import COMMAND_DICT

migration_admin_conv_logger = logging.getLogger('bot.migration_admin_conv')


async def handle_custom_migration_params(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    """Обработка индивидуального переноса: админ вводит дети взрослые стоимость."""
    text_input = update.effective_message.text.strip()
    custom_ticket, error_text = await parse_and_create_custom_ticket(context, text_input)
    if custom_ticket is None:
        keyboard = [
            add_btn_back_and_cancel(
                postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
                postfix_for_back='TICKET',
                add_back_btn=True
            )
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_chat.send_message(
            text=error_text,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        return 'CUSTOM_TICKET_PARAMS'

    cost = int(text_input.split()[2])
    apply_custom_ticket_to_reserve(context, custom_ticket, cost)

    # Execute migration with custom ticket
    original_ticket_id = context.user_data['reserve_admin_data']['ticket_id']
    original_ticket = await db_postgres.get_ticket(context.session, original_ticket_id)

    new_ticket_id = await execute_ticket_migration(
        update, context, original_ticket,
        custom_ticket.base_ticket_id, cost,
        reserve_user_data=context.user_data['reserve_user_data'],
    )

    if new_ticket_id is None:
        await clean_context_on_end_handler(migration_admin_conv_logger, context)
        return ConversationHandler.END

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['ticket_ids'] = [new_ticket_id]
    await update.effective_chat.send_message(text='Билет успешно перенесен.')
    await clean_context_on_end_handler(migration_admin_conv_logger, context)
    return ConversationHandler.END


states = {
    0: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command,
                       migration_admin_hl.get_ticket_by_id),
    ],
    1: [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(migration_admin_hl.migration_ticket, pattern='migration'),
        CallbackQueryHandler(reserve_hl.choice_month, pattern='params'),
        CallbackQueryHandler(reserve_admin_hl.enter_event_id, pattern='id'),
    ],
    2: [
        cancel_callback_handler,
        back_callback_handler,
        MessageHandler(F_text_and_no_command,
                       reserve_admin_hl.choice_option_of_reserve),
    ],
    'TICKET': [
        cancel_callback_handler,
        back_callback_handler,
        CallbackQueryHandler(reserve_admin_hl.start_forma_info,
                             pattern='^TICKET'),
    ],
    'CUSTOM_TICKET_PARAMS': [
        cancel_callback_handler,
        back_callback_handler,
        MessageHandler(F_text_and_no_command,
                       handle_custom_migration_params),
    ],
}

for key in handlers_event_selection.keys():
    states[key] = handlers_event_selection[key]
for key in handlers_client_data_selection.keys():
    states[key] = handlers_client_data_selection[key]


migration_admin_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['MIGRATION_ADMIN'][0],
                       migration_admin_hl.enter_ticket_id),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='migration_admin',
    persistent=True,
    allow_reentry=True
)

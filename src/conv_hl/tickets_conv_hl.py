"""Conversation handler for /tickets — клиентский просмотр своих билетов."""
from __future__ import annotations

from telegram.ext import ConversationHandler, CommandHandler, CallbackQueryHandler

from handlers.tickets_user import TICKETS_MENU, show_tickets, tickets_callback
from conv_hl import common_fallbacks, cancel_callback_handler
from settings.settings import COMMAND_DICT


tickets_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['TICKETS'][0], show_tickets),
    ],
    states={
        TICKETS_MENU: [
            cancel_callback_handler,
            CallbackQueryHandler(tickets_callback, pattern='^tickets:'),
        ],
    },
    fallbacks=common_fallbacks,
    name='tickets',
    persistent=True,
    allow_reentry=True,
)

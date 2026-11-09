"""Conversation handler for /tickets — клиентский просмотр своих билетов."""
from __future__ import annotations

from telegram.ext import ConversationHandler, CommandHandler

from handlers import profile_hl
from conv_hl import common_fallbacks
from settings.settings import COMMAND_DICT


tickets_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['TICKETS'][0], profile_hl.show_tickets),
    ],
    states={},
    fallbacks=common_fallbacks,
    name='tickets',
    persistent=True,
    allow_reentry=True,
)

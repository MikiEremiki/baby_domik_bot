"""Conversation handler for /tickets_admin — админское меню управления билетом."""
from __future__ import annotations

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler, CommandHandler, ContextTypes, MessageHandler,
    CallbackQueryHandler,
)

from handlers import init_conv_hl_dialog
from handlers.main_hl import back as main_back
from handlers.receipt_hl import receipt_send_callback
from handlers.tickets_admin import (
    # States
    MENU, SEARCH_USER, TICKET_LIST, TICKET_CARD, STATUS_PICK,
    INPUT_EMAIL, INPUT_PHONE, INPUT_NOTES, NOTES_MODE, INPUT_BASE_TICKET,
    BUYER_CARD, BUYER_TICKETS, SEARCH_TICKET_ID, SEARCH_CONTACT_PHONE,
    SEARCH_CONTACT_EMAIL,
    # Callbacks
    tickets_admin_callback,
    # Inputs
    handle_search_user, handle_search_ticket_id,
    handle_search_contact_phone, handle_search_contact_email,
    handle_email_input, handle_phone_input, handle_notes_input,
    handle_base_ticket_input,
    # Display
    show_ticket_card,
)
from utilities.utl_func import set_back_context
from utilities.utl_kbd import add_btn_back_and_cancel
from sulguk import transform_html
from conv_hl import (
    cancel_callback_handler,
    F_text_and_no_command, common_fallbacks,
)
from settings.settings import COMMAND_DICT


async def enter_tickets_admin(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Стартовая точка /tickets_admin."""
    await init_conv_hl_dialog(update, context)
    context.user_data['postfix_for_cancel'] = 'tickets_admin'
    context.user_data['tickets_admin'] = {}

    # Прямой вызов: /tickets_admin <id>
    if context.args:
        try:
            ticket_id = int(context.args[0])
            return await show_ticket_card(update, context, ticket_id, edit=False)
        except ValueError:
            pass

    text = '<b>Меню управления билетом</b><br><br>Выберите способ поиска:'
    keyboard = [
        [InlineKeyboardButton('По билету', callback_data='ta:search_ticket')],
        [InlineKeyboardButton('По пользователю', callback_data='ta:search_user')],
        [InlineKeyboardButton('По контактам', callback_data='ta:search_contact')],
        add_btn_back_and_cancel(
            postfix_for_cancel='tickets_admin',
            add_back_btn=False,
        ),
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    res = transform_html(text)
    await update.effective_chat.send_message(
        text=res.text, entities=res.entities,
        reply_markup=reply_markup, parse_mode=None)
    await set_back_context(context, MENU, res.text, reply_markup)
    context.user_data['STATE'] = MENU
    return MENU


# ── State machine ───────────────────────────────────────────────────────────

states = {
    MENU: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
    ],
    SEARCH_USER: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_search_user),
    ],
    SEARCH_TICKET_ID: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_search_ticket_id),
    ],
    SEARCH_CONTACT_PHONE: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_search_contact_phone),
    ],
    SEARCH_CONTACT_EMAIL: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_search_contact_email),
    ],
    TICKET_LIST: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
    ],
    TICKET_CARD: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
        CallbackQueryHandler(receipt_send_callback, pattern='^receipt_send'),
    ],
    STATUS_PICK: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
    ],
    INPUT_EMAIL: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
        MessageHandler(F_text_and_no_command, handle_email_input),
    ],
    INPUT_PHONE: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_phone_input),
    ],
    NOTES_MODE: [
        cancel_callback_handler,
        CallbackQueryHandler(tickets_admin_callback, pattern='^ta:'),
    ],
    INPUT_NOTES: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_notes_input),
    ],
    INPUT_BASE_TICKET: [
        cancel_callback_handler,
        MessageHandler(F_text_and_no_command, handle_base_ticket_input),
    ],
    BUYER_TICKETS: [
        cancel_callback_handler,
    ],
    BUYER_CARD: [
        cancel_callback_handler,
    ],
}

# Кнопка «Назад» в tickets_admin
for state_key in states:
    states[state_key].append(CallbackQueryHandler(main_back, pattern='^Назад'))


tickets_admin_conv_hl = ConversationHandler(
    entry_points=[
        CommandHandler(COMMAND_DICT['TICKETS_ADMIN'][0], enter_tickets_admin),
    ],
    states=states,
    fallbacks=common_fallbacks,
    name='tickets_admin',
    persistent=True,
    allow_reentry=True,
)

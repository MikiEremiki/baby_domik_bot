"""Handler functions for /tickets_admin — бизнес-логика управления билетом."""
from .constants import (
    MENU, SEARCH_USER, TICKET_LIST, TICKET_CARD, STATUS_PICK,
    INPUT_EMAIL, INPUT_PHONE, INPUT_NOTES, NOTES_MODE, INPUT_BASE_TICKET,
    BUYER_CARD, BUYER_TICKETS, SEARCH_TICKET_ID, SEARCH_CONTACT_PHONE,
    SEARCH_CONTACT_EMAIL, PAGE_SIZE_TICKETS_ADMIN,
)
from .callbacks import tickets_admin_callback
from .inputs import (
    handle_search_user, handle_search_ticket_id,
    handle_search_contact_phone, handle_search_contact_email,
    handle_email_input, handle_phone_input, handle_notes_input,
    handle_base_ticket_input,
)
from .display import show_ticket_card, format_ticket_card
from .ticket_list import show_compact_ticket_list, show_user_tickets
from .buyer import show_buyer_card, show_buyer_tickets
from .status import set_ticket_status
from .keyboards import ticket_card_keyboard, status_keyboard, email_keyboard

__all__ = [
    # States
    'MENU', 'SEARCH_USER', 'TICKET_LIST', 'TICKET_CARD', 'STATUS_PICK',
    'INPUT_EMAIL', 'INPUT_PHONE', 'INPUT_NOTES', 'NOTES_MODE', 'INPUT_BASE_TICKET',
    'BUYER_CARD', 'BUYER_TICKETS', 'SEARCH_TICKET_ID', 'SEARCH_CONTACT_PHONE',
    'SEARCH_CONTACT_EMAIL', 'PAGE_SIZE_TICKETS_ADMIN',
    # Callbacks
    'tickets_admin_callback',
    # Inputs
    'handle_search_user', 'handle_search_ticket_id',
    'handle_search_contact_phone', 'handle_search_contact_email',
    'handle_email_input', 'handle_phone_input', 'handle_notes_input',
    'handle_base_ticket_input',
    # Display
    'show_ticket_card', 'format_ticket_card',
    # Ticket list
    'show_compact_ticket_list', 'show_user_tickets',
    # Buyer
    'show_buyer_card', 'show_buyer_tickets',
    # Status
    'set_ticket_status',
    # Keyboards
    'ticket_card_keyboard', 'status_keyboard', 'email_keyboard',
]

"""Length fix handler for sales campaigns."""
from telegram import Update
from telegram.ext import ContextTypes

from .states import LENGTH_FIX, GET_MESSAGE
from utilities.utl_kbd import remove_intent_id


async def handle_length_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle LENGTH_FIX state actions: shorten or send_separate."""
    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})

    if action == 'send_separate':
        extra_payload = sales_state.get('extra_payload', {})
        extra_payload['text_mode'] = 'separate'
        sales_state['extra_payload'] = extra_payload
        sales_state.pop('length_report', None)
        from .preview import show_preview
        return await show_preview(update, context)

    if action == 'shorten':
        sales_state.pop('length_report', None)
        from .message import ask_message
        return await ask_message(update, context)

    return LENGTH_FIX

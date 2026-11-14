"""Message input step for sales campaigns."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from .states import (
    GET_MESSAGE, BUILD_AUDIENCE, PICK_ATTACH_THEATER, PICK_AUDIENCE_THEATER,
    _serialize_entities, _get_step_info,
)
from utilities.utl_kbd import add_btn_back_and_cancel


async def ask_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END
    audience_summary = sales_state.pop('audience_summary', None)
    media = sales_state.get('media', [])
    media_hint = f'Медиа прикреплено: {len(media)}' if media else 'Медиа не прикреплено.'
    campaign_type = sales_state.get('type')
    step_n, step_total = _get_step_info(campaign_type, 'text')

    # Check if text was already entered (e.g., coming from "Edit Media" in preview)
    extra_payload = sales_state.get('extra_payload', {})
    existing_text = extra_payload.get('text', '')
    has_existing_text = bool(existing_text)

    step_text = (
        f'<b>Шаг {step_n}/{step_total}: Отправьте текст сообщения</b>\n\n'
        f'{media_hint}\n\n'
    )
    if has_existing_text:
        step_text += (
            'Текст уже введён. Отправьте новый текст, чтобы заменить,\n'
            'или нажмите «Оставить этот текст».\n\n'
        )
    step_text += (
        'Отправьте текстовое сообщение.\n'
        'Текст будет добавлен к медиа как подпись (до 1024 символов)\n'
        'или отправлен отдельным сообщением, если не помещается.\n\n'
        'После отправки вы увидите предпросмотр.'
    )
    text = step_text
    if audience_summary:
        text = audience_summary + '\n\n' + step_text

    if sales_state.get('dev_mode'):
        back_target = BUILD_AUDIENCE
    elif campaign_type == 'TICKET_HOLDERS':
        back_target = PICK_ATTACH_THEATER
    elif campaign_type == 'SEASON_TICKET_HOLDERS':
        back_target = PICK_ATTACH_THEATER
    else:
        back_target = PICK_AUDIENCE_THEATER

    kb = []
    if has_existing_text:
        kb.append([InlineKeyboardButton('✅ Оставить этот текст', callback_data='keep_text')])
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales',
                                       add_back_btn=True,
                                       postfix_for_back=back_target))
    reply_markup = InlineKeyboardMarkup(kb)
    from utilities.utl_func import set_back_context
    sent = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    sales_state['ask_message_msg_id'] = sent.message_id
    state = GET_MESSAGE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return GET_MESSAGE


async def _delete_ask_message_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete the ask_message prompt message if it exists."""
    sales_state = context.user_data.setdefault('sales', {})
    prompt_msg_id = sales_state.pop('ask_message_msg_id', None)
    if prompt_msg_id:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=prompt_msg_id,
            )
        except Exception:
            pass


async def handle_keep_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Keep this text' button — skip text input and go to preview."""
    from utilities.utl_kbd import remove_intent_id
    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    if action != 'keep_text':
        return GET_MESSAGE

    sales_state = context.user_data.setdefault('sales', {})
    prompt_msg_id = sales_state.pop('ask_message_msg_id', None)
    if prompt_msg_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=prompt_msg_id,
                reply_markup=None
            )
        except Exception:
            pass

    from .preview import show_preview
    return await show_preview(update, context)


async def back_from_get_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Back' button from GET_MESSAGE — delete prompt and navigate back."""
    query = update.callback_query
    await query.answer()

    # Delete the ask_message prompt message
    await _delete_ask_message_prompt(update, context)

    # Determine target state from callback_data
    callback_data = query.data
    # callback_data is like "Назад-PICK_AUDIENCE_THEATER" or "Назад-PICK_FILTERS" etc.
    if '-' in callback_data:
        target_state = callback_data.split('-', 1)[1]
    else:
        # Fallback: determine from campaign type
        sales_state = context.user_data.setdefault('sales', {})
        campaign_type = sales_state.get('type')
        if campaign_type == 'TICKET_HOLDERS':
            target_state = 'PICK_ATTACH_THEATER'
        elif campaign_type == 'SEASON_TICKET_HOLDERS':
            target_state = 'PICK_ATTACH_THEATER'
        else:
            target_state = 'PICK_AUDIENCE_THEATER'

    # Route to the appropriate back handler
    if target_state == 'PICK_FILTERS':
        from .ticket_holders import show_pick_filters
        return await show_pick_filters(update, context)
    elif target_state == 'PICK_ATTACH_THEATER':
        from .shared_steps import show_pick_attach_theater
        return await show_pick_attach_theater(update, context)
    elif target_state == 'PICK_AUDIENCE_THEATER':
        from .was_this_year import show_pick_audience_theater
        return await show_pick_audience_theater(update, context,
                                                page=sales_state.get('aud_theater_page', 1))
    elif target_state == 'BUILD_AUDIENCE':
        from .shared_steps import show_build_audience
        return await show_build_audience(update, context)
    else:
        # Fallback: just change state
        context.user_data['STATE'] = target_state
        return GET_MESSAGE


async def handle_admin_message(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Store admin text message into extra_payload and proceed to preview."""
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END

    prompt_msg_id = sales_state.pop('ask_message_msg_id', None)
    if prompt_msg_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=prompt_msg_id,
                reply_markup=None
            )
        except Exception:
            pass

    msg = update.effective_message

    if not msg.text:
        await update.effective_chat.send_message(
            'На этом шаге принимается только текст. Медиа отправлялось на предыдущем шаге.\n'
            'Если вы хотели отправить медиа, нажмите «Назад».'
        )
        return GET_MESSAGE

    plain_text = msg.text_html or ''
    # Convert newlines to <br> for HTML storage.
    # Telegram sends \n for line breaks, but sulguk.transform_html() ignores
    # bare \n in HTML input — they disappear. Use <br> so transform_html
    # converts them back to \n in the final Telegram text.
    plain_text = plain_text.replace('\n', '<br>')
    entities = _serialize_entities(msg.entities)

    extra_payload = sales_state.get('extra_payload', {})
    extra_payload['text'] = plain_text
    extra_payload['text_entities'] = entities

    media = sales_state.get('media', [])
    if media:
        extra_payload['text_mode'] = 'caption'
    else:
        extra_payload['text_mode'] = 'separate'

    sales_state['extra_payload'] = extra_payload

    from db.sales_crud import update_campaign_message
    fields = {
        'message_kind': 'text',
        'message_text': plain_text,
        'message_entities': entities,
    }
    await update_campaign_message(context.session, campaign_id, **fields)
    await context.session.commit()

    from .preview import show_preview
    return await show_preview(update, context)

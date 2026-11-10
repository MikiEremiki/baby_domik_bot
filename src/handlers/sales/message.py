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
    step_text = (
        f'<b>Шаг {step_n}/{step_total}: Отправьте текст сообщения</b>\n\n'
        f'{media_hint}\n\n'
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
    reply_markup = InlineKeyboardMarkup([
        add_btn_back_and_cancel(postfix_for_cancel='sales',
                                add_back_btn=True,
                                postfix_for_back=back_target)])
    from utilities.utl_func import set_back_context
    sent = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    sales_state['ask_message_msg_id'] = sent.message_id
    state = GET_MESSAGE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
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

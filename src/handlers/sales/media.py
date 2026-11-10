"""Media collection step for sales campaigns."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from .states import (
    MAX_MEDIA_COUNT, GET_MEDIA, BUILD_AUDIENCE, PICK_ATTACH_THEATER,
    PICK_AUDIENCE_THEATER, _extract_media_info, _serialize_entities,
    _get_step_info,
)
from .ui_helpers import _show_step
from utilities.utl_kbd import add_intent_id, add_btn_back_and_cancel


async def show_get_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step: collect media files (up to 10). Admin can skip to go straight to text."""
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END

    audience_summary = sales_state.pop('audience_summary', None)
    media = sales_state.get('media', [])
    campaign_type = sales_state.get('type')
    step_n, step_total = _get_step_info(campaign_type, 'media')
    step_text = (
        f'<b>Шаг {step_n}/{step_total}: Пришлите медиа (необязательно)</b>\n\n'
        f'Текущих медиа: {len(media)}/{MAX_MEDIA_COUNT}\n\n'
        'Отправьте фото, видео или анимацию (до 10 файлов).\n'
        'GIF-анимации считаются отдельно — только одна GIF в альбоме.\n\n'
        'После отправки медиа можно сразу написать текст —\n'
        'это завершит выбор медиа и покажет предпросмотр.\n\n'
        'Нажмите «Пропустить», чтобы перейти к вводу текста.'
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

    kb = [
        [InlineKeyboardButton('⏭ Пропустить', callback_data='skip')],
    ]
    if media:
        kb.append([InlineKeyboardButton('🗑 Очистить медиа', callback_data='clear')])
    kb = add_intent_id(kb, 'sales:media')
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales',
                                       add_back_btn=True,
                                       postfix_for_back=back_target))
    reply_markup = InlineKeyboardMarkup(kb)

    state = await _show_step(update, context, text, reply_markup, GET_MEDIA)
    sales_state['get_media_msg_id'] = sales_state.get('step_msg_id')
    return state


async def handle_media_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Accumulate media files in sales_state['media']."""
    sales_state = context.user_data.setdefault('sales', {})
    msg = update.effective_message

    if getattr(msg, 'media_group_id', None):
        await update.effective_chat.send_message(
            'Альбомы напрямую не поддерживаются. Отправляйте по одному файлу.')
        return GET_MEDIA

    media_info = _extract_media_info(msg)
    if not media_info:
        await update.effective_chat.send_message(
            'Поддерживаются только фото, видео и анимация (GIF).')
        return GET_MEDIA

    if media_info['type'] == 'animation':
        existing = sales_state.get('media', [])
        if any(m['type'] == 'animation' for m in existing):
            await update.effective_chat.send_message(
                'GIF-анимация уже добавлена. Только одна GIF допускается.')
            return GET_MEDIA

    media = sales_state.get('media', [])
    if len(media) >= MAX_MEDIA_COUNT:
        await update.effective_chat.send_message(
            f'Лимит {MAX_MEDIA_COUNT} медиа достигнут. Нажмите «Далее» или очистите список.')
        return GET_MEDIA

    media.append(media_info)
    sales_state['media'] = media

    extra_payload = sales_state.get('extra_payload', {})
    extra_payload['media'] = media
    sales_state['extra_payload'] = extra_payload

    await update.effective_chat.send_message(
        f'✅ Медиа добавлено ({len(media)}/{MAX_MEDIA_COUNT}). '
        f'Отправьте ещё, напишите текст для предпросмотра, '
        f'или нажмите «Пропустить».'
    )
    return GET_MEDIA


async def handle_media_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text message in GET_MEDIA state: store text and proceed to preview."""
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END

    msg = update.effective_message
    plain_text = msg.text_html or ''
    entities = _serialize_entities(msg.entities)

    prompt_msg_id = sales_state.pop('get_media_msg_id', None)
    if prompt_msg_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=prompt_msg_id,
                reply_markup=None
            )
        except Exception:
            pass

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


async def handle_media_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle skip/clear actions in GET_MEDIA state."""
    from utilities.utl_kbd import remove_intent_id
    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})

    if action == 'skip':
        prompt_msg_id = sales_state.pop('get_media_msg_id', None)
        if prompt_msg_id:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=update.effective_chat.id,
                    message_id=prompt_msg_id,
                    reply_markup=None
                )
            except Exception:
                pass
        from .message import ask_message
        return await ask_message(update, context)

    if action == 'clear':
        sales_state['media'] = []
        extra_payload = sales_state.get('extra_payload', {})
        extra_payload.pop('media', None)
        sales_state['extra_payload'] = extra_payload
        return await show_get_media(update, context)

    return GET_MEDIA


async def input_dev_chat_ids(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """Parse admin-provided chat_ids in dev mode and replace recipients' snapshot, then ask for a message."""
    import sqlalchemy as sa
    from db import SalesRecipient
    from db.sales_crud import snapshot_recipients

    sales_state = context.user_data.setdefault('sales', {})
    if not sales_state.get('dev_mode'):
        await update.effective_chat.send_message(
            'Этот шаг доступен только в dev-режиме. Используйте /sales dev')
        return BUILD_AUDIENCE

    text = (update.effective_message.text or '').strip()
    raw = text.replace(',', ' ').replace('\n', ' ').split()
    chat_ids = []
    for token in raw:
        try:
            cid = int(token)
            chat_ids.append(cid)
        except ValueError:
            continue
    uniq = sorted(set(chat_ids))
    if not uniq:
        await update.effective_chat.send_message(
            'Не найдено ни одного корректного chat_id. Повторите ввод.')
        return BUILD_AUDIENCE

    session = context.session
    campaign_id = sales_state.get('campaign_id')
    await session.execute(sa.delete(SalesRecipient.__table__).where(
        SalesRecipient.__table__.c.campaign_id == campaign_id))
    await snapshot_recipients(session, campaign_id,
                              [(cid, cid) for cid in uniq])
    await session.flush()
    await session.commit()

    await update.effective_chat.send_message(
        f'Dev-режим: список получателей заменён. Всего chat_id: {len(uniq)}')
    return await show_get_media(update, context)

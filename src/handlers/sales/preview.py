"""Preview step for sales campaigns."""
from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from db import SalesCampaign, SalesRecipient, db_postgres
import sqlalchemy as sa

from .states import (
    PREVIEW, GET_MESSAGE, LENGTH_FIX, _get_step_info,
)
from .ui_helpers import _safe_edit_message
from utilities.utl_kbd import add_intent_id, add_btn_back_and_cancel
from utilities.utl_sales_message import (
    send_campaign_message, analyze_length, format_length_report, build_extra,
)
from utilities.utl_func import get_full_name_event
from .audience import _availability_block


async def _cleanup_preview(bot, chat_id: int, message_ids: list):
    """Remove old preview messages: delete or remove buttons as fallback."""
    for mid in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=mid, reply_markup=None
                )
            except Exception:
                pass


async def show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    campaign_id = sales_state.get('campaign_id')
    if not campaign_id:
        await update.effective_chat.send_message(
            'Внутренняя ошибка: нет кампании. Начните заново /sales')
        return ConversationHandler.END

    session = context.session
    campaign: SalesCampaign = await session.get(SalesCampaign, campaign_id)
    schedule_ids: List[int] = context.user_data['sales'].get('schedule_ids', [])
    # Fallback: load schedule_ids from DB if not in user data (e.g., after bot restart or resume)
    if not schedule_ids:
        from db.models import SalesCampaignSchedule
        rows = (await session.execute(
            sa.select(SalesCampaignSchedule.schedule_event_id)
            .where(SalesCampaignSchedule.campaign_id == campaign_id)
        )).all()
        schedule_ids = [r[0] for r in rows]

    full_name = ""
    availability_block = ""
    # Use <br> for HTML storage so sulguk.transform_html() converts them
    # back to \n in the final Telegram text. Bare \n are ignored in HTML.
    reserve_text = (f"👉 /reserve команда для покупки билетов<br>"
                    f"Выбирайте подходящий спектакль и следуйте инструкциям")

    if campaign.type in ('WAS_THIS_YEAR_ON_PLAY', 'TICKET_HOLDERS', 'SEASON_TICKET_HOLDERS') and campaign.theater_event_id:
        availability_block = await _availability_block(session, schedule_ids)
        # Only show the show name if there's at least one session with
        # available children's seats. Otherwise the name is misleading.
        if availability_block:
            theater_event = await db_postgres.get_theater_event(
                session, campaign.theater_event_id)
            if theater_event:
                full_name = get_full_name_event(theater_event)

    extra = build_extra(full_name, availability_block, reserve_text)

    extra_payload = sales_state.get('extra_payload', {})
    media = extra_payload.get('media', [])
    plain_text = extra_payload.get('text', '')
    text_mode = extra_payload.get('text_mode', 'caption')

    # Fallback: load text from DB if not in extra_payload (e.g., after resume)
    if not plain_text:
        plain_text = campaign.message_text or campaign.caption_text or ''

    # Fallback: load media from DB if not in extra_payload
    if not media:
        kind = campaign.message_kind
        if kind == 'photo' and campaign.photo_file_id:
            media = [{'type': 'photo', 'file_id': campaign.photo_file_id}]
        elif kind == 'video' and campaign.video_file_id:
            media = [{'type': 'video', 'file_id': campaign.video_file_id}]
        elif kind == 'animation' and campaign.animation_file_id:
            media = [{'type': 'animation', 'file_id': campaign.animation_file_id}]
        if not media:
            text_mode = 'separate'

    has_media = bool(media)
    report = analyze_length(plain_text, extra, has_media, text_mode)
    if report:
        from utilities.utl_func import set_back_context
        sales_state['length_report'] = report
        text_report = format_length_report(report)
        kb = [
            [InlineKeyboardButton('✂️ Сократить текст', callback_data='shorten')],
            [InlineKeyboardButton('📤 Отправить текст отдельно', callback_data='send_separate')],
        ]
        kb = add_intent_id(kb, 'sales:length')
        kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales',
                                          add_back_btn=True,
                                          postfix_for_back=GET_MESSAGE))
        reply_markup = InlineKeyboardMarkup(kb)
        await update.effective_chat.send_message(
            text=text_report,
            reply_markup=reply_markup,
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        state = LENGTH_FIX
        await set_back_context(context, state, text_report, reply_markup)
        context.user_data['STATE'] = state
        return LENGTH_FIX

    pending_cnt = (await session.execute(
        sa.select(sa.func.count()).select_from(SalesRecipient).where(
            SalesRecipient.campaign_id == campaign_id)
    )).scalar() or 0

    action_rows = [
        [InlineKeyboardButton('Запустить', callback_data='run')],
        [InlineKeyboardButton('Изменить текст', callback_data='edit_text')],
        [InlineKeyboardButton('Изменить медиа', callback_data='edit_media')],
    ]
    # Show "Изменить сеансы" only if there are valid future schedules with free places
    if availability_block:
        action_rows.append([InlineKeyboardButton('Изменить сеансы',
                              callback_data='edit_schedules')])
    action_rows = add_intent_id(action_rows, 'sales:preview')
    action_rows.append(add_btn_back_and_cancel(
        postfix_for_cancel='sales',
        add_back_btn=True,
        postfix_for_back='preview_back',
    ))
    reply_markup = InlineKeyboardMarkup(action_rows)

    chat = update.effective_chat
    thread_id = getattr(update.effective_message, 'message_thread_id', None)

    # Clean up old preview messages before sending new ones
    old_preview_ids = sales_state.pop('preview_message_ids', [])
    if old_preview_ids:
        await _cleanup_preview(context.bot, chat.id, old_preview_ids)

    # Remove buttons from the old step message before sending preview
    old_step_msg_id = sales_state.get('step_msg_id')
    if old_step_msg_id is not None:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat.id,
                message_id=old_step_msg_id,
                reply_markup=None,
            )
        except Exception:
            pass

    sent_messages = await send_campaign_message(
        context.bot,
        chat.id,
        media=media,
        text=plain_text,
        extra=extra,
        text_mode=text_mode,
        reply_markup=reply_markup,
        message_thread_id=thread_id,
    )

    sales_state['preview_message_ids'] = [m.message_id for m in sent_messages]

    await chat.send_message(
        f'👁 Предпросмотр. Получателей: {pending_cnt}. Показов: {len(schedule_ids)}',
        message_thread_id=thread_id,
    )

    return PREVIEW


async def cancel_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Cancel' button in preview — clean up preview messages and exit."""
    from utilities.utl_kbd import remove_intent_id
    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    for mid in sales_state.pop('preview_message_ids', []):
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id, message_id=mid)
        except Exception:
            pass
    return ConversationHandler.END


async def preview_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import logging
    sales_logger = logging.getLogger('bot.sales')

    from utilities.utl_kbd import remove_intent_id
    from api.sales_pub import publish_sales
    from db.sales_crud import set_campaign_status

    query = update.callback_query
    await query.answer()
    _, action = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})
    if action == 'edit_text':
        from .message import ask_message
        return await ask_message(update, context)
    if action == 'edit_media':
        from .media import show_get_media
        return await show_get_media(update, context)
    if action == 'edit_schedules':
        from .was_this_year import show_pick_schedules
        return await show_pick_schedules(update, context, page=1)
    if action == 'Назад-preview_back':
        from .campaign import show_pick_existing_campaign
        # Clean up preview messages
        for mid in sales_state.pop('preview_message_ids', []):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=mid)
            except Exception:
                pass
        return await show_pick_existing_campaign(update, context)
    if action == 'run':
        session = context.session
        campaign_id = sales_state.get('campaign_id')
        if not campaign_id:
            await query.answer(
                'Внутренняя ошибка: нет кампании. Начните заново /sales',
                show_alert=True)
            return PREVIEW
        campaign: SalesCampaign = await session.get(SalesCampaign, campaign_id)
        if not campaign:
            await query.answer('Кампания не найдена.', show_alert=True)
            return PREVIEW
        if campaign.status == 'done':
            await query.answer('Кампания уже завершена.', show_alert=True)
            return PREVIEW
        if campaign.status == 'running':
            sales_logger.info(
                f'Кампания #{campaign_id} в running, перезапуск: recipients в pending')

        extra_payload = sales_state.get('extra_payload', {})
        has_text = bool(extra_payload.get('text'))
        has_media = bool(extra_payload.get('media'))
        has_old_message = campaign.message_kind is not None
        if not has_text and not has_media and not has_old_message:
            await query.answer('Сначала задайте текст сообщения.',
                               show_alert=True)
            return PREVIEW

        campaign_type = campaign.type
        schedule_ids: List[int] = context.user_data['sales'].get('schedule_ids', [])
        # Fallback: load schedule_ids from DB if not in user data (e.g., after bot restart or resume)
        if not schedule_ids:
            from db.models import SalesCampaignSchedule
            rows = (await session.execute(
                sa.select(SalesCampaignSchedule.schedule_event_id)
                .where(SalesCampaignSchedule.campaign_id == campaign_id)
            )).all()
            schedule_ids = [r[0] for r in rows]

        pending_cnt = (await session.execute(
            sa.select(sa.func.count()).select_from(SalesRecipient).where(
                (SalesRecipient.campaign_id == campaign_id) & (
                        SalesRecipient.status == 'pending')
            )
        )).scalar() or 0
        if pending_cnt <= 0:
            await query.answer('Аудитория пуста или уже отправлена.',
                               show_alert=True)
            return PREVIEW

        if extra_payload:
            await session.execute(
                sa.update(SalesCampaign)
                .where(SalesCampaign.id == campaign_id)
                .values(extra_payload=extra_payload)
            )
            await session.commit()

        try:
            await set_campaign_status(session, campaign_id, 'running')
            await session.commit()
            await publish_sales(campaign_id)
        except Exception as e:
            sales_logger.exception('Failed to publish sales task: %s', e)
            try:
                await set_campaign_status(session, campaign_id, 'failed')
                await session.commit()
            except Exception:
                pass
            text = ('Не удалось запустить рассылку: ошибка публикации задачи.\n'
                    'Попробуйте позже.')
            await _safe_edit_message(query, text)
            return PREVIEW
        text = (f'Задача на рассылку опубликована.\nКампания #{campaign_id}\n'
                f'Статус кампании: running. Ожидайте отчёт по завершении.')
        await _safe_edit_message(query, text)
        return ConversationHandler.END

    return ConversationHandler.END

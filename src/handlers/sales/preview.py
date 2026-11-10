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

    full_name = ""
    availability_block = ""
    reserve_text = (f"👉 /reserve команда для покупки билетов\n"
                    f"Выбирайте подходящий спектакль и следуйте инструкциям")

    if campaign.type in ('WAS_THIS_YEAR_ON_PLAY', 'TICKET_HOLDERS', 'SEASON_TICKET_HOLDERS') and campaign.theater_event_id:
        theater_event = await db_postgres.get_theater_event(
            session, campaign.theater_event_id)
        if theater_event:
            full_name = get_full_name_event(theater_event)
        availability_block = await _availability_block(session, schedule_ids)

    extra = build_extra(full_name, availability_block, reserve_text)

    extra_payload = sales_state.get('extra_payload', {})
    media = extra_payload.get('media', [])
    plain_text = extra_payload.get('text', '')
    text_mode = extra_payload.get('text_mode', 'caption')

    if not media and not plain_text:
        plain_text = campaign.message_text or campaign.caption_text or ''
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
        kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales',
                                          add_back_btn=True,
                                          postfix_for_back=GET_MESSAGE))
        reply_markup = InlineKeyboardMarkup(add_intent_id(kb, 'sales:length'))
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
    if campaign.theater_event_id or schedule_ids:
        action_rows.append([InlineKeyboardButton('Изменить сеансы',
                              callback_data='edit_schedules')])
    action_rows = add_intent_id(action_rows, 'sales:preview')
    action_rows.append([InlineKeyboardButton('Отмена', callback_data='Отменить')])
    reply_markup = InlineKeyboardMarkup(action_rows)

    chat = update.effective_chat
    thread_id = getattr(update.effective_message, 'message_thread_id', None)

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
        for mid in sales_state.pop('preview_message_ids', []):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=mid)
            except Exception:
                pass
        from .message import ask_message
        return await ask_message(update, context)
    if action == 'edit_media':
        for mid in sales_state.pop('preview_message_ids', []):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=mid)
            except Exception:
                pass
        from .media import show_get_media
        return await show_get_media(update, context)
    if action == 'edit_schedules':
        from .was_this_year import show_pick_schedules
        return await show_pick_schedules(update, context, page=1)
    if action == 'cancel':
        campaign_id = sales_state.get('campaign_id')
        await set_campaign_status(context.session, campaign_id, 'canceled')
        await context.session.commit()
        for mid in sales_state.pop('preview_message_ids', []):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=mid)
            except Exception:
                pass
        await update.effective_chat.send_message(
            'Кампания отменена.\n\nЧтобы запустить рассылку заново, используйте команду /sales.',
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return ConversationHandler.END
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
        if campaign.status == 'canceled':
            await query.answer('Кампания отменена. Создайте новую через /sales.',
                               show_alert=True)
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
        if not schedule_ids and campaign_type == 'WAS_THIS_YEAR_ON_PLAY':
            await query.answer(
                'Не выбраны сеансы. Вернитесь и выберите даты/сеансы.',
                show_alert=True)
            return PREVIEW

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

"""Campaign CRUD and management UI for sales campaigns."""
from datetime import datetime
from typing import Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from db import SalesCampaign, TheaterEvent
import sqlalchemy as sa
from db.sales_crud import (
    create_campaign, set_campaign_schedules, snapshot_recipients,
    update_campaign_message, set_campaign_status, get_free_places,
    get_recent_campaigns, get_campaign_with_schedules,
    delete_campaign, get_recipient_counts
)

from .states import (
    SALES_TYPES, MENU, PICK_EXISTING_CAMPAIGN, CAMPAIGN_ACTION_MENU,
    PICK_TYPE, PICK_FILTERS, PICK_SEASON_START, PICK_THEATER,
    _status_label, _get_step_info, _get_usage_text_with_highlight,
)
from .ui_helpers import _show_step
from utilities.utl_kbd import (
    create_replay_markup, remove_intent_id, add_intent_id, adjust_kbd,
    add_btn_back_and_cancel,
)


async def _ensure_campaign_and_schedules(update: Update,
                                         context: ContextTypes.DEFAULT_TYPE):
    """Create a SalesCampaign if needed and persist selected schedules."""
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
    campaign_type = sales_state.get('type')

    theater_id_raw = sales_state.get('theater_event_id')
    theater_id = int(theater_id_raw) if theater_id_raw else None

    schedule_ids: List[int] = list(
        map(int, sales_state.get('schedule_ids', [])))

    if not schedule_ids and campaign_type not in ('TICKET_HOLDERS', 'SEASON_TICKET_HOLDERS', 'WAS_THIS_YEAR_ON_PLAY'):
        return None

    theater_name = "Без спектакля"
    if theater_id:
        te_row = (await session.execute(
            TheaterEvent.__table__.select().where(
                TheaterEvent.__table__.c.id == theater_id)
        )).mappings().first()
        theater_name = te_row['name'] if te_row else f"#{theater_id}"

    if campaign_type == 'TICKET_HOLDERS':
        title = f"Рассылка: Обладатели билетов ({datetime.now().strftime('%d.%m %H:%M')})"
    elif campaign_type == 'SEASON_TICKET_HOLDERS':
        season_start = sales_state.get('season_start')
        season_end = sales_state.get('season_end')
        if season_start and season_end:
            title = f"Рассылка: Сезон {season_start.strftime('%d.%m.%Y')}–{season_end.strftime('%d.%m.%Y')}"
        else:
            title = f"Рассылка: Посетители сезона ({datetime.now().strftime('%d.%m %H:%M')})"
    else:
        title = f"Продажи: {theater_name} ({len(schedule_ids)} сеансов)"

    campaign = await create_campaign(
        session,
        created_by_admin_id=update.effective_user.id,
        campaign_type=campaign_type,
        theater_event_id=theater_id,
        title=title,
        status='draft',
    )
    campaign_id = campaign.id
    sales_state['campaign_id'] = campaign_id

    if schedule_ids:
        await set_campaign_schedules(session, campaign_id, schedule_ids)

    await session.flush()
    await session.commit()
    return campaign_id


async def _show_pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        '<b>Рассылки/Продажи</b>\n',
        'Выберите тип рассылки, нажав на цифру под списком.',
        '\nДоступные типы:'
    ]
    number_to_code: Dict[int, str] = {}
    i = 0
    for code, meta in SALES_TYPES.items():
        if not meta.get('enabled'):
            continue
        i += 1
        number_to_code[i] = code
        title = meta['title']
        lines.append(f"{i}. {title}")
    if i == 0:
        await update.effective_chat.send_message(
            'Нет доступных типов рассылок. Пожалуйста, попробуйте позже.')
        return MENU

    context.user_data.setdefault('sales', {})['type_map'] = number_to_code

    text = '\n'.join(lines)
    kb: List[InlineKeyboardButton] = [
        InlineKeyboardButton(str(n), callback_data=str(n)) for n in
        range(1, i + 1)
    ]
    reply_markup = await create_replay_markup(
        kb,
        intent_id='sales:type',
        postfix_for_cancel='sales',
        add_back_btn=False,
        size_row=5
    )
    return await _show_step(update, context, text, reply_markup, PICK_TYPE)


async def show_pick_existing_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of recent campaigns that can be resumed, plus 'Create new' button."""
    session = context.session
    campaigns = await get_recent_campaigns(session, limit=10)

    type_labels = {
        'WAS_THIS_YEAR_ON_PLAY': 'Свободные места',
        'TICKET_HOLDERS': 'Обладатели билетов',
        'SEASON_TICKET_HOLDERS': 'Посетители сезона',
    }

    lines = ['<b>Выберите кампанию или создайте новую:</b>\n']
    kb = []

    for c in campaigns:
        label = type_labels.get(c.type, c.type)
        status_emoji = _status_label(c.status)
        title = (c.title or f'Кампания #{c.id}')
        lines.append(f'{status_emoji} <b>#{c.id}</b> — {title}\n<i>{label} · {c.status}</i>')

    kb.append([InlineKeyboardButton(
        '➕ Создать новую', callback_data='new'
    )])

    campaign_buttons = []
    for c in campaigns:
        status_emoji = _status_label(c.status)
        campaign_buttons.append(InlineKeyboardButton(
            f'{status_emoji} #{c.id}',
            callback_data=f'campaign:{c.id}'
        ))
    kb.extend(adjust_kbd(campaign_buttons, 4))
    kb = add_intent_id(kb, 'sales:existing')
    kb.append([InlineKeyboardButton('Отмена', callback_data='Отменить')])
    reply_markup = InlineKeyboardMarkup(kb)

    text = '\n\n'.join(lines) if campaigns else '<b>Нет доступных кампаний.</b>\n\nСоздайте новую.'
    return await _show_step(update, context, text, reply_markup, PICK_EXISTING_CAMPAIGN)


async def pick_existing_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle selection: show action menu for existing campaign or create a new one."""
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    if payload == 'new':
        context.user_data['sales'] = {
            'dev_mode': context.user_data['sales'].get('dev_mode', False),
            'type': None,
            'campaign_id': None,
            'theater_event_id': None,
            'schedule_ids': [],
            'filters': {},
            'audience_theater_ids': [],
            'f_schedule_time': 'all',
            'f_schedule_show': 'all',
            'child_age_min': None,
            'child_age_max': None,
            'attach_theater': False,
        }
        return await _show_pick_type(update, context)

    if payload.startswith('campaign:'):
        campaign_id = int(payload.split(':', 1)[1])
        return await show_campaign_action_menu(update, context, campaign_id)

    return await show_pick_existing_campaign(update, context)


async def show_campaign_action_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, campaign_id: int):
    """Show action menu for a selected campaign: resume, continue, edit, cancel, delete."""
    session = context.session
    campaign = await get_campaign_with_schedules(session, campaign_id)

    if not campaign:
        return await show_pick_existing_campaign(update, context)

    context.user_data['sales']['campaign_id'] = campaign.id

    type_labels = {
        'WAS_THIS_YEAR_ON_PLAY': 'Свободные места',
        'TICKET_HOLDERS': 'Обладатели билетов',
        'SEASON_TICKET_HOLDERS': 'Посетители сезона',
    }
    label = type_labels.get(campaign.type, campaign.type)
    status_emoji = _status_label(campaign.status)
    title = campaign.title or f'Кампания #{campaign.id}'

    total, pending = await get_recipient_counts(session, campaign_id)

    has_content = (
        campaign.extra_payload or
        campaign.message_text or
        campaign.caption_text or
        campaign.message_kind
    )

    text = (
        f'{status_emoji} <b>{title}</b> (#{campaign.id})\n\n'
        f'Тип: {label}\n'
        f'Статус: {campaign.status}\n'
        f'Получатели: {total} (ожидает: {pending})\n'
        f'Сообщение: {"есть" if has_content else "не задано"}'
    )

    kb = []
    if has_content and pending > 0 and campaign.status != 'done':
        kb.append([InlineKeyboardButton(
            '🔄 Перезапустить', callback_data='action:resume'
        )])
    if not has_content or campaign.status in ('draft', 'running'):
        kb.append([InlineKeyboardButton(
            '▶️ Продолжить настройку', callback_data='action:continue'
        )])
    if has_content:
        kb.append([InlineKeyboardButton(
            '✏️ Изменить сообщение', callback_data='action:edit'
        )])
    if campaign.status in ('draft', 'running'):
        kb.append([InlineKeyboardButton(
            '❌ Отменить', callback_data='action:cancel'
        )])
    if campaign.status in ('draft', 'canceled'):
        kb.append([InlineKeyboardButton(
            '🗑 Удалить', callback_data='action:delete'
        )])

    kb.append([InlineKeyboardButton('← Назад', callback_data='back')])
    kb = add_intent_id(kb, 'sales:action')
    reply_markup = InlineKeyboardMarkup(kb)

    return await _show_step(update, context, text, reply_markup, CAMPAIGN_ACTION_MENU)


async def handle_campaign_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle action selection for a campaign."""
    import logging
    sales_logger = logging.getLogger('bot.sales')

    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    campaign_id = context.user_data['sales'].get('campaign_id')
    if not campaign_id:
        await query.answer('Сначала выберите кампанию.', show_alert=True)
        return await show_pick_existing_campaign(update, context)

    if payload == 'action:resume':
        from .preview import show_preview
        return await show_preview(update, context)

    if payload == 'action:continue':
        session = context.session
        campaign = await get_campaign_with_schedules(session, campaign_id)
        if not campaign:
            await query.answer('Кампания не найдена.', show_alert=True)
            return await show_pick_existing_campaign(update, context)

        sales_state = context.user_data['sales']
        sales_state['campaign_id'] = campaign.id
        sales_state['type'] = campaign.type
        sales_state['theater_event_id'] = campaign.theater_event_id
        sales_state['schedule_ids'] = [s.schedule_event_id for s in campaign.schedules]
        if campaign.extra_payload:
            sales_state['extra_payload'] = campaign.extra_payload

        has_content = (
            campaign.extra_payload or
            campaign.message_text or
            campaign.caption_text or
            campaign.message_kind
        )

        if has_content:
            from .preview import show_preview
            return await show_preview(update, context)
        else:
            start_state = SALES_TYPES.get(campaign.type, {}).get('start_state', PICK_THEATER)
            if start_state == PICK_FILTERS:
                from .ticket_holders import show_pick_filters
                return await show_pick_filters(update, context)
            if start_state == PICK_SEASON_START:
                from .season_ticket_holders import show_pick_season_start
                return await show_pick_season_start(update, context)
            from .was_this_year import show_pick_theater
            return await show_pick_theater(update, context)

    if payload == 'action:edit':
        from .preview import show_preview
        return await show_preview(update, context)

    if payload == 'action:cancel':
        session = context.session
        await set_campaign_status(session, campaign_id, 'canceled')
        await session.commit()
        sales_logger.info(f'Кампания #{campaign_id} отменена')
        await query.answer('Кампания отменена.', show_alert=True)
        return await show_pick_existing_campaign(update, context)

    if payload == 'action:delete':
        session = context.session
        deleted = await delete_campaign(session, campaign_id)
        if deleted:
            await session.commit()
            sales_logger.info(f'Кампания #{campaign_id} удалена')
            await query.answer('Кампания удалена.', show_alert=True)
        else:
            await query.answer('Кампания не найдена.', show_alert=True)
        return await show_pick_existing_campaign(update, context)

    if payload == 'back':
        return await show_pick_existing_campaign(update, context)

    return await show_campaign_action_menu(update, context, campaign_id)

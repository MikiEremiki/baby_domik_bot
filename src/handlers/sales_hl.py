"""Sales campaigns handler — entry points only.

All logic is split into `handlers.sales.*` submodules.
Import directly from submodules for explicit dependencies:
    from handlers.sales.states import MENU, PICK_TYPE, ...
    from handlers.sales.was_this_year import pick_theater, ...
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from .sales.states import SALES_TYPES, PICK_TYPE, PICK_FILTERS, PICK_SEASON_START, PICK_THEATER
from .sales.campaign import show_pick_existing_campaign, _show_pick_type
from .sales.was_this_year import show_pick_theater
from .sales.ticket_holders import show_pick_filters
from .sales.season_ticket_holders import show_pick_season_start

sales_logger = logging.getLogger('bot.sales')


async def start_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: /sales [dev]"""
    from handlers import init_conv_hl_dialog
    args = context.args or []
    await init_conv_hl_dialog(update, context)

    context.user_data['sales'] = {
        'dev_mode': False,
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

    if args and args[0].lower() == 'dev':
        context.user_data['sales']['dev_mode'] = True
    sales_logger.info("/sales started by %s dev_mode=%s",
                      update.effective_user.id,
                      context.user_data['sales']['dev_mode'])

    return await show_pick_existing_campaign(update, context)


async def pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from utilities.utl_kbd import remove_intent_id
    query = update.callback_query
    await query.answer()
    data = query.data
    _, type_code = remove_intent_id(data)

    sales_state = context.user_data.setdefault('sales', {})
    if type_code.isdigit():
        mapping = sales_state.get('type_map') or {}
        type_code = mapping.get(int(type_code))
    else:
        type_code = type_code

    meta = SALES_TYPES.get(type_code) if type_code else None
    if not meta:
        await query.edit_message_text("Неизвестный тип. Попробуйте ещё раз.")
        return await _show_pick_type(update, context)

    if not meta.get('enabled'):
        await query.answer("Скоро", show_alert=False)
        return PICK_TYPE

    context.user_data['sales']['type'] = type_code

    start_state = meta.get('start_state', PICK_THEATER)
    if start_state == PICK_FILTERS:
        return await show_pick_filters(update, context)
    if start_state == PICK_SEASON_START:
        return await show_pick_season_start(update, context)

    return await show_pick_theater(update, context)

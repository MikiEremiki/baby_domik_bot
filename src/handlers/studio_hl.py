import logging

from telegram import Update
from telegram.ext import ContextTypes

from db import db_postgres
from handlers.sub_hl import get_theater_and_schedule_events_by_month
from utilities.utl_func import set_back_context, create_event_names_text
from utilities.utl_kbd import create_kbd_schedule_and_date, create_replay_markup

studio_hl_logger = logging.getLogger('bot.studio_hl')


async def choice_show_and_date(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.delete_message()

    number_of_month_str = query.data

    studio_hl_logger.info(f'Пользователь выбрал месяц: {number_of_month_str}')
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_ids = reserve_user_data['schedule_event_ids']
    schedule_events = await db_postgres.get_schedule_events_by_ids(
        context.session, schedule_event_ids)

    enum_theater_events, schedule_events_filter_by_month = await (
        get_theater_and_schedule_events_by_month(context,
                                                 schedule_events,
                                                 number_of_month_str)
    )

    text_legend = (
        '📍 - Премьера\n'
        '👶🏼 - Рекомендованный возраст\n'
        '⏳ - Продолжительность\n'
        '\n'
    )

    text = '<b>Выберите мероприятие и дату\n</b>' + text_legend
    text = await create_event_names_text(enum_theater_events, text)

    keyboard = await create_kbd_schedule_and_date(
        schedule_events_filter_by_month, enum_theater_events)
    reply_markup = await create_replay_markup(
        keyboard,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='MONTH',
        size_row=2
    )

    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.callback_query.message.message_thread_id,
    )

    reserve_user_data['number_of_month_str'] = number_of_month_str

    state = 'DATE'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

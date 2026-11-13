"""Shared steps: build_audience, attach_theater."""
from typing import List

import sqlalchemy as sa
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import SalesRecipient, SalesCampaign, TheaterEvent
from db.sales_crud import snapshot_recipients

from .states import (
    MENU, BUILD_AUDIENCE, PICK_ATTACH_THEATER, PICK_AUDIENCE_THEATER,
    PICK_FILTERS, PICK_SEASON_STATUSES, PICK_SCOPE,
    _compress_ids, _get_step_info, _get_usage_text_with_highlight,
)
from .ui_helpers import _show_step
from .audience import (
    _select_audience_rows, _select_ticket_holders_audience, _select_season_audience,
)
from .campaign import _ensure_campaign_and_schedules
from utilities.utl_kbd import (
    create_replay_markup, remove_intent_id, add_intent_id, add_btn_back_and_cancel,
)


async def show_build_audience(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Build audience snapshot and show summary."""
    session = context.session
    sales_state = context.user_data.setdefault('sales', {})
    campaign_type = sales_state.get('type')

    if campaign_type == 'TICKET_HOLDERS':
        rows, ticket_ids = await _select_ticket_holders_audience(session, sales_state)
        filters = sales_state.get('filters', {})
        f_time = sales_state.get('f_schedule_time', 'all')
        f_show = sales_state.get('f_schedule_show', 'all')
        filter_lines = []
        if filters.get('ticket_ids'):
            filter_lines.append("• ID билетов вручную")
        else:
            if filters.get('status'):
                filter_lines.append("• Статус билета")
            if filters.get('type_event_ids'):
                filter_lines.append("• Тип мероприятия")
            if filters.get('theater_event_ids'):
                filter_lines.append("• Спектакль")
            if filters.get('schedule_event_ids'):
                filter_lines.append("• Сеанс")
            if filters.get('base_ticket_ids'):
                filter_lines.append("• Базовый билет")
            if filters.get('child_age_min') is not None or filters.get('child_age_max') is not None:
                filter_lines.append("• Возраст детей")
            has_event = any([filters.get('type_event_ids'), filters.get('theater_event_ids'), filters.get('schedule_event_ids')])
            if not has_event:
                time_label = {'all': 'все', 'past': 'прошедшие', 'future': 'будущие'}.get(f_time, f_time)
                show_label = {'all': 'любая', 'on': 'вкл в боте', 'off': 'выкл в боте'}.get(f_show, f_show)
                filter_lines.append(f"• Время сеансов: {time_label}, видимость: {show_label}")
        filters_text = "\n<b>Применённые фильтры:</b>\n" + "\n".join(filter_lines) if filter_lines else "\n<b>Фильтры не заданы</b> (выбраны все билеты)"
        audience_info = "Аудитория: обладатели билеты." + filters_text
        if ticket_ids:
            audience_info += f"\n<b>ID билетов ({len(ticket_ids)}):</b> {_compress_ids(ticket_ids)}"
        postfix_for_back = PICK_FILTERS
    elif campaign_type == 'SEASON_TICKET_HOLDERS':
        rows = await _select_season_audience(session, sales_state)
        season_start = sales_state.get('season_start')
        season_end = sales_state.get('season_end')
        theater_ids = sales_state.get('season_theater_ids') or []
        c_min = sales_state.get('child_age_min')
        c_max = sales_state.get('child_age_max')
        status_values = sales_state.get('season_statuses') or []

        period_label = ""
        if season_start and season_end:
            period_label = f"\nПериод: {season_start.strftime('%d.%m.%Y')} – {season_end.strftime('%d.%m.%Y')}"

        theater_label = ""
        if theater_ids:
            names = (await session.execute(sa.select(TheaterEvent.name).where(
                TheaterEvent.id.in_(theater_ids)))).scalars().all()
            if names:
                theater_label = f"\nСпектакли ({len(names)}): {', '.join(names)}"
        else:
            theater_label = "\nСпектакли: все"

        age_label = ""
        if c_min is not None and c_max is not None:
            age_label = f"\nВозраст ребёнка: от {c_min} до {c_max} лет"
        elif c_min is not None:
            age_label = f"\nВозраст ребёнка: от {c_min}+ лет"
        elif c_max is not None:
            age_label = f"\nВозраст ребёнка: до {c_max} лет"
        else:
            age_label = "\nВозраст ребёнка: без ограничения"

        status_label = ""
        if status_values:
            status_label = f"\nСтатусы билетов: {', '.join(status_values)}"
        else:
            status_label = "\nСтатусы билетов: все"

        audience_info = (
            f"\nАудитория: посетители сезона.{period_label}{theater_label}{age_label}{status_label}"
        )
        if sales_state.get('attach_theater'):
            postfix_for_back = PICK_SCOPE
        else:
            postfix_for_back = PICK_ATTACH_THEATER
    else:
        theater_ids: List[int] = list(
            map(int, sales_state.get('audience_theater_ids') or []))
        if not theater_ids:
            theater_ids = [int(sales_state['theater_event_id'])]
        rows = await _select_audience_rows(session, theater_ids)

        audience_info = ''
        try:
            if theater_ids:
                names = (await session.execute(sa.select(TheaterEvent.name).where(
                    TheaterEvent.id.in_(theater_ids)))).scalars().all()
                if names:
                    audience_info = f"\nФильтр по спектаклям для аудитории: {', '.join(names)}"
        except Exception:
            pass
        postfix_for_back = PICK_AUDIENCE_THEATER

    if not rows:
        text = (
            '<b>Аудитория пуста</b>\n\n'
            'По заданным условиям не найдено получателей.\n'
            'Создание рассылки завершено.\n\n'
            'Чтобы запустить рассылку заново, используйте команду /sales.'
        )
        await update.effective_chat.send_message(
            text=text,
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return MENU

    campaign_id = await _ensure_campaign_and_schedules(update, context)

    if not campaign_id:
        text = (
            '<b>Ошибка создания кампании</b>\n\n'
            'Не удалось создать кампанию. Проверьте данные и попробуйте снова.\n'
            'Используйте команду /sales.'
        )
        await update.effective_chat.send_message(
            text=text,
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        return MENU

    if campaign_id:
        await session.execute(
            sa.delete(SalesRecipient.__table__).where(
                SalesRecipient.__table__.c.campaign_id == campaign_id
            )
        )

    inserted = await snapshot_recipients(session, campaign_id, rows)
    await session.flush()
    await session.commit()

    total_found = len(rows)
    total_pending = inserted

    if campaign_type == 'SEASON_TICKET_HOLDERS':
        step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'build_audience')
        step_header = f'<b>Шаг {step_n}/{step_total}: Проверьте сводку аудитории</b>'
        usage_block = _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)
    elif campaign_type == 'TICKET_HOLDERS':
        step_n, step_total = _get_step_info('TICKET_HOLDERS', 'build_audience')
        step_header = f'<b>Шаг {step_n}/{step_total}: Проверьте сводку аудитории</b>'
        usage_block = _get_usage_text_with_highlight('TICKET_HOLDERS', step_n)
    elif campaign_type == 'WAS_THIS_YEAR_ON_PLAY':
        step_n, step_total = _get_step_info('WAS_THIS_YEAR_ON_PLAY', 'build_audience')
        step_header = f'<b>Шаг {step_n}/{step_total}: Проверьте сводку аудитории</b>'
        usage_block = _get_usage_text_with_highlight('WAS_THIS_YEAR_ON_PLAY', step_n)
    else:
        step_header = '<b>Отбор аудитории завершён.</b>'
        usage_block = None

    text_lines = [
        step_header,
        f'Всего найдено уникальных пользователей: {total_found}',
        f'Добавлено получателей (pending): {total_pending}',
        audience_info,
    ]

    summary_lines = [
        f'Всего найдено уникальных пользователей: {total_found}',
        f'Добавлено получателей (pending): {total_pending}',
        audience_info,
    ]
    audience_summary = '\n'.join([t for t in summary_lines if t is not None and t != ''])

    text = '\n'.join([t for t in text_lines if t is not None and t != ''])
    if usage_block:
        text += '\n\n' + usage_block

    if sales_state.get('dev_mode'):
        text += '\n\nDev-режим: отправьте одним сообщением список chat_id через пробелы или переносы строк.\nПример: 123 456 789'
        kb = [InlineKeyboardButton("Далее (сообщение)", callback_data="next_message")]
        reply_markup = await create_replay_markup(
            kb,
            intent_id='sales',
            postfix_for_cancel='sales',
            add_back_btn=True,
            postfix_for_back=postfix_for_back,
            size_row=1
        )
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=getattr(update.effective_message, 'message_thread_id', None)
        )
        from utilities.utl_func import set_back_context
        state = BUILD_AUDIENCE
        await set_back_context(context, state, text, reply_markup)
        context.user_data['STATE'] = state
        return BUILD_AUDIENCE

    sales_state['audience_summary'] = audience_summary
    from .media import show_get_media
    return await show_get_media(update, context)


async def show_pick_attach_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales_state = context.user_data.setdefault('sales', {})
    campaign_type = sales_state.get('type')

    if campaign_type == 'SEASON_TICKET_HOLDERS':
        season_start = sales_state.get('season_start')
        season_end = sales_state.get('season_end')
        period_str = ""
        if season_start and season_end:
            period_str = f"{season_start.strftime('%d.%m.%Y')} – {season_end.strftime('%d.%m.%Y')}"
        theater_ids = sales_state.get('season_theater_ids') or []
        theater_str = f"{len(theater_ids)} спектаклей" if theater_ids else "все спектакли"
        c_min = sales_state.get('child_age_min')
        c_max = sales_state.get('child_age_max')
        age_str = "без ограничения"
        if c_min is not None and c_max is not None:
            age_str = f"от {c_min} до {c_max} лет"
        elif c_min is not None:
            age_str = f"от {c_min}+ лет"
        elif c_max is not None:
            age_str = f"до {c_max} лет"
        status_values = sales_state.get('season_statuses') or []
        status_str = ", ".join(status_values) if status_values else "все"
        summary_lines = [
            "<b>Параметры рассылки посетителям сезона:</b>",
            f"Период: {period_str}",
            f"Спектакли: {theater_str}",
            f"Возраст ребёнка: {age_str}",
            f"Статусы билетов: {status_str}",
            "",
        ]
        back_target = PICK_SEASON_STATUSES
    elif campaign_type == 'TICKET_HOLDERS':
        filters = sales_state.get('filters', {})
        filter_lines = []
        if filters.get('status'):
            filter_lines.append(f"Статусы: {', '.join(filters['status'])}")
        if filters.get('type_event_ids'):
            filter_lines.append(f"Типы: {len(filters['type_event_ids'])} выбрано")
        if filters.get('theater_event_ids'):
            filter_lines.append(f"Спектакли: {len(filters['theater_event_ids'])} выбрано")
        if filters.get('schedule_event_ids'):
            filter_lines.append(f"Сеансы: {len(filters['schedule_event_ids'])} выбрано")
        if filters.get('ticket_ids'):
            filter_lines.append(f"Билеты (по ID): {len(filters['ticket_ids'])} выбрано")
        if filters.get('base_ticket_ids'):
            filter_lines.append(f"Базовые билеты: {len(filters['base_ticket_ids'])} выбрано")
        if filters.get('child_age_min') is not None or filters.get('child_age_max') is not None:
            c_min = filters.get('child_age_min')
            c_max = filters.get('child_age_max')
            if c_min is not None and c_max is not None:
                filter_lines.append(f"Возраст: от {c_min} до {c_max} лет")
            elif c_min is not None:
                filter_lines.append(f"Возраст: от {c_min}+ лет")
            elif c_max is not None:
                filter_lines.append(f"Возраст: до {c_max} лет")
        if filter_lines:
            summary_lines = [
                "<b>Параметры рассылки обладателям билетов:</b>",
            ] + filter_lines + [""]
        else:
            summary_lines = [
                "<b>Параметры рассылки обладателям билетов:</b>",
                "Фильтры не заданы (будут отобраны все с Оплаченными/Подтверждёнными билетами на будущие сеансы)",
                "",
            ]
        back_target = PICK_FILTERS

    if campaign_type == 'SEASON_TICKET_HOLDERS':
        step_n, step_total = _get_step_info('SEASON_TICKET_HOLDERS', 'attach_theater')
        usage_block = _get_usage_text_with_highlight('SEASON_TICKET_HOLDERS', step_n)
        attach_header = f"<b>Шаг {step_n}/{step_total}: Прикрепить спектакль со свободными местами?</b>\n"
    elif campaign_type == 'TICKET_HOLDERS':
        step_n, step_total = _get_step_info('TICKET_HOLDERS', 'attach_theater')
        usage_block = _get_usage_text_with_highlight('TICKET_HOLDERS', step_n)
        attach_header = f"<b>Шаг {step_n}/{step_total}: Прикрепить спектакль со свободными местами?</b>\n"
    else:
        usage_block = None
        attach_header = "<b>Прикрепить спектакль со свободными местами?</b>\n"

    text = (
        "\n".join(summary_lines)
        + "\n"
        + attach_header
        + ("Вы можете прикрепить спектакль и сеансы "
           "(в сообщение добавится блок со свободными местами и кнопка покупки)"
           " или отправить простое информационное сообщение.")
    )
    if usage_block:
        text += "\n\n" + usage_block
    kb = [
        [InlineKeyboardButton("🎭 Прикрепить спектакль", callback_data="yes")],
        [InlineKeyboardButton("✉️ Без спектакля (только сообщение)", callback_data="no")],
    ]
    kb = add_intent_id(kb, 'sales:attach_theater')
    kb.append(add_btn_back_and_cancel(postfix_for_cancel='sales', add_back_btn=True,
                                      postfix_for_back=back_target))
    reply_markup = InlineKeyboardMarkup(kb)

    return await _show_step(update, context, text, reply_markup, PICK_ATTACH_THEATER)


async def pick_attach_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, payload = remove_intent_id(query.data)

    sales_state = context.user_data.setdefault('sales', {})

    if payload == "yes":
        sales_state['attach_theater'] = True
        from .was_this_year import show_pick_theater
        return await show_pick_theater(update, context)

    if payload == "no":
        sales_state['attach_theater'] = False
        sales_state['theater_event_id'] = None
        sales_state['schedule_ids'] = []
        return await show_build_audience(update, context)

    return PICK_ATTACH_THEATER

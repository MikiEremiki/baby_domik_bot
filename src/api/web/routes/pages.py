import time
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import MOSCOW_TZ, templates
from ..deps import get_session
from ..logger import logger
from ..services.metrics_service import metrics_service
from db.db_postgres import get_all_theater_events_actual, get_theater_event, get_afishas
from settings.settings import (
    DICT_CONVERT_WEEKDAY_NUMBER_TO_STR,
    PUBLIC_TYPE_EVENT_IDS,
    PUBLIC_TYPE_EVENT_LABELS,
)

router = APIRouter()

@router.get('/')
async def show_index(
    request: Request,
    age: int | None = None,
    only_actual: bool = True,
    month: str | None = None,
    date: str | None = None,
    type_id: int | None = None,
    session: AsyncSession = Depends(get_session)
):
    # Невалидный/непубличный type_id игнорируем (показываем все публичные типы)
    if type_id is not None and type_id not in PUBLIC_TYPE_EVENT_IDS:
        type_id = None

    t_db0 = time.perf_counter()
    events_db = await get_all_theater_events_actual(session)
    dur_db = (time.perf_counter() - t_db0) * 1000
    metrics_service.record_db_query(dur_db / 1000.0)
    events = []
    now = datetime.now(timezone.utc)

    available_months = set()
    all_available_dates = set()
    available_types_map = {}

    for e in events_db:
        active_sessions_count = 0
        free_seats_child_in_filtered_sessions = 0
        free_seats_adult_in_filtered_sessions = 0
        # type_event_id живёт на ScheduleEvent, а не на TheaterEvent —
        # определяем тип по первому активному сеансу.
        te_type_id = None
        te_type_name = ''
        min_session_dt = None

        for s in e.schedule_events:
            if not s.flag_turn_in_bot:
                continue
            if te_type_id is None:
                te_type_id = s.type_event_id
                te_type_name = s.type_event.name if getattr(s, 'type_event', None) else ''

            dt = s.datetime_event
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            if dt >= now:
                dt_moscow = dt.astimezone(MOSCOW_TZ)
                m_key = dt_moscow.strftime('%Y-%m')
                d_key = dt_moscow.strftime('%Y-%m-%d')
                
                match_month = not month or month == m_key
                match_date = not date or date == d_key
                
                if match_month and match_date:
                    active_sessions_count += 1
                    free_seats_child_in_filtered_sessions += max(getattr(s, 'qty_child_free_seat', 0) or 0, 0)
                    free_seats_adult_in_filtered_sessions += max(getattr(s, 'qty_adult_free_seat', 0) or 0, 0)

                    if min_session_dt is None or dt < min_session_dt:
                        min_session_dt = dt

                available_months.add(m_key)
                all_available_dates.add(d_key)

        if age is not None and e.min_age_child < age:
            continue

        if only_actual and active_sessions_count == 0:
            continue
            
        if (month or date) and active_sessions_count == 0:
            continue

        # Фильтр по публичным типам (аналог type_event_id.in_(PUBLIC_TYPE_EVENT_IDS))
        if te_type_id is None or te_type_id not in PUBLIC_TYPE_EVENT_IDS:
            continue

        # Собираем доступные типы по тем событиям, что прошли базовые проверки,
        # до применения фильтра type_id — чтобы селект не пустел после выбора.
        available_types_map.setdefault(te_type_id, te_type_name)

        # Фильтр по выбранному типу (применяется после сбора available_types)
        if type_id is not None and te_type_id != type_id:
            continue

        events.append({
            'id': e.id,
            'title': e.name,
            'description': e.note or '',
            'duration': e.duration.strftime('%H:%M') if e.duration else '',
            'age': f'{e.min_age_child}+',
            'has_sessions': active_sessions_count > 0,
            'has_free_seats': free_seats_child_in_filtered_sessions > 0,
            'sessions_count': active_sessions_count,
            'type_event_id': te_type_id,
            'type_event_name': te_type_name,
            'type_event_label': PUBLIC_TYPE_EVENT_LABELS.get(te_type_id, ''),
            'min_session_dt': min_session_dt,
        })
    
    events.sort(key=lambda x: x['min_session_dt'] or datetime.max.replace(tzinfo=timezone.utc))
    
    sorted_months = sorted(list(available_months))
    month_names = {
        '01': 'Янв', '02': 'Фев', '03': 'Мар', '04': 'Апр',
        '05': 'Май', '06': 'Июн', '07': 'Июл', '08': 'Авг',
        '09': 'Сен', '10': 'Окт', '11': 'Ноя', '12': 'Дек'
    }
    months_display = [
        {'key': m, 'name': f"{month_names[m.split('-')[1]]} {m.split('-')[0][2:]}"}
        for m in sorted_months
    ]
    
    # Список типов для селекта — отсортирован по порядку PUBLIC_TYPE_EVENT_IDS
    types_display = [
        {'id': tid, 'name': available_types_map[tid]}
        for tid in PUBLIC_TYPE_EVENT_IDS
        if tid in available_types_map
    ]

    year_for_afisha = int(month.split('-')[0]) if month else now.year
    t_af0 = time.perf_counter()
    afishas_db = await get_afishas(session, year_for_afisha)
    dur_af = (time.perf_counter() - t_af0) * 1000
    metrics_service.record_db_query(dur_af / 1000.0)
    dur_db += dur_af
    if hasattr(request.state, 'timings'):
        request.state.timings['db'] = round(dur_db, 1)

    afishas = []
    selected_month_int = int(month.split('-')[1]) if month else None
    
    for a in afishas_db:
        if selected_month_int and a.month != selected_month_int:
            continue
        path = '/' + a.file_path if not a.file_path.startswith('/') else a.file_path
        afishas.append({
            'month': a.month,
            'year': a.year,
            'image_url': path
        })
    afishas.sort(key=lambda x: x['month'])

    t_render0 = time.perf_counter()
    response = templates.TemplateResponse(
        request=request,
        name='index.html',
        context={
            'events': events,
            'current_age': age,
            'only_actual': only_actual,
            'current_month': month,
            'current_date': date,
            'current_type_id': type_id,
            'months': months_display,
            'types': types_display,
            'available_dates': list(all_available_dates),
            'afishas': afishas,
        },
    )
    if hasattr(request.state, 'timings'):
        request.state.timings['render'] = round((time.perf_counter() - t_render0) * 1000, 1)
    return response

@router.get('/event/{event_id}')
async def show_event_details(request: Request, event_id: int, session: AsyncSession = Depends(get_session)):
    logger.info(f"Showing details for event {event_id}")
    t_db0 = time.perf_counter()
    e = await get_theater_event(session, event_id)
    dur_db = (time.perf_counter() - t_db0) * 1000
    metrics_service.record_db_query(dur_db / 1000.0)
    if hasattr(request.state, 'timings'):
        request.state.timings['db'] = round(dur_db, 1)

    if e is None:
        logger.warning(f"Event {event_id} not found")
        raise HTTPException(status_code=404, detail="Event not found")

    sessions = []
    now = datetime.now(timezone.utc)
    for s in e.schedule_events:
        if not s.flag_turn_in_bot:
            continue
        dt = s.datetime_event
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < now:
            continue
            
        dt_moscow = dt.astimezone(MOSCOW_TZ)
        sessions.append({
            'id': s.id,
            'date': dt_moscow.strftime('%d.%m'),
            'time': dt_moscow.strftime('%H:%M'),
            'weekday': DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[dt_moscow.weekday()],
            'free_seats_child': max(s.qty_child_free_seat or 0, 0),
            'free_seats_adult': max(s.qty_adult_free_seat or 0, 0),
        })

    event = {
        'id': e.id,
        'title': e.name,
        'description': e.note or '',
        'duration': e.duration.strftime('%H:%M') if e.duration else '',
        'age': f'{e.min_age_child}+',
        'sessions': sessions,
    }

    t_render0 = time.perf_counter()
    response = templates.TemplateResponse(
        request=request,
        name='event_details.html',
        context={'event': event, 'sessions': sessions},
    )
    if hasattr(request.state, 'timings'):
        request.state.timings['render'] = round((time.perf_counter() - t_render0) * 1000, 1)
    return response

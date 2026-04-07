from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import MOSCOW_TZ, templates
from ..deps import get_session
from ..logger import logger
from db.db_postgres import get_all_theater_events_actual, get_theater_event
from settings.settings import DICT_CONVERT_WEEKDAY_NUMBER_TO_STR

router = APIRouter()

@router.get('/')
async def show_index(
    request: Request,
    age: int | None = None,
    only_actual: bool = True,
    month: str | None = None,
    date: str | None = None,
    session: AsyncSession = Depends(get_session)
):
    events_db = await get_all_theater_events_actual(session)
    events = []
    now = datetime.now(timezone.utc)
    
    available_months = set()
    all_available_dates = set()
    
    for e in events_db:
        active_sessions_count = 0
        free_seats_child_in_filtered_sessions = 0
        free_seats_adult_in_filtered_sessions = 0
        
        for s in e.schedule_events:
            if not s.flag_turn_in_bot:
                continue
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

                available_months.add(m_key)
                all_available_dates.add(d_key)

        if age is not None and e.min_age_child < age:
            continue

        if only_actual and active_sessions_count == 0:
            continue
            
        if (month or date) and active_sessions_count == 0:
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
        })
    
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
    
    return templates.TemplateResponse(
        request=request,
        name='index.html',
        context={
            'events': events,
            'current_age': age,
            'only_actual': only_actual,
            'current_month': month,
            'current_date': date,
            'months': months_display,
            'available_dates': list(all_available_dates),
        },
    )

@router.get('/event/{event_id}')
async def show_event_details(request: Request, event_id: int, session: AsyncSession = Depends(get_session)):
    logger.info(f"Showing details for event {event_id}")
    e = await get_theater_event(session, event_id)
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
    return templates.TemplateResponse(
        request=request,
        name='event_details.html',
        context={'event': event, 'sessions': sessions},
    )

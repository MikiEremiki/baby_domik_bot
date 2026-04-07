import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from yookassa import Payment

from ..config import MOSCOW_TZ, templates, settings
from ..deps import get_session
from ..logger import logger
from ..services.booking_service import (
    get_ticket_price_for_web,
    check_promo_restrictions_web,
    compute_discounted_price_web,
)
from db.models import BaseTicket, ScheduleEvent, TheaterEvent, Promotion, Adult, Child, Person, Ticket, PersonTicket, UserTicket
from db.enum import AgeType, TicketStatus, UserRole
from db.db_postgres import (
    get_theater_event,
    get_schedule_event,
    get_base_tickets_by_event_or_all,
    get_promotion,
    get_user_by_phone,
    get_ticket,
    get_user,
    get_phone,
    get_email,
    get_adult_name,
)
from api.gspread_pub import publish_write_data_reserve, publish_write_client_reserve
from api.yookassa_connect import create_param_payment
from utilities.utl_text import extract_phone_number_from_text, check_email
from settings.settings import DICT_CONVERT_WEEKDAY_NUMBER_TO_STR

router = APIRouter()

async def _get_booking_form_context(request: Request, s: ScheduleEvent, session: AsyncSession):
    t_e = s.theater_event
    base_tickets = await get_base_tickets_by_event_or_all(s, s.theater_event, s.type_event, session)
    
    dt = s.datetime_event
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_moscow = dt.astimezone(MOSCOW_TZ)
    
    tickets_data = []
    for bt in base_tickets:
        price = await get_ticket_price_for_web(session, bt, s, t_e)
        tickets_data.append({
            'id': bt.base_ticket_id,
            'name': bt.name,
            'price': price,
            'quality_of_children': bt.quality_of_children,
            'quality_of_adult': bt.quality_of_adult,
            'quality_of_add_adult': bt.quality_of_add_adult,
        })

    form_data = {}
    user_session = request.session.get('user')
    if user_session:
        user_id = user_session.get('id')
        user = await get_user(session, user_id)
        if user:
            phone = await get_phone(session, user_id)
            email = await get_email(session, user_id)
            adult_name = await get_adult_name(session, user_id)
            form_data = {
                'adult_name': adult_name or user_session.get('first_name'),
                'phone': phone or '',
                'email': email or user.email or '',
            }

    return {
        'request': request,
        'event': {
            'id': t_e.id,
            'title': t_e.name,
        },
        'session': {
            'id': s.id,
            'date': dt_moscow.strftime('%d.%m.%Y'),
            'time': dt_moscow.strftime('%H:%M'),
            'free_seats_child': max(s.qty_child_free_seat or 0, 0),
            'free_seats_adult': max(s.qty_adult_free_seat or 0, 0),
        },
        'ticket_types': tickets_data,
        'form_data': form_data,
    }

@router.get('/booking/{schedule_id}')
async def show_booking_form(request: Request, schedule_id: int, session: AsyncSession = Depends(get_session)):
    s = await get_schedule_event(session, schedule_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Сеанс не найден")
    
    context = await _get_booking_form_context(request, s, session)
    return templates.TemplateResponse(
        request=request,
        name='booking_form.html',
        context=context,
    )

@router.post('/booking/{schedule_id}')
async def post_booking_form(
    request: Request,
    schedule_id: int,
    ticket_type: int = Form(...),
    adult_name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    child_name: list[str] = Form(...),
    child_age: list[int] = Form(...),
    promo_code: str | None = Form(None),
    applied_promo_id: int | None = Form(None),
    session: AsyncSession = Depends(get_session)
):
    logger.info(f"Processing booking for schedule {schedule_id}. Promo: {promo_code}, ID: {applied_promo_id}")
    
    phone = extract_phone_number_from_text(phone)
    if len(phone) > 10:
        phone = phone[-10:]

    s = await get_schedule_event(session, schedule_id)
    if s is None:
        logger.warning(f"Schedule event {schedule_id} not found")
        raise HTTPException(status_code=404, detail="Сеанс не найден")
    
    if not s.flag_turn_in_bot:
        logger.warning(f"Schedule event {schedule_id} is turned off for bot/web")
        context = await _get_booking_form_context(request, s, session)
        context.update({
            'error_message': 'Извините, этот сеанс более не доступен для бронирования.',
            'form_data': {
                'ticket_type': ticket_type,
                'adult_name': adult_name,
                'phone': phone,
                'email': email,
                'child_name': child_name,
                'child_age': child_age,
                'promo_code': promo_code,
                'applied_promo_id': applied_promo_id,
            }
        })
        return templates.TemplateResponse(request=request, name='booking_form.html', context=context, status_code=400)
    
    t_e = s.theater_event
    if not check_email(email):
        context = await _get_booking_form_context(request, s, session)
        context.update({
            'error_message': 'Указан неверный формат email.',
            'form_data': {
                'ticket_type': ticket_type,
                'adult_name': adult_name,
                'phone': phone,
                'email': email,
                'child_name': child_name,
                'child_age': child_age,
                'promo_code': promo_code,
                'applied_promo_id': applied_promo_id,
            }
        })
        return templates.TemplateResponse(request=request, name='booking_form.html', context=context, status_code=400)
    
    if not t_e.flag_active_repertoire:
        logger.warning(f"Theater event {t_e.id} is not active in repertoire")
        context = await _get_booking_form_context(request, s, session)
        context.update({
            'error_message': 'Извините, этот спектакль более не доступен для бронирования',
            'form_data': {
                'ticket_type': ticket_type,
                'adult_name': adult_name,
                'phone': phone,
                'email': email,
                'child_name': child_name,
                'child_age': child_age,
                'promo_code': promo_code,
                'applied_promo_id': applied_promo_id,
            }
        })
        return templates.TemplateResponse(request=request, name='booking_form.html', context=context, status_code=400)
    
    num_children = len(child_name)
    if s.qty_child_free_seat < num_children:
        logger.warning(f"Not enough seats for schedule {schedule_id}. Requested: {num_children}, Available: {s.qty_child_free_seat}")
        context = await _get_booking_form_context(request, s, session)
        context.update({
            'error_message': f"Извините, осталось всего {max(s.qty_child_free_seat, 0)} детских мест",
            'form_data': {
                'ticket_type': ticket_type,
                'adult_name': adult_name,
                'phone': phone,
                'email': email,
                'child_name': child_name,
                'child_age': child_age,
                'promo_code': promo_code,
                'applied_promo_id': applied_promo_id,
            }
        })
        return templates.TemplateResponse(request=request, name='booking_form.html', context=context, status_code=400)

    base_tickets = await get_base_tickets_by_event_or_all(s, s.theater_event, s.type_event, session)
    ticket_type_obj = next((bt for bt in base_tickets if bt.base_ticket_id == ticket_type), None)
    if not ticket_type_obj:
        raise HTTPException(status_code=400, detail="Неверный тип билета")

    base_price = await get_ticket_price_for_web(session, ticket_type_obj, s, t_e)
    final_price = base_price
    promo_id = None
    if applied_promo_id:
        promo = await get_promotion(session, applied_promo_id)
        if promo:
            is_valid, _ = await check_promo_restrictions_web(promo, s.id, ticket_type, session)
            if is_valid and base_price >= promo.min_purchase_sum:
                final_price = await compute_discounted_price_web(base_price, promo)
                promo_id = promo.id

    user_session = request.session.get('user')
    found_chat_id = 0
    if user_session:
        found_chat_id = user_session.get('id', 0)
    else:
        found_user = await get_user_by_phone(session, phone)
        if found_user:
            if found_user.status and found_user.status.role == UserRole.ADMIN:
                found_chat_id = 0
            else:
                found_chat_id = found_user.user_id

    person_adult = Person(name=adult_name, age_type=AgeType.adult, user_id=found_chat_id if found_chat_id else None)
    session.add(person_adult)
    await session.flush()
    
    adult = Adult(phone=phone, person_id=person_adult.id)
    session.add(adult)
    
    children_objs = []
    for i in range(num_children):
        person_child = Person(name=child_name[i], age_type=AgeType.child, parent_id=person_adult.id)
        session.add(person_child)
        await session.flush()
        
        child = Child(age=child_age[i], person_id=person_child.id)
        session.add(child)
        children_objs.append(person_child)
    
    await session.flush()

    ticket = Ticket(
        base_ticket_id=ticket_type,
        schedule_event_id=schedule_id,
        status=TicketStatus.CREATED,
        notes=f"Website booking: {email}\nPromo: {promo_code if promo_id else 'None'}",
        payment_id=None,
        price=final_price,
    )
    session.add(ticket)
    await session.flush()

    # Связываем персон с билетом через таблицу PersonTicket (она же people_tickets)
    session.add(PersonTicket(person_id=person_adult.id, ticket_id=ticket.id))
    for pc in children_objs:
        session.add(PersonTicket(person_id=pc.id, ticket_id=ticket.id))
    
    if found_chat_id:
        session.add(UserTicket(user_id=found_chat_id, ticket_id=ticket.id))

    q_child = ticket_type_obj.quality_of_children
    q_adult = ticket_type_obj.quality_of_adult
    q_add_adult = ticket_type_obj.quality_of_add_adult

    s.qty_child_free_seat -= q_child
    s.qty_child_nonconfirm_seat += q_child
    s.qty_adult_free_seat -= (q_adult + q_add_adult)
    s.qty_adult_nonconfirm_seat += (q_adult + q_add_adult)

    await session.commit()
    
    try:
        numbers = [s.qty_child_free_seat, s.qty_child_nonconfirm_seat, s.qty_adult_free_seat, s.qty_adult_nonconfirm_seat]
        await publish_write_data_reserve(settings.sheets.sheet_id_domik, s.id, numbers)
        
        reserve_user_data_gs = {
            'chose_price': final_price,
            'client_data': {
                'name_adult': adult_name,
                'phone': phone,
                'data_children': [[name, str(age)] for name, age in zip(child_name, child_age)]
            },
            'ticket_ids': [ticket.id],
            'choose_schedule_event_ids': [s.id],
        }
        await publish_write_client_reserve(
            settings.sheets.sheet_id_domik,
            reserve_user_data_gs,
            found_chat_id,
            ticket_type_obj.to_dto(),
            str(TicketStatus.CREATED.value)
        )
    except Exception as gs_err:
        logger.error(f"Failed to publish gspread tasks: {gs_err}")

    dt_event = s.datetime_event.replace(tzinfo=timezone.utc).astimezone(MOSCOW_TZ)
    ticket_id = ticket.id
    ticket_name_for_desc = ticket_type_obj.name.split(' | ')[0]
    weekday = int(dt_event.strftime('%w'))
    date_event_str = (f"{dt_event.strftime('%d.%m ')}"
                  f"({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]})")
    time_event_str = dt_event.strftime('%H:%M')
    name_event = t_e.name

    max_len_decs = 128
    prefix = f"Билет №{ticket_id} на "
    suffix = f" {date_event_str} в {time_event_str} ({ticket_name_for_desc})"

    len_for_name = max_len_decs - len(prefix) - len(suffix)
    name_for_desc = name_event[:len_for_name] if len_for_name > 0 else ""
    description = f"{prefix}{name_for_desc}{suffix}"

    base_return_url = settings.yookassa.return_url or str(request.url_for('show_payment_result'))
    sep = "&" if "?" in str(base_return_url) else "?"
    return_url = f"{base_return_url}{sep}ticket_id={ticket.id}"

    payment_params = create_param_payment(
        price=final_price,
        description=description,
        email=email,
        payment_method_type=settings.yookassa.payment_method_type,
        return_url=return_url,
        chat_id=found_chat_id,
        message_id=0,
        ticket_ids=str(ticket.id),
        choose_schedule_event_ids=str(s.id),
        command='reserve',
        promo_id=promo_id,
        source='website',
    )

    idempotency_id = uuid.uuid4()
    try:
        payment = Payment.create(payment_params, idempotency_id)
        logger.info(f"YooKassa payment created: {payment.id} for ticket {ticket.id}")
        ticket.payment_id = payment.id
        await session.commit()
        return RedirectResponse(url=payment.confirmation.confirmation_url, status_code=303)
    except Exception as pay_err:
        logger.exception(f"YooKassa payment creation failed: {pay_err}")
        return RedirectResponse(url=f"/payment-result?status=error&ticket_id={ticket.id}", status_code=303)

@router.get('/payment-result')
async def show_payment_result(
    request: Request,
    status: str = 'success',
    ticket_id: int | None = None,
    session: AsyncSession = Depends(get_session)
):
    is_success = False
    schedule_id = None
    confirmation_url = None

    if ticket_id:
        ticket = await get_ticket(session, ticket_id)
        if ticket:
            schedule_id = ticket.schedule_event_id
            if ticket.status == TicketStatus.PAID:
                is_success = True
            elif ticket.payment_id:
                try:
                    payment = Payment.find_one(ticket.payment_id)
                    if payment.status == 'succeeded':
                        is_success = True
                    elif payment.status == 'pending':
                        if hasattr(payment, 'confirmation') and hasattr(payment.confirmation, 'confirmation_url'):
                            confirmation_url = payment.confirmation.confirmation_url
                except Exception as e:
                    logger.error(f"Error checking payment status for ticket {ticket_id}: {e}")
                    is_success = (status.lower() == 'success')
        else:
            is_success = (status.lower() == 'success')
    else:
        is_success = (status.lower() == 'success')

    return templates.TemplateResponse(
        request=request,
        name='payment_result.html',
        context={
            'is_success': is_success,
            'ticket_id': ticket_id,
            'schedule_id': schedule_id,
            'confirmation_url': confirmation_url,
        },
    )

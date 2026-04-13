import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import session_factory, MOSCOW_TZ, settings
from ..logger import logger
from db.models import BaseTicket, ScheduleEvent, TheaterEvent, Promotion
from db.enum import PriceType, PromotionDiscountType, TicketStatus
from db.db_postgres import (
    get_expired_tickets,
    get_base_ticket,
    get_schedule_event,
    get_special_ticket_price,
)
from api.gspread_pub import publish_write_data_reserve

async def cleanup_expired_bookings():
    """
    Периодическая задача для освобождения мест билетов, 
    которые не были оплачены в течение 10 минут.
    """
    while True:
        try:
            await asyncio.sleep(60) # Проверка каждую минуту
            async with session_factory() as session:
                expired_tickets = await get_expired_tickets(session, 10)
                if not expired_tickets:
                    continue
                
                logger.info(f"Found {len(expired_tickets)} expired tickets. Starting cleanup.")
                for ticket in expired_tickets:
                    try:
                        bt = await get_base_ticket(session, ticket.base_ticket_id)
                        s = await get_schedule_event(session, ticket.schedule_event_id)
                        
                        if bt and s:
                            q_child = bt.quality_of_children
                            q_adult = bt.quality_of_adult
                            q_add_adult = bt.quality_of_add_adult
                            
                            s.qty_child_free_seat += q_child
                            s.qty_child_nonconfirm_seat -= q_child
                            s.qty_adult_free_seat += (q_adult + q_add_adult)
                            s.qty_adult_nonconfirm_seat -= (q_adult + q_add_adult)
                            
                            logger.info(f"Returning seats for ticket {ticket.id} on schedule {s.id}")
                            
                            numbers = [
                                s.qty_child_free_seat,
                                s.qty_child_nonconfirm_seat,
                                s.qty_adult_free_seat,
                                s.qty_adult_nonconfirm_seat
                            ]
                            await publish_write_data_reserve(settings.sheets.sheet_id_domik, s.id, numbers)
                        
                        ticket.status = TicketStatus.CANCELED
                        await session.commit()
                        logger.info(f"Ticket {ticket.id} marked as CANCELED")
                        
                    except Exception as ticket_err:
                        logger.error(f"Error cleaning up ticket {ticket.id}: {ticket_err}")
                        await session.rollback()
                        
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception(f"Error in cleanup_expired_bookings loop: {e}")

async def get_ticket_price_for_web(
    session: AsyncSession,
    ticket: BaseTicket,
    schedule_event: ScheduleEvent,
    theater_event: TheaterEvent
):
    option = ''
    if schedule_event.flag_gift:
        option = 'Подарок'
    if schedule_event.flag_christmas_tree:
        option = 'Ёлка'

    if not option:
        price_type = theater_event.price_type
        if price_type == PriceType.INDIVIDUAL:
            option = str(theater_event.id)
        else:
            option = price_type.value

    dt = schedule_event.datetime_event
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_moscow = dt.astimezone(MOSCOW_TZ)
    type_ticket_price = schedule_event.ticket_price_type.value
    if not type_ticket_price:
        date_for_price = dt_moscow.date()
        if date_for_price.weekday() in range(5):
            type_ticket_price = 'будни'
        else:
            type_ticket_price = 'выходные'

    date_for_price = dt_moscow.date()
    price, _ = ticket.get_price_from_date(date_for_price)

    if theater_event.flag_indiv_cost:
        special_price = await get_special_ticket_price(
            session,
            option=option,
            base_ticket_id=ticket.base_ticket_id,
            type_ticket_price=type_ticket_price
        )
        if special_price is not None:
            price = special_price
        else:
            logger.error(f"Special price not found for ticket {ticket.base_ticket_id}, option {option}, type {type_ticket_price}")

    return int(price)

async def check_promo_restrictions_web(
        promo: Promotion,
        schedule_event_id: int,
        base_ticket_id: int,
        session: AsyncSession
) -> tuple[bool, str]:
    schedule_event = await get_schedule_event(session, schedule_event_id)
    if not schedule_event:
        return False, "Сеанс не найден."

    if promo.type_events:
        type_event_ids = [te.id for te in promo.type_events]
        if schedule_event.type_event_id not in type_event_ids:
            return False, "Этот промокод не действует на данный тип мероприятий."

    if promo.theater_events:
        theater_event_ids = [te.id for te in promo.theater_events]
        if schedule_event.theater_event_id not in theater_event_ids:
            return False, "Этот промокод не действует на данный спектакль."

    if promo.schedule_events:
        schedule_ids = [se.id for se in promo.schedule_events]
        if schedule_event.id not in schedule_ids:
            return False, "Этот промокод не действует на выбранный сеанс."

    if promo.weekdays is not None:
        dt = schedule_event.datetime_event
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_moscow = dt.astimezone(MOSCOW_TZ)
        event_weekday = dt_moscow.weekday()
        if not (promo.weekdays & (1 << event_weekday)):
            return False, "Этот промокод не действует в данный день недели."

    if promo.base_tickets:
        ticket_ids = [bt.base_ticket_id for bt in promo.base_tickets]
        if base_ticket_id not in ticket_ids:
            return False, "Этот промокод не действует на выбранный тип билета."

    if promo.max_count_of_usage > 0:
        if promo.count_of_usage >= promo.max_count_of_usage:
            return False, "Лимит использования данного промокода исчерпан."

    now = datetime.now(timezone.utc)
    start = promo.start_date
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    expire = promo.expire_date
    if expire and expire.tzinfo is None:
        expire = expire.replace(tzinfo=timezone.utc)

    if start and now < start:
        return False, "Срок действия этого промокода еще не наступил."
    if expire and now > expire:
        return False, "Срок действия этого промокода истек."

    return True, ""

async def compute_discounted_price_web(price: int, promo: Promotion) -> int:
    if promo.discount_type == PromotionDiscountType.fixed:
        new_price = price - promo.discount
    else:
        new_price = price * (100 - promo.discount) / 100
    return max(0, int(new_price))

from fastapi import APIRouter, Depends, Form, Response
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_session
from ..logger import logger
from ..schemas import WebhookNotification
from ..config import broker
from ..services.booking_service import (
    check_promo_restrictions_web,
    compute_discounted_price_web,
)
from db.db_postgres import get_promotion_by_code

router = APIRouter()

@router.post('/api/check-promo')
async def check_promo(
    code: str = Form(...),
    schedule_id: int = Form(...),
    base_ticket_id: int = Form(...),
    price: int = Form(...),
    session: AsyncSession = Depends(get_session)
):
    logger.info(f"Checking promo code {code} for schedule {schedule_id}, ticket {base_ticket_id}, price {price}")
    code = code.strip().upper()
    promo = await get_promotion_by_code(session, code)
    if not promo:
        return {"success": False, "message": "Промокод не найден"}

    is_valid, message = await check_promo_restrictions_web(
        promo, schedule_id, base_ticket_id, session
    )
    if not is_valid:
        return {"success": False, "message": message}

    if price < promo.min_purchase_sum:
        return {"success": False, "message": f"Минимальная сумма для этого промокода: {promo.min_purchase_sum} ₽"}

    new_price = await compute_discounted_price_web(price, promo)
    return {
        "success": True,
        "new_price": new_price,
        "promo_id": promo.id,
        "message": f"Промокод применен! Скидка: {price - new_price} ₽"
    }

@router.post("/yookassa")
async def post_notification(message: WebhookNotification):
    logger.info(message)
    await broker.publish(message, subject='yookassa', stream="baby_domik")
    return Response(status_code=200)

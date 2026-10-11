"""Receipt service — business logic for fiscal receipt lookup by ticket."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from db import Ticket
from db.db_postgres import get_ticket
from api.yookassa_connect import build_ofd_url, fetch_payment_receipts

logger = logging.getLogger('bot.receipt')


class ReceiptStatus(StrEnum):
    READY = 'READY'
    PENDING = 'PENDING'
    CANCELED = 'CANCELED'
    NO_PAYMENT = 'NO_PAYMENT'
    NOT_FOUND = 'NOT_FOUND'
    API_ERROR = 'API_ERROR'


@dataclass
class ReceiptInfo:
    status: ReceiptStatus
    ticket_id: int
    ticket_status: str | None = None
    price: int | None = None
    fn: str | None = None
    fd: str | None = None
    fp: str | None = None
    registered_at: datetime | None = None
    ofd_url: str | None = None
    client_chat_id: int | None = None


def select_payment_receipt(items) -> object | None:
    """Select the best payment-type receipt from a list of receipt items.

    Ignores refund receipts. Prefers `succeeded` over `pending`.
    Returns None if no suitable receipt is found.
    """
    payment_receipts = [r for r in items if getattr(r, 'type', None) == 'payment']
    if not payment_receipts:
        return None

    # Prefer succeeded
    for r in payment_receipts:
        if getattr(r, 'status', None) == 'succeeded':
            return r
    # Fallback to the first payment receipt (pending, etc.)
    return payment_receipts[0]


async def get_ticket_receipt(session, ticket_id: int) -> ReceiptInfo:
    """Retrieve fiscal receipt info for a ticket.

    Maps all FR-2/FR-3/FR-7 statuses. SDK errors become API_ERROR with a log entry.
    """
    # FR-2: ticket not found
    ticket: Ticket | None = await get_ticket(session, ticket_id)
    if ticket is None:
        return ReceiptInfo(
            status=ReceiptStatus.NOT_FOUND,
            ticket_id=ticket_id,
        )

    t_status = str(ticket.status.value) if ticket.status else None
    t_price = ticket.price
    t_client = ticket.user.chat_id if ticket.user else None

    # FR-2: no payment_id
    if not ticket.payment_id:
        return ReceiptInfo(
            status=ReceiptStatus.NO_PAYMENT,
            ticket_id=ticket_id,
            ticket_status=t_status,
            price=t_price,
            client_chat_id=t_client,
        )

    # Fetch receipts from YooKassa
    try:
        items = await fetch_payment_receipts(ticket.payment_id)
    except asyncio.TimeoutError:
        logger.exception('YooKassa timeout for ticket %s', ticket_id)
        return ReceiptInfo(
            status=ReceiptStatus.API_ERROR,
            ticket_id=ticket_id,
            ticket_status=t_status,
            price=t_price,
            client_chat_id=t_client,
        )
    except Exception:
        logger.exception('YooKassa SDK error for ticket %s', ticket_id)
        return ReceiptInfo(
            status=ReceiptStatus.API_ERROR,
            ticket_id=ticket_id,
            ticket_status=t_status,
            price=t_price,
            client_chat_id=t_client,
        )

    # No receipts returned
    if not items:
        return ReceiptInfo(
            status=ReceiptStatus.PENDING,
            ticket_id=ticket_id,
            ticket_status=t_status,
            price=t_price,
            client_chat_id=t_client,
        )

    receipt = select_payment_receipt(items)
    if receipt is None:
        # Only refund receipts — treat as canceled
        return ReceiptInfo(
            status=ReceiptStatus.CANCELED,
            ticket_id=ticket_id,
            ticket_status=t_status,
            price=t_price,
            client_chat_id=t_client,
        )

    status = getattr(receipt, 'status', None)
    fn = getattr(receipt, 'fn', None)
    fp = getattr(receipt, 'fp', None)
    i = getattr(receipt, 'i', None)
    registered_at = getattr(receipt, 'registered_at', None)

    # Parse registered_at if it's a string
    if isinstance(registered_at, str):
        try:
            registered_at = datetime.fromisoformat(registered_at.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            registered_at = None

    # FR-3: canceled
    if status == 'canceled':
        return ReceiptInfo(
            status=ReceiptStatus.CANCELED,
            ticket_id=ticket_id,
            ticket_status=t_status,
            price=t_price,
            client_chat_id=t_client,
        )

    # FR-3: pending (no fiscal data yet)
    if status != 'succeeded' or not fn or not fp or not i:
        return ReceiptInfo(
            status=ReceiptStatus.PENDING,
            ticket_id=ticket_id,
            ticket_status=t_status,
            price=t_price,
            client_chat_id=t_client,
        )

    # READY — all fiscal data present
    ofd_url = build_ofd_url(fn, fp, i)
    return ReceiptInfo(
        status=ReceiptStatus.READY,
        ticket_id=ticket_id,
        ticket_status=t_status,
        price=t_price,
        fn=fn,
        fd=getattr(receipt, 'fd', None),
        fp=fp,
        registered_at=registered_at,
        ofd_url=ofd_url,
        client_chat_id=t_client,
    )

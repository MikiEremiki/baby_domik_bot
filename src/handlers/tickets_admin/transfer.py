"""Transfer (migration) logic for /tickets_admin — reuses migration_admin flow."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from db import db_postgres
from db.enum import AgeType

from .constants import TRANSFER_PICK, TICKET_CARD, MENU


def _extract_client_data_from_ticket(ticket) -> dict:
    """Извлечь client_data (name_adult, phone, data_children) из билета."""
    name_adult = None
    data_children: list[list[str]] = []

    for person in ticket.people:
        if person.age_type == AgeType.adult and person.adult:
            if name_adult is None:
                name_adult = person.name or ''
        elif person.age_type == AgeType.child and person.child:
            age_str = str(person.child.age) if person.child.age is not None else '0'
            data_children.append([person.name or '', age_str])

    if not data_children:
        data_children = [['0', '0']]

    return {
        'name_adult': name_adult or '',
        'phone': ticket.phone,
        'data_children': data_children,
    }


# ── Инициализация переноса ─────────────────────────────────────────────────
# migration_admin_hl.migration_ticket (показ "по id / по параметрам")
# используется напрямую через tickets_admin_conv_hl.
# cb_transfer_start только инициализирует контекст перед ним.

def _get_thread_id(update: Update) -> int | None:
    """Извлекает message_thread_id из update для отправки в тему форума."""
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.message_thread_id
    if update.effective_message:
        return update.effective_message.message_thread_id
    return None


async def cb_transfer_start(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
    ticket_id: int,
) -> str:
    """Инициализация контекста переноса, затем делегируем в migration_ticket."""
    from handlers.migration_admin_hl import migration_ticket

    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        await update.effective_chat.send_message(
            'Билет не найден.', message_thread_id=_get_thread_id(update))
        return MENU

    # Контекст, который ожидают функции migration/reserve_admin
    context.user_data['reserve_admin_data']['ticket_id'] = ticket_id
    context.user_data['command'] = 'tickets_admin:migration'
    context.user_data['postfix_for_cancel'] = 'tickets_admin'
    if 'reserve_user_data' not in context.user_data:
        context.user_data['reserve_user_data'] = {
            'back': {},
            'client_data': {},
            'changed_seat': False,
        }

    # Заполняем client_data из оригинального билета — write_client_reserve
    # ожидает name_adult, phone, data_children
    context.user_data['reserve_user_data']['client_data'] = (
        _extract_client_data_from_ticket(ticket)
    )

    # Делегируем в migration_ticket — показывает "по id / по параметрам"
    return await migration_ticket(update, context)


# ── Обёртки для возврата к карточке билета после переноса ──────────────────
# start_forma_info и handle_custom_migration_params возвращают ConversationHandler.END
# после переноса. Обёртки перехватывают END и возвращают к карточке билета.

async def cb_ticket_selected(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> int:
    """Обёртка над start_forma_info: после END возвращаем к карточке билета."""
    from handlers.reserve_admin_hl import start_forma_info

    result = await start_forma_info(update, context)
    if result == ConversationHandler.END:
        return await cb_transfer_back(update, context)
    return result


async def cb_custom_ticket_params(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> str:
    """Обёртка над handle_custom_migration_params: после END возвращаем к карточке."""
    from conv_hl.migration_admin_conv_hl import handle_custom_migration_params

    result = await handle_custom_migration_params(update, context)
    if result == ConversationHandler.END:
        return await cb_transfer_back(update, context)
    return result


# ── Возврат в карточку билета ──────────────────────────────────────────────

async def cb_transfer_back(
    update: Update,
    context: 'ContextTypes.DEFAULT_TYPE',
) -> str:
    """Вернуться к карточке билета после переноса."""
    from .display import show_ticket_card

    ticket_id = context.user_data.get('tickets_admin', {}).get('current_ticket_id')
    if ticket_id is None:
        ticket_id = context.user_data['reserve_admin_data'].get('ticket_id')

    if ticket_id is not None:
        return await show_ticket_card(update, context, ticket_id, edit=False)
    return MENU

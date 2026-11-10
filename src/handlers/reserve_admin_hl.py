from __future__ import annotations

import logging

from sulguk import transform_html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, ConversationHandler

from api.googlesheets import write_client_reserve
from api.gspread_pub import publish_write_client_reserve
from db import db_postgres
from db.models import Ticket
from db.enum import TicketStatus
from db.db_googlesheets import increase_free_seat, decrease_free_seat
from db.db_postgres import get_schedule_theater_base_tickets
from handlers import init_conv_hl_dialog
from handlers.sub_hl import processing_successful_payment
from utilities.utl_googlesheets import update_ticket_db_and_gspread
from utilities.utl_func import (
    set_back_context,
    create_str_info_by_schedule_event_id,
    clean_context_on_end_handler,
)
from utilities.utl_kbd import (
    create_kbd_and_text_tickets_for_choice, create_replay_markup,
    remove_intent_id, add_btn_back_and_cancel,
)
from handlers.reserve_common_hl import (
    send_email_step,
    handle_email_input,
    handle_email_confirm_callback,
)
from utilities.utl_ticket import (
    get_ticket_and_price,
    parse_and_create_custom_ticket,
    apply_custom_ticket_to_reserve,
)

reserve_admin_hl_logger = logging.getLogger('bot.reserve_admin_hl')


async def _migrate_ticket_db(
        session,
        original_ticket,
        base_ticket_id: int,
        price: int,
        schedule_event_id: int,
        user_id: int,
) -> Ticket | None:
    """Одна транзакция БД: MIGRATED старый билет + новый билет + привязка."""
    people_ids = [person.id for person in original_ticket.people]
    ticket_id = original_ticket.id

    try:
        await db_postgres.update_ticket(
            session, ticket_id,
            status=TicketStatus.MIGRATED,
            auto_commit=False,
        )

        new_ticket = await db_postgres.create_transferred_ticket(
            session,
            original_ticket=original_ticket,
            base_ticket_id=base_ticket_id,
            price=price,
            schedule_event_id=schedule_event_id,
        )

        await db_postgres.attach_user_and_people_to_ticket(
            session,
            new_ticket.id,
            user_id,
            people_ids,
            auto_commit=False,
        )

        await session.commit()
        return new_ticket
    except Exception:
        await session.rollback()
        reserve_admin_hl_logger.exception("DB transaction rollback during ticket migration")
        return None


async def _sync_gspread_migration(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE',
        original_ticket,
        new_ticket,
        base_ticket_id: int,
        schedule_event_id: int,
        reserve_user_data: dict,
        send_status: callable,
) -> int | None:
    """Google Sheets синхронизация после успешной БД-транзакции."""
    ticket_id = original_ticket.id

    text = 'Обновляю клиентскую базу...'
    await send_status(text)
    await update.effective_chat.send_action(ChatAction.TYPING)
    await update_ticket_db_and_gspread(
        context, ticket_id, status=TicketStatus.MIGRATED, auto_commit=False
    )

    text += '\nВозвращаю места с перенесенного мероприятия...'
    await send_status(text)
    reserve_user_data['changed_seat'] = False
    result = await increase_free_seat(context, original_ticket.schedule_event_id)
    if not result:
        text += ('\nМеста не были возвращены в продажу.'
                 '\nНеобходимо проверить вручную.')
        await send_status(text)
        return new_ticket.id
    reserve_user_data['changed_seat'] = True

    # Write new ticket to client DB and decrease free seats
    text += '\nЗаписываю новый билет в клиентскую базу...'
    await send_status(text)
    await update.effective_chat.send_action(ChatAction.TYPING)
    sheet_id_domik = context.config.sheets.sheet_id_domik
    chat_id = update.effective_chat.id
    base_ticket_dto = (await db_postgres.get_base_ticket(
        context.session, base_ticket_id)).to_dto()
    ticket_status_value = str(TicketStatus.CREATED.value)
    reserve_user_data['ticket_ids'] = [new_ticket.id]
    try:
        await publish_write_client_reserve(
            sheet_id_domik,
            reserve_user_data,
            chat_id,
            base_ticket_dto,
            ticket_status_value
        )
    except Exception as e:
        reserve_admin_hl_logger.exception(
            f'Failed to publish gspread task, fallback to direct call: {e}')
        res = await write_client_reserve(sheet_id_domik,
                                         reserve_user_data,
                                         chat_id,
                                         base_ticket_dto,
                                         ticket_status_value)
        if res == 0:
            await context.bot.send_message(
                chat_id=context.config.bot.developer_chat_id,
                text=f'Не записался билет {new_ticket.id} в клиентскую базу')

    reserve_user_data['changed_seat'] = False
    result = await decrease_free_seat(context, schedule_event_id)
    if not result:
        await update_ticket_db_and_gspread(
            context, new_ticket.id, status=TicketStatus.CANCELED, auto_commit=False)
        text += ('\nНе уменьшились свободные места'
                 '\nНовый билет отменен.'
                 '\nНеобходимо проверить вручную')
        await send_status(text)
        return new_ticket.id
    reserve_user_data['changed_seat'] = True

    text += '\nУменьшил кол-во свободных мест...'
    await send_status(text)
    return new_ticket.id


async def execute_ticket_migration(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE',
        original_ticket,
        base_ticket_id: int,
        price: int,
        *,
        reserve_user_data: dict,
        send_status: callable | None = None,
) -> int | None:
    """Переносит билет одной транзакцией БД.

    Возвращает ID нового билета при успехе, None при ошибке.
    Google Sheets обновляется только после успешного commit.

    :param send_status: Асинхронная функция(text) для отправки статуса пользователю.
                        Если None, статус отправляется в чат как новое сообщение.
    """
    if send_status is None:
        async def send_status(text: str) -> None:
            await update.effective_chat.send_message(text=text)

    # Check if already migrated
    if original_ticket.status == TicketStatus.MIGRATED:
        await send_status('Билет уже перенесён')
        return None

    # Single DB transaction
    new_ticket = await _migrate_ticket_db(
        context.session,
        original_ticket,
        base_ticket_id,
        price,
        reserve_user_data.get('choose_schedule_event_id'),
        update.effective_user.id,
    )
    if new_ticket is None:
        text = 'Транзакция БД откатилась, выполните откат в Google Sheets вручную'
        await context.bot.send_message(
            chat_id=context.config.bot.developer_chat_id,
            text=text,
        )
        await send_status('Ошибка переноса билета. Обратитесь к разработчику.')
        return None

    # Google Sheets sync
    schedule_event_id = reserve_user_data.get('choose_schedule_event_id')
    return await _sync_gspread_migration(
        update, context, original_ticket, new_ticket,
        base_ticket_id, schedule_event_id, reserve_user_data, send_status,
    )


async def event_selection_option(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    await init_conv_hl_dialog(update, context)

    command = context.user_data['command']
    postfix_for_cancel = command
    context.user_data['postfix_for_cancel'] = postfix_for_cancel

    user = context.user_data.setdefault('user', update.effective_user)

    reserve_admin_hl_logger.info(
        f'Запущена команда бронирования администратором: {user}')

    text = 'Выбор показа по id или по параметрам?'

    keyboard = [
        [InlineKeyboardButton('по id', callback_data='id'),
         InlineKeyboardButton('по параметрам', callback_data='params')],
        add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            add_back_btn=False
        )
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.effective_message.message_thread_id
    )

    state = 1
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def enter_event_id(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    state = context.user_data['STATE']

    user = context.user_data.get('user', update.effective_user)
    reserve_admin_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    text = 'Введите id события'

    reply_markup = InlineKeyboardMarkup([
        add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'],
            postfix_for_back=state,
            add_back_btn=True
        )
    ])
    message = await query.edit_message_text(text=text, reply_markup=reply_markup)

    context.user_data['message'] = message.id

    state = 2
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def choice_option_of_reserve(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    await context.bot.delete_message(
        update.effective_chat.id,
        context.user_data['message'])
    try:
        choice_event_id = int(update.effective_message.text)
    except (ValueError, TypeError):
        await update.effective_chat.send_message(
            'Некорректный ID события. Пожалуйста, введите числовое значение.'
        )
        return ConversationHandler.END
    message = await update.effective_chat.send_message('Загружаю данные')

    (
        base_tickets,
        schedule_event,
        theater_event,
        type_event
    ) = await get_schedule_theater_base_tickets(context, choice_event_id)

    text_select_event = await create_str_info_by_schedule_event_id(
        context, choice_event_id)

    text = (f'Кол-во свободных мест: '
            f'<i>'
            f'{schedule_event.qty_adult_free_seat} взр'
            f' | '
            f'{schedule_event.qty_child_free_seat} дет'
            f'</i><br>')
    text = f'{text_select_event}{text}'
    text += '<b>Выберите подходящий вариант бронирования:</b><br>'

    keyboard, text = await create_kbd_and_text_tickets_for_choice(
        context, text, base_tickets, schedule_event, theater_event)
    state = 'TICKET'
    reply_markup = await create_replay_markup(
        keyboard,
        intent_id=state,
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back=1,
        size_row=5
    )

    res_text = transform_html(text)
    await message.edit_text(
        text=res_text.text,
        entities=res_text.entities,
        parse_mode=None,
        reply_markup=reply_markup)

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['choose_schedule_event_id'] = schedule_event.id
    reserve_user_data['choose_theater_event_id'] = theater_event.id

    context.user_data['STATE'] = state
    return state


async def start_forma_info(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)

    _, callback_data = remove_intent_id(query.data)
    if callback_data == 'CUSTOM':
        text = ('<b>Индивидуальный расчет билета</b><br><br>'
                'Введите через пробел: <code>кол-во детей</code> <code>кол-во взрослых</code> <code>стоимость</code><br>'
                'Например: <code>8 1 15000</code>')
        keyboard = [
            add_btn_back_and_cancel(
                postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
                postfix_for_back='TICKET',
                add_back_btn=True
            )
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        res_text = transform_html(text)
        message = await query.edit_message_text(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_markup=reply_markup
        )
        reserve_user_data = context.user_data['reserve_user_data']
        reserve_user_data['message_id'] = message.message_id
        state = 'CUSTOM_TICKET_PARAMS'
        context.user_data['STATE'] = state
        await set_back_context(context, state, res_text.text, reply_markup)
        return state

    base_ticket_id = int(callback_data)

    chose_base_ticket, chose_price = await get_ticket_and_price(
        context, base_ticket_id)
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    reserve_user_data['chose_price'] = chose_price
    reserve_user_data['chose_base_ticket_id'] = chose_base_ticket.base_ticket_id
    reserve_user_data['choose_schedule_event_ids'] = [schedule_event_id]

    if 'migration' in context.user_data['command']:
        original_ticket_id = context.user_data['reserve_admin_data']['ticket_id']
        original_ticket = await db_postgres.get_ticket(context.session, original_ticket_id)

        async def send_status(text: str) -> None:
            await query.edit_message_text(text)

        new_ticket_id = await execute_ticket_migration(
            update, context, original_ticket,
            base_ticket_id, chose_price,
            reserve_user_data=context.user_data['reserve_user_data'],
            send_status=send_status,
        )

        if new_ticket_id is None:
            await clean_context_on_end_handler(reserve_admin_hl_logger, context)
            state = ConversationHandler.END
        else:
            reserve_user_data = context.user_data['reserve_user_data']
            reserve_user_data['ticket_ids'] = [new_ticket_id]
            await processing_successful_payment(update, context)
            text = 'Билет успешно перенесен.'
            await query.edit_message_text(text)
            state = ConversationHandler.END
    else:
        # Prompt for buyer email first
        _, state = await send_email_step(update, context, postfix_for_back='TICKET',
                                          edit_message=True)

    context.user_data['STATE'] = state
    return state


async def handle_custom_ticket_params(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    text_input = update.effective_message.text.strip()
    custom_ticket, error_text = await parse_and_create_custom_ticket(context, text_input)
    if custom_ticket is None:
        keyboard = [
            add_btn_back_and_cancel(
                postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
                postfix_for_back='TICKET',
                add_back_btn=True
            )
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        res_text = transform_html(error_text)
        await update.effective_chat.send_message(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_markup=reply_markup
        )
        return 'CUSTOM_TICKET_PARAMS'

    cost = int(text_input.strip().split()[2])
    apply_custom_ticket_to_reserve(context, custom_ticket, cost)

    # Prompt for buyer email first
    _, state = await send_email_step(update, context, postfix_for_back='TICKET')
    context.user_data['STATE'] = state
    return state


async def get_email_admin(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    """Admin reservation: collect buyer email before proceeding to FORMA."""
    return await handle_email_input(update, context, postfix_for_back='TICKET')


async def email_confirm(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """Admin reservation: confirm pre-filled email from admin profile."""
    return await handle_email_confirm_callback(update, context, postfix_for_back='TICKET')

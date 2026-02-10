import logging

from sulguk import transform_html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, ConversationHandler

from api.googlesheets import write_client_reserve
from api.gspread_pub import publish_write_client_reserve
from db import db_postgres
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
from utilities.utl_ticket import get_ticket_and_price

reserve_admin_hl_logger = logging.getLogger('bot.reserve_admin_hl')


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
        message_thread_id=update.message.message_thread_id
    )

    state = 1
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def enter_event_id(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    state = context.user_data['STATE']

    user = context.user_data['user']
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
    choice_event_id = update.effective_message.text
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
    base_ticket_id = int(callback_data)

    chose_base_ticket, chose_price = await get_ticket_and_price(
        context, base_ticket_id)
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    reserve_user_data['chose_price'] = chose_price
    reserve_user_data['chose_base_ticket_id'] = chose_base_ticket.base_ticket_id
    reserve_user_data['choose_schedule_event_ids'] = [schedule_event_id]

    if 'migration' in context.user_data['command']:
        ticket_id = context.user_data['reserve_admin_data']['ticket_id']
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        people_ids = []
        for person in ticket.people:
            people_ids.append(person.id)

        old_ticket_status = ticket.status
        new_ticket_status = TicketStatus.MIGRATED
        text = 'Проверяю надо ли переносить билет...'
        await query.edit_message_text(text)
        if new_ticket_status != old_ticket_status:
            text += '\nОбновляю билет который надо перенести...'
            await query.edit_message_text(text)
            await update.effective_chat.send_action(ChatAction.TYPING)
            await update_ticket_db_and_gspread(context,
                                               ticket_id,
                                               status=new_ticket_status)
            text += '\nВозвращаю места с перенесенного мероприятия...'
            await query.edit_message_text(text)
            reserve_user_data['changed_seat'] = False
            result = await increase_free_seat(
                context, ticket.schedule_event_id, ticket.base_ticket_id)
            if not result:
                await update_ticket_db_and_gspread(context,
                                                   ticket_id,
                                                   status=old_ticket_status)
                text += (
                    '\nМеста не были возвращены в продажу.'
                    '\nСтатус билета возвращен обратно.'
                    '\nНеобходимо повторить перенос заново.')
                await query.edit_message_text(text)
                await clean_context_on_end_handler(
                    reserve_admin_hl_logger, context)
                return ConversationHandler.END
            else:
                reserve_user_data['changed_seat'] = True
        else:
            text += '\nБилет уже в статусе Перенесен...'
            await query.edit_message_text(text)

        text += '\nСоздаю новые билеты в бд...'
        await query.edit_message_text(text)

        ticket_ids = []
        ticket = await db_postgres.create_ticket(
            context.session,
            base_ticket_id=base_ticket_id,
            price=chose_price,
            schedule_event_id=schedule_event_id,
            promo_id=ticket.promo_id,
            status=TicketStatus.CREATED,
            notes=ticket.notes
        )
        ticket_ids.append(ticket.id)

        reserve_user_data['ticket_ids'] = ticket_ids

        await db_postgres.attach_user_and_people_to_ticket(context.session,
                                                           ticket.id,
                                                           update.effective_user.id,
                                                           people_ids)

        text += '\nЗаписываю новый билет в клиентскую базу...'
        await query.edit_message_text(text)
        await update.effective_chat.send_action(ChatAction.TYPING)
        sheet_id_domik = context.config.sheets.sheet_id_domik
        chat_id = update.effective_chat.id
        base_ticket_dto = chose_base_ticket.to_dto()
        ticket_status_value = str(TicketStatus.CREATED.value)
        reserve_user_data = context.user_data['reserve_user_data']
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
                    text=f'Не записался билет {ticket_ids} в клиентскую базу')
        reserve_user_data['changed_seat'] = False
        result = await decrease_free_seat(
            context, schedule_event_id, base_ticket_id)
        if not result:
            await update_ticket_db_and_gspread(context,
                                               ticket_id,
                                               status=TicketStatus.CANCELED)
            text += ('\nНе уменьшились свободные места'
                     '\nНовый билет отменен.'
                     '\nСтарый билет будет учтен, что уже перенесен.'
                     '\nНеобходимо повторить перенос заново')
            await query.edit_message_text(text)
            await clean_context_on_end_handler(reserve_admin_hl_logger, context)
            return ConversationHandler.END
        else:
            reserve_user_data['changed_seat'] = True

        text += '\nУменьшил кол-во свободных мест...\nПоследняя проверка...'
        await query.edit_message_text(text)
        await update.effective_chat.send_action(ChatAction.TYPING)
        await processing_successful_payment(update, context)
        text += '\n\nБилет успешно перенесен.'
        await query.edit_message_text(text)

        state = ConversationHandler.END
    else:
        keyboard = [add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=False
        )]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = '<b>Напишите фамилию и имя (взрослого)</b>'
        message = await query.edit_message_text(
            text=text, reply_markup=reply_markup)

        reserve_user_data['message_id'] = message.message_id
        state = 'FORMA'

    context.user_data['STATE'] = state
    return state

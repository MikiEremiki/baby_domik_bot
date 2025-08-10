import logging

from telegram.ext import (
    ContextTypes, ConversationHandler, ApplicationHandlerStop)
from telegram import (
    Update, ReplyKeyboardRemove, LinkPreviewOptions,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.constants import ChatType, ChatAction
from telegram.error import BadRequest, TimedOut

from db import db_postgres
from db.enum import TicketStatus, CustomMadeStatus
from handlers import check_user_db
from db.db_googlesheets import (
    decrease_nonconfirm_seat,
    increase_free_seat,
    increase_free_and_decrease_nonconfirm_seat, update_free_seat,
)
from settings.settings import (
    COMMAND_DICT, ADMIN_GROUP, FEEDBACK_THREAD_ID_GROUP_ADMIN, FILE_ID_RULES
)
from api.googlesheets import update_cme_in_gspread, update_ticket_in_gspread
from utilities.utl_func import (
    is_admin, get_back_context, clean_context,
    clean_context_on_end_handler, cancel_common, del_messages,
    append_message_ids_back_context, create_str_info_by_schedule_event_id,
    get_formatted_date_and_time_of_event
)
from utilities.utl_ticket import cancel_tickets_db_and_gspread

main_handlers_logger = logging.getLogger('bot.main_handlers')


async def start(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    await check_user_db(update, context)
    await cancel_tickets_db_and_gspread(update, context)
    await clean_context(context)
    await clean_context_on_end_handler(main_handlers_logger, context)

    context.user_data['user'] = update.effective_user
    context.user_data['common_data'] = {}

    context.user_data['last_update'] = None

    start_text = '<b>Вас приветствует Бот Бэби-театра «Домик»</b>\n\n'
    description = context.bot_data['texts']['description']
    address = context.bot_data['texts']['address']
    ask_question = context.bot_data['texts']['ask_question']
    command = (
        'Для продолжения работы используйте команды:\n'
        f'/{COMMAND_DICT['RESERVE'][0]} - выбрать и оплатить билет на спектакль '
        f'\n'
        # f'(<a href="https://vk.com/baby_theater_domik?w=wall-202744340_2446">инструкция</a>)\n'
        f'/{COMMAND_DICT['BD_ORDER'][0]} - оформить заявку на проведение дня рождения '
        # f'(<a href="https://vk.com/wall-202744340_2469">инструкция</a>)
        '\n\n'
    )
    await update.effective_chat.send_message(
        text=start_text + description + command + address + ask_question,
        reply_markup=ReplyKeyboardRemove(),
        link_preview_options=LinkPreviewOptions(
            url='https://t.me/theater_domik')
    )

    context.user_data['conv_hl_run'] = False
    return ConversationHandler.END


async def send_approve_msg(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    if not context.args:
        text = (
            'Отправляет:\n'
            '- подтверждение пользователю по номеру билета\n'
            '- правила при добавлении слова <code>Правила</code> в конце\n'
        )
        text += '\n\n<code>/send_approve_msg 0</code>'
        text += '\nИЛИ'
        text += '\n<code>/send_approve_msg 0 Правила</code>'
        await update.effective_message.reply_text(
            text, reply_to_message_id=update.message.message_id)
        return
    text = ''
    ticket_id = context.args[0]
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        text = (f'Проверь номер билета\n'
                f'Введено: {ticket_id}')
        await update.effective_message.reply_text(
            text, reply_to_message_id=update.message.message_id)
        return
    chat_id = ticket.user.chat_id
    await send_approve_message(chat_id, context)
    text += 'Подтверждение'

    if len(context.args) == 2:
        if context.args[1] == 'Правила':
            await context.bot.send_photo(
                chat_id=chat_id, photo=FILE_ID_RULES, caption='Правила театра')
            text += ' и правила'
        else:
            text = (f'Проверь ключевое слово <code>Правила</code>\n'
                    f'Введено: {context.args[1]}')
            await update.effective_message.reply_text(
                text, reply_to_message_id=update.message.message_id)
            return
    text += ' успешно отправлено'
    await update.effective_message.reply_text(text)


async def send_msg(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    if not context.args:
        text = (
            'Отправить сообщение пользователю:\n'
            '- по номеру билета (<code>Билет</code>)\n'
            '- по номеру заявки заказного мероприятия (<code>Заявка</code>)\n'
            '- по chat_id в telegram (<code>Чат</code>)\n\n'
        )
        text += '<code>/send_msg Тип 0 Сообщение</code>\n\n'
        await update.message.reply_text(
            text, reply_to_message_id=update.message.message_id)
        return
    type_enter_chat_id = context.args[0]
    text = ' '.join(context.args[2:])
    match type_enter_chat_id:
        case 'Билет':
            ticket_id = context.args[1]
            ticket = await db_postgres.get_ticket(context.session, ticket_id)
            if not ticket:
                text = 'Проверь номер билета'
                await update.message.reply_text(
                    text, reply_to_message_id=update.message.message_id)
                return
            chat_id = ticket.user.chat_id
        case 'Заявка':
            cme_id = context.args[1]
            cme = await db_postgres.get_custom_made_event(context.session,
                                                          cme_id)
            if not cme:
                text = 'Проверь номер заявки'
                await update.message.reply_text(
                    text, reply_to_message_id=update.message.message_id)
                return
            chat_id = cme.user_id
        case 'Чат':
            chat_id = context.args[1]
        case _:
            text = ('Проверь что Тип указан верно, возможные варианты:\n'
                    '<code>Билет</code>\n'
                    '<code>Заявка</code>\n'
                    '<code>Чат</code>')
            await update.message.reply_text(
                text, reply_to_message_id=update.message.message_id)
            return
    await context.bot.send_message(text=text, chat_id=chat_id)
    await update.effective_message.reply_text(
        f'Сообщение:\n{text}\nУспешно отправлено')


async def update_ticket(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    text = 'Справка по команде\n'
    text += '<code>/update_ticket 0 Слово Текст</code>\n\n'
    text += '0 - это номер билета\n'
    text += ('<i>Если написать только номер, то будет отправлена информация по '
             'билету</i>\n')
    help_id_number = text
    text += 'Слово - может быть:\n'
    text += ('<code>Статус</code>\n'
             '<code>Примечание</code>\n'
             '<code>Базовый</code>\n'
             '<code>Покупатель</code>\n\n')
    help_key_word_text = text
    text += 'Для <code>Примечание</code> просто пишем Текст примечания\n\n'
    text += 'Для <code>Базовый</code> Текст это номер базового билета\n\n'
    text += 'Для <code>Статус</code> Текст может быть:\n'
    text += get_ticket_status_name()
    text += '\nПовлияют на расписание\n'
    text += '<i>Сейчас -> Станет:</i>\n'
    text += 'Создан -> Подтвержден|Отклонен|Отменен\n'
    text += 'Оплачен -> Подтвержден|Отклонен|Возвращен\n'
    text += ('Подтвержден -> '
             'Отклонен|Возвращен|Передан|Перенесен|Отменен\n\n')
    text += 'Остальные направления не повлияют на расписание\n'
    text += 'если билет Сейчас:\n'
    text += 'Отклонен|Передан|Возвращен|Перенесен|Отменен\n'
    text += ('Это финальные статусы, если нужно сменить, '
             'то используем новый билет\n')
    help_text = text
    reply_to_msg_id = update.message.message_id

    if not context.args:
        await update.message.reply_text(
            help_text, reply_to_message_id=reply_to_msg_id)
        return

    try:
        ticket_id = int(context.args[0])
    except ValueError:
        text = 'Задан не номер' + help_id_number
        await update.message.reply_text(
            text, reply_to_message_id=reply_to_msg_id)
        return

    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        text = 'Проверь номер билета'
        await update.message.reply_text(
            text, reply_to_message_id=reply_to_msg_id)
        return
    try:
        await update.effective_chat.send_action(
            ChatAction.TYPING,
            message_thread_id=update.effective_message.message_thread_id)
    except TimedOut as e:
        main_handlers_logger.error(e)

    if len(context.args) == 1:
        user = ticket.user
        people = ticket.people
        base_ticket = await db_postgres.get_base_ticket(
            context.session, ticket.base_ticket_id)
        schedule_event = await db_postgres.get_schedule_event(
            context.session, ticket.schedule_event_id)
        theater_event = await db_postgres.get_theater_event(
            context.session, schedule_event.theater_event_id
        )
        adult_str = ''
        child_str = ''
        for person in people:
            if hasattr(person.adult, 'phone'):
                adult_str = f'{person.name}\n+7{person.adult.phone}\n'
            elif hasattr(person.child, 'age'):
                child_str += f'{person.name} {person.child.age}\n'
        people_str = adult_str + child_str
        date_event, time_event = await get_formatted_date_and_time_of_event(
            schedule_event)
        text = (
            f'Техническая информация по билету {ticket_id}\n\n'
            f'Событие {schedule_event.id}: {theater_event.name}\n'
            f'{date_event} в {time_event}\n\n'
            f'Привязан к профилю: {user.user_id}\n'
            f'Билет: {base_ticket.name}\n'
            f'Стоимость: {ticket.price}\n'
            f'Статус: {ticket.status.value}\n'
            f'{people_str}'
            f'Примечание: {ticket.notes}\n'
        )
        await update.message.reply_text(
            text, reply_to_message_id=reply_to_msg_id)
        return
    else:
        data = {}
        match context.args[1]:
            case 'Примечание':
                if context.args[2:]:
                    new_ticket_notes = ' '.join(context.args[2:])
                    data['notes'] = new_ticket_notes
                else:
                    text = 'Не задан текст примечания'
                    await update.message.reply_text(
                        text, reply_to_message_id=reply_to_msg_id)
                    return
            case 'Статус':
                try:
                    new_ticket_status = TicketStatus(context.args[2])
                except ValueError:
                    text = 'Неверный статус билета\n'
                    text += 'Возможные статусы:\n'
                    text += get_ticket_status_name()
                    text += '\n\n Для подробной справки нажми /update_ticket'
                    await update.message.reply_text(
                        text, reply_to_message_id=reply_to_msg_id)
                    return
                except IndexError:
                    text = '<b>>>>Не задано новое значение статуса</b>\n\n'
                    text += help_text
                    await update.message.reply_text(
                        text, reply_to_message_id=reply_to_msg_id)
                    return

                schedule_event_id = ticket.schedule_event_id
                base_ticket_id = ticket.base_ticket_id

                if ticket.status == TicketStatus.CREATED:
                    if new_ticket_status == TicketStatus.CANCELED:
                        await increase_free_and_decrease_nonconfirm_seat(
                            context, schedule_event_id, base_ticket_id)
                    if new_ticket_status == TicketStatus.APPROVED:
                        await decrease_nonconfirm_seat(
                            context, schedule_event_id, base_ticket_id)
                    if new_ticket_status == TicketStatus.REJECTED:
                        await increase_free_and_decrease_nonconfirm_seat(
                            context, schedule_event_id, base_ticket_id)

                if ticket.status == TicketStatus.PAID:
                    if new_ticket_status == TicketStatus.APPROVED:
                        await decrease_nonconfirm_seat(
                            context, schedule_event_id, base_ticket_id)
                    if new_ticket_status == TicketStatus.REJECTED:
                        await increase_free_and_decrease_nonconfirm_seat(
                            context, schedule_event_id, base_ticket_id)
                    if new_ticket_status == TicketStatus.REFUNDED:
                        await increase_free_and_decrease_nonconfirm_seat(
                            context, schedule_event_id, base_ticket_id)

                if ticket.status == TicketStatus.APPROVED:
                    if (
                            new_ticket_status == TicketStatus.REJECTED or
                            new_ticket_status == TicketStatus.REFUNDED or
                            new_ticket_status == TicketStatus.TRANSFERRED or
                            new_ticket_status == TicketStatus.MIGRATED or
                            new_ticket_status == TicketStatus.CANCELED
                    ):
                        await increase_free_seat(
                            context, schedule_event_id, base_ticket_id)

                if (
                        ticket.status == TicketStatus.REJECTED or
                        ticket.status == TicketStatus.REFUNDED or
                        ticket.status == TicketStatus.TRANSFERRED or
                        ticket.status == TicketStatus.MIGRATED or
                        ticket.status == TicketStatus.CANCELED
                ):
                    pass

                sheet_id_domik = context.config.sheets.sheet_id_domik
                await update_ticket_in_gspread(sheet_id_domik, ticket_id,
                                         new_ticket_status.value)
                data['status'] = new_ticket_status
            case 'Покупатель':
                people = ticket.people
                adult_str = ''
                child_str = ''
                for person in people:
                    if hasattr(person.adult, 'phone'):
                        adult_str = f'{person.name}\n+7{person.adult.phone}\n'
                    elif hasattr(person.child, 'age'):
                        child_str += f'{person.name} {person.child.age}\n'
                people_str = adult_str + child_str
                schedule_event_id = ticket.schedule_event_id
                price = ticket.price
                base_ticket = await db_postgres.get_base_ticket(
                    context.session, ticket.base_ticket_id)

                text_select_event = await create_str_info_by_schedule_event_id(
                    context, schedule_event_id)

                text = f'<b>Номер билета <code>{ticket_id}</code></b>\n\n'
                text += text_select_event + (f'\nВариант бронирования:\n'
                                             f'{base_ticket.name} '
                                             f'{int(price)}руб\n\n')
                text += 'На кого оформлен:\n'
                text += people_str + '\n\n'
                refund = '❗️ВОЗВРАТ ДЕНЕЖНЫХ СРЕДСТВ ИЛИ ПЕРЕНОС ВОЗМОЖЕН НЕ МЕНЕЕ, ЧЕМ ЗА 24 ЧАСА❗\n\n'
                text += refund

                await update.message.reply_text(
                    text, reply_to_message_id=reply_to_msg_id)
                return
            case 'Базовый':
                try:
                    new_base_ticket_id = int(context.args[2])
                    old_base_ticket_id = ticket.base_ticket_id
                except ValueError:
                    text = 'Задан не номер базового билета'
                    await update.message.reply_text(
                        text, reply_to_message_id=reply_to_msg_id)
                    return
                new_base_ticket = await db_postgres.get_base_ticket(
                    context.session, new_base_ticket_id)
                if not new_base_ticket:
                    text = 'Проверь номер базового билета'
                    await update.message.reply_text(
                        text, reply_to_message_id=reply_to_msg_id)
                    return
                if new_base_ticket_id == old_base_ticket_id:
                    text = (f'Билету {ticket_id} уже присвоен '
                            f'базовый билет {new_base_ticket_id}')
                    await update.message.reply_text(
                        text, reply_to_message_id=reply_to_msg_id)
                    return

                data['base_ticket_id'] = new_base_ticket_id
                await update_free_seat(
                    context,
                    ticket.schedule_event_id,
                    old_base_ticket_id,
                    new_base_ticket_id
                )
            case _:
                text = 'Не задано ключевое слово или оно написано с ошибкой\n\n'
                text += help_key_word_text
                await update.message.reply_text(
                    text, reply_to_message_id=reply_to_msg_id)
                return

    await db_postgres.update_ticket(context.session, ticket_id, **data)

    await send_result_update_ticket(update, context, ticket_id, data)


def get_ticket_status_name():
    text = ''
    for status in TicketStatus:
        text += f'<code>{status.value}</code>\n'
    return text


async def send_result_update_ticket(
        update,
        context,
        ticket_id,
        data
):
    text = f'Билет <code>{ticket_id}</code> обновлен\n'
    status = data.get('status', None)
    text += ('Статус: ' + status.value) if status else ''
    base_ticket_id = data.get('base_ticket_id', None)
    text += ('Новый базовый билет: '
             + str(base_ticket_id)
             + '\nВ Расписании обновлено, а в клиентской базе данную '
               'информацию надо поменять в ручную'
             ) if base_ticket_id else ''
    notes = data.get('notes', None)
    text += ('Примечание: ' + notes) if notes else ''
    if bool(update.message.reply_to_message):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_to_message_id=update.message.reply_to_message.message_id,
            message_thread_id=update.message.message_thread_id
        )
    else:
        await update.effective_message.reply_text(
            text=text,
            message_thread_id=update.message.message_thread_id,
            reply_to_message_id=update.message.message_id
        )


async def confirm_reserve(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    query = update.callback_query
    if not is_admin(update):
        text = 'Не разрешенное действие: подтвердить бронь'
        main_handlers_logger.warning(text)
        return
    message_thread_id = query.message.message_thread_id
    try:
        await update.effective_chat.send_action(
            ChatAction.TYPING,
            message_thread_id=message_thread_id)
    except TimedOut as e:
        main_handlers_logger.error(e)

    message = await update.effective_chat.send_message(
        text='Начат процесс подтверждения...',
        reply_to_message_id=query.message.message_id,
        message_thread_id=message_thread_id
    )

    chat_id = query.data.split('|')[1].split()[0]
    message_id_buy_info = query.data.split('|')[1].split()[1]

    ticket_ids = [int(update.effective_message.text.split('#ticket_id ')[1])]
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)
    for ticket_id in ticket_ids:
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        await decrease_nonconfirm_seat(
            context, ticket.schedule_event_id, ticket.base_ticket_id)

    text = message.text + f'\nСписаны неподтвержденные места...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    ticket_status = TicketStatus.APPROVED
    sheet_id_domik = context.config.sheets.sheet_id_domik
    for ticket_id in ticket_ids:
        await update_ticket_in_gspread(sheet_id_domik, ticket_id, ticket_status.value)
        await db_postgres.update_ticket(context.session,
                                        ticket_id,
                                        status=ticket_status)

    try:
        await query.edit_message_reply_markup()
    except TimedOut as e:
        main_handlers_logger.error(e)

    text = message.text + f'\nОбновлен статус билета: {ticket_status.value}...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    await send_approve_message(chat_id, context)
    text = message.text + f'\nОтправлено сообщение о подтверждении бронирования...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    text = f'Бронь подтверждена\n'
    for ticket_id in ticket_ids:
        text += 'Билет ' + str(ticket_id) + '\n'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id_buy_info
        )
    except BadRequest as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info('Cообщение уже удалено')


async def send_approve_message(chat_id, context):
    description = context.bot_data['texts']['description']
    address = context.bot_data['texts']['address']
    ask_question = context.bot_data['texts']['ask_question']
    command = (
        'Для продолжения работы используйте команды:\n'
        f'/{COMMAND_DICT['RESERVE'][0]} - выбрать и оплатить билет на спектакль\n'
    )
    approve_text = '<b>Ваша бронь подтверждена, ждем вас на мероприятии.</b>\n\n'
    refund = '❗️ВОЗВРАТ ДЕНЕЖНЫХ СРЕДСТВ ИЛИ ПЕРЕНОС ВОЗМОЖЕН НЕ МЕНЕЕ, ЧЕМ ЗА 24 ЧАСА❗\n\n'
    text = approve_text + address + refund + description + ask_question + command
    await context.bot.send_message(text=text, chat_id=chat_id)


async def send_reject_message(chat_id, context):
    text = (
        'Ваша бронь отклонена.\n\n'
        'Если это произошло по ошибке, пожалуйста, '
        'напишите в ЛС или позвоните Администратору:\n'
        f'{context.bot_data['admin']['contacts']}'
    )
    await context.bot.send_message(text=text, chat_id=chat_id)


async def reject_reserve(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    query = update.callback_query
    if not is_admin(update):
        main_handlers_logger.warning('Не разрешенное действие: отклонить бронь')
        return
    message_thread_id = query.message.message_thread_id
    try:
        await update.effective_chat.send_action(
            ChatAction.TYPING,
            message_thread_id=message_thread_id)
    except TimedOut as e:
        main_handlers_logger.error(e)

    message = await update.effective_chat.send_message(
        text='Начат процесс отклонения...',
        reply_to_message_id=query.message.message_id,
        message_thread_id=message_thread_id
    )

    chat_id = query.data.split('|')[1].split()[0]
    message_id_buy_info = query.data.split('|')[1].split()[1]

    ticket_ids = [int(update.effective_message.text.split('#ticket_id ')[1])]
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)
    for ticket_id in ticket_ids:
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        await increase_free_and_decrease_nonconfirm_seat(
            context, ticket.schedule_event_id, ticket.base_ticket_id)

    text = message.text + f'\nВозвращены места в продажу...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    ticket_status = TicketStatus.REJECTED
    sheet_id_domik = context.config.sheets.sheet_id_domik
    for ticket_id in ticket_ids:
        await update_ticket_in_gspread(sheet_id_domik, ticket_id, ticket_status.value)
        await db_postgres.update_ticket(context.session,
                                        ticket_id,
                                        status=ticket_status)

    await query.edit_message_reply_markup()
    text = message.text + f'\nОбновлен статус билета: {ticket_status.value}...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    await send_reject_message(chat_id, context)
    text = message.text + f'\nОтправлено сообщение об отклонении бронирования...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    text = f'Бронь отклонена\n'
    for ticket_id in ticket_ids:
        text += 'Билет ' + str(ticket_id) + '\n'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id_buy_info
        )
    except BadRequest as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info('Cообщение уже удалено')


async def confirm_birthday(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    query = update.callback_query
    if not is_admin(update):
        main_handlers_logger.warning(
            'Не разрешенное действие: подтвердить день рождения')
        return
    message_thread_id = query.message.message_thread_id
    try:
        await update.effective_chat.send_action(
            ChatAction.TYPING,
            message_thread_id=message_thread_id)
    except TimedOut as e:
        main_handlers_logger.error(e)

    message = await update.effective_chat.send_message(
        text='Начат процесс подтверждения...',
        reply_to_message_id=query.message.message_id,
        message_thread_id=message_thread_id
    )

    chat_id = query.data.split('|')[1].split()[0]
    message_id_for_reply = query.data.split('|')[1].split()[1]
    cme_id = query.data.split('|')[1].split()[2]

    step = query.data.split('|')[0][-1]
    text = ('Возникла ошибка\n'
            'Cвяжитесь с администратором:\n'
            f'{context.bot_data['cme_admin']['contacts']}')

    match step:
        case '1':
            cme_status = CustomMadeStatus.APPROVED
        case '2':
            cme_status = CustomMadeStatus.PREPAID

    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)

    sheet_id_cme = context.config.sheets.sheet_id_cme
    await update_cme_in_gspread(sheet_id_cme, cme_id, cme_status.value)
    await message.edit_text(
        message.text + f'\nОбновил статус в гугл-таблице {cme_status.value}')

    await db_postgres.update_custom_made_event(
        context.session, cme_id, status=cme_status)
    await message.edit_text(message.text + f'и бд {cme_status.value}')

    await query.edit_message_reply_markup()
    reply_markup = None
    match step:
        case '1':
            await message.edit_text(
                f'Заявка {cme_id} подтверждена, ждём предоплату')

            text = (f'<b>У нас отличные новости'
                    f' по вашей заявке: {cme_id}</b>\n')
            text += 'Мы с радостью проведем день рождения вашего малыша\n\n'
            text += (
                '❗️важно\n'
                'При отмене мероприятия заказчиком не менее чем за 24 часа до '
                'запланированного времени проведения, возможен перенос на другую'
                ' дату или сохранение средств, внесенных в предоплату, '
                'на депозите, которыми можно воспользоваться и забронировать '
                'билеты в театр «Домик» в течение 6 месяцев❗️\n\n'
                'В случае отмены мероприятия заказчиком менее, чем за 24 часа до '
                'мероприятия, перенос даты или сохранение средств на депозите '
                'не возможно и внесенная предоплата не возвращается\n\n')
            text += (
                '- Если вы согласны с правилами, то переходите к оплате:\n'
                '<b>- Сумма к оплате поступит в течении 5 минут</b>\n'
                ' Нажмите кнопку <b>Оплатить</b>\n'
                ' <i>Вы будете перенаправлены на платежный сервис Юкасса'
                ' Способ оплаты - СБП</i>\n\n'
            )
            text += '<i>- Ссылка не имеет ограничений по времени</i>\n'
            text += ('<i>- После оплаты отправьте сюда в чат квитанцию об '
                     'оплате файлом или картинкой.</i>\n')
            text += '<i> и <u>обязательно</u> напишите номер заявки</i>\n'
            keyboard = []
            button_payment = InlineKeyboardButton(
                'Оплатить',
                url='https://yookassa.ru/my/i/Z1Xo7iDNcw7l/l'
            )
            keyboard.append([button_payment])
            reply_markup = InlineKeyboardMarkup(keyboard)

        case '2':
            await message.edit_text(f'Подтверждена бронь по заявке {cme_id}')

            text = f'Ваша бронь по заявке {cme_id} подтверждена\n'
            text += 'До встречи в Домике'

    try:
        await context.bot.send_message(
            text=text,
            chat_id=chat_id,
            reply_to_message_id=message_id_for_reply,
            reply_markup=reply_markup,
        )
    except BadRequest as e:
        main_handlers_logger.error(e)
        await context.bot.send_message(
            text=text,
            chat_id=chat_id,
        )


async def reject_birthday(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    query = update.callback_query
    if not is_admin(update):
        main_handlers_logger.warning(
            'Не разрешенное действие: отклонить день рождения')
        return
    message_thread_id = query.message.message_thread_id
    try:
        await update.effective_chat.send_action(
            ChatAction.TYPING,
            message_thread_id=message_thread_id)
    except TimedOut as e:
        main_handlers_logger.error(e)

    message = await update.effective_chat.send_message(
        text='Начат процесс отклонения...',
        reply_to_message_id=query.message.message_id,
        message_thread_id=message_thread_id
    )

    chat_id = query.data.split('|')[1].split()[0]
    message_id_for_reply = query.data.split('|')[1].split()[1]
    cme_id = query.data.split('|')[1].split()[2]

    step = query.data.split('|')[0][-1]
    text = ('Возникла ошибка\n'
            'Cвяжитесь с администратором:\n'
            f'{context.bot_data['cme_admin']['contacts']}')

    cme_status = CustomMadeStatus.REJECTED

    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)

    sheet_id_cme = context.config.sheets.sheet_id_cme
    await update_cme_in_gspread(sheet_id_cme, cme_id, cme_status.value)
    await message.edit_text(
        message.text + f'\nОбновил статус в гугл-таблице {cme_status.value}')

    await db_postgres.update_custom_made_event(
        context.session, cme_id, status=cme_status)
    await message.edit_text(message.text + f'и бд {cme_status.value}')

    await query.edit_message_reply_markup()
    match step:
        case '1':
            await message.edit_text(f'Заявка {cme_id} отклонена')

            text = f'Мы рассмотрели Вашу заявку: {cme_id}.\n'
            text += ('Срок обработки данной заявки истёк.\n'
                     'При необходимости сформируйте повторную заявку.\n'
                     'Мы всегда готовы стать частью Вашего праздника🏡💚')

        case '2':
            await message.edit_text(f'Отклонена бронь по заявке {cme_id}')

            text = f'Ваша бронь по заявке: {cme_id} отклонена.\n'

    text += ('При возникновении вопросов, свяжитесь с Администратором:\n'
             f'{context.bot_data['cme_admin']['contacts']}')
    try:
        await context.bot.send_message(
            text=text,
            chat_id=chat_id,
            reply_to_message_id=message_id_for_reply,
        )
    except BadRequest as e:
        main_handlers_logger.error(e)
        await context.bot.send_message(
            text=text,
            chat_id=chat_id,
        )


async def back(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    query = update.callback_query

    state = query.data.split('-')[1]
    if state.isdigit():
        state = int(state)
    else:
        state = state.upper()
    try:
        (
            text,
            reply_markup,
            del_message_ids
        ) = await get_back_context(context, state)
    except KeyError as e:
        main_handlers_logger.error(e)
        await update.effective_chat.send_message(
            'Произошла ошибка при возврате назад\n'
            'Пожалуйста, выполните команду /start и повторите операцию заново')
        raise ApplicationHandlerStop
    if del_message_ids:
        await del_messages(update, context, del_message_ids)

    command = context.user_data['command']
    message = None
    message_thread_id = query.message.message_thread_id

    if state == 'MONTH':
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id
        )
    elif state == 'SHOW':
        try:
            await query.edit_message_caption(
                caption=text,
                reply_markup=reply_markup,
            )
        except BadRequest as e:
            main_handlers_logger.error(e)
            await query.delete_message()
            await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup,
                message_thread_id=message_thread_id
            )
    elif state == 'DATE' and command != 'birthday':
        try:
            number_of_month_str = context.user_data['reserve_user_data'][
                'number_of_month_str']
            await query.delete_message()
            photo = (
                context.bot_data
                .get('afisha', {})
                .get(int(number_of_month_str), False)
            )
            if (
                    update.effective_chat.type == ChatType.PRIVATE and
                    photo and
                    'reserve' in command
            ):
                await update.effective_chat.send_photo(
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                    message_thread_id=message_thread_id
                )
            else:
                await update.effective_chat.send_message(
                    text=text,
                    reply_markup=reply_markup,
                    message_thread_id=message_thread_id
                )
        except BadRequest as e:
            main_handlers_logger.error(e)
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
            )
    elif state == 'TIME':
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
        )
    elif state == 'TICKET':
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
        )
        try:
            message_id = context.user_data['reserve_user_data'].get(
                'accept_message_id', False)
            if message_id:
                await context.bot.delete_message(
                    update.effective_chat.id,
                    message_id
                )
        except BadRequest as e:
            main_handlers_logger.error(e)

    else:
        try:
            message = await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
            )
        except BadRequest as e:
            main_handlers_logger.error(e)
            try:
                await query.delete_message()
            except BadRequest as e:
                main_handlers_logger.error(e)
            message = await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup,
                message_thread_id=message_thread_id
            )
    context.user_data['STATE'] = state
    if message:
        await append_message_ids_back_context(
            context, [message.message_id])
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)
    return state


async def cancel(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    query = update.callback_query

    user = context.user_data['user']
    state = context.user_data.get('STATE')
    data = query.data.split('|')[0].split('-')[-1]

    first_text = '<b>Вы выбрали отмену</b>\n\n'
    use_command_text = 'Используйте команды:\n'
    reserve_text = (f'/{COMMAND_DICT['RESERVE'][0]} - для повторного '
                    f'резервирования свободных мест на мероприятие\n')
    reserve_admin_text = (
        f'/{COMMAND_DICT['RESERVE_ADMIN'][0]} - для повторной '
        f'записи без подтверждения\n')
    migration_admin_text = (
        f'/{COMMAND_DICT['MIGRATION_ADMIN'][0]} - для повторного '
        f'переноса без подтверждения\n')
    studio_text = (f'/{COMMAND_DICT['STUDIO'][0]} - для повторного '
                   f'резервирования свободных мест на мероприятие\n')
    studio_admin_text = (
        f'/{COMMAND_DICT['RESERVE_ADMIN'][0]} - для повторной '
        f'записи без подтверждения\n')
    bd_order_text = (f'/{COMMAND_DICT['BD_ORDER'][0]} - для повторной '
                     f'отправки заявки на проведение Дня рождения\n')
    bd_paid_text = (f'/{COMMAND_DICT['BD_PAID'][0]} - для повторного '
                    f'запуска процедуры внесения предоплаты, если ваша заявка '
                    f'была одобрена\n')

    explanation_text = ('\nОзнакомится более подробно с театром можно по '
                        'ссылкам:\n')
    description = context.bot_data['texts']['description']
    address = context.bot_data['texts']['address']
    ask_question = context.bot_data['texts']['ask_question']

    text = first_text
    match data:
        case 'reserve':
            text += (use_command_text + reserve_text + '\n' +
                     description + address + ask_question)
            await cancel_common(update, text)

            if state == 'OFFER':
                await context.bot.delete_message(
                    update.effective_chat.id,
                    context.user_data['reserve_user_data']['accept_message_id']
                )

            if '|' in query.data:
                await cancel_tickets_db_and_gspread(update, context)
        case 'reserve_admin':
            text += (use_command_text + reserve_text + reserve_admin_text)
            await cancel_common(update, text)

            if '|' in query.data:
                await cancel_tickets_db_and_gspread(update, context)
        case 'studio':
            text += (use_command_text + studio_text + '\n' +
                     description + address + ask_question)
            await cancel_common(update, text)

            if state == 'OFFER':
                await context.bot.delete_message(
                    update.effective_chat.id,
                    context.user_data['reserve_user_data']['accept_message_id']
                )

            if '|' in query.data:
                await cancel_tickets_db_and_gspread(update, context)
        case 'studio_admin':
            text += (use_command_text + studio_text + studio_admin_text)
            await cancel_common(update, text)

            if '|' in query.data:
                await cancel_tickets_db_and_gspread(update, context)
        case 'birthday':
            text += (use_command_text + bd_order_text + '\n' +
                     description + address + ask_question)
            await cancel_common(update, text)
        case 'settings':
            await cancel_common(update, text)
        case 'migration_admin':
            text += (use_command_text + migration_admin_text)
            await cancel_common(update, text)
        case 'list':
            await cancel_common(update, text)
        case 'list_wait':
            await cancel_common(update, text)
        case 'afisha':
            await cancel_common(update, text)
        case _:
            await cancel_common(update, text)

    try:
        main_handlers_logger.info(f'Для пользователя {user}')
    except KeyError:
        main_handlers_logger.info(f'Пользователь {user}: Не '
                                  f'оформил заявку, а сразу использовал '
                                  f'команду /{COMMAND_DICT['BD_PAID'][0]}')
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)
    await clean_context_on_end_handler(main_handlers_logger, context)
    context.user_data['conv_hl_run'] = False
    return ConversationHandler.END


async def reset(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> -1:
    main_handlers_logger.info(
        f'{update.effective_user.id}: '
        f'{update.effective_user.full_name}\n'
        f'Вызвал команду reset'
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text='Попробуйте выполнить новый запрос'
    )
    await cancel_tickets_db_and_gspread(update, context)
    await clean_context_on_end_handler(main_handlers_logger, context)
    context.user_data['conv_hl_run'] = False
    return ConversationHandler.END


async def help_command(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    main_handlers_logger.info(": ".join(
        [
            'Пользователь',
            f'{update.effective_user}',
            'Вызвал help',
        ]
    ))
    # TODO Прописать логику использования help
    await update.effective_chat.send_message(
        'Текущая операция сброшена.\nМожете выполните новую команду',
        message_thread_id=update.message.message_thread_id
    )
    await cancel_tickets_db_and_gspread(update, context)
    await clean_context_on_end_handler(main_handlers_logger, context)
    context.user_data['conv_hl_run'] = False
    return ConversationHandler.END


async def feedback_send_msg(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    main_handlers_logger.info('FEEDBACK')
    main_handlers_logger.info(update.effective_user)
    main_handlers_logger.info(update.message)

    user = context.user_data['user']

    chat_id = ADMIN_GROUP
    if update.edited_message:
        await update.effective_message.reply_text(
            'Пожалуйста не редактируйте сообщение, отправьте новое')
    elif hasattr(update.message, 'forward'):
        message = await update.message.forward(
            chat_id,
            message_thread_id=FEEDBACK_THREAD_ID_GROUP_ADMIN
        )
        await context.bot.send_message(
            chat_id,
            f'Сообщение от пользователя @{user.username} '
            f'<a href="tg://user?id={user.id}">{user.full_name}</a>\n'
            f'{update.effective_message.message_id}\n'
            f'{update.effective_chat.id}',
            reply_to_message_id=message.message_id,
            message_thread_id=message.message_thread_id
        )
        text = 'Ваше сообщение принято.\n\n'
        await update.effective_chat.send_message(text)
    else:
        await update.effective_message.reply_text(
            'К сожалению я не могу работать с данным сообщением, попробуйте '
            'повторить или отправить другой текст')


async def feedback_reply_msg(
        update: Update,
        context: "ContextTypes.DEFAULT_TYPE"
):
    technical_info = update.effective_message.reply_to_message.text.split('\n')
    try:
        chat_id = technical_info[-1]
        message_id = technical_info[-2]
        if bool(update.message.text):
            await context.bot.send_message(
                chat_id=chat_id,
                text=update.message.text,
                reply_to_message_id=int(message_id),
            )
        if bool(update.message.document):
            await context.bot.send_document(
                chat_id=chat_id,
                document=update.message.document,
                caption=update.message.caption,
                reply_to_message_id=int(message_id),
            )
        if bool(update.message.photo):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=update.message.photo[-1],
                caption=update.message.caption,
                reply_to_message_id=int(message_id),
            )
        if bool(update.message.video):
            await context.bot.send_video(
                chat_id=chat_id,
                video=update.message.video,
                caption=update.message.caption,
                reply_to_message_id=int(message_id),
            )
    except (IndexError, ValueError) as e:
        main_handlers_logger.error(e)
        await update.effective_message.reply_text(
            text='Проверьте что отвечаете на правильное сообщение',
            message_thread_id=update.message.message_thread_id
        )


async def global_on_off(update: Update, context: "ContextTypes.DEFAULT_TYPE"):
    """
    Функция для обработки команды /global_on_off и вкл/выкл возможности
    использовать команды пользователями в личных чатах
    """
    if context.args[0] == 'on':
        context.bot_data['global_on_off'] = True
        await update.effective_chat.send_message(
            'Использование команд пользователями включено')
    if context.args[0] == 'off':
        context.bot_data['global_on_off'] = False
        await update.effective_chat.send_message(
            'Использование команд пользователями выключено')

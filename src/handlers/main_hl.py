import logging
from typing import List

from sulguk import transform_html, RenderResult
from telegram.ext import (
    ContextTypes, ConversationHandler, ApplicationHandlerStop)
from telegram import (
    Update, ReplyKeyboardRemove, LinkPreviewOptions,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.constants import ChatType, ChatAction, ParseMode
from telegram.error import BadRequest, TimedOut, Forbidden

from api.gspread_pub import publish_update_ticket, publish_update_cme
from db import db_postgres
from db.enum import TicketStatus, CustomMadeStatus, UserRole
from handlers import check_user_db
from db.db_googlesheets import (
    decrease_nonconfirm_seat,
    increase_free_seat,
    increase_free_and_decrease_nonconfirm_seat, update_free_seat,
)
from settings.settings import (
    COMMAND_DICT, FILE_ID_RULES
)
from api.googlesheets import update_cme_in_gspread, update_ticket_in_gspread
from utilities.utl_check import is_user_blocked
from utilities.utl_func import (
    is_admin, is_dev, get_back_context, clean_context,
    clean_context_on_end_handler, cancel_common, del_messages,
    append_message_ids_back_context, create_str_info_by_schedule_event_id,
    get_formatted_date_and_time_of_event, get_child_and_adult_from_ticket,
    extract_status_change
)
from utilities.utl_ticket import (
    cancel_tickets_db_and_gspread, check_and_set_privilege
)
from schedule.worker_jobs import cancel_old_created_tickets

main_handlers_logger = logging.getLogger('bot.main_handlers')


async def start(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    await check_user_db(update, context)
    await cancel_tickets_db_and_gspread(update, context)
    await clean_context(context)
    await clean_context_on_end_handler(main_handlers_logger, context)

    context.user_data['user'] = update.effective_user
    context.user_data['common_data'] = {}

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
        text=f"{start_text}{description}{command}{address}{ask_question}",
        reply_markup=ReplyKeyboardRemove(),
        link_preview_options=LinkPreviewOptions(
            url='https://t.me/theater_domik')
    )

    return ConversationHandler.END


async def send_approve_msg(update: Update,
                           context: 'ContextTypes.DEFAULT_TYPE'):
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
            text, reply_to_message_id=update.effective_message.message_id)
        return
    text = ''
    ticket_id = int(context.args[0])
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        text = f'Проверь номер билета\nВведено: {ticket_id}'
        await update.effective_message.reply_text(
            text, reply_to_message_id=update.effective_message.message_id)
        return
    chat_id = ticket.user.chat_id
    await send_approve_message(chat_id, context, [ticket_id])
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
                text, reply_to_message_id=update.effective_message.message_id)
            return
    text += ' успешно отправлено'
    await update.effective_message.reply_text(text)


async def on_my_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик обновлений статуса бота в чатах (my_chat_member).
    Используется для отслеживания блокировки бота пользователем в личных сообщениях,
    а также для логирования вступления/выхода из групп.
    """
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return
    was_member, is_member = result

    cause_name = update.effective_user.full_name if update.effective_user else 'Unknown'
    chat = update.effective_chat

    # Обработка личных чатов (блокировка/разблокировка)
    if chat.type == ChatType.PRIVATE:
        await check_user_db(update, context)
        if was_member and not is_member:
            main_handlers_logger.info(f'{cause_name} заблокировал бота')
            await db_postgres.update_user_status(
                context.session, chat.id, is_blocked_by_user=True)
        elif not was_member and is_member:
            main_handlers_logger.info(f'{cause_name} разблокировал бота')
            await db_postgres.update_user_status(
                context.session, chat.id, is_blocked_by_user=False)

    # Логирование для групп и каналов
    elif chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if was_member and not is_member:
            main_handlers_logger.info(
                f'Бот был удален из группы {chat.title} ({chat.id}) пользователем {cause_name}'
            )
        elif not was_member and is_member:
            main_handlers_logger.info(
                f'Бот был добавлен в группу {chat.title} ({chat.id}) пользователем {cause_name}'
            )
    elif chat.type == ChatType.CHANNEL:
        if was_member and not is_member:
            main_handlers_logger.info(
                f'Бот был удален из канала {chat.title} ({chat.id}) пользователем {cause_name}'
            )
        elif not was_member and is_member:
            main_handlers_logger.info(
                f'Бот был добавлен в канал {chat.title} ({chat.id}) пользователем {cause_name}'
            )


async def send_msg(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    if not context.args:
        text = (
            'Отправить сообщение пользователю:\n'
            '- по номеру билета (<code>Билет</code>)\n'
            '- по номеру заявки заказного мероприятия (<code>Заявка</code>)\n'
            '- по chat_id в telegram (<code>Чат</code>)\n\n'
        )
        text += '<code>/send_msg Тип 0 Сообщение</code>\n\n'
        await update.effective_message.reply_text(
            text, reply_to_message_id=update.effective_message.message_id)
        return

    type_enter_chat_id = context.args[0]

    match type_enter_chat_id:
        case 'Билет':
            ticket_id = int(context.args[1])
            ticket = await db_postgres.get_ticket(context.session, ticket_id)
            if not ticket:
                text = 'Проверь номер билета'
                await update.effective_message.reply_text(
                    text, reply_to_message_id=update.effective_message.message_id)
                return
            chat_id = ticket.user.chat_id
        case 'Заявка':
            cme_id = int(context.args[1])
            cme = await db_postgres.get_custom_made_event(context.session, cme_id)
            if not cme:
                text = 'Проверь номер заявки'
                await update.effective_message.reply_text(
                    text, reply_to_message_id=update.effective_message.message_id)
                return
            chat_id = cme.user_id
        case 'Чат':
            chat_id = context.args[1]
        case _:
            text = ('Проверь что Тип указан верно, возможные варианты:\n'
                    '<code>Билет</code>\n'
                    '<code>Заявка</code>\n'
                    '<code>Чат</code>')
            await update.effective_message.reply_text(
                text, reply_to_message_id=update.effective_message.message_id)
            return

    parts = update.effective_message.text_html.strip().split(maxsplit=3)
    if len(parts) < 4:
        await update.effective_message.reply_text(
            'Неверный формат. Используйте:\n'
            '<code>/send_msg Тип 0 Сообщение</code>',
            reply_to_message_id=update.effective_message.message_id
        )
        return
    text = parts[3]

    try:
        await context.bot.send_message(
            text=text,
            chat_id=chat_id,
        )
        await update.effective_message.reply_text(
            f'Сообщение:\n{text}\n\n<i>Успешно отправлено</i>'
        )
    except Forbidden as e:
        if 'bot was blocked by the user' in str(e).lower():
            target_uid = int(chat_id)
            await db_postgres.update_user_status(
                context.session, target_uid, is_blocked_by_user=True)
            await update.effective_message.reply_text(
                f'Ошибка: Бот заблокирован пользователем {target_uid}. '
                f'Статус в базе обновлен.'
            )
        else:
            await update.effective_message.reply_text(
                f'Ошибка при отправке сообщения: {e}'
            )


async def update_ticket(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    text = 'Справка по команде<br>'
    text += '<code>/update_ticket 0 Слово Текст</code><br><br>'
    text += '0 - это номер билета<br>'
    text += ('<i>Если написать только номер, то будет отправлена информация по '
             'билету</i><br>')
    help_id_number = text
    text += 'Слово - может быть:<br>'
    text += ('<ul>'
             '<li><code>Статус</code></li>'
             '<li><code>Примечание</code></li>'
             '<li><code>Базовый</code></li>'
             '<li><code>Покупатель</code></li>'
             '</ul><br>')
    help_key_word_text = text
    text += 'Для <code>Примечание</code> просто пишем Текст примечания<br><br>'
    text += 'Для <code>Базовый</code> Текст это номер базового билета<br><br>'
    text += 'Для <code>Статус</code> Текст может быть:<br>'
    text += get_ticket_status_name()
    text += '<br>Повлияют на расписание<br>'
    text += '<i>Сейчас -> Станет:</i><br>'
    text += ('<ul>'
             '<li>Создан -> Подтвержден|Отклонен|Отменен</li>'
             '<li>Оплачен -> Подтвержден|Отклонен|Возвращен</li>'
             '<li>Подтвержден -> '
             'Отклонен|Возвращен|Передан|Перенесен|Отменен</li>'
             '</ul>')
    text += 'Остальные направления не повлияют на расписание<br><br>'
    text += 'если билет Сейчас:<br>'
    text += ('<ul>'
             '<li>Отклонен|Передан|Возвращен|Перенесен|Отменен</li>'
             '</ul>')
    text += ('тогда это финальные статусы.<br>Если нужно их сменить, '
             'то используем новый билет<br>')
    help_text = text
    reply_to_msg_id = update.effective_message.message_id

    if not context.args:
        res_text = transform_html(text)
        await update.effective_message.reply_text(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_to_message_id=reply_to_msg_id)
        return

    try:
        ticket_id = int(context.args[0])
    except ValueError:
        text = f'Задан не номер {help_id_number}'
        res_text = transform_html(text)
        await update.effective_message.reply_text(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_to_message_id=reply_to_msg_id)
        return

    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        text = 'Проверь номер билета'
        res_text = transform_html(text)
        await update.effective_message.reply_text(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_to_message_id=reply_to_msg_id)
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
            if person.adult and hasattr(person.adult, 'phone'):
                adult_str = f'{person.name}<br>+7{person.adult.phone}<br>'
            elif person.child and hasattr(person.child, 'age'):
                child_str += f'{person.name} {person.child.age}<br>'
        people_str = adult_str + child_str
        date_event, time_event = await get_formatted_date_and_time_of_event(
            schedule_event)
        text = (
            f'Техническая информация по билету {ticket_id}<br><br>'
            f'Событие {schedule_event.id}: {theater_event.name}<br>'
            f'{date_event} в {time_event}<br><br>'
            f'Привязан к профилю: {user.user_id if user else "Нет привязки"}<br>'
            f'Билет: {base_ticket.name}<br>'
            f'Стоимость: {ticket.price}<br>'
            f'Статус: {ticket.status.value}<br>'
            f'{people_str}'
            f'Примечание: {ticket.notes}<br>'
        )
        res_text = transform_html(text)
        await update.effective_message.reply_text(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_to_message_id=reply_to_msg_id)
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
                    await update.effective_message.reply_text(
                        text, reply_to_message_id=reply_to_msg_id)
                    return
            case 'Статус':
                try:
                    new_ticket_status = TicketStatus(context.args[2])
                except ValueError:
                    text = 'Неверный статус билета<br>'
                    text += 'Возможные статусы:<br>'
                    text += get_ticket_status_name()
                    text += '<br><br> Для подробной справки нажми /update_ticket'

                    res_text = transform_html(text)
                    await update.effective_message.reply_text(
                        res_text.text,
                        entities=res_text.entities,
                        parse_mode=None,
                        reply_to_message_id=reply_to_msg_id)
                    return
                except IndexError:
                    text = '<b>>>>Не задано новое значение статуса</b><br><br>'
                    text += help_text
                    res_text = transform_html(text)
                    await update.effective_message.reply_text(
                        res_text.text,
                        entities=res_text.entities,
                        parse_mode=None,
                        reply_to_message_id=reply_to_msg_id)
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
                try:
                    await publish_update_ticket(
                        sheet_id_domik,
                        ticket_id,
                        str(new_ticket_status.value),
                    )
                except Exception as e:
                    main_handlers_logger.exception(
                        f"Failed to publish gspread task, fallback to direct call: {e}")
                    await update_ticket_in_gspread(
                        sheet_id_domik, ticket_id, new_ticket_status.value)
                data['status'] = new_ticket_status
            case 'Покупатель':
                adult_str, child_str = await get_child_and_adult_from_ticket(
                    ticket)
                people_str = adult_str + child_str
                schedule_event_id = ticket.schedule_event_id
                price = ticket.price
                base_ticket = await db_postgres.get_base_ticket(
                    context.session, ticket.base_ticket_id)

                text_select_event = await create_str_info_by_schedule_event_id(
                    context, schedule_event_id)

                text = f'<b>Номер билета <code>{ticket_id}</code></b><br><br>'
                text += text_select_event + (f'<br>Вариант бронирования:<br>'
                                             f'{base_ticket.name} '
                                             f'{int(price)}руб<br><br>')
                text += 'На кого оформлен:<br>'
                text += people_str + '<br><br>'
                refund = context.bot_data.get('settings', {}).get('REFUND_INFO', '')
                text += refund + '<br><br>'

                res_text = transform_html(text)
                await update.effective_message.reply_text(
                    res_text.text,
                    entities=res_text.entities,
                    parse_mode=None,
                    reply_to_message_id=reply_to_msg_id)
                return
            case 'Базовый':
                try:
                    new_base_ticket_id = int(context.args[2])
                    old_base_ticket_id = int(ticket.base_ticket_id)
                except ValueError:
                    text = 'Задан не номер базового билета'
                    await update.effective_message.reply_text(
                        text, reply_to_message_id=reply_to_msg_id)
                    return
                new_base_ticket = await db_postgres.get_base_ticket(
                    context.session, new_base_ticket_id)
                if not new_base_ticket:
                    text = 'Проверь номер базового билета'
                    await update.effective_message.reply_text(
                        text, reply_to_message_id=reply_to_msg_id)
                    return
                if new_base_ticket_id == old_base_ticket_id:
                    text = (f'Билету {ticket_id} уже присвоен '
                            f'базовый билет {new_base_ticket_id}')
                    await update.effective_message.reply_text(
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

                res_text = transform_html(text)
                await update.effective_message.reply_text(
                    res_text.text,
                    entities=res_text.entities,
                    parse_mode=None,
                    reply_to_message_id=reply_to_msg_id)
                return

    await db_postgres.update_ticket(context.session, ticket_id, **data)

    await send_result_update_ticket(update, context, ticket_id, data)


def get_ticket_status_name():
    text = '<ul>'
    for status in TicketStatus:
        text += f'<li><code>{status.value}</code></li>'
    text += '</ul>'
    return text


async def send_result_update_ticket(
        update,
        context,
        ticket_id,
        data
):
    text = f'Билет <code>{ticket_id}</code> обновлен\n'
    status = data.get('status', None)
    if status:
        text += f'Статус: {status.value}'
    base_ticket_id = data.get('base_ticket_id', None)
    if base_ticket_id:
        text += (f'Новый базовый билет: {base_ticket_id}\n'
                 f'В Расписании обновлено, а в клиентской базе данную '
                 f'информацию надо поменять в ручную')
    notes = data.get('notes', None)
    if notes:
        text += f'Примечание: {notes}'
    message_thread_id = update.effective_message.message_thread_id
    if bool(update.effective_message.reply_to_message):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_to_message_id=update.effective_message.reply_to_message.message_id,
            message_thread_id=message_thread_id
        )
    else:
        await update.effective_message.reply_text(
            text=text,
            message_thread_id=message_thread_id,
            reply_to_message_id=update.effective_message.message_id
        )


async def confirm_reserve(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)

    if not is_admin(update):
        text = 'Не разрешенное действие: подтвердить бронь'
        main_handlers_logger.warning(text)
        return
    message_thread_id = update.effective_message.message_thread_id
    try:
        await update.effective_chat.send_action(
            ChatAction.TYPING,
            message_thread_id=message_thread_id)
    except BadRequest as e:
        main_handlers_logger.error(e)
        await update.effective_chat.send_action(ChatAction.TYPING)
    except TimedOut as e:
        main_handlers_logger.error(e)

    try:
        message = await update.effective_chat.send_message(
            text='Начат процесс подтверждения...',
            reply_to_message_id=query.message.message_id,
            message_thread_id=message_thread_id
        )
    except BadRequest as e:
        main_handlers_logger.error(e)
        message = await update.effective_chat.send_message(
            text='Начат процесс подтверждения...',
            reply_to_message_id=query.message.message_id,
        )

    chat_id = query.data.split('|')[1].split()[0]
    message_id_buy_info = int(query.data.split('|')[1].split()[1])

    ticket_ids = [int(update.effective_message.text.split('#ticket_id ')[1])]
    for ticket_id in ticket_ids:
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        ticket_status = TicketStatus.APPROVED
        if ticket.status != TicketStatus.APPROVED:
            await decrease_nonconfirm_seat(
                context, ticket.schedule_event_id, ticket.base_ticket_id)

            text = f'{message.text}\nСписаны неподтвержденные места...'
            try:
                await message.edit_text(text)
            except TimedOut as e:
                main_handlers_logger.error(e)
                main_handlers_logger.info(text)

            sheet_id_domik = context.config.sheets.sheet_id_domik
            try:
                await publish_update_ticket(
                    sheet_id_domik,
                    ticket_id,
                    str(ticket_status.value),
                )
            except Exception as e:
                main_handlers_logger.exception(
                    f"Failed to publish gspread task, fallback to direct call: {e}")
                await update_ticket_in_gspread(
                    sheet_id_domik, ticket_id, ticket_status.value)
            await db_postgres.update_ticket(context.session,
                                            ticket_id,
                                            status=ticket_status)
        
        try:
            await check_and_set_privilege(context.session, ticket_id)
        except AttributeError as e:
            if "'NoneType' object has no attribute 'is_privilege'" in str(e):
                if int(chat_id) != 0:
                    keyboard = [
                        [
                            InlineKeyboardButton(
                                "Да",
                                callback_data=f"approve-privilege|{chat_id}|{ticket_id}"
                            ),
                            InlineKeyboardButton(
                                "Нет",
                                callback_data="reject-privilege"
                            )
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.effective_chat.send_message(
                        text=f"У пользователя (ID: {chat_id}) не было подтверждения о документе, сделать подтверждение? "
                             f"После повторите подтверждение/отклонение на билете {ticket_id}",
                        reply_markup=reply_markup,
                        message_thread_id=message_thread_id
                    )
                else:
                    main_handlers_logger.warning(
                        f"Could not set privilege for ticket {ticket_id}: "
                        f"user is not a Telegram user (chat_id=0)"
                    )
        
        if int(chat_id) != 0 and ticket.status != TicketStatus.APPROVED:
            await send_approve_message(chat_id, context, [ticket_id])

        if ticket.status != TicketStatus.APPROVED:
            text = f'{message.text}\nОтправлено сообщение о подтверждении бронирования...'
            try:
                await message.edit_text(text)
            except TimedOut as e:
                main_handlers_logger.error(e)
                main_handlers_logger.info(text)

    try:
        await query.edit_message_reply_markup()
    except TimedOut as e:
        main_handlers_logger.error(e)

    text = f'Бронь подтверждена\n'
    for ticket_id in ticket_ids:
        text += f'Билет {ticket_id}\n'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    if int(chat_id) != 0 and message_id_buy_info != 0:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message_id_buy_info
            )
        except BadRequest as e:
            main_handlers_logger.error(e)
            main_handlers_logger.info('Cообщение уже удалено')


async def approve_privilege(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    await query.answer()

    data = query.data.split('|')
    chat_id = int(data[1])
    ticket_id = int(data[2])

    user = await db_postgres.get_user(context.session, chat_id)
    if user:
        await db_postgres.update_user(
            context.session, chat_id, is_privilege=True)
        text = (f"Статус привилегии для пользователя {chat_id} подтвержден. "
                f"Пожалуйста, повторите подтверждение/отклонение на "
                f"билете {ticket_id}.")
    else:
        text = f"Пользователь {chat_id} не найден в базе данных."

    await query.edit_message_text(text)


async def reject_privilege(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Действие отменено.")


async def send_approve_message(chat_id, context, ticket_ids: List[int]):
    if await is_user_blocked(context, chat_id, 'sending approve message'):
        return

    description = context.bot_data['texts']['description']
    address = context.bot_data['texts']['address']
    ask_question = context.bot_data['texts']['ask_question']
    command = (
        'Для продолжения работы используйте команды:<br>'
        f'/{COMMAND_DICT['RESERVE'][0]} - выбрать и оплатить билет на спектакль<br>'
    )
    text = ''
    for ticket_id in ticket_ids:
        text += f'Билет {ticket_id}<br>'
    approve_text = (f'<b>Ваша бронь<br>'
                    f'{text}'
                    f'подтверждена, ждем вас на мероприятии.</b><br><br>')
    refund = context.bot_data.get('settings', {}).get('REFUND_INFO', '')
    text = f'{approve_text}{address}{refund}<br><br>{description}{ask_question}{command}'

    res_text = transform_html(text)
    await context.bot.send_message(
        text=res_text.text,
        entities=res_text.entities,
        chat_id=chat_id,
        parse_mode=None
    )


async def send_reject_message(chat_id, context):
    if await is_user_blocked(context, chat_id, 'sending reject message'):
        return

    text = (
        'Ваша бронь отклонена.<br><br>'
        'Если это произошло по ошибке, пожалуйста, '
        'напишите в ЛС или позвоните Администратору:<br>'
        f'{context.bot_data['admin']['contacts']}'
    )
    res_text = transform_html(text)
    await context.bot.send_message(
        text=res_text.text,
        entities=res_text.entities,
        chat_id=chat_id,
        parse_mode=None
    )


async def reject_reserve(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)

    if not is_admin(update):
        main_handlers_logger.warning('Не разрешенное действие: отклонить бронь')
        return
    message_thread_id = update.effective_message.message_thread_id
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
    message_id_buy_info = int(query.data.split('|')[1].split()[1])

    ticket_ids = [int(update.effective_message.text.split('#ticket_id ')[1])]
    for ticket_id in ticket_ids:
        ticket = await db_postgres.get_ticket(context.session, ticket_id)
        await increase_free_and_decrease_nonconfirm_seat(
            context, ticket.schedule_event_id, ticket.base_ticket_id)

    text = f'{message.text}\nВозвращены места в продажу...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    ticket_status = TicketStatus.REJECTED
    sheet_id_domik = context.config.sheets.sheet_id_domik
    for ticket_id in ticket_ids:
        try:
            await publish_update_ticket(
                sheet_id_domik,
                ticket_id,
                str(ticket_status.value),
            )
        except Exception as e:
            main_handlers_logger.exception(
                f"Failed to publish gspread task, fallback to direct call: {e}")
            await update_ticket_in_gspread(
                sheet_id_domik, ticket_id, ticket_status.value)
        await db_postgres.update_ticket(context.session,
                                        ticket_id,
                                        status=ticket_status)

    await query.edit_message_reply_markup()
    text = f'{message.text}\nОбновлен статус билета: {ticket_status.value}...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    if int(chat_id) != 0:
        await send_reject_message(chat_id, context)
    
    text = f'{message.text}\nОтправлено сообщение об отклонении бронирования...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    text = f'Бронь отклонена\n'
    for ticket_id in ticket_ids:
        text += f'Билет {ticket_id}\n'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(text)

    if int(chat_id) != 0 and message_id_buy_info != 0:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message_id_buy_info
            )
        except BadRequest as e:
            main_handlers_logger.error(e)
            main_handlers_logger.info('Cообщение уже удалено')


async def confirm_birthday(update: Update,
                           context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)

    if not is_admin(update):
        main_handlers_logger.warning(
            'Не разрешенное действие: подтвердить день рождения')
        return
    message_thread_id = update.effective_message.message_thread_id
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
    message_id_for_reply = int(query.data.split('|')[1].split()[1])
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

    sheet_id_cme = context.config.sheets.sheet_id_cme
    try:
        await publish_update_cme(
            sheet_id_cme,
            int(cme_id),
            str(cme_status.value),
        )
    except Exception as e:
        main_handlers_logger.exception(
            f"Failed to publish gspread task, fallback to direct call: {e}")
        await update_cme_in_gspread(sheet_id_cme, cme_id, cme_status.value)
    await message.edit_text(
        f'{message.text}\nОбновил статус в гугл-таблице {cme_status.value}')

    await db_postgres.update_custom_made_event(
        context.session, cme_id, status=cme_status)
    await message.edit_text(f'{message.text} и бд {cme_status.value}')

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

    if await is_user_blocked(
            context, chat_id, 'sending confirm birthday message'):
        return

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


async def reject_birthday(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)

    if not is_admin(update):
        main_handlers_logger.warning(
            'Не разрешенное действие: отклонить день рождения')
        return
    message_thread_id = update.effective_message.message_thread_id
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
    message_id_for_reply = int(query.data.split('|')[1].split()[1])
    cme_id = query.data.split('|')[1].split()[2]

    step = query.data.split('|')[0][-1]
    text = ('Возникла ошибка\n'
            'Cвяжитесь с администратором:\n'
            f'{context.bot_data['cme_admin']['contacts']}')

    cme_status = CustomMadeStatus.REJECTED

    sheet_id_cme = context.config.sheets.sheet_id_cme
    try:
        await publish_update_cme(
            sheet_id_cme,
            int(cme_id),
            str(cme_status.value),
        )
    except Exception as e:
        main_handlers_logger.exception(
            f"Failed to publish gspread task, fallback to direct call: {e}")
        await update_cme_in_gspread(sheet_id_cme, cme_id, cme_status.value)
    await message.edit_text(
        f'{message.text}\nОбновил статус в гугл-таблице {cme_status.value}')

    await db_postgres.update_custom_made_event(
        context.session, cme_id, status=cme_status)
    await message.edit_text(f'{message.text} и бд {cme_status.value}')

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
    if await is_user_blocked(
            context, chat_id, 'sending reject birthday message'):
        return

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


async def back(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)

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
    message_thread_id = update.effective_message.message_thread_id

    entities = None
    if isinstance(text, str) and '<br>' in text:
        res_text = transform_html(text)
        entities = res_text.entities
        text = res_text.text
    elif isinstance(text, RenderResult):
        entities = text.entities
        text = text.text

    parse_mode = None if entities else ParseMode.HTML

    if state == 'MONTH':
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            parse_mode=parse_mode,
            entities=entities,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id
        )
    elif state == 'MODE':
        # Возврат к начальному экрану выбора режима: удаляем текущее сообщение (в т.ч. фото) и отправляем новое
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            parse_mode=parse_mode,
            entities=entities,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id
        )
    elif state == 'SHOW':
        try:
            await query.edit_message_caption(
                caption=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                caption_entities=entities,
            )
        except BadRequest as e:
            main_handlers_logger.error(e)
            await query.delete_message()
            await update.effective_chat.send_message(
                text=text,
                parse_mode=parse_mode,
                entities=entities,
                reply_markup=reply_markup,
                message_thread_id=message_thread_id
            )
    elif state == 'DATE' and command != 'birthday':
        try:
            reserve_data = context.user_data.get('reserve_user_data', {})
            number_of_month_str = reserve_data.get('number_of_month_str')
            await query.delete_message()
            photo = None
            if number_of_month_str is not None:
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
                    parse_mode=parse_mode,
                    caption_entities=entities,
                    reply_markup=reply_markup,
                    message_thread_id=message_thread_id
                )
            else:
                await update.effective_chat.send_message(
                    text=text,
                    parse_mode=parse_mode,
                    entities=entities,
                    reply_markup=reply_markup,
                    message_thread_id=message_thread_id
                )
        except BadRequest as e:
            main_handlers_logger.error(e)
            await query.edit_message_text(
                text=text,
                parse_mode=parse_mode,
                entities=entities,
                reply_markup=reply_markup
            )
    elif state == 'TIME':
        await query.edit_message_text(
            text=text,
            parse_mode=parse_mode,
            entities=entities,
            reply_markup=reply_markup
        )
    elif state == 'TICKET':
        await query.edit_message_text(
            text=text,
            parse_mode=parse_mode,
            entities=entities,
            reply_markup=reply_markup)
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
                parse_mode=parse_mode,
                entities=entities,
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
                parse_mode=parse_mode,
                entities=entities,
                reply_markup=reply_markup,
                message_thread_id=message_thread_id
            )
    context.user_data['STATE'] = state
    if message:
        await append_message_ids_back_context(
            context, [message.message_id])
    return state


async def cancel(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        main_handlers_logger.error(e)

    user = context.user_data.get('user', update.effective_user)
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
    await clean_context_on_end_handler(main_handlers_logger, context)
    return ConversationHandler.END


async def reset(update: Update, context: 'ContextTypes.DEFAULT_TYPE') -> int:
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
    return ConversationHandler.END


async def help_cmd(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    main_handlers_logger.info(f"Пользователь: {update.effective_user}: Вызвал help")

    user_is_admin = is_admin(update)
    user_is_dev = is_dev(update)

    help_text = '<b>Доступные команды:</b>\n\n'

    # Группировка команд
    client_cmds = [
        'START', 'HELP', 'RESET', 'RESERVE', 'STUDIO', 'BD_ORDER', 'BD_PAID', 'REFUNDED_MIGRATED'
    ]
    admin_cmds = [
        'RESERVE_ADMIN', 'STUDIO_ADMIN', 'MIGRATION_ADMIN', 'LIST', 'LIST_WAIT',
        'AFISHA', 'ADM_INFO', 'ADM_CME_INFO', 'SALES', 'SETTINGS',
        'SEND_APPROVE_MSG', 'UPDATE_TICKET', 'SEND_MSG', 'CANCEL_OLD_TICKETS', 'SET_USER_STATUS',
    ]
    update_data_cmds = [
        'UP_BT_DATA', 'UP_TE_DATA', 'UP_SE_DATA', 'UP_SPEC_PRICE',
        'UP_CMF_DATA', 'UP_PROM_DATA'
    ]
    tech_cmds = [
        'TOPIC', 'TOPIC_DEL', 'GLOB_ON_OFF', 'CB_TW', 'LOG', 'POSTGRES_LOG',
        'ECHO', 'CLEAN_UD', 'PRINT_UD', 'CLEAN_BD', 'UP_CONFIG', 'UP_SETTINGS', 'RCL'
    ]

    def format_cmds(cmd_keys):
        text = ""
        for key in cmd_keys:
            if key in COMMAND_DICT:
                cmd_name, cmd_desc = COMMAND_DICT[key]
                stub_mark = ""
                # Помечаем заглушки и не-команды только для разработчика
                if user_is_dev:
                    if key in ['STUDIO', 'STUDIO_ADMIN', 'REFUNDED_MIGRATED']:
                        stub_mark = " (заглушка)"
                    elif key in update_data_cmds:
                        stub_mark = " (через /settings)"
                text += f"/{cmd_name} - {cmd_desc}{stub_mark}\n"
        return text

    if user_is_dev:
        help_text += "<b>Клиентские команды:</b>\n"
        help_text += format_cmds(client_cmds)
        help_text += "\n<b>Админские команды:</b>\n"
        help_text += format_cmds(admin_cmds)
        help_text += "\n<b>Обновление данных:</b>\n"
        help_text += format_cmds(update_data_cmds)
        help_text += "\n<b>Технические команды:</b>\n"
        help_text += format_cmds(tech_cmds)
    elif user_is_admin:
        help_text += "<b>Основные команды:</b>\n"
        help_text += format_cmds(['START', 'HELP', 'RESET', 'RESERVE', 'BD_ORDER'])
        help_text += "\n<b>Управление:</b>\n"
        help_text += format_cmds(admin_cmds)
    else:
        help_text += format_cmds(['START', 'HELP', 'RESET', 'RESERVE', 'BD_ORDER'])
        help_text += "\nЕсли у вас возникли вопросы, вы можете связаться с администратором."

    await update.effective_chat.send_message(
        help_text,
        message_thread_id=update.effective_message.message_thread_id
    )

    return context.user_data.get('STATE')


async def feedback_send_msg(update: Update,
                            context: 'ContextTypes.DEFAULT_TYPE'):
    main_handlers_logger.info('FEEDBACK from user %s', update.effective_user.id)

    if update.edited_message:
        await update.effective_message.reply_text(
            'Пожалуйста не редактируйте сообщение, отправьте новое')
        return

    user = update.effective_user
    feedback_group_id = context.bot_data.get('feedback_group_id')

    if not feedback_group_id:
        main_handlers_logger.error('feedback_group_id not found in bot_data')
        return

    # Ищем топик в базе
    fb_topic = await db_postgres.get_feedback_topic_by_user_id(
        context.session, user.id)
    topic_id = fb_topic.topic_id if fb_topic else None

    async def create_new_topic():
        # Создаем новый топик
        topic_name = f"[ФБ] {user.full_name[:95]}"
        new_topic = await context.bot.create_forum_topic(
            chat_id=feedback_group_id,
            name=topic_name
        )
        t_id = new_topic.message_thread_id

        # Сохраняем в базу
        if fb_topic:
            await db_postgres.update_feedback_topic(
                context.session, user.id, t_id)
        else:
            await db_postgres.create_feedback_topic(
                context.session, user.id, t_id)

        # Отправляем инфо о пользователе первым сообщением в новый топик
        user_info = (f"Новое обращение от @{user.username} "
                     f"<a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                     f"ID: <code>{user.id}</code>")
        info_msg = await context.bot.send_message(
            chat_id=feedback_group_id,
            text=user_info,
            message_thread_id=t_id
        )
        # Сохраняем ID инфо-сообщения, чтобы на него можно было отвечать
        await db_postgres.create_feedback_message(
            context.session, user.id, 0, info_msg.message_id
        )
        return t_id

    async def send_to_admin(t_id):
        reply_to_message_id = None
        if update.effective_message.reply_to_message:
            replied_msg = update.effective_message.reply_to_message
            fb_msg = await db_postgres.get_feedback_message_by_user_message_id(
                context.session, replied_msg.message_id
            )
            if fb_msg:
                reply_to_message_id = fb_msg.admin_message_id
            else:
                # Если сообщения нет в базе, пересылаем его в топик (как просил юзер)
                try:
                    copied_replied_msg = await replied_msg.copy(
                        chat_id=feedback_group_id,
                        message_thread_id=t_id
                    )
                    # Сохраняем маппинг для этого сообщения тоже
                    await db_postgres.create_feedback_message(
                        context.session, user.id, replied_msg.message_id,
                        copied_replied_msg.message_id
                    )
                    reply_to_message_id = copied_replied_msg.message_id
                except Exception as error_message:
                    main_handlers_logger.warning(
                        'Не удалось скопировать сообщение, на которое ответили: %s', error_message)

        copy_msg = await update.effective_message.copy(
            chat_id=feedback_group_id,
            message_thread_id=t_id,
            reply_to_message_id=reply_to_message_id
        )
        await db_postgres.create_feedback_message(
            context.session, user.id, update.effective_message.message_id,
            copy_msg.message_id
        )

    try:
        if not topic_id:
            topic_id = await create_new_topic()

        try:
            await send_to_admin(topic_id)
        except BadRequest as e:
            if 'Topic not found' in str(e) or 'Message thread not found' in str(e):
                topic_id = await create_new_topic()
                await send_to_admin(topic_id)
            else:
                raise e

    except Exception as e:
        main_handlers_logger.exception('Error in feedback_send_msg: %s', e)
        await update.effective_message.reply_text(
            'Произошла ошибка при отправке сообщения администратору. '
            'Попробуйте позже или свяжитесь напрямую.')


async def feedback_reply_msg(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    topic_id = update.effective_message.message_thread_id
    if not topic_id:
        return

    # Ищем пользователя по topic_id
    fb_topic = await db_postgres.get_feedback_topic_by_topic_id(
        context.session, topic_id)
    if not fb_topic:
        # Возможно это системный топик
        return

    user_id = fb_topic.user_id
    message = update.effective_message

    # Если сообщение начинается с точки, это внутренняя заметка
    if (message.text and message.text.startswith('.')) or \
       (message.caption and message.caption.startswith('.')):
        return

    try:
        reply_to_message_id = None
        if message.reply_to_message:
            # Если это ответ на заголовок топика (сервисное сообщение), 
            # то для пользователя это будет обычное сообщение без реплая.
            if message.reply_to_message.message_id == topic_id:
                reply_to_message_id = None
            else:
                fb_msg = await db_postgres.get_feedback_message_by_admin_id(
                    context.session, message.reply_to_message.message_id
                )
                if fb_msg:
                    # user_message_id=0 означает инфо-сообщение, 
                    # в этом случае reply_to_message_id для пользователя остается None
                    reply_to_message_id = fb_msg.user_message_id if fb_msg.user_message_id != 0 else None
                else:
                    # Если это ответ на сообщение, которого нет в базе 
                    # (например, на другую внутреннюю заметку без точки), 
                    # то не пересылаем пользователю.
                    return

        sent_msg = None
        if message.text:
            sent_msg = await context.bot.send_message(
                chat_id=user_id,
                text=message.text,
                reply_to_message_id=reply_to_message_id
            )
        elif message.photo:
            sent_msg = await context.bot.send_photo(
                chat_id=user_id,
                photo=message.photo[-1],
                caption=message.caption,
                reply_to_message_id=reply_to_message_id)
        elif message.document:
            sent_msg = await context.bot.send_document(
                chat_id=user_id,
                document=message.document,
                caption=message.caption,
                reply_to_message_id=reply_to_message_id)
        elif message.video:
            sent_msg = await context.bot.send_video(
                chat_id=user_id,
                video=message.video,
                caption=message.caption,
                reply_to_message_id=reply_to_message_id)
        elif message.voice:
            sent_msg = await context.bot.send_voice(
                chat_id=user_id,
                voice=message.voice,
                caption=message.caption,
                reply_to_message_id=reply_to_message_id)
        elif message.video_note:
            sent_msg = await context.bot.send_video_note(
                chat_id=user_id,
                video_note=message.video_note,
                reply_to_message_id=reply_to_message_id)
        # Можно добавить другие типы медиа при необходимости

        if sent_msg:
            await db_postgres.create_feedback_message(
                context.session, user_id, sent_msg.message_id,
                message.message_id
            )
    except Exception as e:
        main_handlers_logger.error('Error sending reply to user %s: %s', user_id,
                                   e)
        await update.effective_message.reply_text(
            'Не удалось отправить сообщение пользователю.')


async def close_feedback_topic(update: Update,
                               context: 'ContextTypes.DEFAULT_TYPE'):
    topic_id = update.effective_message.message_thread_id
    if not topic_id:
        return

    # Ищем в базе
    fb_topic = await db_postgres.get_feedback_topic_by_topic_id(
        context.session, topic_id)
    if not fb_topic:
        await update.effective_message.reply_text(
            'Это не топик фидбека или он уже закрыт в базе.')
        return

    feedback_group_id = context.bot_data.get('feedback_group_id')

    try:
        # Удаляем из базы
        await db_postgres.del_feedback_topic_by_topic_id(context.session,
                                                         topic_id)

        # Удаляем топик в Telegram
        await context.bot.delete_forum_topic(chat_id=feedback_group_id,
                                             message_thread_id=topic_id)

    except Exception as e:
        main_handlers_logger.error('Error closing feedback topic %s: %s',
                                   topic_id, e)
        await update.effective_message.reply_text(
            f'Ошибка при закрытии топика: {e}')


async def global_on_off(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
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


async def manual_cancel_old_created_tickets(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Ручной запуск обработчика автоотмены созданных билетов старше 30 минут.
    Только для администраторов.
    """
    await update.effective_message.reply_text(
        'Запускаю проверку созданных билетов старше 30 минут...')
    try:
        await cancel_old_created_tickets(context)
        await update.effective_message.reply_text(
            'Готово. Проверка и авто-отмена завершены.')
    except Exception as e:
        main_handlers_logger.exception(
            f'Ошибка ручного запуска авто-отмены: {e}')
        await update.effective_message.reply_text(f'Ошибка при выполнении: {e}')


async def set_user_status(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Админ-команда:
    /set_user_status <user_id> [role=<роль>] [blacklist=on|off] [block_admin=on|off]

    Примеры:
    /set_user_status 454342281 role=администратор
    /set_user_status 454342281 blacklist=on
    /set_user_status 454342281 block_admin=on
    /set_user_status 454342281 block_admin=off
    """
    if not context.args:
        help_text = (
            'Сменить статус пользователя<br><br>'
            '<code>/set_user_status &lt;user_id&gt; [role=&lt;пользователь|администратор|разработчик|суперпользователь&gt;] '
            '[blacklist=on|off] [block_admin=on|off]</code><br><br>'
            'Примеры:<br>'
            '<ul>'
            '<li><code>/set_user_status 454342281 role=администратор</code></li>'
            '<li><code>/set_user_status 454342281 blacklist=on</code></li>'
            '<li><code>/set_user_status 454342281 block_admin=on</code></li>'
            '<li><code>/set_user_status 454342281 block_admin=off</code></li>'
            '</ul>'
        )
        res_text = transform_html(help_text)
        await update.effective_message.reply_text(
            res_text.text,
            entities=res_text.entities,
            parse_mode=None)
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text('Первый аргумент должен быть user_id (число)')
        return

    # default no changes
    data = {}

    mapping = {
        'пользователь': UserRole.USER,
        'администратор': UserRole.ADMIN,
        'разработчик': UserRole.DEVELOPER,
        'суперпользователь': UserRole.SUPERUSER,
    }

    for token in context.args[1:]:
        if '=' not in token:
            await update.effective_message.reply_text(f'Некорректный параметр: {token}')
            return
        key, value = token.split('=', 1)
        key = key.lower()
        value = value.lower()
        if key == 'role':
            role = mapping.get(value)
            if role is None:
                await update.effective_message.reply_text('Неверная роль. Допустимые: пользователь, администратор, разработчик, суперпользователь')
                return
            data['role'] = role
        elif key == 'blacklist':
            if value not in ('on', 'off'):
                await update.effective_message.reply_text('blacklist ожидает on|off')
                return
            data['is_blacklisted'] = (value == 'on')
        elif key == 'block_admin':
            if value not in ('on', 'off'):
                await update.effective_message.reply_text('block_admin ожидает on|off')
                return
            data['is_blocked_by_admin'] = (value == 'on')
            data['blocked_by_admin_id'] = update.effective_user.id if value == 'on' else None
        else:
            await update.effective_message.reply_text(f'Неизвестный параметр: {key}')
            return

    status = await db_postgres.update_user_status(context.session, uid, **data)

    def _role_str(r: UserRole | None):
        return r.value if isinstance(r, UserRole) else str(r)

    text = (
        'Статус пользователя обновлён:\n\n'
        f'user_id: <code>{uid}</code>\n'
        f'роль: <b>{_role_str(status.role)}</b>\n'
        f'ЧС: <b>{"да" if status.is_blacklisted else "нет"}</b>\n'
        f'Заблокирован админом: <b>{"да" if status.is_blocked_by_admin else "нет"}</b>\n'
        f'Кем заблокирован: <code>{status.blocked_by_admin_id or "-"}</code>'
    )
    await update.effective_message.reply_text(text)

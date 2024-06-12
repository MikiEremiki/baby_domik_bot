import logging

from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update, ReplyKeyboardRemove
from telegram.constants import ChatType
from telegram.error import BadRequest

from db import db_postgres
from db.enum import TicketStatus
from handlers import check_user_db
from handlers.sub_hl import remove_inline_button
from db.db_googlesheets import (
    decrease_nonconfirm_seat,
    increase_free_seat,
    increase_free_and_decrease_nonconfirm_seat,
)
from settings.settings import (
    COMMAND_DICT, ADMIN_GROUP, FEEDBACK_THREAD_ID_GROUP_ADMIN, ADDRESS_OFFICE
)
from api.googlesheets import set_approve_order, update_ticket_in_gspread
from utilities.utl_func import (
    is_admin, get_back_context, clean_context,
    clean_context_on_end_handler, utilites_logger, cancel_common
)
from utilities.utl_googlesheets import write_to_return_seats_for_sale

main_handlers_logger = logging.getLogger('bot.main_handlers')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Приветственная команда при первом запуске бота,
    при перезапуске бота или при использовании команды start
    """
    await check_user_db(update, context)
    await clean_context(context)

    context.user_data['user'] = update.effective_user
    context.user_data['common_data'] = {}

    start_text = '<b>Вас приветствует Бот Бэби-театра «Домик»</b>\n\n'
    description = context.bot_data['texts']['description']
    command = (
        'Для продолжения работы используйте команды:\n'
        f'/{COMMAND_DICT['RESERVE'][0]} - выбрать и оплатить билет на спектакль '
        f'(<a href="https://vk.com/baby_theater_domik?w=wall-202744340_2446">инструкция</a>)\n'
        f'/{COMMAND_DICT['BD_ORDER'][0]} - оформить заявку на проведение дня рождения '
        f'(<a href="https://vk.com/wall-202744340_2469">инструкция</a>)'
    )
    await update.effective_chat.send_message(
        text=start_text + description + command,
        reply_markup=ReplyKeyboardRemove()
    )


async def send_approve_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        text = 'Только отправляет подтверждение пользователю по номеру билета\n'
        text += '<code>/send_approve_msg 0</code>\n\n'
        await update.message.reply_text(
            text, reply_to_message_id=update.message.message_id)
        return
    ticket_id = context.args[0]
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        text = 'Проверь номер билета'
        await update.message.reply_text(
            text, reply_to_message_id=update.message.message_id)
        return
    chat_id = ticket.user.chat_id

    await send_approve_message(chat_id, context)
    await update.effective_message.reply_text(
        'Подтверждение успешно отправлено')


async def update_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        text = 'Нужно написать\n'
        text += '<code>/update_ticket 0 слово</code>\n\n'
        text += '0 - это номер билета\n'
        text += 'слово - может быть:\n'
        text = get_ticket_status_name(text)
        text += 'Повлияют на расписание\n'
        text += 'Сейчас -> Станет:\n'
        text += 'Создан -> Подтвержден|Отклонен|Отменен\n'
        text += 'Оплачен -> Подтвержден|Отклонен|Возвращен\n'
        text += 'Подтвержден -> Отклонен|Возвращен|Передан|Перенесен|Отменен\n'
        text += 'Остальные направления не повлияют на расписание\n'
        text += 'если билет Сейчас:\n'
        text += 'Отклонен|Передан|Возвращен|Перенесен|Отменен\n'
        text += ('Это финальные статусы, если нужно сменить, '
                 'то используем новый билет\n')
        await update.message.reply_text(
            text, reply_to_message_id=update.message.message_id)
        return

    try:
        new_ticket_status = TicketStatus(context.args[1])
    except ValueError:
        text = 'Неверный статус билета\n'
        text = get_ticket_status_name(text)
        await update.message.reply_text(
            text, reply_to_message_id=update.message.message_id)
        return

    ticket_id = int(context.args[0])
    ticket = await db_postgres.get_ticket(context.session, ticket_id)
    if not ticket:
        text = 'Проверь номер билета'
        await update.message.reply_text(
            text, reply_to_message_id=update.message.message_id)
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

    update_ticket_in_gspread(ticket_id, new_ticket_status.value)
    await db_postgres.update_ticket(
        context.session, ticket_id, status=new_ticket_status)

    await send_result_update_ticket(
        update, context, new_ticket_status.value)


def get_ticket_status_name(text):
    for status in TicketStatus:
        text += f'<code>{status.value}</code>\n'
    return text


async def send_result_update_ticket(update, context, new_ticket_status):
    text = f'Билет {new_ticket_status}'
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


async def confirm_reserve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет оповещение о подтверждении в бронировании, удаляет сообщение
    используемое в ConversationHandler и возвращает свободные места для
    доступа к бронированию
    """
    if not is_admin(update):
        main_handlers_logger.warning(
            'Не разрешенное действие: подтвердить бронь')
        return
    query = await remove_inline_button(update)

    message = await update.effective_chat.send_message(
        text='Начат процесс подтверждения...',
        reply_to_message_id=query.message.message_id,
        message_thread_id=query.message.message_thread_id
    )

    chat_id = query.data.split('|')[1].split()[0]
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    reserve_user_data = user_data['reserve_user_data']
    choose_schedule_event_ids = reserve_user_data['choose_schedule_event_ids']
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    ticket_ids = reserve_user_data['ticket_ids']

    try:
        for schedule_event_id in choose_schedule_event_ids:
            await decrease_nonconfirm_seat(context,
                                           schedule_event_id,
                                           chose_base_ticket_id)

        text = (f'\n\nПользователю @{user.username} {user.full_name} '
                f'Списаны неподтвержденные места...')
        await message.edit_text(text)

        ticket_status = TicketStatus.APPROVED
        for ticket_id in ticket_ids:
            update_ticket_in_gspread(ticket_id, ticket_status.value)
            await db_postgres.update_ticket(context.session,
                                            ticket_id,
                                            status=ticket_status)

        text = f'Обновлен статус билета...'
        await message.edit_text(text)

        chat_id = query.data.split('|')[1].split()[0]
        message_id = query.data.split('|')[1].split()[1]

        await send_approve_message(chat_id, context)

        text = f'Бронь подтверждена'
        await message.edit_text(text)

        # Сообщение уже было удалено самим пользователем
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message_id
            )
        except BadRequest as e:
            main_handlers_logger.error(e)
            main_handlers_logger.info(
                f'Cообщение уже удалено'
            )
    except BadRequest as e:
        main_handlers_logger.error(e)
        main_handlers_logger.info(": ".join(
            [
                'Пользователь',
                f'{user}',
                'Пытается спамить',
            ]
        ))


async def send_approve_message(chat_id, context):
    text = (
        'Ваша бронь подтверждена, ждем вас на мероприятии.\n'
        f'Адрес: {ADDRESS_OFFICE}\n\n'
        '❗️ВОЗВРАТ ДЕНЕЖНЫХ СРЕДСТВ ИЛИ ПЕРЕНОС ВОЗМОЖЕН НЕ МЕНЕЕ, ЧЕМ ЗА 24 ЧАСА❗\n'
        '<a href="https://vk.com/baby_theater_domik">Ссылка ВКонтакте</a> на нашу группу\n'
        'В ней более подробно описаны:\n'
        '- <a href="https://vk.com/baby_theater_domik?w=wall-202744340_2446">Бронь билетов</a>\n'
        '- <a href="https://vk.com/baby_theater_domik?w=wall-202744340_2495">Репертуар</a>\n'
        '- Фотографии\n'
        '- Команда и жизнь театра\n'
        '- <a href="https://vk.com/wall-202744340_1239">Ответы на часто задаваемые вопросы</a>\n'
        '- <a href="https://vk.com/baby_theater_domik?w=wall-202744340_2003">Как нас найти</a>\n\n'
        '<i>Задать любые интересующие вас вопросы вы можете через сообщения группы</i>\n\n'
        'Для продолжения работы используйте команды:\n'
        f'/{COMMAND_DICT['RESERVE'][0]} - выбрать и оплатить билет на спектакль '
    )
    await context.bot.send_message(text=text, chat_id=chat_id)


async def send_reject_message(chat_id, context):
    text = (
        'Ваша бронь отклонена.\n\n'
        'Если это произошло по ошибке, пожалуйста, '
        'напишите в ЛС или позвоните Администратору:\n'
        f'{context.bot_data['admin']['contacts']}'
    )
    await context.bot.send_message(text=text, chat_id=chat_id)


async def reject_reserve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет оповещение об отказе в бронировании, удаляет сообщение
    используемое в ConversationHandler и уменьшает кол-во неподтвержденных мест
    """
    if not is_admin(update):
        main_handlers_logger.warning(
            'Не разрешенное действие: отклонить бронь')
        return
    query = await remove_inline_button(update)

    message = await update.effective_chat.send_message(
        text='Начат процесс отклонения...',
        reply_to_message_id=query.message.message_id,
        message_thread_id=query.message.message_thread_id
    )

    chat_id = query.data.split('|')[1].split()[0]
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']
    ticket_ids = user_data['reserve_user_data']['ticket_ids']

    try:
        reserve_user_data = user_data['reserve_user_data']
        choose_schedule_event_ids = reserve_user_data['choose_schedule_event_ids']
        chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']

        for schedule_event_id in choose_schedule_event_ids:
            await increase_free_and_decrease_nonconfirm_seat(context,
                                                             schedule_event_id,
                                                             chose_base_ticket_id)

        text = f'Возвращены места в продажу...'
        await message.edit_text(text)

        ticket_status = TicketStatus.REJECTED
        for ticket_id in ticket_ids:
            update_ticket_in_gspread(ticket_id, ticket_status.value)
            await db_postgres.update_ticket(context.session,
                                            ticket_id,
                                            status=ticket_status)

        text = f'Обновлен статус билета...'
        await message.edit_text(text)

        message = await message.edit_text(
            text=f'Пользователю @{user.username} {user.full_name} '
                 f'отправляем сообщение об отклонении бронирования'
                 f'user_id {user.id}',
        )

        chat_id = query.data.split('|')[1].split()[0]
        message_id = query.data.split('|')[1].split()[1]

        await send_reject_message(chat_id, context)

        text = f'Бронь отклонена'
        await message.edit_text(text)

        # Сообщение уже было удалено самим пользователем
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message_id
            )
        except BadRequest:
            main_handlers_logger.info(
                f'Cообщение {message_id}, которое должно быть удалено'
            )

    except BadRequest:
        main_handlers_logger.info(": ".join(
            [
                'Пользователь',
                f'{user}',
                'Пытается спамить',
            ]
        ))


async def confirm_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        main_handlers_logger.warning(
            'Не разрешенное действие: подтвердить день рождения')
        return
    query = await remove_inline_button(update)

    chat_id = query.data.split('|')[1].split()[0]
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    data = query.data.split('|')[0][-1]
    message_id = query.data.split('|')[1].split()[1]
    text = ('Возникла ошибка\n'
            'Cвяжитесь с администратором:\n'
            f'{context.bot_data['admin']['contacts']}')
    context_bd = user_data['birthday_user_data']
    match data:
        case '1':
            await query.edit_message_text(
                query.message.text + '\n\n Заявка подтверждена, ждём предоплату'
            )

            text = '<b>У нас отличные новости!</b>\n'
            text += ('Мы с радостью проведем день рождения вашего малыша\n\n'
                     'Если вы готовы внести предоплату, то нажмите на команду\n'
                     f'/{COMMAND_DICT['BD_PAID'][0]}\n\n')
            text += '<i>Вам будет отправлено сообщение с информацией об оплате</i>'

            set_approve_order(context_bd, 0)

        case '2':
            await query.edit_message_text(
                f'Пользователю @{user.username} {user.full_name}\n'
                f'подтверждена бронь'
            )

            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )

                set_approve_order(context_bd, 2)
            except BadRequest:
                main_handlers_logger.info(
                    f'Cообщение уже удалено'
                )

            text = 'Ваша бронь подтверждена\nДо встречи в Домике'

    await context.bot.send_message(
        text=text,
        chat_id=chat_id,
    )


async def reject_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        main_handlers_logger.warning(
            'Не разрешенное действие: отклонить день рождения')
        return
    query = await remove_inline_button(update)

    chat_id = query.data.split('|')[1].split()[0]
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    data = query.data.split('|')[0][-1]
    message_id = query.data.split('|')[1].split()[1]
    text = ('Возникла ошибка\n'
            'Cвяжитесь с администратором:\n'
            f'{context.bot_data['admin']['contacts']}')
    match data:
        case '1':
            text = ('Мы рассмотрели Вашу заявку.\n'
                    'К сожалению, мы не сможем провести день рождения вашего '
                    'малыша\n\n'
                    'Для решения данного вопроса, пожалуйста, '
                    'свяжитесь с Администратором:\n'
                    f'{context.bot_data['admin']['contacts']}')

            await query.edit_message_text(
                query.message.text + '\n\n Заявка отклонена'
            )
        case '2':
            await query.edit_message_text(
                f'Пользователю @{user.username} {user.full_name}\n'
                f'отклонена бронь'
            )

            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )
            except BadRequest:
                main_handlers_logger.info(
                    f'Cообщение уже удалено'
                )
            text = ('Ваша бронь отклонена.\n'
                    'Для решения данного вопроса, пожалуйста, '
                    'свяжитесь с Администратором:\n'
                    f'{context.bot_data['admin']['contacts']}')

    await context.bot.send_message(
        text=text,
        chat_id=chat_id,
    )


async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    state = query.data.split('-')[1]
    if state.isdigit():
        state = int(state)
    else:
        state = state.upper()
    text, reply_markup = get_back_context(context, state)

    command = context.user_data['command']

    if state == 'MONTH':
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=query.message.message_thread_id
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
                message_thread_id=query.message.message_thread_id
            )
    elif state == 'DATE':
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
                    message_thread_id=query.message.message_thread_id
                )
            else:
                await update.effective_chat.send_message(
                    text=text,
                    reply_markup=reply_markup,
                    message_thread_id=query.message.message_thread_id
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
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
            )
        except BadRequest as e:
            main_handlers_logger.error(e)
            try:
                await query.delete_message()
            except BadRequest as e:
                main_handlers_logger.error(e)
            await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup,
                message_thread_id=query.message.message_thread_id
            )
    context.user_data['STATE'] = state
    return state


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Хэндлер отмены, может использоваться на этапе бронирования и оплаты,
    для отмены действий и выхода из ConversationHandler
    """
    query = update.callback_query
    await query.answer()

    user = context.user_data['user']
    data = query.data.split('|')[0].split('-')[-1]

    first_text = 'Вы выбрали отмену\n'
    use_command_text = 'Используйте команды:\n'
    reserve_text = (f'/{COMMAND_DICT['RESERVE'][0]} - для повторного '
                    f'резервирования свободных мест на мероприятие\n')
    reserve_admin_text = (
        f'/{COMMAND_DICT['RESERVE_ADMIN'][0]} - для повторной '
        f'записи без подтверждения\n')
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

    text = first_text
    match data:
        case 'reserve':
            text += (use_command_text + reserve_text + explanation_text +
                     description)
            await cancel_common(update, text)

            if context.user_data['STATE'] == 'OFFER':
                await context.bot.delete_message(
                    update.effective_chat.id,
                    context.user_data['reserve_user_data']['accept_message_id']
                )

            if '|' in query.data:
                await cancel_payment(context)
        case 'reserve_admin':
            text += (use_command_text + reserve_text + reserve_admin_text)
            await cancel_common(update, text)

            if '|' in query.data:
                await cancel_payment(context)
        case 'studio':
            text += (use_command_text + studio_text + explanation_text +
                     description)
            await cancel_common(update, text)

            if context.user_data['STATE'] == 'OFFER':
                await context.bot.delete_message(
                    update.effective_chat.id,
                    context.user_data['reserve_user_data']['accept_message_id']
                )

            if '|' in query.data:
                await cancel_payment(context)
        case 'studio_admin':
            text += (use_command_text + studio_text + studio_admin_text)
            await cancel_common(update, text)

            if '|' in query.data:
                await cancel_payment(context)
        case 'bd':
            text += (use_command_text + bd_order_text + bd_paid_text)
            await cancel_common(update, text)
        case 'settings':
            await cancel_common(update, text)
        case 'migration_admin':
            await cancel_common(update, text)
        case 'list':
            await cancel_common(update, text)
        case 'list_wait':
            await cancel_common(update, text)
        case 'afisha':
            await cancel_common(update, text)

    try:
        main_handlers_logger.info(f'Для пользователя {user}')
    except KeyError:
        main_handlers_logger.info(f'Пользователь {user}: Не '
                                  f'оформил заявку, а сразу использовал '
                                  f'команду /{COMMAND_DICT['BD_PAID'][0]}')
    await clean_context_on_end_handler(main_handlers_logger, context)
    return ConversationHandler.END


async def cancel_payment(context):
    new_ticket_status = TicketStatus.CANCELED
    await write_to_return_seats_for_sale(context, status=new_ticket_status)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> -1:
    utilites_logger.info(
        f'{update.effective_user.id}: '
        f'{update.effective_user.full_name}\n'
        f'Вызвал команду reset'
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text='Попробуйте выполнить новый запрос'
    )
    await clean_context_on_end_handler(utilites_logger, context)
    return ConversationHandler.END


async def help_command(update: Update, _: ContextTypes.DEFAULT_TYPE):
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
    return ConversationHandler.END


async def feedback_send_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    main_handlers_logger.info('FEEDBACK')
    main_handlers_logger.info(update.effective_user)
    main_handlers_logger.info(update.message)

    user = context.user_data['user']

    text = 'Ваше сообщение принято.\n\n'
    await update.effective_chat.send_message(text)

    chat_id = ADMIN_GROUP
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


async def feedback_reply_msg(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
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
    except (IndexError, ValueError) as e:
        main_handlers_logger.error(e)
        await update.effective_message.reply_text(
            text='Проверьте что отвечаете на правильное сообщение',
            message_thread_id=update.message.message_thread_id
        )


async def global_on_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

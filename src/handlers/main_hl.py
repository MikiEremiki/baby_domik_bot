import logging

from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update, ReplyKeyboardRemove
from telegram.constants import ChatType
from telegram.error import BadRequest

from handlers import check_user_db
from handlers.sub_hl import write_old_seat_info, remove_inline_button
from settings.settings import (
    COMMAND_DICT, ADMIN_GROUP, FEEDBACK_THREAD_ID_GROUP_ADMIN
)
from api.googlesheets import (
    get_quality_of_seats, write_data_for_reserve, set_approve_order
)
from utilities.utl_func import (
    is_admin, get_back_context, clean_context,
    clean_context_on_end_handler, utilites_logger
)

main_handlers_logger = logging.getLogger('bot.main_handlers')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Приветственная команда при первом запуске бота,
    при перезапуске бота или при использовании команды start
    """
    if not await AsyncORM.get_user(update, context.session):
        res = await AsyncORM.create_user(update, context.session)
        if res:
            main_handlers_logger.info(
                f'Пользователь {res} начал общение с ботом')
    else:
        main_handlers_logger.info('Пользователь уже в есть в базе')
    clean_context(context)

    context.user_data['user'] = update.effective_user
    context.user_data['common_data'] = {}

    await update.effective_chat.send_message(
        text='<b>Вас приветствует Бот Бэби-театра «Домик»</b>\n\n'
             '--><a href="https://vk.com/baby_theater_domik">Наша группа ВКонтакте</a>\n\n'
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
             f'(<a href="https://vk.com/baby_theater_domik?w=wall-202744340_2446">инструкция</a>)\n'
             f'/{COMMAND_DICT['BD_ORDER'][0]} - оформить заявку на проведение дня рождения '
             f'(<a href="https://vk.com/wall-202744340_2469">инструкция</a>)',
        reply_markup=ReplyKeyboardRemove()
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

    chat_id = query.data.split('|')[1].split()[0]
    payment_id = int(query.data.split('|')[1].split()[2])
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    try:
        payment_data = user_data['reserve_admin_data'][payment_id]
        event_id = payment_data['event_id']
        chose_ticket = payment_data['chose_ticket']

        # Обновляем кол-во доступных мест
        list_of_name_colum = [
            'qty_child_nonconfirm_seat',
            'qty_adult_nonconfirm_seat'
        ]
        (qty_child_nonconfirm_seat_now,
         qty_adult_nonconfirm_seat_now
         ) = get_quality_of_seats(event_id,
                                  list_of_name_colum)

        qty_child_nonconfirm_seat_new = int(
            qty_child_nonconfirm_seat_now) - int(chose_ticket.quality_of_children)
        qty_adult_nonconfirm_seat_new = int(
            qty_adult_nonconfirm_seat_now) - int(chose_ticket.quality_of_adult +
                                                 chose_ticket.quality_of_add_adult)

        numbers = [
            qty_child_nonconfirm_seat_new,
            qty_adult_nonconfirm_seat_new
        ]
        try:
            write_data_for_reserve(event_id, numbers, 2)

            main_handlers_logger.info(": ".join(
                [
                    'Для пользователя',
                    f'{user}',
                    'event_id для обновления',
                    event_id,
                ]
            ))
        except TimeoutError:
            await update.effective_chat.send_message(
                text=f'Для пользователя @{user.username} {user.full_name} '
                     f'подтверждение в авто-режиме не сработало\n'
                     f'Номер строки для обновления:\n{event_id}'
            )
            main_handlers_logger.error(TimeoutError)
            main_handlers_logger.error(": ".join(
                [
                    f'Для пользователя {user} подтверждение в '
                    f'авто-режиме не сработало',
                    'event_id для обновления',
                    event_id,
                ]
            ))

        await query.edit_message_text(
            text=f'Пользователю @{user.username} {user.full_name} '
                 f'подтверждена бронь'
        )

        chat_id = query.data.split('|')[1].split()[0]
        message_id = query.data.split('|')[1].split()[1]

        text = (
            'Ваша бронь подтверждена, ждем вас на спектакле.\n'
            'Адрес: Малая Покровская, д18, 2 этаж\n\n'
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
        await context.bot.send_message(
            text=text,
            chat_id=chat_id,
        )

        # TODO Добавить галочку подтверждения в клиентскую базу

        # Сообщение уже было удалено самим пользователем
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message_id
            )
        except BadRequest:
            main_handlers_logger.info(
                f'Cообщение уже удалено'
            )
    except BadRequest:
        main_handlers_logger.info(": ".join(
            [
                'Пользователь',
                f'{user}',
                'Пытается спамить',
            ]
        ))


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

    chat_id = query.data.split('|')[1].split()[0]
    payment_id = int(query.data.split('|')[1].split()[2])
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    try:
        payment_data = user_data['reserve_admin_data'][payment_id]
        event_id = payment_data['event_id']
        chose_ticket = payment_data['chose_ticket']

        await write_old_seat_info(user,
                                  event_id,
                                  chose_ticket)

        await query.edit_message_text(
            text=f'Пользователю @{user.username} {user.full_name} '
                 f'отклонена бронь'
        )

        chat_id = query.data.split('|')[1].split()[0]
        message_id = query.data.split('|')[1].split()[1]
        await context.bot.send_message(
            text='Ваша бронь отклонена.\n'
                 'Для решения данного вопроса, пожалуйста, '
                 'напишите в ЛС или позвоните Администратору:\n'
                 f'{context.bot_data['admin']['contacts']}',
            chat_id=chat_id,
        )

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

        main_handlers_logger.info(": ".join(
            [
                'Для пользователя',
                f'{user}',
                'event_id для обновления',
                event_id,
            ]
        ))
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
            if update.effective_chat.type == ChatType.PRIVATE and photo:
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
    else:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
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
    match data:
        case 'res':
            await query.delete_message()
            await update.effective_chat.send_message(
                text='Вы выбрали отмену\nИспользуйте команды:\n'
                     f'/{COMMAND_DICT['RESERVE'][0]} - для повторного '
                     f'резервирования свободных мест на спектакль',
                message_thread_id=query.message.message_thread_id
            )

            if '|' in query.data:
                chat_id = query.data.split('|')[1].split()[0]
                message_id = query.data.split('|')[1].split()[1]
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )

                reserve_admin_data = context.user_data['reserve_admin_data']
                payment_id = reserve_admin_data['payment_id']
                chose_ticket = reserve_admin_data[payment_id]['chose_ticket']
                event_id = reserve_admin_data[payment_id]['event_id']

                await write_old_seat_info(user, event_id, chose_ticket)
        case 'bd':
            await query.delete_message()
            await update.effective_chat.send_message(
                text='Вы выбрали отмену\nИспользуйте команды:\n'
                     f'/{COMMAND_DICT['BD_ORDER'][0]} - для повторной '
                     f'отправки заявки на проведение Дня рождения\n'
                     f'/{COMMAND_DICT['BD_PAID'][0]} - для повторного '
                     f'запуска процедуры внесения предоплаты, если ваша заявка '
                     f'была одобрена',
                message_thread_id=query.message.message_thread_id
            )
        case 'res_adm':
            await query.delete_message()
            await update.effective_chat.send_message(
                text='Вы выбрали отмену\nИспользуйте команды:\n'
                     f'/{COMMAND_DICT['RESERVE'][0]} - для повторного '
                     f'резервирования свободных мест на спектакль\n'
                     f'/{COMMAND_DICT['RESERVE_ADMIN'][0]} - для повторной '
                     f'записи без подтверждения',
                message_thread_id=query.message.message_thread_id
            )

    try:
        main_handlers_logger.info(f'Для пользователя {user}')
    except KeyError:
        main_handlers_logger.info(f'Пользователь {user}: Не '
                                  f'оформил заявку, а сразу использовал '
                                  f'команду /{COMMAND_DICT['BD_PAID'][0]}')
    await clean_context_on_end_handler(main_handlers_logger, context)
    return ConversationHandler.END


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

    text = (
        'К сожалению, у меня пока нет полномочий для помощи по любым вопросам\n'
        'Я переслал ваше сообщение Администратору, дождитесь ответа\n\n'
        'Также проверьте, пожалуйста:\n <i>Настройки > Конфиденциальность > '
        'Пересылка сообщений</i>\n'
        'Если установлен вариант <code>Мои контакты</code> или '
        '<code>Никто</code>, добавьте бота в исключения, иначе Администратор '
        'не сможет с вами связаться\n\n'
        'После смены настроек отправьте сообщение еще раз или перешлите в '
        'этот чат предыдущее сообщение\n\n'
        'Вместо смены настроек можете написать свой номер телефона или '
        'связаться самостоятельно\n\n'
        '<a href="https://vk.com/baby_theater_domik">Ссылка ВКонтакте</a> на нашу группу'
        'Задать любые интересующие вас вопросы вы можете через сообщения группы'
    )
    await update.effective_chat.send_message(text)

    chat_id = ADMIN_GROUP
    message = await update.message.forward(
        chat_id,
        message_thread_id=FEEDBACK_THREAD_ID_GROUP_ADMIN
    )
    await context.bot.send_message(
        chat_id,
        f'Сообщение от пользователя @{user.username} '
        f'<a href="tg://user?id={user.id}">{user.full_name}</a>',
        reply_to_message_id=message.message_id,
        message_thread_id=message.message_thread_id
    )

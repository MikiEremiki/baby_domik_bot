import logging

from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update, ReplyKeyboardRemove
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest
from telegram.helpers import escape_markdown

from handlers.sub_hl import write_old_seat_info
from utilities.settings import (
    COMMAND_DICT,
    ADMIN_GROUP,
    FEEDBACK_THREAD_ID_GROUP_ADMIN)
from utilities.hlp_func import do_italic, do_bold
from utilities.googlesheets import (
    update_quality_of_seats,
    write_data_for_reserve,
    set_approve_order
)

main_handlers_logger = logging.getLogger('bot.main_handlers')


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """
    Приветственная команда при первом запуске бота,
    при перезапуске бота или при использовании команды start
    """
    await update.effective_chat.send_message(
        text='Отлично! Мы рады, что вы с нами. Используйте команды:\n '
             f'/{COMMAND_DICT["RESERVE"][0]} - чтобы выбрать и оплатить билет на'
             f' спектакль для просмотра в нашем театре\n'
             f'/{COMMAND_DICT["BD_ORDER"][0]} - чтобы оформить заявку на '
             f'проведение дня рождения в театре или по вашему адресу\n',
        reply_markup=ReplyKeyboardRemove()
    )


async def confirm_reserve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет оповещение о подтверждении в бронировании, удаляет сообщение
    используемое в ConversationHandler и возвращает свободные места для
    доступа к бронированию
    """
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    chat_id = query.data.split('|')[1].split()[0]
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    try:
        chose_ticket = user_data['chose_ticket']
        row_in_googlesheet = user_data['row_in_googlesheet']

        nonconfirm_number_of_seats_now = update_quality_of_seats(
            row_in_googlesheet, 'qty_child_nonconfirm_seat')

        new_nonconfirm_number_of_seats = int(
            nonconfirm_number_of_seats_now) - int(
            chose_ticket.quality_of_children)
        try:
            write_data_for_reserve(
                row_in_googlesheet,
                [new_nonconfirm_number_of_seats]
            )

            main_handlers_logger.info(": ".join(
                [
                    'Для пользователя',
                    f'{user}',
                    'Номер строки для обновления',
                    row_in_googlesheet,
                ]
            ))
        except TimeoutError:
            await update.effective_chat.send_message(
                text=f'Для пользователя @{user.username} {user.full_name} подтверждение в '
                     f'авто-режиме не сработало\n'
                     f'Номер строки для обновления:\n{row_in_googlesheet}'
            )
            main_handlers_logger.error(TimeoutError)
            main_handlers_logger.error(": ".join(
                [
                    f'Для пользователя {user} подтверждение в '
                    f'авто-режиме не сработало',
                    'Номер строки для обновления',
                    row_in_googlesheet,
                ]
            ))

        await query.edit_message_text(
            text=f'Пользователю @{user.username} {user.full_name} подтверждена бронь'
        )

        chat_id = query.data.split('|')[1].split()[0]
        message_id = query.data.split('|')[1].split()[1]
        text = 'Ваша бронь подтверждена\nЖдем вас на спектакле.'
        await context.bot.send_message(
            text=text,
            chat_id=chat_id,
        )

        # TODO Решить нужна ли действительно очистка контекста пользователя
        context.application.user_data.get(int(chat_id)).clear()
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
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    chat_id = query.data.split('|')[1].split()[0]
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    try:
        chose_ticket = user_data['chose_ticket']
        row_in_googlesheet = user_data['row_in_googlesheet']

        await write_old_seat_info(update,
                                  user,
                                  row_in_googlesheet,
                                  chose_ticket)

        await query.edit_message_text(
            text=f'Пользователю @{user.username} {user.full_name} отклонена бронь'
        )

        chat_id = query.data.split('|')[1].split()[0]
        message_id = query.data.split('|')[1].split()[1]
        await context.bot.send_message(
            text='Ваша бронь отклонена.\nДля решения данного вопроса '
                 'напишите, пожалуйста, в ЛС или позвоните:\n'
                 'Татьяна Бурганова @Tanya_domik +79159383529',
            chat_id=chat_id,
        )
        context.application.user_data.get(int(chat_id)).clear()

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
                'Номер строки, которая должна быть обновлена',
                row_in_googlesheet,
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
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    chat_id = query.data.split('|')[1].split()[0]
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    data = query.data.split('|')[0][-1]
    message_id = query.data.split('|')[1].split()[1]
    text = ('Возникла ошибка\n'
            'Cвяжитесь с администратором:'
            'Татьяна Бурганова @Tanya_domik +79159383529')
    context_bd = user_data['birthday_data']
    match data:
        case '1':
            await query.edit_message_text(
                query.message.text + '\n\n Заявка подтверждена, ждём предоплату'
            )

            text = do_bold('У нас отличные новости!\n')
            text += escape_markdown(
                'Мы с радостью проведем день рождения вашего малыша\n\n'
                'Если вы готовы внести предоплату, то нажмите на команду\n'
                f' /{COMMAND_DICT["BD_PAID"][0]}\n\n',
                2
            )
            text += do_italic(
                'Вам будет отправлено сообщение с информацией об оплате'
            )

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
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def reject_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    chat_id = query.data.split('|')[1].split()[0]
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']

    data = query.data.split('|')[0][-1]
    message_id = query.data.split('|')[1].split()[1]
    text = ('Возникла ошибка\n'
            'Cвяжитесь с администратором:'
            'Татьяна Бурганова @Tanya_domik +79159383529')
    match data:
        case '1':
            text = ('Мы рассмотрели Вашу заявку.\n'
                    'К сожалению, мы не сможем провести день рождения вашего '
                    'малыша\n\nДля решения данного вопроса напишите, '
                    'пожалуйста, в ЛС или позвоните:\n'
                    'Татьяна Бурганова @Tanya_domik +79159383529')

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
                    'Для решения данного вопроса напишите, пожалуйста, '
                    'в ЛС или позвоните:\n'
                    'Татьяна Бурганова @Tanya_domik +79159383529')

    await context.bot.send_message(
        text=text,
        chat_id=chat_id,
    )


async def back_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()
    await query.delete_message()

    text = context.user_data['text_month']
    reply_markup = context.user_data['keyboard_month']
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )
    return 'MONTH'


async def back_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    text = context.user_data['text_show']
    reply_markup = context.user_data['keyboard_show']
    try:
        await query.edit_message_caption(
            caption=text,
            reply_markup=reply_markup
        )
    except BadRequest as e:
        main_handlers_logger.error(e)
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup
        )
    return 'SHOW'


async def back_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    text = context.user_data['text_date']
    reply_markup = context.user_data['keyboard_date']

    try:
        number_of_month_str = context.user_data['number_of_month_str']
        await query.delete_message()
        photo = (
            context.bot_data
            .get('afisha', {})
            .get(int(number_of_month_str), False)
        )
        if update.effective_chat.type == ChatType.PRIVATE and photo:
            message = await update.effective_chat.send_photo(
                photo=photo,
                caption=text,
                reply_markup=reply_markup
            )
            context.user_data['afisha_media'] = [message]
        else:
            await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup
            )
    except BadRequest as e:
        main_handlers_logger.error(e)
        await query.edit_message_text(
            text,
            reply_markup=reply_markup
        )
    return 'DATE'


async def back_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    text = context.user_data['text_time']
    reply_markup = context.user_data['keyboard_time']
    await query.edit_message_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    return 'TIME'


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
                     f'/{COMMAND_DICT["RESERVE"][0]} - для повторного '
                     f'резервирования свободных мест на спектакль'
            )

            if '|' in query.data:
                chat_id = query.data.split('|')[1].split()[0]
                message_id = query.data.split('|')[1].split()[1]
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )

                chose_ticket = context.user_data['chose_ticket']
                row_in_googlesheet = context.user_data['row_in_googlesheet']

                await write_old_seat_info(update,
                                          user,
                                          row_in_googlesheet,
                                          chose_ticket)
        case 'bd':
            await query.delete_message()
            await update.effective_chat.send_message(
                text='Вы выбрали отмену\nИспользуйте команды:\n'
                     f'/{COMMAND_DICT["BD_ORDER"][0]} - для повторной '
                     f'отправки заявки на проведение Дня рождения\n'
                     f'/{COMMAND_DICT["BD_PAID"][0]} - для повторного '
                     f'запуска процедуры внесения предоплаты, если ваша заявка '
                     f'была одобрена'
            )

    try:
        main_handlers_logger.info(f'Для пользователя {user}')
    except KeyError:
        main_handlers_logger.info(f'Пользователь {user}: Не '
                                  f'оформил заявку, а сразу использовал '
                                  f'команду /{COMMAND_DICT["BD_PAID"][0]}')
    main_handlers_logger.info(
        f'Обработчик завершился на этапе {context.user_data["STATE"]}')

    context.user_data.clear()
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
    await update.effective_chat.send_message('Текущая операция сброшена.\n'
                                             'Можете выполните новую команду')
    return ConversationHandler.END


async def feedback_send_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    main_handlers_logger.info('FEEDBACK')
    main_handlers_logger.info(update.effective_user)
    main_handlers_logger.info(update.message)

    user = update.effective_user

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
        '<u>Контакты для связи:</u>\n'
        'Татьяна Бурганова @Tanya_domik +79159383529'
    )
    await update.effective_chat.send_message(text, parse_mode=ParseMode.HTML)

    chat_id = ADMIN_GROUP
    message = await update.message.forward(
        chat_id,
        message_thread_id=FEEDBACK_THREAD_ID_GROUP_ADMIN
    )
    await context.bot.send_message(
        chat_id,
        f'Сообщение от пользователя @{user.username} '
        f'<a href="tg://user?id={user.id}">{user.full_name}</a>',
        parse_mode=ParseMode.HTML,
        reply_to_message_id=message.message_id,
        message_thread_id=message.message_thread_id
    )

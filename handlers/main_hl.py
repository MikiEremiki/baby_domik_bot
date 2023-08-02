import logging

from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)
from telegram import Update, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.error import BadRequest

from utilities.googlesheets import (
    update_quality_of_seats,
    write_data_for_reserve,
)
from utilities.settings import COMMAND_DICT

main_handlers_logger = logging.getLogger('bot.main_handlers')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    # Способ защиты от многократного нажатия
    await query.edit_message_reply_markup()

    text_query_split = query.message.text.split('\n')[0]
    user = text_query_split[text_query_split.find(' ') + 1:]

    try:
        dict_of_option_for_reserve = context.bot_data['dict_of_option_for_reserve']
        key_option_for_reserve = int(query.data.split('|')[1].split()[3])
        chose_reserve_option = dict_of_option_for_reserve.get(
            key_option_for_reserve)

        row_in_googlesheet = query.data.split('|')[1].split()[2]

        nonconfirm_number_of_seats_now = update_quality_of_seats(
            row_in_googlesheet, 5)

        new_nonconfirm_number_of_seats = int(
            nonconfirm_number_of_seats_now) - int(
            chose_reserve_option.get('quality_of_children'))
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
                text=f'Для пользователя {user} подтверждение в '
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
            text=f'Пользователю {user} подтверждена бронь'
        )

        chat_id = query.data.split('|')[1].split()[0]
        message_id = query.data.split('|')[1].split()[1]
        text = 'Ваша бронь подтверждена\nЖдем вас на спектакле.'
        await context.bot.send_message(
            text=text,
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

    text_query_split = query.message.text.split('\n')[0]
    user = text_query_split[text_query_split.find(' ') + 1:]

    try:
        dict_of_option_for_reserve = context.bot_data['dict_of_option_for_reserve']
        key_option_for_reserve = int(query.data.split('|')[1].split()[3])
        chose_reserve_option = dict_of_option_for_reserve.get(
            key_option_for_reserve)

        # Номер строки для извлечения актуального числа доступных мест
        row_in_googlesheet = query.data.split('|')[1].split()[2]

        # Обновляем кол-во доступных мест
        availibale_number_of_seats_now = update_quality_of_seats(
            row_in_googlesheet, 4)
        nonconfirm_number_of_seats_now = update_quality_of_seats(
            row_in_googlesheet, 5)

        old_number_of_seats = int(
            availibale_number_of_seats_now) + int(
            chose_reserve_option.get('quality_of_children'))
        old_nonconfirm_number_of_seats = int(
            nonconfirm_number_of_seats_now) - int(
            chose_reserve_option.get('quality_of_children'))

        try:
            write_data_for_reserve(
                row_in_googlesheet,
                [old_number_of_seats, old_nonconfirm_number_of_seats]
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
                text=f'Для пользователя {user} отклонение в '
                     f'авто-режиме не сработало\n'
                     f'Номер строки для обновления:\n{row_in_googlesheet}'
            )
            main_handlers_logger.error(TimeoutError)
            main_handlers_logger.error(": ".join(
                [
                    f'Для пользователя {user} отклонение в '
                    f'авто-режиме не сработало',
                    'Номер строки для обновления',
                    row_in_googlesheet,
                ]
            ))

        await query.edit_message_text(
            text=f'Пользователю {user} отклонена бронь'
        )

        chat_id = query.data.split('|')[1].split()[0]
        message_id = query.data.split('|')[1].split()[1]
        await context.bot.send_message(
            text='Ваша бронь отклонена.\n'
                 'Для решения данного вопроса, напишите пожалуйста в ЛС или позвоните:\n'
                 'Татьяна Бурганова @Tanya_domik +79159383529',
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

    text_query_split = query.message.text.split('\n')[0]
    user = text_query_split[text_query_split.find(' ') + 1:]

    data = query.data.split('|')[0][-1]
    chat_id = query.data.split('|')[1].split()[0]
    message_id = query.data.split('|')[1].split()[1]
    text = 'Возникла ошибка\n' \
           'Cвяжитесь с администратором:' \
           'Татьяна Бурганова @Tanya_domik +79159383529'
    match data:
        case '1':
            await query.edit_message_text(
                query.message.text + '\n\n Заявка подтверждена, ждём предоплату'
            )

            text = 'У нас отличные новости!\n' \
                   'Мы с радостью проведем день рождения вашего малыша\n\n' \
                   'Если вы готовы внести предоплату то нажмите на команду ' \
                   f'/{COMMAND_DICT["BD_PAID"][0]}\n\n' \
                   'Вам будет отправлено сообщение с информацией об оплате'
        case '2':
            await query.edit_message_text(
                f'Пользователю {user}\n'
                f'подтверждена бронь'
            )

            try:
                # TODO Дополнить запись в гугл-таблице о факте подтверждения
                #  оплаты администратором
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )
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
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    text_query_split = query.message.text.split('\n')[0]
    user = text_query_split[text_query_split.find(' ') + 1:]

    data = query.data.split('|')[0][-1]
    chat_id = query.data.split('|')[1].split()[0]
    message_id = query.data.split('|')[1].split()[1]
    text = 'Возникла ошибка\n' \
           'Cвяжитесь с администратором:' \
           'Татьяна Бурганова @Tanya_domik +79159383529'
    match data:
        case '1':
            text = 'Мы рассмотрели Вашу заявку\n' \
                   'К сожалению мы не сможем провести день рождения вашего ' \
                   'малыша\n\n' \
                   'Для решения данного вопроса, напишите пожалуйста в ЛС или позвоните:\n' \
                   'Татьяна Бурганова @Tanya_domik +79159383529'

            await query.edit_message_text(
                query.message.text + '\n\n Заявка отклонена'
            )
        case '2':
            await query.edit_message_text(
                f'Пользователю {user}\n'
                f'отклонена бронь'
            )

            try:
                # TODO Дополнить запись в гугл-таблице о факте отказа от
                #  оплаты администратором
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )
            except BadRequest:
                main_handlers_logger.info(
                    f'Cообщение уже удалено'
                )
            text = 'Ваша бронь отклонена.\n' \
                   'Для решения данного вопроса, напишите пожалуйста в ЛС или позвоните:\n' \
                   'Татьяна Бурганова @Tanya_domik +79159383529'

    await context.bot.send_message(
        text=text,
        chat_id=chat_id,
    )


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
            await query.edit_message_text(
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

                chose_reserve_option = context.user_data['chose_reserve_option']

                # Номер строки для извлечения актуального числа доступных мест
                row_in_googlesheet = context.user_data['row_in_googlesheet']

                # Обновляем кол-во доступных мест
                availibale_number_of_seats_now = update_quality_of_seats(
                    row_in_googlesheet, 4)
                nonconfirm_number_of_seats_now = update_quality_of_seats(
                    row_in_googlesheet, 5)

                old_number_of_seats = int(
                    availibale_number_of_seats_now) + int(
                    chose_reserve_option.get('quality_of_children'))
                old_nonconfirm_number_of_seats = int(
                    nonconfirm_number_of_seats_now) - int(
                    chose_reserve_option.get('quality_of_children'))
                try:
                    write_data_for_reserve(
                        row_in_googlesheet,
                        [old_number_of_seats, old_nonconfirm_number_of_seats]
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
                        text=f'Для пользователя @{user.username} {user.full_name} отклонение в '
                             f'авто-режиме не сработало\n'
                             f'Номер строки для обновления:\n{row_in_googlesheet}'
                    )
                    main_handlers_logger.error(TimeoutError)
                    main_handlers_logger.error(": ".join(
                        [
                            f'Для пользователя {user} отклонение в '
                            f'авто-режиме не сработало',
                            'Номер строки для обновления',
                            row_in_googlesheet,
                        ]
                    ))
        case 'bd':
            await query.edit_message_text(
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
    main_handlers_logger.info(f'Обработчик завершился на этапе {context.user_data["STATE"]}')

    context.user_data.clear()
    return ConversationHandler.END


def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Название не должно быть просто help
    # TODO Прописать логику использования help
    pass

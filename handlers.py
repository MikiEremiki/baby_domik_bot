import logging

from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    TypeHandler
)
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)

import googlesheets
import utilites


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    await update.effective_chat.send_message(
        text='Отлично! Мы рады, что вы с нами. Воспользуйтесь командой '
             '/choice, чтобы выбрать спектакль.'
    )


async def choice_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update: Update
    :param context: ContextTypes.DEFAULT_TYPE
    :return:
    """
    dict_of_shows, dict_of_date_and_time = utilites.load_data()
    keyboard = []
    for key in dict_of_date_and_time.keys():
        for date in dict_of_date_and_time[key].keys():
            button_tmp = InlineKeyboardButton(
                str(key) + ' | ' + date,
                callback_data=str(key) + ' | ' + date
            )
            keyboard.append([button_tmp])

    button_tmp = InlineKeyboardButton(
        "Отменить",
        callback_data='Отменить'
    )
    keyboard.append([button_tmp])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите спектакль и дату\n'
    for key, item in dict_of_shows.items():
        text += f'{item}: {key}\n'
    answer = await update.message.reply_text(text, reply_markup=reply_markup)

    context.user_data['user'] = update.message.from_user
    context.user_data['message_id'] = answer.message_id

    context.user_data['text_date'] = text
    context.user_data['keyboard_date'] = reply_markup

    context.user_data.setdefault('dict_of_shows', dict_of_shows)
    context.user_data.setdefault('dict_of_date_and_time', dict_of_date_and_time)

    return 'DATE'


async def choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query: CallbackQuery = update.callback_query
    await query.answer()

    list_name_and_date = query.data.split(' | ')
    key_of_name_show = int(list_name_and_date[0])
    date_show = list_name_and_date[1]
    dict_of_shows = context.user_data.get('dict_of_shows')
    dict_of_date_and_time = context.user_data.get('dict_of_date_and_time')

    name_show = '---'
    for key, item in dict_of_shows.items():
        if item == key_of_name_show:
            name_show = key

    keyboard = []

    for time in dict_of_date_and_time[key_of_name_show][date_show].keys():
        if dict_of_date_and_time[key_of_name_show][date_show][time][0][1] == 0:
            continue
        number = dict_of_date_and_time[key_of_name_show][date_show][time][0][1]
        button_tmp = InlineKeyboardButton(
            time + ' | ' + str(number) + ' шт свободно',
            callback_data=time
        )
        keyboard.append([button_tmp])

    keyboard.append(utilites.add_btn_back_and_cancel())
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = f'Вы выбрали {name_show}\n' \
           'Выберите удобное время.'
    await query.message.edit_text(text, reply_markup=reply_markup)

    context.user_data['key_of_name_show'] = key_of_name_show
    context.user_data['date_show'] = date_show
    context.user_data['name_show'] = name_show

    context.user_data['text_time'] = text
    context.user_data['keyboard_time'] = reply_markup

    return 'TIME'


async def choice_number_of_seats(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    key = context.user_data['key_of_name_show']
    date = context.user_data['date_show']
    time = query.data
    dict_of_date_and_time = context.user_data.get('dict_of_date_and_time')
    number_of_available_seats = dict_of_date_and_time[key][date][time][0][1]

    keyboard = []
    list_btn_of_numbers = []
    for i in range(number_of_available_seats):
        button_tmp = InlineKeyboardButton(
            str(i + 1),
            callback_data=i + 1
        )
        list_btn_of_numbers.append(button_tmp)
    keyboard.append(list_btn_of_numbers)

    keyboard.append(utilites.add_btn_back_and_cancel())
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = f'Выберите сколько мест вы хотите забронировать\n' \
           f'Введите цифру от 1 до {number_of_available_seats}'
    await query.message.edit_text(text, reply_markup=reply_markup)

    context.user_data['time_of_show'] = time

    return 'ORDER'


async def send_qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    key = context.user_data['key_of_name_show']
    name_show = context.user_data['name_show']
    date = context.user_data['date_show']
    time = context.user_data['time_of_show']
    dict_of_date_and_time = context.user_data.get('dict_of_date_and_time')
    number_of_seats = query.data
    text = f'Вы выбрали:\n' \
           f'{name_show}\n' \
           f'{date}\n' \
           f'В {time}\n' \
           f'Кол-во мест для бронирования: {number_of_seats}'
    await query.message.edit_text(text)

    row_in_googlesheet = dict_of_date_and_time[key][date][time][1]

    availibale_number_of_seats_now = googlesheets.check_seats(
        row_in_googlesheet, 4)
    nonconfirm_number_of_seats_now = googlesheets.check_seats(
        row_in_googlesheet, 5)

    new_number_of_seats = int(availibale_number_of_seats_now) - int(
        number_of_seats)
    new_nonconfirm_number_of_seats = int(nonconfirm_number_of_seats_now) + int(
        number_of_seats)
    if availibale_number_of_seats_now >= number_of_seats:
        googlesheets.confirm(row_in_googlesheet, [new_number_of_seats,
                                                  new_nonconfirm_number_of_seats])
    else:
        keyboard = []
        keyboard.append(utilites.add_btn_back_and_cancel())
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            text='К сожалению места уже забронировали и свободных мест не осталось\n'
                 'Пожалуйста выберите другое время.',
            reply_markup=reply_markup
        )
        return 'ORDER'

    keyboard = []
    button_approve = InlineKeyboardButton(
        "Подтвердить",
        callback_data=f'Подтвердить|{query.message.chat_id} {query.message.message_id}'
    )
    old_number_of_seats = new_number_of_seats + int(number_of_seats)
    old_nonconfirm_number_of_seats = new_nonconfirm_number_of_seats - int(
        number_of_seats)
    button_cancel = InlineKeyboardButton(
        "Отменить",
        callback_data=f'Отменить|'
                      f'{query.message.chat_id} {query.message.message_id} '
                      f'{row_in_googlesheet} {old_nonconfirm_number_of_seats} '
                      f'{old_number_of_seats}'
    )
    keyboard.append([button_approve, button_cancel])
    reply_markup = InlineKeyboardMarkup(keyboard)

    payment = int(number_of_seats) * 1000
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f'К оплате {payment} руб\n'
             'Для оплаты вы можете считать qrcode или сделать перевод по номеру телефона:\n'
             '+70000000000 Имя Отчество Ф. Банк\n\n'
             'Вам необходимо сделать оплату в течении 15 мин, '
             'после нажать кнопку подтвердить или бронь будет отменена\n',
        reply_markup=reply_markup
    )

    context.user_data['payment'] = payment
    context.user_data['row_in_googlesheet'] = \
        dict_of_date_and_time[key][date][time][1]
    context.user_data[
        'new_nonconfirm_number_of_seats'] = new_nonconfirm_number_of_seats - int(
        number_of_seats)
    context.user_data['number_of_seats'] = number_of_seats

    return 'PAID'


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        'Ожидайте подтверждения перевода.\n'
        'Для ускорения процесса, '
        'можете отправить платеж @Tanya_domik в личные сообщения')

    row_in_googlesheet = context.user_data['row_in_googlesheet']
    new_nonconfirm_number_of_seats = context.user_data[
        'new_nonconfirm_number_of_seats']
    keyboard = []
    button_approve = InlineKeyboardButton(
        "Подтвердить",
        callback_data=f'Разрешить|'
                      f'{query.message.chat_id} {query.message.message_id} '
                      f'{row_in_googlesheet} {new_nonconfirm_number_of_seats}'
    )

    number_of_seats = context.user_data['number_of_seats']

    availibale_number_of_seats_now = googlesheets.check_seats(
        row_in_googlesheet, 4)
    nonconfirm_number_of_seats_now = googlesheets.check_seats(
        row_in_googlesheet, 5)

    old_number_of_seats = int(availibale_number_of_seats_now) + int(
        number_of_seats)
    old_nonconfirm_number_of_seats = int(nonconfirm_number_of_seats_now) - int(
        number_of_seats)
    button_cancel = InlineKeyboardButton(
        "Отклонить",
        callback_data=f'Отклонить|'
                      f'{query.message.chat_id} {query.message.message_id} '
                      f'{row_in_googlesheet} {old_nonconfirm_number_of_seats} '
                      f'{old_number_of_seats}'
    )
    keyboard.append([button_approve, button_cancel])
    reply_markup = InlineKeyboardMarkup(keyboard)

    user = context.user_data['user']
    payment = context.user_data['payment']

    await context.bot.send_message(
        chat_id=454342281,
        text=f'Пользователь {user.username} {user.full_name}\n'
             f'Запросил подтверждение брони на сумму {payment} руб\n',
        reply_markup=reply_markup
    )

    context.user_data.clear()

    return ConversationHandler.END


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    row_in_googlesheet = query.data.split('|')[1].split()[2]
    new_nonconfirm_number_of_seats = query.data.split('|')[1].split()[3]
    googlesheets.confirm(row_in_googlesheet, [new_nonconfirm_number_of_seats])

    username = query.message.text.split('\n')[0].split(' ')[1]
    full_name = query.message.text.split('\n')[0].split(' ')[2] + ' ' + \
                query.message.text.split('\n')[0].split(' ')[3]
    await query.edit_message_text(
        text=f'Пользователю {username} {full_name} подтверждена бронь'
    )

    chat_id = query.data.split('|')[1].split()[0]
    message_id = query.data.split('|')[1].split()[1]
    await context.bot.send_message(
        text='Ваша бронь подтверждена.\n'
             'Ждем вас на спектакле, по вопросам обращайтесь к следующим людям:\n'
             'Имя Фамилия @Tanya_domik +70000000000',
        chat_id=chat_id,
    )
    await context.bot.delete_message(
        chat_id=chat_id,
        message_id=message_id
    )


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    username = query.message.text.split('\n')[0].split(' ')[1]
    full_name = query.message.text.split('\n')[0].split(' ')[2] + ' ' + \
                query.message.text.split('\n')[0].split(' ')[3]
    await query.edit_message_text(
        text=f'Пользователю {username} {full_name} отклонена бронь'
    )

    chat_id = query.data.split('|')[1].split()[0]
    message_id = query.data.split('|')[1].split()[1]
    await context.bot.send_message(
        text='Ваша бронь отклонена.\n'
             'Для решения данного вопроса, напишите пожалуйста в ЛС или позвоните:\n'
             'Имя Фамилия @Tanya_domik +70000000000',
        chat_id=chat_id,
    )
    await context.bot.delete_message(
        chat_id=chat_id,
        message_id=message_id
    )

    row_in_googlesheet = query.data.split('|')[1].split()[2]
    old_nonconfirm_number_of_seats = query.data.split('|')[1].split()[3]
    old_number_of_seats = query.data.split('|')[1].split()[4]
    googlesheets.confirm(row_in_googlesheet,
                         [old_number_of_seats, old_nonconfirm_number_of_seats])


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
        reply_markup=reply_markup
    )
    return 'TIME'


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """

    :param update:
    :param context:
    :return:
    """
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        text='Вы выбрали отмену, для повтора используйте команду /choice'
    )

    if '|' in query.data:
        chat_id = query.data.split('|')[1].split()[0]
        message_id = query.data.split('|')[1].split()[1]
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )

        row_in_googlesheet = query.data.split('|')[1].split()[2]
        old_nonconfirm_number_of_seats = query.data.split('|')[1].split()[3]
        old_number_of_seats = query.data.split('|')[1].split()[4]
        googlesheets.confirm(row_in_googlesheet, [old_number_of_seats,
                                                  old_nonconfirm_number_of_seats])

    return ConversationHandler.END


def help_command():
    """


async def conversation_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Informs the user that the operation has timed out, calls :meth:`remove_reply_markup` and
    ends the conversation.
    :return:
        int: :attr:`telegram.ext.ConversationHandler.END`.
    """

    if context.user_data['STATE'] == 'ORDER':
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос'
        )

        chose_reserve_option = context.user_data['chose_reserve_option']

        # Номер строки для извлечения актуального числа доступных мест
        row_in_googlesheet = context.user_data['row_in_googlesheet']

        # Обновляем кол-во доступных мест
        availibale_number_of_seats_now = googlesheets.update_quality_of_seats(
            row_in_googlesheet, 4)
        nonconfirm_number_of_seats_now = googlesheets.update_quality_of_seats(
            row_in_googlesheet, 5)

        old_number_of_seats = int(
            availibale_number_of_seats_now) + int(
            chose_reserve_option.get('quality_of_children'))
        old_nonconfirm_number_of_seats = int(
            nonconfirm_number_of_seats_now) - int(
            chose_reserve_option.get('quality_of_children'))
        googlesheets.confirm(
            row_in_googlesheet,
            [old_number_of_seats, old_nonconfirm_number_of_seats]
        )
    else:
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос'
        )

    logging.info(": ".join(
        [
            'Для пользователя',
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
        ]
    ))
    logging.info(f'Обработчик завершился на этапе {context.user_data["STATE"]}')
    context.user_data.clear()

    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)

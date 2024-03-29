import logging

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from db import db_postgres
from settings.settings import SUPPORT_DATA, ADMIN_GROUP
from db.db_googlesheets import (
    load_ticket_data, load_list_show, load_special_ticket_price)
from api.googlesheets import get_quality_of_seats, write_data_for_reserve
from utilities.hlp_func import create_approve_and_reject_replay
from utilities.schemas.ticket import BaseTicket
from utilities.utl_func import send_message_to_admin

sub_hl_logger = logging.getLogger('bot.sub_hl')


async def request_phone_number(update, phone):
    await update.effective_chat.send_message(
        text=f'Возможно вы ошиблись, вы указали {phone} \n'
             'Напишите ваш номер телефона еще раз пожалуйста\n'
             'Идеальный пример из 10 цифр: 9991119090'
    )


async def send_and_del_message_to_remove_kb(update: Update):
    return await update.effective_chat.send_message(
        text='Загружаем данные',
        reply_markup=ReplyKeyboardRemove(),
        message_thread_id=update.effective_message.message_thread_id
    )


async def write_old_seat_info(
        user,
        event_id,
        chose_ticket
):
    # Обновляем кол-во доступных мест
    list_of_name_colum = [
        'qty_child_free_seat',
        'qty_child_nonconfirm_seat',
        'qty_adult_free_seat',
        'qty_adult_nonconfirm_seat'
    ]
    (qty_child_free_seat_now,
     qty_child_nonconfirm_seat_now,
     qty_adult_free_seat_now,
     qty_adult_nonconfirm_seat_now
     ) = get_quality_of_seats(event_id,
                              list_of_name_colum)

    qty_child_free_seat_new = int(
        qty_child_free_seat_now) + int(chose_ticket.quality_of_children)
    qty_child_nonconfirm_seat_new = int(
        qty_child_nonconfirm_seat_now) - int(chose_ticket.quality_of_children)
    qty_adult_free_seat_new = int(
        qty_adult_free_seat_now) + int(chose_ticket.quality_of_adult +
                                       chose_ticket.quality_of_add_adult)
    qty_adult_nonconfirm_seat_new = int(
        qty_adult_nonconfirm_seat_now) - int(chose_ticket.quality_of_adult +
                                             chose_ticket.quality_of_add_adult)

    numbers = [
        qty_child_free_seat_new,
        qty_child_nonconfirm_seat_new,
        qty_adult_free_seat_new,
        qty_adult_nonconfirm_seat_new
    ]

    try:
        write_data_for_reserve(event_id, numbers)
    except TimeoutError:
        sub_hl_logger.error(": ".join(
            [
                f'Для пользователя {user} отклонение в '
                f'авто-режиме не сработало',
                'event_id для обновления',
                event_id,
            ]
        ))


async def update_admin_info(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data.setdefault('admin', {})
    admin_info = context.bot_data['admin']
    if context.args:
        if context.args[0] == 'clean':
            context.bot_data['admin'] = {}
            await update.effective_chat.send_message(
                f'Зафиксировано: {context.bot_data['admin']}')
            return
        if len(context.args) == 4:
            admin_info['name'] = ' '.join(context.args[0:2])
            admin_info['username'] = context.args[2]
            admin_info['phone'] = context.args[3]
            admin_info['contacts'] = '\n'.join(
                [admin_info['name'],
                 'telegram ' + admin_info['username'],
                 'телефон ' + admin_info['phone']]
            )
            await update.effective_chat.send_message(
                f'Зафиксировано: {context.bot_data['admin']}')
        else:
            await update.effective_chat.send_message(
                f'Должно быть 4 параметра, а передано {len(context.args)}\n'
                'Формат: Имя Фамилия @username +79991234455')
    else:
        await update.effective_chat.send_message(
            'Не заданы параметры к команде\n'
            'Текущие контакты администратора:\n'
            f'{admin_info}')


async def update_ticket_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    context.bot_data['list_of_tickets'] = load_ticket_data()
    text = 'Билеты обновлены'
    await update.effective_chat.send_message(text)

    sub_hl_logger.info(text)
    for item in context.bot_data['list_of_tickets']:
        sub_hl_logger.info(f'{str(item)}')


async def update_special_ticket_price(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    context.bot_data['special_ticket_price'] = load_special_ticket_price()
    text = 'Индивидуальные стоимости обновлены'
    await update.effective_chat.send_message(text)

    sub_hl_logger.info(text)
    for item in context.bot_data['special_ticket_price']:
        sub_hl_logger.info(f'{str(item)}')


async def update_show_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    context.bot_data['dict_show_data'] = load_list_show()
    text = 'Репертуар обновлен'
    await update.effective_chat.send_message(text)

    sub_hl_logger.info(text)
    for item in context.bot_data['dict_show_data']:
        sub_hl_logger.info(f'{str(item)}')


async def remove_inline_button(update: Update):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    return query


async def update_bd_price(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    birthday_price = context.bot_data.setdefault('birthday_price', {})
    if context.args:
        if context.args[0] == 'clean':
            context.bot_data['birthday_price'] = {}
            await update.effective_chat.send_message(
                f'Зафиксировано: {context.bot_data['birthday_price']}')
            return
        if len(context.args) % 2 == 0:
            for i in range(0, len(context.args), 2):
                birthday_price[int(context.args[i])] = int(context.args[i+1])
            await update.effective_chat.send_message(
                f'Зафиксировано: {context.bot_data['birthday_price']}')
        else:
            await update.effective_chat.send_message(
                f'Должно быть четное кол-во параметров\n'
                f'Передано {len(context.args)}\n'
                'Формат: 1 15000 2 20000\n'
                'В качестве разделителей только пробелы')
    else:
        await update.effective_chat.send_message(
            'Не заданы параметры к команде\n'
            '1 - Спектакль (40 минут) + аренда комнаты под чаепитие (1 час)\n'
            '2 - Спектакль (40 минут) + аренда комнаты под чаепитие + серебряная дискотека (1 час)\n'
            '3 - Спектакль (40 минут) + Свободная игра с персонажами и фотосессия (20 минут)\n'
            'Текущие цены заказных мероприятий:\n'
            f'{birthday_price}')


async def get_chose_ticket_and_price(
        choose_event_info,
        context,
        key_option_for_reserve,
        reserve_user_data
):
    option = choose_event_info['option']
    flag_indiv_cost = choose_event_info['flag_indiv_cost']
    list_of_tickets = context.bot_data['list_of_tickets']
    chose_ticket: BaseTicket = list_of_tickets[0]
    price = chose_ticket.price
    for ticket in list_of_tickets:
        if ticket.base_ticket_id == key_option_for_reserve:
            chose_ticket = ticket
            price = chose_ticket.price

            key = chose_ticket.base_ticket_id
            if flag_indiv_cost:
                special_ticket_price: dict = load_special_ticket_price()
                try:
                    type_ticket_price = reserve_user_data['type_ticket_price']
                    price = special_ticket_price[option][type_ticket_price][key]
                except KeyError:
                    sub_hl_logger.error(
                        f'{key=} - данному билету не назначена индив. цена')
    return chose_ticket, price


async def get_emoji_and_options_for_event(event, name_column=None):
    text_emoji = ''
    option = ''
    if isinstance(event, dict):
        if event['flag_gift']:
            text_emoji += f'{SUPPORT_DATA['Подарок'][0]}'
            option = 'Подарок'
        if event['flag_christmas_tree']:
            text_emoji += f'{SUPPORT_DATA['Елка'][0]}'
            option = 'Ёлка'
        if event['flag_santa']:
            text_emoji += f'{SUPPORT_DATA['Дед'][0]}'
    if isinstance(event, list):
        if event[name_column['flag_gift']] == 'TRUE':
            text_emoji += f'{SUPPORT_DATA['Подарок'][0]}'
            option = 'Подарок'
        if event[name_column['flag_christmas_tree']] == 'TRUE':
            text_emoji += f'{SUPPORT_DATA['Елка'][0]}'
            option = 'Ёлка'
        if event[name_column['flag_santa']] == 'TRUE':
            text_emoji += f'{SUPPORT_DATA['Дед'][0]}'
    return option, text_emoji


async def send_breaf_message(update: Update):
    """
    Сообщение для опроса
    :param update: обновление от telegram
    :return: None
    """
    text_brief = (
        'Для подтверждения брони заполните, пожалуйста, анкету.\n'
        'Вход на мероприятие ведется по спискам.\n'
        '__________\n'
        '<i>Пожалуйста, не пишите лишней информации/дополнительных слов в '
        'сообщении.\n'
        'Вопросы будут приходить последовательно (их будет всего 3)</i>'
    )
    await update.effective_chat.send_message(
        text=text_brief,
    )
    await update.effective_chat.send_message(
        '<b>Напишите фамилию и имя (взрослого)</b>',
    )


async def send_approve_reject_message_to_admin(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    # Сообщение для администратора
    user = update.effective_user
    message_id = context.user_data['common_data']['message_id_buy_info']
    text = context.user_data['common_data']['text_for_notification_massage']
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Бронирование спектаклей', None))
    res = await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=f'#Бронирование\n'
             f'Квитанция пользователя @{user.username} {user.full_name}\n',
        message_thread_id=thread_id
    )
    await update.effective_message.forward(
        chat_id=ADMIN_GROUP,
        message_thread_id=thread_id
    )
    message_id_for_admin = res.message_id
    await send_message_to_admin(ADMIN_GROUP,
                                text,
                                message_id_for_admin,
                                context,
                                thread_id)
    reply_markup = create_approve_and_reject_replay(
        'reserve',
        update.effective_user.id,
        message_id,
    )
    chose_price = context.user_data['reserve_user_data']['chose_price']
    message = await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=f'Пользователь @{user.username} {user.full_name}\n'
             f'Запросил подтверждение брони на сумму {chose_price} руб\n'
             f'Ждем заполнения анкеты, если всё хорошо, то только после '
             f'нажимаем подтвердить',
        reply_markup=reply_markup,
        message_thread_id=thread_id
    )
    return message


async def remove_button_from_last_message(update, context):
    # Убираем у старого сообщения кнопки
    message_id = context.user_data['common_data']['message_id_buy_info']
    await context.bot.edit_message_reply_markup(
        chat_id=update.effective_chat.id,
        message_id=message_id
    )


async def update_ticket_status(context, new_status):
    ticket_id = context.user_data['reserve_admin_data']['payment_data']['ticket_id']
    await db_postgres.update_ticket(
        context.session,
        ticket_id,
        status=new_status,
    )

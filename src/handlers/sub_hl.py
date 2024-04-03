import logging
import re
import uuid

from telegram import Update, ReplyKeyboardRemove, InlineKeyboardMarkup, \
    InlineKeyboardButton
from telegram.ext import ContextTypes
from yookassa import Payment

import utilities as utl
from api.yookassa_connect import create_param_payment
from api.googlesheets import (get_quality_of_seats, write_data_for_reserve,
    write_client)
from db import db_postgres
from db.enum import TicketStatus
from db.db_googlesheets import (
    load_base_tickets, load_list_show, load_special_ticket_price,
    load_show_info)
from settings.settings import SUPPORT_DATA, ADMIN_GROUP, FILE_ID_RULES
from utilities.schemas.ticket import BaseTicketDTO

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
    context.bot_data['list_of_tickets'] = load_base_tickets()
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
    chose_ticket: BaseTicketDTO = list_of_tickets[0]
    price = chose_ticket.price
    for ticket in list_of_tickets:
        if ticket.base_ticket_id == key_option_for_reserve:
            chose_ticket = ticket
            price = chose_ticket.price

            key = chose_ticket.base_ticket_id
            if flag_indiv_cost:
                special_ticket_price: dict = context.bot_data['special_ticket_price']
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


async def send_breaf_message(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """
    Сообщение для опроса
    """
    text_brief = (
        'Для подтверждения брони заполните, пожалуйста, анкету.\n'
        'Вход на мероприятие ведется по спискам.\n'
        '__________\n'
        '<i>Пожалуйста, не пишите лишней информации/дополнительных слов в '
        'сообщении.\n'
        'Вопросы будут приходить последовательно (их будет всего 3)</i>'
    )
    keyboard = [utl.add_btn_back_and_cancel(postfix_for_cancel='res|',
                                        add_back_btn=False)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.effective_chat.send_message(
        text=text_brief,
        reply_markup=reply_markup
    )
    await update.effective_chat.send_message(
        '<b>Напишите фамилию и имя (взрослого)</b>',
    )
    context.user_data['reserve_user_data']['message_id'] = message.message_id


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
    await utl.send_message_to_admin(ADMIN_GROUP,
                                text,
                                message_id_for_admin,
                                context,
                                thread_id)
    reply_markup = utl.create_approve_and_reject_replay(
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


async def create_and_send_payment(update, context):
    message = await context.bot.send_message(
        text='Готовлю информацию об оплате...',
        chat_id=update.effective_chat.id,
    )
    key_option_for_reserve = context.user_data['reserve_user_data'][
        'key_option_for_reserve']
    reserve_user_data = context.user_data['reserve_user_data']
    choose_event_info = reserve_user_data['choose_event_info']
    dict_show_data = context.bot_data['dict_show_data']
    show_data = dict_show_data[choose_event_info['show_id']]
    name_show = show_data['full_name']
    date = choose_event_info['date_show']
    time = choose_event_info['time_show']
    chose_ticket, price = await get_chose_ticket_and_price(
        choose_event_info,
        context,
        key_option_for_reserve,
        reserve_user_data
    )
    email = await db_postgres.get_email(context.session,
                                        update.effective_user.id)
    idempotency_id = uuid.uuid4()
    payment = Payment.create(
        create_param_payment(
            price,
            f'Билет на спектакль {name_show} {date} в {time} {chose_ticket.name}',
            email,
            payment_method_type=context.config.yookassa.payment_method_type,
            chat_id=update.effective_chat.id,
            message_id=message.message_id,
        ),
        idempotency_id)
    keyboard = []
    button_payment = InlineKeyboardButton(
        'Оплатить',
        callback_data=f'payment|{payment.id}',
        url=payment.confirmation.confirmation_url
    )
    button_cancel = InlineKeyboardButton(
        'Отменить',
        callback_data=f'Отменить-res|'
                      f'{update.effective_chat.id} {message.message_id}'
    )
    keyboard.append([button_payment])
    keyboard.append([button_cancel])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text(
        text=f"""Бронь билета осуществляется по 100% оплате.
❗️ВОЗВРАТ ДЕНЕЖНЫХ СРЕДСТВ ИЛИ ПЕРЕНОС ВОЗМОЖЕН НЕ МЕНЕЕ ЧЕМ ЗА 24 ЧАСА❗️
❗️ПЕРЕНОС ВОЗМОЖЕН ТОЛЬКО 1 РАЗ❗️
Более подробно о правилах возврата в группе театра <a href="https://vk.com/baby_theater_domik?w=wall-202744340_3109">ссылка</a>

- Если вы согласны с правилами, то переходите к оплате:
  Нажмите кнопку <b>Оплатить</b>
  <i>Вы будете перенаправлены на платежный сервис Юкасса
  Способ оплаты - СБП</i>

- Если вам нужно подумать, нажмите кнопку <b>Отменить</b> под сообщением.
- Если вы уже сделали оплату, <b>отправьте квитанцию об оплате файлом или картинкой.</b>

__________
После оплаты необходимо:
Дождаться подтверждения""",
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    common_data = context.user_data['common_data']
    common_data['message_id_buy_info'] = message.message_id
    common_data['dict_of_shows'].clear()

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['chose_price'] = price
    reserve_user_data['dict_of_name_show'].clear()
    reserve_user_data['dict_of_name_show_flip'].clear()
    reserve_user_data['dict_of_date_show'].clear()
    reserve_user_data['back'].clear()
    payment_data = context.user_data['reserve_admin_data']['payment_data']
    event_id = payment_data['event_id']

    ticket = await db_postgres.create_ticket(
        context.session,
        base_ticket_id=chose_ticket.base_ticket_id,
        price=price,
        schedule_event_id=event_id,
        status=TicketStatus.CREATED,
        payment_id=payment.id,
        idempotency_id=idempotency_id,
    )
    payment_data['ticket_id'] = ticket.id


async def processing_successful_payment(update, context):
    user = context.user_data['user']
    reserve_user_data = context.user_data['reserve_user_data']
    client_data = reserve_user_data['client_data']
    text = reserve_user_data['original_input_text']
    chose_price = reserve_user_data['chose_price']
    payment_data = context.user_data['reserve_admin_data']['payment_data']
    chose_ticket = payment_data['chose_ticket']
    event_id = payment_data['event_id']
    record_id = write_client(
        client_data,
        event_id,
        chose_ticket,
        chose_price,
    )
    ticket_id = context.user_data['reserve_admin_data']['payment_data'][
        'ticket_id']

    await update_ticket_status(context, TicketStatus.PAID)

    message = await send_approve_reject_message_to_admin(update, context)
    context.user_data['common_data'][
        'message_id_for_admin'] = message.message_id

    people = await db_postgres.create_people(context.session,
                                             update.effective_user.id,
                                             client_data)
    await db_postgres.attach_user_and_people_to_ticket(context.session,
                                                       ticket_id,
                                                       update.effective_user.id,
                                                       people)
    text = '\n'.join([
        client_data['name_adult'],
        '+7' + client_data['phone'],
        text,
        ])
    message_id_for_admin = None
    if context.user_data.get('command', False) == 'reserve':
        message_id_for_admin = context.user_data['common_data'][
            'message_id_for_admin']

        text += '\n\n'
        text += f'#id{record_id}\n'

        await send_by_ticket_info(update, context)
    if context.user_data.get('command', False) == 'reserve_admin':
        text += '\n\n'
        text += f'event_id: {event_id}\n'
        event_info, name_column = load_show_info(int(event_id))
        text += event_info[name_column['name_show']]
        text += '\n' + event_info[name_column['date_show']]
        text += '\n' + event_info[name_column['time_show']]
        text += '\n' + chose_ticket.name + ' ' + str(chose_price) + 'руб'
        text += '\n\n'
        text += f'Добавлено: {update.effective_chat.full_name}\n'
        text += f'#id{record_id}'
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Бронирование спектаклей', None))
    await utl.send_message_to_admin(
        chat_id=ADMIN_GROUP,
        text=text,
        message_id=message_id_for_admin,
        context=context,
        thread_id=thread_id
    )
    sub_hl_logger.info(f'Для пользователя {user}')
    sub_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')


async def check_input_text(update, text_for_message):
    text = update.effective_message.text
    count = text.count('\n')
    result = re.findall(
        r'\w+ \d',
        text,
        flags=re.U | re.M
    )
    if len(result) <= count:
        sub_hl_logger.info('Не верный формат текста')
        keyboard = [utl.add_btn_back_and_cancel(postfix_for_cancel='res|',
                                            add_back_btn=False)]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_chat.send_message(
            text=text_for_message,
            reply_markup=reply_markup,
        )
        return False
    return True


async def send_by_ticket_info(update, context):
    await update.effective_chat.send_message(
        'Благодарим за ответы.\n\n'
        'Ожидайте подтверждение брони в течении 24 часов.\n'
        'Вам придет сообщение: "Ваша бронь подтверждена"\n'
        '<i>Если сообщение не поступит, напишите боту:</i>\n'
        '<code>Подтверждение не поступило</code>',
    )
    text = context.user_data['common_data']['text_for_notification_massage']
    text += (f'__________\n'
             'Задать вопросы можно в сообщениях группы\n'
             'https://vk.com/baby_theater_domik')
    message = await update.effective_chat.send_message(
        text=text,
    )
    await message.pin()

    await update.effective_chat.send_photo(photo=FILE_ID_RULES,
                                           caption='Правила театра')

import logging
import uuid
from typing import List, Union, Optional

from telegram import (
    Update,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, Message
)
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from yookassa import Payment

from api.yookassa_connect import create_param_payment
from api.googlesheets import write_client_reserve
from db import db_postgres, TheaterEvent
from db.enum import TicketStatus
from db.db_googlesheets import (
    load_base_tickets, load_special_ticket_price,
    load_schedule_events, load_theater_events, load_custom_made_format
)
from settings.settings import ADMIN_GROUP, FILE_ID_RULES, OFFER
from utilities import add_btn_back_and_cancel
from utilities.utl_func import (
    get_unique_months, get_full_name_event,
    filter_schedule_event_by_active, clean_replay_kb_and_send_typing_action,
    get_formatted_date_and_time_of_event,
    create_approve_and_reject_replay, set_back_context
)
from utilities.utl_googlesheets import update_ticket_db_and_gspread
from utilities.utl_kbd import (
    adjust_kbd, create_kbd_with_months, create_email_confirm_btn)

sub_hl_logger = logging.getLogger('bot.sub_hl')


async def request_phone_number(update, context):
    phone = update.effective_message.text
    keyboard = [add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
        add_back_btn=False)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.effective_chat.send_message(
        text=f'Возможно вы ошиблись, вы указали {phone} \n'
             'Напишите ваш номер телефона еще раз пожалуйста\n'
             'Идеальный пример из 10 цифр: 9991119090',
        reply_markup=reply_markup,
    )
    return message


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
                birthday_price[int(context.args[i])] = int(context.args[i + 1])
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


async def update_base_ticket_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    ticket_list = load_base_tickets(True)
    await db_postgres.update_base_tickets_from_googlesheets(
        context.session, ticket_list)

    text = 'Билеты обновлены'
    await update.effective_chat.send_message(text)

    await update.callback_query.answer()
    return 'updates'


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

    await update.callback_query.answer()
    return 'updates'


async def update_custom_made_format_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    custom_made_format_list = load_custom_made_format()
    await db_postgres.update_custom_made_format_from_googlesheets(
        context.session, custom_made_format_list)

    text = 'Форматы заказных мероприятий обновлены'
    await update.effective_chat.send_message(text)

    sub_hl_logger.info(text)

    await update.callback_query.answer()
    return 'updates'


async def update_theater_event_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    theater_event_list = load_theater_events()
    await db_postgres.update_theater_events_from_googlesheets(
        context.session, theater_event_list)

    text = 'Репертуар обновлен'
    await update.effective_chat.send_message(text)

    sub_hl_logger.info(text)

    await update.callback_query.answer()
    return 'updates'


async def update_schedule_event_data(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE):
    schedule_event_list = load_schedule_events(False)
    await db_postgres.update_schedule_events_from_googlesheets(
        context.session, schedule_event_list)

    text = 'Расписание обновлено'
    await update.effective_chat.send_message(text)

    sub_hl_logger.info(text)

    await update.callback_query.answer()
    return 'updates'


async def get_schedule_events_and_month_by_type_event(context, type_event_ids):
    schedule_events = await db_postgres.get_schedule_events_by_type_actual(
        context.session, type_event_ids)
    schedule_events = await filter_schedule_event_by_active(schedule_events)
    months = get_unique_months(schedule_events)
    return months, schedule_events


async def get_theater_and_schedule_events_by_month(context, schedule_events,
                                                   number_of_month_str):
    schedule_events_filter_by_month = []
    theatre_event_ids = []
    for event in schedule_events:
        if event.datetime_event.month == int(number_of_month_str):
            if event.theater_event_id not in theatre_event_ids:
                theatre_event_ids.append(event.theater_event_id)
            schedule_events_filter_by_month.append(event)
    theater_events: List[
        TheaterEvent] = await db_postgres.get_theater_events_by_ids(
        context.session,
        theatre_event_ids)
    theater_events = sorted(
        theater_events,
        key=lambda e: theatre_event_ids.index(e.id)
    )
    try:
        enum_theater_events = enumerate(theater_events, start=1)
    except TypeError:
        enum_theater_events = (1, theater_events),
    return tuple(enum_theater_events), schedule_events_filter_by_month


async def remove_button_from_last_message(update, context):
    message_id = context.user_data['common_data']['message_id_buy_info']
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=message_id
        )
    except BadRequest as e:
        sub_hl_logger.error(e)


async def create_and_send_payment(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    message = await context.bot.send_message(
        text='Готовлю информацию об оплате...',
        chat_id=chat_id,
    )

    reserve_user_data = context.user_data['reserve_user_data']
    chose_price = reserve_user_data['chose_price']
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    client_data = reserve_user_data['client_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    theater_event_id = reserve_user_data['choose_theater_event_id']
    command = context.user_data['command']

    schedule_event = await db_postgres.get_schedule_event(
        context.session, schedule_event_id)
    theater_event = await db_postgres.get_theater_event(
        context.session, theater_event_id)
    date_event, time_event = await get_formatted_date_and_time_of_event(
        schedule_event)
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)
    full_name = get_full_name_event(theater_event.name,
                                    theater_event.flag_premier,
                                    theater_event.min_age_child,
                                    theater_event.max_age_child,
                                    theater_event.duration)

    email = await db_postgres.get_email(context.session,
                                        update.effective_user.id)

    people_ids = await db_postgres.create_people(context.session,
                                                 update.effective_user.id,
                                                 client_data)

    studio = context.bot_data['studio']
    choose_schedule_event_ids = [schedule_event_id]
    if command == 'studio' and chose_base_ticket.flag_season_ticket:
        for v in studio['Театральный интенсив']:
            if schedule_event_id in v:
                choose_schedule_event_ids = v

    ticket_ids = []
    for event_id in choose_schedule_event_ids:
        ticket = await db_postgres.create_ticket(
            context.session,
            base_ticket_id=chose_base_ticket.base_ticket_id,
            price=chose_price,
            schedule_event_id=event_id,
            status=TicketStatus.CREATED,
        )
        ticket_ids.append(ticket.id)

        await db_postgres.attach_user_and_people_to_ticket(context.session,
                                                           ticket.id,
                                                           update.effective_user.id,
                                                           people_ids)

    reserve_user_data['ticket_ids'] = ticket_ids
    reserve_user_data['choose_schedule_event_ids'] = choose_schedule_event_ids

    # TODO Заменить на запись в другой лист
    write_client_reserve(context, chat_id, chose_base_ticket)

    ticket_name_for_desc = chose_base_ticket.name.split(' | ')[0]
    max_len_decs = 128
    len_desc_without_name = len(
        f'Билет на мероприятие  {date_event} в {time_event}' +
        ticket_name_for_desc
    )
    len_for_name = max_len_decs - len_desc_without_name
    full_name_for_desc = full_name[:len_for_name]
    description = f'Билет на мероприятие {full_name_for_desc} {date_event} в {time_event}'
    param = create_param_payment(
                price=chose_price,
                description=' '.join([description, ticket_name_for_desc]),
                email=email,
                payment_method_type=context.config.yookassa.payment_method_type,
                chat_id=update.effective_chat.id,
                message_id=message.message_id,
                ticket_ids='|'.join(str(v) for v in ticket_ids),
                choose_schedule_event_ids='|'.join(
                    str(v) for v in choose_schedule_event_ids),
                command=command
            )
    idempotency_id = uuid.uuid4()
    try:
        payment = Payment.create(param, idempotency_id)
    except ValueError as e:
        sub_hl_logger.error(e)
        sub_hl_logger.error(param)
        if e == 'Invalid email value type':
            sub_hl_logger.error(email)
            await update.effective_chat.send_message(
                f'Платежная система не приняла почту: {email}\n\n'
                f'Попробуйте еще раз и/или укажите другую почту.'
            )
            text, reply_markup = await send_request_email(update, context)
            state = 'EMAIL'

            await set_back_context(context, state, text, reply_markup)
            context.user_data['STATE'] = state
            return state
        raise ValueError('Проблема с созданием платежа')

    await db_postgres.update_ticket(
        context.session,
        ticket_ids[0],
        payment_id=payment.id,
        idempotency_id=idempotency_id,
    )

    keyboard = []
    button_payment = InlineKeyboardButton(
        'Оплатить',
        callback_data=f'payment|{payment.id}',
        url=payment.confirmation.confirmation_url
    )
    button_cancel = add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
        add_back_btn=False)
    keyboard.append([button_payment])
    keyboard.append(button_cancel)
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
    reserve_user_data['flag_send_ticket_info'] = True


async def processing_successful_payment(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text('Платеж успешно обработан')

    reserve_user_data = context.user_data['reserve_user_data']
    command = context.user_data['command']
    ticket_ids = reserve_user_data['ticket_ids']
    ticket = await db_postgres.get_ticket(context.session, ticket_ids[0])
    if ticket.status == TicketStatus.CREATED:
        user = context.user_data['user']
        client_data = reserve_user_data['client_data']
        original_child_text = reserve_user_data['original_child_text']
        chose_price = reserve_user_data['chose_price']
        chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
        schedule_event_id = reserve_user_data['choose_schedule_event_id']
        theater_event_id = reserve_user_data['choose_theater_event_id']

        schedule_event = await db_postgres.get_schedule_event(
            context.session, schedule_event_id)
        theater_event = await db_postgres.get_theater_event(
            context.session, theater_event_id)
        chose_base_ticket = await db_postgres.get_base_ticket(
            context.session, chose_base_ticket_id)

        event_id = schedule_event_id

        if '_admin' in command:
            new_ticket_status = TicketStatus.APPROVED
        else:
            new_ticket_status = TicketStatus.PAID
        for ticket_id in ticket_ids:
            await update_ticket_db_and_gspread(context,
                                               ticket_id,
                                               status=new_ticket_status)

        text = f'#Бронирование\n'
        text += f'Платеж успешно обработан\n'
        text += f'Покупатель: @{user.username} {user.full_name}'
        text += '\n\n'

        text += f'#event_id <code>{event_id}</code>\n'
        date_event, time_event = await get_formatted_date_and_time_of_event(
            schedule_event)
        text += theater_event.name
        text += '\n' + date_event
        text += ' в ' + time_event
        text += '\n' + chose_base_ticket.name + ' ' + str(chose_price) + 'руб'
        text += '\n'

        text += '\n'.join([
            client_data['name_adult'],
            '+7' + client_data['phone'],
            original_child_text,
            ])
        text += '\n\n'

        if '_admin' in command:
            text += f'Добавлено: {update.effective_chat.full_name}\n\n'

        for ticket_id in ticket_ids:
            text += f'#ticket_id <code>{ticket_id}</code>'

        if 'migration' in command:
            ticket_id = context.user_data['reserve_admin_data']['ticket_id']
            text += f'\nПеренесен с #ticket_id <code>{ticket_id}</code>'

        message_id_for_admin, reply_markup = await create_reply_markup_and_msg_id_for_admin(
            update, context)

        thread_id = await get_thread_id(context, command, schedule_event)
        await send_message_to_admin(
            chat_id=ADMIN_GROUP,
            text=text,
            message_id=message_id_for_admin,
            context=context,
            thread_id=thread_id,
            reply_markup=reply_markup
        )
        sub_hl_logger.info(f'Для пользователя {user}')
        sub_hl_logger.info(
            f'Обработчик завершился на этапе {context.user_data['STATE']}')

    elif ticket.status == TicketStatus.PAID:
        sub_hl_logger.info(
            f'Проверь, что по билету {ticket_ids=} прикреплены люди')

    check_send = reserve_user_data.get('flag_send_ticket_info', False)
    if (command == 'reserve' or command == 'studio') and check_send:
        await send_by_ticket_info(update, context)


async def create_reply_markup_and_msg_id_for_admin(update, context):
    command = context.user_data['command']
    reply_markup = None
    message_id_for_admin = None
    if command == 'reserve' or command == 'studio':
        message = await forward_message_to_admin(update, context)

        message_id = context.user_data['common_data']['message_id_buy_info']

        reply_markup = create_approve_and_reject_replay(
            'reserve',
            update.effective_user.id,
            message_id,
        )
        context.user_data['common_data'][
            'message_id_for_admin'] = message.message_id
        message_id_for_admin = message.message_id
    return message_id_for_admin, reply_markup


async def get_thread_id(context, command, schedule_event):
    thread_id = None
    if (
            command == 'reserve' or
            ('_admin' in command and schedule_event.type_event_id in [1, 2])
    ):
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Бронирования спектаклей', None))
        # TODO Переписать ключи словаря с топиками на использование enum
        if not thread_id:
            thread_id = (context.bot_data['dict_topics_name']
                         .get('Бронирование спектаклей', None))
    if (
            command == 'studio' or
            ('_admin' in command and schedule_event.type_event_id in [12])
    ):
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Бронирования студия', None))
    return thread_id


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
    keyboard = [add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
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


async def forward_message_to_admin(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
) -> Message:
    ticket_ids = context.user_data['reserve_user_data']['ticket_ids']
    ticket_id = ticket_ids[0]
    command = context.user_data['command']
    thread_id = None
    if command == 'reserve':
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Бронирования спектаклей', None))
        # TODO Переписать ключи словаря с топиками на использование enum
        if not thread_id:
            thread_id = (context.bot_data['dict_topics_name']
                         .get('Бронирование спектаклей', None))
    if command == 'studio':
        thread_id = (context.bot_data['dict_topics_name']
                     .get('Бронирования студия', None))
    message = await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=f'#Бронирование\n'
             f'Квитанция по билету: <code>{ticket_id}</code>\n',
        message_thread_id=thread_id
    )
    await update.effective_message.forward(
        chat_id=ADMIN_GROUP,
        message_thread_id=thread_id
    )

    return message


async def send_by_ticket_info(update, context):
    await update.effective_chat.send_message(
        'Благодарим за ответы.\n\n'
        'Ожидайте подтверждение брони в течении 24 часов.\n'
        'Вам придет сообщение: "<b>Ваша бронь подтверждена</b>"\n\n'
        '<i>Если сообщение не поступит, напишите боту:</i>\n'
        '<code>Подтверждение не поступило</code>',
    )
    ticket_ids = context.user_data['reserve_user_data']['ticket_ids']
    ticket_id = ticket_ids[0]
    text = f'<b>Номер вашего билета <code>{ticket_id}</code></b>\n\n'
    text += context.user_data['common_data']['text_for_notification_massage']
    text += (f'__________\n'
             'Задать вопросы можно в сообщениях группы\n'
             'https://vk.com/baby_theater_domik')
    message = await update.effective_chat.send_message(
        text=text,
    )
    await message.pin()

    command = context.user_data['command']
    if command == 'reserve':
        await update.effective_chat.send_photo(photo=FILE_ID_RULES,
                                               caption='Правила театра')

    context.user_data['reserve_user_data']['flag_send_ticket_info'] = False


async def send_request_email(update: Update, context):
    text = 'Напишите email, на него вам будет направлен чек после оплаты\n\n'
    email = await db_postgres.get_email(context.session,
                                        update.effective_user.id)
    back_and_cancel_btn = add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='TICKET')

    email_confirm_btn, text = await create_email_confirm_btn(text, email)

    if email_confirm_btn:
        keyboard = [email_confirm_btn, back_and_cancel_btn]
    else:
        keyboard = [back_and_cancel_btn]

    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        message = await update.callback_query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
    except AttributeError as e:
        sub_hl_logger.error(e)

        if context.user_data['STATE'] == 'TICKET':
            message = await update.effective_message.edit_text(
                text=text,
                reply_markup=reply_markup
            )
        if context.user_data['STATE'] == 'OFFER':
            message = await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup
            )

    context.user_data['reserve_user_data']['message_id'] = message.message_id
    return text, reply_markup


async def send_agreement(update, context):
    query = update.callback_query
    text = f'<i>{OFFER}</i>'
    keyboard = [add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        postfix_for_back='TICKET')]
    inline_markup = InlineKeyboardMarkup(keyboard)
    inline_message = await query.edit_message_text(
        text=text,
        reply_markup=inline_markup
    )
    reply_markup = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton('Принимаю')]],
        one_time_keyboard=True,
        resize_keyboard=True
    )
    reply_message = await update.effective_chat.send_message(
        text='Если вы согласны нажмите внизу экрана\n'
             '⬇️⬇️⬇️️<b>Принимаю</b>⬇️⬇️⬇️️',
        reply_markup=reply_markup
    )

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['message_id'] = inline_message.message_id
    reserve_user_data['accept_message_id'] = reply_message.message_id

    return text, inline_markup


async def send_filtered_schedule_events(update, context, type_event_ids):
    months, schedule_events = await get_schedule_events_and_month_by_type_event(
        context, type_event_ids)
    message = await clean_replay_kb_and_send_typing_action(update)
    text = 'Выберите месяц'
    keyboard = await create_kbd_with_months(months)
    keyboard = adjust_kbd(keyboard, 1)
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'],
        add_back_btn=False
    ))
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=message.message_id
    )
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.effective_message.message_thread_id
    )
    schedule_event_ids = [item.id for item in schedule_events]
    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['schedule_event_ids'] = schedule_event_ids
    return reply_markup, text


async def send_message_about_list_waiting(update: Update, context):
    reserve_user_data = context.user_data['reserve_user_data']
    command = context.user_data.get('command', None)

    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    schedule_event = await db_postgres.get_schedule_event(
        context.session, schedule_event_id)

    text = reserve_user_data['text_select_event']
    if command == 'reserve':
        text += ('К сожалению места уже забронировали и свободных мест\n'
                 f' Осталось: '
                 f'<i>{schedule_event.qty_adult_free_seat} взр</i>'
                 f' | '
                 f'<i>{schedule_event.qty_child_free_seat} дет</i>'
                 f'\n\n')
    text += ('⬇️Нажмите на одну из двух кнопок ниже, '
             'чтобы выбрать другое время '
             'или записаться в лист ожидания на эту дату и время⬇️')
    reply_keyboard = [
        ['Выбрать другое время'],
        ['Записаться в лист ожидания'],
    ]
    reply_markup = ReplyKeyboardMarkup(
        reply_keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )


async def send_info_about_individual_ticket(update, context):
    query = update.callback_query
    text = ('Для оформления данного варианта обратитесь к Администратору:\n'
            f'{context.bot_data['admin']['contacts']}')
    await query.edit_message_text(
        text=text
    )
    sub_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')
    context.user_data['common_data'].clear()
    context.user_data['reserve_user_data'].clear()


async def send_message_to_admin(
        chat_id: Union[int, str],
        text: str,
        message_id: Optional[Union[int, str]],
        context: ContextTypes.DEFAULT_TYPE,
        thread_id: Optional[int],
        reply_markup=None,
):
    try:
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=message_id,
            message_thread_id=thread_id,
            reply_markup=reply_markup,
        )
    except BadRequest as e:
        sub_hl_logger.error(e)
        sub_hl_logger.info(": ".join(
            [
                'Для пользователя',
                str(context.user_data['user'].id),
                str(context.user_data['user'].full_name),
                'сообщение на которое нужно ответить, удалено'
            ],
        ))
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
            reply_markup=reply_markup,
        )
    return message


async def send_approve_reject_message_to_admin_in_webhook(
        context,
        chat_id,
        message_id,
        ticket_ids,
        thread_id,
        callback_name
):
    user_data = context.application.user_data.get(int(chat_id))
    user = user_data['user']
    reserve_user_data = user_data['reserve_user_data']
    client_data = reserve_user_data['client_data']
    original_child_text = reserve_user_data['original_child_text']
    event_id = reserve_user_data['choose_schedule_event_id']

    text = f'#Бронирование\n'
    text += f'Платеж успешно обработан\n'
    text += f'Покупатель: @{user.username} {user.full_name}'
    text += '\n\n'

    text += f'#event_id <code>{event_id}</code>\n'
    text += user_data['common_data']['text_for_notification_massage']
    text += '\n'

    text += '\n'.join([
        client_data['name_adult'],
        '+7' + client_data['phone'],
        original_child_text,
        ])
    text += '\n\n'
    for ticket_id in ticket_ids:
        text += f'#ticket_id <code>{ticket_id}</code>'

    reply_markup = create_approve_and_reject_replay(
        callback_name,
        chat_id,
        message_id,
    )
    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=text,
        message_thread_id=thread_id,
        reply_markup=reply_markup,
    )

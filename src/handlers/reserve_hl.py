import logging
import pprint
from datetime import datetime

from telegram.ext import ContextTypes, ConversationHandler, TypeHandler
from telegram import (
    Update,
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
)
from telegram.constants import ChatType, ChatAction

from db import db_postgres
from handlers import init_conv_hl_dialog, check_user_db
from handlers.sub_hl import (
    request_phone_number,
    send_and_del_message_to_remove_kb, write_old_seat_info,
    get_chose_ticket_and_price, get_emoji_and_options_for_event,
    send_breaf_message, remove_button_from_last_message,
    create_and_send_payment, processing_successful_payment, check_input_text,
)
from db.db_googlesheets import (
    load_clients_data, load_show_data, load_list_show,
    load_special_ticket_price,
)
from api.googlesheets import (
    write_data_for_reserve, write_client_list_waiting, get_quality_of_seats,
)
from utilities.utl_func import (
    extract_phone_number_from_text, add_btn_back_and_cancel,
    set_back_context, get_back_context, check_email,
    get_month_numbers, check_phone_number,
    create_replay_markup_for_list_of_shows,
    enum_current_show_by_month, add_text_of_show_and_numerate
)
from settings.settings import (
    ADMIN_GROUP, COMMAND_DICT, SUPPORT_DATA, RESERVE_TIMEOUT, OFFER,
    DICT_OF_EMOJI_FOR_BUTTON, DICT_CONVERT_MONTH_NUMBER_TO_STR
)

reserve_hl_logger = logging.getLogger('bot.reserve_hl')


async def choice_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю список месяцев.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state MONTH
    """
    query = update.callback_query
    if context.user_data.get('command', False) and query:
        state = context.user_data['STATE']
        await query.answer()
        await query.delete_message()
    else:
        state = init_conv_hl_dialog(update, context)
        await check_user_db(update, context)

    user = context.user_data.setdefault('user', update.effective_user)

    if update.effective_message.is_topic_message:
        thread_id = None
        if context.user_data['command'] == 'list':
            thread_id = (context.bot_data['dict_topics_name']
                         .get('Списки на показы', None))
        if context.user_data['command'] == 'list_wait':
            thread_id = (context.bot_data['dict_topics_name']
                         .get('Лист ожидания', None))
        if update.effective_message.message_thread_id != thread_id:
            await update.effective_message.reply_text(
                'Выполните команду в правильном топике')
            return ConversationHandler.END

    reserve_hl_logger.info(f'Пользователь начал выбор месяца: {user}')

    message = await send_and_del_message_to_remove_kb(update)
    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)

    try:
        (
            dict_of_shows,
            dict_of_name_show,
            dict_of_name_show_flip,
            dict_of_date_show
        ) = load_show_data()
    except ConnectionError or ValueError:
        reserve_hl_logger.info(
            f'Для пользователя {user}')
        reserve_hl_logger.info(
            f'Обработчик завершился на этапе {state}')
        await update.effective_chat.send_message(
            text='К сожалению я сегодня на техническом обслуживании\n'
                 'Но вы можете забронировать место связавшись напрямую с '
                 'Администратором:\n'
                 f'{context.bot_data['admin']['contacts']}',
            message_thread_id=update.effective_message.message_thread_id
        )
        return ConversationHandler.END
    except TimeoutError:
        reserve_hl_logger.info(
            f'Для пользователя {user}')
        reserve_hl_logger.info(
            f'Обработчик завершился на этапе {state}')
        await update.effective_chat.send_message(
            text='Произошел разрыв соединения, попробуйте еще раз\n'
                 'Если проблема повторится вы можете оформить заявку '
                 'напрямую у Администратора:\n'
                 f'{context.bot_data['admin']['contacts']}',
            message_thread_id=update.effective_message.message_thread_id
        )
        return ConversationHandler.END

    list_of_months = get_month_numbers(dict_of_date_show)

    keyboard = []

    for item in list_of_months:
        button_tmp = InlineKeyboardButton(
            text=DICT_CONVERT_MONTH_NUMBER_TO_STR[item],
            callback_data=str(item)
        )
        keyboard.append([button_tmp])

    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel='res',
        add_back_btn=False
    ))
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите месяц'

    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=message.message_id
    )
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.effective_message.message_thread_id
    )

    context.user_data['common_data'][
        'dict_of_shows'] = dict_of_shows
    context.user_data['reserve_user_data'][
        'dict_of_name_show'] = dict_of_name_show
    context.user_data['reserve_user_data'][
        'dict_of_name_show_flip'] = dict_of_name_show_flip
    context.user_data['reserve_user_data'][
        'dict_of_date_show'] = dict_of_date_show

    state = 'MONTH'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_show_or_date(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Функция отправляет пользователю список спектаклей с датами.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state DATE
    """
    query = update.callback_query
    await query.answer()
    await query.delete_message()

    user = context.user_data['user']

    reserve_hl_logger.info(f'Пользователь начал выбор спектакля:'
                           f' {user}')

    reserve_user_data = context.user_data['reserve_user_data']
    dict_of_name_show = reserve_user_data['dict_of_name_show']
    dict_of_date_show = reserve_user_data['dict_of_date_show']

    number_of_month_str = query.data
    filter_show_id = enum_current_show_by_month(dict_of_date_show,
                                                number_of_month_str)

    dict_show_data = context.bot_data['dict_show_data']
    text_age_note = 'Пожалуйста, обратите внимание на рекомендованный возраст\n'
    if number_of_month_str == '12':
        text = '<b>Выберите спектакль\n</b>' + text_age_note
        text = add_text_of_show_and_numerate(text,
                                             dict_of_name_show,
                                             filter_show_id,
                                             dict_show_data)
        keyboard = []
        for key, item in dict_of_name_show.items():
            if item in filter_show_id.keys():
                button_tmp = InlineKeyboardButton(
                    text=f'{DICT_OF_EMOJI_FOR_BUTTON[filter_show_id[item]]}',
                    callback_data=str(item)
                )
                if len(keyboard) == 0:
                    keyboard.append([button_tmp])
                else:
                    keyboard[0].append(button_tmp)

        keyboard.append(add_btn_back_and_cancel(
            postfix_for_cancel='res',
            add_back_btn=True,
            postfix_for_back='MONTH'
        ))
        reply_markup = InlineKeyboardMarkup(keyboard)

        state = 'SHOW'
        set_back_context(context, state, text, reply_markup)
    else:
        text = '<b>Выберите спектакль и дату\n</b>' + text_age_note
        text = add_text_of_show_and_numerate(text,
                                             dict_of_name_show,
                                             filter_show_id,
                                             dict_show_data)
        reply_markup = create_replay_markup_for_list_of_shows(
            dict_of_date_show,
            add_cancel_btn=True,
            postfix_for_cancel='res',
            postfix_for_back='MONTH',
            number_of_month=number_of_month_str,
        )
        if context.user_data['command'] == 'list_wait':
            state = 'LIST_WAIT'
        else:
            state = 'DATE'
        set_back_context(context, state, text, reply_markup)

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
        )
    else:
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            message_thread_id=update.callback_query.message.message_thread_id,
        )

    reserve_user_data['number_of_month_str'] = number_of_month_str

    context.user_data['STATE'] = state
    return state


async def choice_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю варианты
    времени и кол-во свободных мест

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state TIME
    """
    query = update.callback_query
    await query.answer()

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    number_of_show = int(query.data)
    reserve_user_data = context.user_data['reserve_user_data']
    dict_of_date_show = reserve_user_data['dict_of_date_show']
    dict_of_name_show_flip = reserve_user_data['dict_of_name_show_flip']
    number_of_month_str = reserve_user_data['number_of_month_str']
    dict_of_shows = context.user_data['common_data']['dict_of_shows']
    name_of_show = dict_of_name_show_flip[number_of_show]

    reply_markup = create_replay_markup_for_list_of_shows(
        dict_of_date_show,
        ver=3,
        add_cancel_btn=True,
        postfix_for_cancel='res',
        postfix_for_back='SHOW',
        number_of_month=number_of_month_str,
        number_of_show=number_of_show,
        dict_of_events_show=dict_of_shows
    )

    flag_gift = False
    flag_christmas_tree = False
    flag_santa = False

    for event in dict_of_shows.values():
        if name_of_show == event['name_show']:
            if event['flag_gift']:
                flag_gift = True
            if event['flag_christmas_tree']:
                flag_christmas_tree = True
            if event['flag_santa']:
                flag_santa = True

    text = (f'Вы выбрали спектакль:\n'
            f'<b>{name_of_show}</b>\n'
            f'<i>Выберите удобную дату</i>\n\n')
    if flag_gift:
        text += f'{SUPPORT_DATA['Подарок'][0]} - {SUPPORT_DATA['Подарок'][1]}\n'
    if flag_christmas_tree:
        text += f'{SUPPORT_DATA['Елка'][0]} - {SUPPORT_DATA['Елка'][1]}\n'
    if flag_santa:
        text += f'{SUPPORT_DATA['Дед'][0]} - {SUPPORT_DATA['Дед'][1]}\n'

    photo = (
        context.bot_data
        .get('afisha', {})
        .get(int(number_of_month_str), False)
    )
    if update.effective_chat.type == ChatType.PRIVATE and photo:
        await query.edit_message_caption(
            caption=text,
            reply_markup=reply_markup,
        )
    else:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
        )

    if context.user_data['command'] == 'list_wait':
        state = 'LIST_WAIT'
    else:
        state = 'DATE'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю варианты
    времени и кол-во свободных мест

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state TIME
    """
    query = update.callback_query
    await query.answer()
    await query.delete_message()

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    key_of_name_show, date_show = query.data.split(' | ')
    key_of_name_show = int(key_of_name_show)

    dict_of_shows: dict = context.user_data['common_data']['dict_of_shows']
    reserve_user_data = context.user_data['reserve_user_data']
    dict_of_name_show_flip = reserve_user_data['dict_of_name_show_flip']
    name_show: str = dict_of_name_show_flip[key_of_name_show]

    keyboard = []

    # Определение кнопок для inline клавиатуры с исключением вариантов где
    # свободных мест уже не осталось
    for key, item in dict_of_shows.items():
        if item['name_show'] == name_show and item['date_show'] == date_show:
            show_id = item['show_id']
            time = item['time_show']
            qty_child = item['qty_child_free_seat']
            qty_adult = item['qty_adult_free_seat']
            if int(qty_child) < 0:
                qty_child = 0
            if int(qty_adult) < 0:
                qty_adult = 0
            text = time
            text_emoji = ''
            if item['flag_gift']:
                text_emoji += f'{SUPPORT_DATA['Подарок'][0]}'
            if item['flag_christmas_tree']:
                text_emoji += f'{SUPPORT_DATA['Елка'][0]}'
            if item['flag_santa']:
                text_emoji += f'{SUPPORT_DATA['Дед'][0]}'
            text += text_emoji
            # TODO вместо key использовать event_id, и кол-во мест на
            #  следующих этапах доставать из контекста по event_id вместо
            #  callback_data
            text += ' | ' + str(qty_child) + ' дет'
            text += ' | ' + str(qty_adult) + ' взр'

            callback_data = time
            callback_data += ' | ' + str(key)
            callback_data += ' | ' + str(qty_child)
            callback_data += ' | ' + str(qty_adult)
            button_tmp = InlineKeyboardButton(
                text=text,
                callback_data=callback_data
            )
            keyboard.append([button_tmp])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='res',
                                            postfix_for_back='DATE'))
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (f'Вы выбрали:\n'
            f'<b>{name_show}\n'
            f'{date_show}</b>\n\n')
    if update.effective_chat.id == ADMIN_GROUP:
        # Отправка сообщения в админский чат
        text += 'Выберите время'
    else:
        # Отправка сообщения пользователю
        text += ('<b>Выберите удобное время</b>\n\n'
                 '<i>Вы также можете выбрать вариант с 0 кол-вом мест '
                 'для записи в лист ожидания на данное время</i>\n\n'
                 'Кол-во свободных мест:\n'
                 '⬇️<i>Время</i> | <i>Детских</i> | <i>Взрослых</i>⬇️')

    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        message_thread_id=update.callback_query.message.message_thread_id
    )

    choose_event_info = reserve_user_data['choose_event_info']
    choose_event_info['show_id'] = int(show_id)
    choose_event_info['name_show'] = name_show
    choose_event_info['date_show'] = date_show

    if context.user_data.get('command', False) == 'list':
        state = 'LIST'
    else:
        state = 'TIME'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_option_of_reserve(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю,
    дате, времени и варианты бронирования

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state ORDER
    """
    query = update.callback_query
    await query.answer()
    await query.edit_message_text('Загружаю данные по билетам...')

    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    time, event_id, qty_child, qty_adult = query.data.split(' | ')
    reserve_user_data = context.user_data['reserve_user_data']
    choose_event_info = reserve_user_data['choose_event_info']
    choose_event_info['time_show'] = time

    payment_data = context.user_data['reserve_admin_data']['payment_data']
    reserve_hl_logger.info(f'Бронирование: {payment_data}')
    payment_data['event_id'] = event_id

    dict_of_shows = context.user_data['common_data']['dict_of_shows']
    event = dict_of_shows[int(event_id)]
    choose_event_info['event_id'] = int(event_id)
    option, text_emoji = await get_emoji_and_options_for_event(event)

    choose_event_info['text_emoji'] = text_emoji

    name_show = choose_event_info['name_show']
    date = choose_event_info['date_show']
    text_select_show = (f'Вы выбрали спектакль:\n'
                        f'<b>{name_show}\n'
                        f'{date}\n'
                        f'{time}</b>\n'
                        f'{text_emoji}\n')
    if ((int(qty_child) == 0 or int(qty_adult) == 0) and
            context.user_data.get('command', False) == 'reserve'):
        await query.edit_message_text(
            'Готовлю информацию для записи в лист ожидания...')
        reserve_hl_logger.info('Мест нет')
        reserve_hl_logger.info(f'qty_child: {qty_child}')
        reserve_hl_logger.info(f'qty_adult: {qty_adult}')

        text = text_select_show
        await query.edit_message_text(
            text=text,
        )

        reserve_user_data['event_info_for_list_waiting'] = text
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
            text='⬇️Нажмите на одну из двух кнопок ниже, '
                 'чтобы выбрать другое время '
                 'или записаться в лист ожидания на эту дату и время⬇️',
            reply_markup=reply_markup
        )
        state = 'CHOOSING'
        context.user_data['STATE'] = state
        return state

    await query.edit_message_text(
        'Проверяю не изменилось ли кол-во свободных мест...')
    list_of_name_colum = ['qty_child_free_seat',
                          'qty_adult_free_seat']
    (qty_child_free_seat_now,
     qty_adult_free_seat_now
     ) = get_quality_of_seats(event_id,
                              list_of_name_colum)
    await update.effective_chat.send_action(ChatAction.TYPING)

    reserve_hl_logger.info(f'Загрузили данные о доступных билетах')
    reserve_hl_logger.info(f'Свободных детских: {qty_child_free_seat_now}')
    reserve_hl_logger.info(f'Свободных взрослых: {qty_adult_free_seat_now}')

    # TODO Загружать список спектаклей из контекста bot_data и сменить
    #  название dict_of_show на другое
    await query.edit_message_text('Формирую список доступных билетов...')
    dict_of_shows: dict = load_list_show()
    special_ticket_price: dict = load_special_ticket_price()
    show_id = choose_event_info['show_id']
    flag_indiv_cost = False
    for key, item in dict_of_shows.items():
        if key == show_id:
            flag_indiv_cost = item['flag_indiv_cost']
            price_type = item['price_type']
            choose_event_info['flag_indiv_cost'] = flag_indiv_cost
            choose_event_info['price_type'] = price_type
            if not option:
                if price_type == 'Индивид':
                    option = key
                else:
                    option = price_type
    choose_event_info['option'] = option

    list_of_tickets = context.bot_data['list_of_tickets']
    text = (f'Кол-во свободных мест: '
            f'<i>{qty_adult_free_seat_now} взр | '
            f'{qty_child_free_seat_now} дет</i>\n')
    text = text_select_show + text
    text += '<b>Выберите подходящий вариант бронирования:</b>\n'

    date_now = datetime.now().date()
    date_tmp = date.split()[0] + f'.{date_now.year}'
    date_for_price: datetime = datetime.strptime(date_tmp, f'%d.%m.%Y')

    keyboard = []
    list_btn_of_numbers = []
    flag_indiv_cost_sep = False
    for i, ticket in enumerate(list_of_tickets):
        key = ticket.base_ticket_id
        quality_of_children = ticket.quality_of_children
        quality_of_adult = ticket.quality_of_adult
        quality_of_add_adult = ticket.quality_of_add_adult

        if context.user_data.get('command') == 'reserve':
            if (
                    quality_of_children <
                    quality_of_adult + quality_of_add_adult and
                    int(qty_child_free_seat_now) >= int(qty_adult_free_seat_now)
            ):
                continue

        name = ticket.name
        ticket.date_show = date_for_price  # Для расчета стоимости в периоде или нет
        price = ticket.price

        # Если свободных мест меньше, чем требуется для варианта
        # бронирования, то кнопку с этим вариантом не предлагать
        flag = True
        if context.user_data.get('command', False) == 'reserve':
            if int(quality_of_children) <= int(qty_child_free_seat_now):
                flag = True
            else:
                flag = False
        if flag:
            if key // 100 >= 3 and not flag_indiv_cost_sep:
                text += "__________\n    Варианты со скидками:\n"
                flag_indiv_cost_sep = True

            if flag_indiv_cost:
                try:
                    if event['ticket_price_type'] == '':
                        if date_for_price.weekday() in range(5):
                            type_ticket_price = 'будни'
                        else:
                            type_ticket_price = 'выходные'
                    else:
                        type_ticket_price = event['ticket_price_type']
                    reserve_user_data['type_ticket_price'] = type_ticket_price

                    price = special_ticket_price[option][type_ticket_price][key]
                except KeyError:
                    reserve_hl_logger.error(
                        f'{key=} - данному билету не назначена индив. цена')
            text += (f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]} {name} | '
                     f'{price} руб\n')

            button_tmp = InlineKeyboardButton(
                text=f'{DICT_OF_EMOJI_FOR_BUTTON[i + 1]}',
                callback_data=str(key)
            )
            list_btn_of_numbers.append(button_tmp)

            # Позволяет управлять кол-вом кнопок в ряду
            # Максимальное кол-во кнопок в ряду равно 8
            if (i + 1) % 5 == 0:
                keyboard.append(list_btn_of_numbers)
                list_btn_of_numbers = []
    if len(list_btn_of_numbers):
        keyboard.append(list_btn_of_numbers)

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='res',
                                            postfix_for_back='TIME'))
    reply_markup = InlineKeyboardMarkup(keyboard)

    text += ('__________\n'
             '<i>Если вы хотите оформить несколько билетов, '
             'то каждая бронь оформляется отдельно.</i>\n'
             '__________\n'
             '<i>МНОГОДЕТНЫМ:\n'
             '1. Пришлите удостоверение многодетной семьи администратору\n'
             '2. Дождитесь ответа\n'
             '3. Оплатите билет со скидкой 10% от цены, которая указана выше</i>')

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    state = 'TICKET'
    if context.user_data.get('command', False) == 'reserve_admin':
        state = 'TICKET'
    set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def get_ticket(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            query.data,
        ]
    ))

    try:
        context.user_data['reserve_user_data'][
            'key_option_for_reserve'] = int(query.data)
    except ValueError as e:
        reserve_hl_logger.error(e)
        state = 'TIME'
        text_back, reply_markup = get_back_context(context, state)
        text = '<i>Произошла ошибка. Выберите время еще раз</i>\n'
        text += text_back
        await query.delete_message()
        await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
        )
        context.user_data['STATE'] = state
        return state

    key_option_for_reserve = context.user_data['reserve_user_data'][
        'key_option_for_reserve']
    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            str(key_option_for_reserve),
        ]
    ))

    reserve_user_data = context.user_data['reserve_user_data']
    choose_event_info = reserve_user_data['choose_event_info']

    chose_ticket, price = await get_chose_ticket_and_price(
        choose_event_info,
        context,
        key_option_for_reserve,
        reserve_user_data
    )

    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'выбрал',
            chose_ticket.name,
            str(price),
        ]
    ))

    # Если пользователь выбрал не стандартный вариант
    if chose_ticket.flag_individual:
        text = ('Для оформления данного варианта обратитесь к Администратору:\n'
                f'{context.bot_data['admin']['contacts']}')
        await query.edit_message_text(
            text=text
        )

        reserve_hl_logger.info(
            f'Для пользователя {user}')
        reserve_hl_logger.info(
            f'Обработчик завершился на этапе {context.user_data['STATE']}')
        context.user_data['common_data'].clear()
        context.user_data['reserve_user_data'].clear()

        state = ConversationHandler.END
        context.user_data['STATE'] = state
        return state

    # Для всех стандартных вариантов
    payment_data = context.user_data['reserve_admin_data']['payment_data']
    payment_data['chose_ticket'] = chose_ticket

    text = f'<i>{OFFER}</i>'
    keyboard = [add_btn_back_and_cancel(postfix_for_cancel='res',
                                        postfix_for_back='TICKET')]
    reply_markup = InlineKeyboardMarkup(keyboard)
    inline_message = await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )
    reply_markup = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton('Принимаю')]],
        one_time_keyboard=True,
        resize_keyboard=True
    )
    message = await update.effective_chat.send_message(
        text='Если вы согласны нажмите внизу экрана\n'
             '⬇️⬇️⬇️️<b>Принимаю</b>⬇️⬇️⬇️️',
        reply_markup=reply_markup
    )

    context.user_data['reserve_user_data']['message_id'] = inline_message.message_id
    context.user_data['reserve_user_data']['accept_message_id'] = message.message_id

    state = 'OFFER'
    context.user_data['STATE'] = state
    return state


async def get_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.delete_message(
        context.user_data['reserve_user_data']['accept_message_id']
    )
    await context.bot.edit_message_reply_markup(
        chat_id=update.effective_chat.id,
        message_id=context.user_data['reserve_user_data']['message_id'],
    )

    text = 'Напишите email, на него вам будет направлен чек после оплаты\n\n'
    email = await db_postgres.get_email(context.session,
                                        update.effective_user.id)
    if email:
        text += f'Последний введенный email:\n<code>{email}</code>'
    keyboard = [add_btn_back_and_cancel(postfix_for_cancel='res',
                                        postfix_for_back='TICKET')]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['reserve_user_data']['message_id'] = message.message_id

    state = 'EMAIL'
    context.user_data['STATE'] = state
    return state


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.edit_message_reply_markup(
        chat_id=update.effective_chat.id,
        message_id=context.user_data['reserve_user_data']['message_id']
    )
    email = update.effective_message.text
    if not check_email(email):
        state = 'EMAIL'
        keyboard = [add_btn_back_and_cancel(postfix_for_cancel='res',
                                            postfix_for_back=state)]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_chat.send_message(
            text=f'Вы написали: {email}\n'
                 f'Пожалуйста проверьте и введите почту еще раз.',
            reply_markup=reply_markup
        )
        context.user_data['STATE'] = state
        return state

    await db_postgres.update_user(
        session=context.session,
        user_id=update.effective_user.id,
        email=email
    )

    user = context.user_data['user']
    reserve_user_data = context.user_data['reserve_user_data']
    choose_event_info = reserve_user_data['choose_event_info']
    dict_show_data = context.bot_data['dict_show_data']
    show_data = dict_show_data[choose_event_info['show_id']]
    name_show = show_data['full_name']
    date = choose_event_info['date_show']
    time = choose_event_info['time_show']
    text_emoji = choose_event_info['text_emoji']
    payment_data = context.user_data['reserve_admin_data']['payment_data']
    chose_ticket = payment_data['chose_ticket']
    price = chose_ticket.price

    text_select_show = (f'Вы выбрали спектакль:\n'
                        f'<b>{name_show}\n'
                        f'{date}\n'
                        f'{time}</b>\n'
                        f'{text_emoji}\n')
    text = text_select_show + (f'Вариант бронирования:\n'
                               f'{chose_ticket.name} '
                               f'{price}руб\n')

    context.user_data['common_data']['text_for_notification_massage'] = text

    await update.effective_chat.send_message(
        text=text,
    )
    message = await update.effective_chat.send_message(
        'Проверяю наличие свободных мест...')
    await update.effective_chat.send_action(ChatAction.TYPING)

    payment_data = context.user_data['reserve_admin_data']['payment_data']
    event_id = payment_data['event_id']
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

    # Проверка доступности нужного кол-ва мест, за время взаимодействия с
    # ботом, могли изменить базу в ручную или забронировать места раньше
    if (int(qty_child_free_seat_now) <
            int(chose_ticket.quality_of_children)):
        reserve_hl_logger.info(": ".join(
            [
                'Мест не достаточно',
                'Кол-во доступных мест д',
                qty_child_free_seat_now,
                'в',
                qty_adult_free_seat_now,
                'Для',
                f'{name_show} {date} в {time}',
            ]
        ))

        await message.delete()
        reserve_user_data['event_info_for_list_waiting'] = text_select_show
        text = ('К сожалению места уже забронировали и свободных мест для\n'
                f'{name_show}\n'
                f'{date} в {time}\n'
                f'{text_emoji}\n'
                f' Осталось: '
                f'<i>{qty_adult_free_seat_now} взр</i> '
                f'| <i>{qty_child_free_seat_now} дет</i>\n\n'
                '⬇️Нажмите на одну из двух кнопок ниже, '
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
            reply_markup=reply_markup,
        )
        state = 'CHOOSING'
        context.user_data['STATE'] = state
        return state
    else:
        reserve_hl_logger.info(": ".join(
            [
                'Пользователь',
                f'{user}',
                'получил разрешение на бронирование'
            ]
        ))
        qty_child_free_seat_new = int(
            qty_child_free_seat_now) - int(
            chose_ticket.quality_of_children)
        qty_child_nonconfirm_seat_new = int(
            qty_child_nonconfirm_seat_now) + int(
            chose_ticket.quality_of_children)
        qty_adult_free_seat_new = int(
            qty_adult_free_seat_now) - int(
            chose_ticket.quality_of_adult +
            chose_ticket.quality_of_add_adult)
        qty_adult_nonconfirm_seat_new = int(
            qty_adult_nonconfirm_seat_now) + int(
            chose_ticket.quality_of_adult +
            chose_ticket.quality_of_add_adult)

        numbers = [
            qty_child_free_seat_new,
            qty_child_nonconfirm_seat_new,
            qty_adult_free_seat_new,
            qty_adult_nonconfirm_seat_new
        ]

        try:
            write_data_for_reserve(event_id, numbers)
            await db_postgres.update_schedule_event(
                context.session,
                int(event_id),
                qty_child_free_seat=qty_child_free_seat_new,
                qty_child_nonconfirm_seat=qty_child_nonconfirm_seat_new,
                qty_adult_free_seat=qty_adult_free_seat_new,
                qty_adult_nonconfirm_seat=qty_adult_nonconfirm_seat_new,
            )
        except TimeoutError:
            reserve_hl_logger.error(": ".join(
                [
                    f'Для пользователя {user} бронирование в '
                    f'авто-режиме не сработало',
                    'event_id для обновления',
                    event_id,
                ]
            ))

            keyboard = [add_btn_back_and_cancel('res')]
            reply_markup = InlineKeyboardMarkup(keyboard)

            text = ('К сожалению произошла непредвиденная ошибка\n'
                    'Нажмите "Назад" и выберите время повторно.\n'
                    'Если ошибка повторяется свяжитесь с Администратором:\n'
                    f'{context.bot_data['admin']['contacts']}')
            await message.edit_text(
                text=text,
                reply_markup=reply_markup
            )
            state = 'ORDER'
            context.user_data['STATE'] = state
            return state

    await message.delete()
    await send_breaf_message(update, context)

    state = 'FORMA'
    context.user_data['STATE'] = state
    return state


async def get_name_adult(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await context.bot.edit_message_reply_markup(
        update.effective_chat.id,
        message_id=context.user_data['reserve_user_data']['message_id']
    )
    text = update.effective_message.text

    context.user_data['reserve_user_data']['client_data']['name_adult'] = text

    keyboard = [add_btn_back_and_cancel(postfix_for_cancel='res|',
                                        add_back_btn=False)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_chat.send_message(
        text='<b>Напишите номер телефона</b>',
        reply_markup=reply_markup
    )

    state = 'PHONE'
    context.user_data['STATE'] = state
    return state


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        await request_phone_number(update, phone)
        return context.user_data['STATE']

    context.user_data['reserve_user_data']['client_data']['phone'] = phone

    keyboard = [add_btn_back_and_cancel(postfix_for_cancel='res|',
                                        add_back_btn=False)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_chat.send_message(
        text="""<b>Напишите, имя и сколько полных лет ребенку</b>
__________
Например:
Сергей 2
Юля 3
__________
<i> - Если детей несколько, напишите всех в одном сообщении
 - Один ребенок = одна строка
 - Не используйте дополнительные слова и пунктуацию, кроме тех, что указаны в примерах</i>""",
        reply_markup=reply_markup
    )

    state = 'CHILDREN'
    context.user_data['STATE'] = state
    return state


async def get_name_children(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_action(ChatAction.TYPING)

    text = update.effective_message.text
    wrong_input_data_text = (
        'Проверьте, что указали дату или возраст правильно\n'
        'Например:\n'
        'Сергей 2\n'
        'Юля 3\n'
        '__________\n'
        '<i> - Если детей несколько, напишите всех в одном сообщении\n'
        ' - Один ребенок = одна строка\n'
        ' - Не используйте дополнительные слова и пунктуацию, '
        'кроме тех, что указаны в примерах</i>'
    )
    keyboard = [add_btn_back_and_cancel(postfix_for_cancel='res|',
                                        add_back_btn=False)]
    reply_markup = InlineKeyboardMarkup(keyboard)

    result = await check_input_text(update, wrong_input_data_text)
    if not result:
        return context.user_data['STATE']
    reserve_hl_logger.info('Проверка пройдена успешно')

    processed_data_on_children = [item.split() for item in text.split('\n')]

    if not isinstance(processed_data_on_children[0], list):
        await update.effective_chat.send_message(
            text=f'Вы ввели:\n{text}' + wrong_input_data_text,
            reply_markup=reply_markup
        )
        state = 'CHILDREN'
        context.user_data['STATE'] = state
        return state

    try:
        payment_data = context.user_data['reserve_admin_data']['payment_data']
        chose_ticket = payment_data['chose_ticket']
    except KeyError as e:
        reserve_hl_logger.error(e)
        await update.effective_chat.send_message(
            'Произошел технический сбой.\n'
            f'Повторите, пожалуйста, бронирование еще раз\n'
            f'/{COMMAND_DICT['RESERVE'][0]}\n'
            'Приносим извинения за предоставленные неудобства.'
        )
        state = ConversationHandler.END
        context.user_data['STATE'] = state
        return state

    if len(processed_data_on_children) != chose_ticket.quality_of_children:
        await update.effective_chat.send_message(
            text=f'Кол-во детей, которое определено: '
                 f'{len(processed_data_on_children)}\n'
                 f'Кол-во детей, согласно выбранному билету: '
                 f'{chose_ticket.quality_of_children}\n'
                 f'Повторите ввод еще раз, проверьте что каждый ребенок на '
                 f'отдельной строке.\n\nНапример:\nИван 1\nМарина 3',
            reply_markup=reply_markup
        )
        state = 'CHILDREN'
        context.user_data['STATE'] = state
        return state

    reserve_user_data = context.user_data['reserve_user_data']
    client_data = reserve_user_data['client_data']
    client_data['data_children'] = processed_data_on_children
    reserve_user_data['original_input_text'] = text

    user = context.user_data['user']
    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'отправил:',
        ],
    ))
    reserve_hl_logger.info(client_data)

    await create_and_send_payment(update, context)

    state = 'PAID'
    context.user_data['STATE'] = state
    return state


async def check_and_send_buy_info(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    """
    Проверяет кол-во доступных мест, для выбранного варианта пользователем и
    отправляет сообщение об оплате.
    Возвращает state PAID, но если проверка не пройдена, то state ORDER

    :return: str
    """
    await create_and_send_payment(update, context)

    state = 'PAID'
    context.user_data['STATE'] = state
    return state


async def forward_photo_or_file(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await remove_button_from_last_message(update, context)

    await processing_successful_payment(update, context)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def processing_successful_notification(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup()

    await processing_successful_payment(update, context)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def conversation_timeout(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Informs the user that the operation has timed out,
    calls :meth:`remove_reply_markup` and ends the conversation.
    :return:
        int: :attr:`telegram.ext.ConversationHandler.END`.
    """
    user = context.user_data['user']
    if context.user_data['STATE'] == 'PAID':
        reserve_hl_logger.info('Отправка чека об оплате не была совершена')
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['common_data']['message_id_buy_info']
        )
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, бронь отменена, '
            'пожалуйста выполните новый запрос\n'
            'Если вы уже сделали оплату, но не отправили чек об оплате, '
            'выполните оформление повторно и приложите данный чек\n'
            f'/{COMMAND_DICT['RESERVE'][0]}\n\n'
            'Если свободных мест не будет свяжитесь с Администратором:\n'
            f'{context.bot_data['admin']['contacts']}'
        )
        reserve_hl_logger.info(pprint.pformat(context.user_data))
        payment_data = context.user_data['reserve_admin_data']['payment_data']
        chose_ticket = payment_data['chose_ticket']
        event_id = payment_data['event_id']

        await write_old_seat_info(user,
                                  event_id,
                                  chose_ticket)
    else:
        # TODO Прописать дополнительную обработку states, для этапов опроса
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос',
            message_thread_id=update.effective_message.message_thread_id
        )

    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            f'AFK уже {RESERVE_TIMEOUT} мин'
        ]
    ))
    reserve_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')

    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)


async def send_clients_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)

    reserve_user_data = context.user_data['reserve_user_data']
    choose_event_info = reserve_user_data['choose_event_info']
    name = choose_event_info['name_show']
    date = choose_event_info['date_show']
    time, event_id, qty_child, qty_adult = query.data.split(' | ')

    clients_data, name_column = load_clients_data(event_id)
    text = f'#Показ #event_id_{event_id}\n'
    text += f'Список людей для\n{name}\n{date}\n{time}\nКол-во посетителей: '
    qty_child = 0
    qty_adult = 0
    for item in clients_data:
        if item[name_column['flag_exclude_place_sum']] == 'FALSE':
            qty_child += int(item[name_column['qty_child']])
            qty_adult += int(item[name_column['qty_adult']])
    text += f"д={qty_child}|в={qty_adult}"
    for i, item in enumerate(clients_data):
        text += '\n__________\n'
        text += str(i + 1) + '| '
        text += '<b>' + item[name_column['callback_name']] + '</b>'
        text += '\n+7' + item[name_column['callback_phone']]
        child_name = item[name_column['child_name']]
        if child_name != '':
            text += '\nИмя ребенка: '
            text += child_name
        age = item[name_column['child_age']]
        if age != '':
            text += '\nВозраст: '
            text += age
        name = item[name_column['name']]
        if name != '':
            text += '\nСпособ брони: '
            text += name
        try:
            notes = item[name_column['notes']]
            if notes != '':
                text += '\nПримечание: '
                text += notes
        except IndexError:
            reserve_hl_logger.info('Примечание не задано')
    await query.edit_message_text(
        text=text,
    )
    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def write_list_of_waiting(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        text='Напишите контактный номер телефона',
        reply_markup=ReplyKeyboardRemove()
    )
    state = 'PHONE_FOR_WAITING'
    context.user_data['STATE'] = state
    return state


async def get_phone_for_waiting(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    phone = update.effective_message.text
    phone = extract_phone_number_from_text(phone)
    if check_phone_number(phone):
        await request_phone_number(update, phone)
        return context.user_data['STATE']

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['client_data']['phone'] = phone
    text = reserve_user_data['event_info_for_list_waiting'] + '+7' + phone

    user = context.user_data['user']
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Лист ожидания', None))
    text = f'#Лист_ожидания\n' \
           f'Пользователь @{user.username} {user.full_name}\n' \
           f'Запросил добавление в лист ожидания\n' + text
    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=text,
        message_thread_id=thread_id
    )
    write_client_list_waiting(context)
    await update.effective_chat.send_message(
        text='Вы добавлены в лист ожидания, '
             'если место освободится, то с вами свяжутся. '
             'Если у вас есть вопросы, вы можете связаться с Администратором:\n'
             f'{context.bot_data['admin']['contacts']}'
    )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state

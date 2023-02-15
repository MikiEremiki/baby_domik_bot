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
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

import googlesheets
import utilites
from settings import DICT_OF_OPTION_FOR_RESERVE, CHAT_ID_GROUP_ADMIN


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Приветственная команда при первом запуске бота,
    при перезапуске бота или при использовании команды start
    """
    await update.effective_chat.send_message(
        text='Отлично! Мы рады, что вы с нами. Воспользуйтесь командой '
             '/reserve, чтобы выбрать спектакль.'
    )


async def choice_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю список спектаклей с датами.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state DATE
    """

    logging.info(f'Пользователь начал выбор спектакля:'
                 f' {update.message.from_user}')
    context.user_data["STATE"] = 'START'

    # Загрузка базы спектаклей из гугл-таблицы
    dict_of_shows, dict_of_date_and_time = utilites.load_data()

    # Определение кнопок для inline клавиатуры
    # TODO Заменить использование ключа на итератор
    #  с проверкой по имени спектакля
    keyboard = []
    for key in dict_of_date_and_time.keys():
        for date in dict_of_date_and_time[key].keys():
            button_tmp = InlineKeyboardButton(
                text=str(key) + ' | ' + date,
                callback_data=str(key) + ' | ' + date
            )
            keyboard.append([button_tmp])

    button_tmp = InlineKeyboardButton(
        "Отменить",
        callback_data='Отменить'
    )
    keyboard.append([button_tmp])
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправка сообщения пользователю
    text = 'Выберите спектакль и дату\n'
    for key, item in dict_of_shows.items():
        text += f'{item} | {key}\n'
    answer = await update.message.reply_text(text, reply_markup=reply_markup)

    context.user_data['user'] = update.message.from_user
    context.user_data['message_id'] = answer.message_id

    # Контекст для возврата назад
    context.user_data['text_date'] = text
    context.user_data['keyboard_date'] = reply_markup

    # Вместо считывания базы спектаклей каждый раз из гугл-таблицы, прокидываем
    # Базу в контекст пользователя
    context.user_data['dict_of_shows'] = dict_of_shows
    context.user_data['dict_of_date_and_time'] = dict_of_date_and_time

    return 'DATE'


async def choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю варианты
    времени и кол-во свободных мест

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state TIME
    """
    query = update.callback_query
    await query.answer()

    logging.info(": ".join(
        [
            'Пользователь',
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
            'выбрал',
            query.data,
        ]
    ))
    context.user_data["STATE"] = 'DATE'

    key_of_name_show = int(query.data.split(' | ')[0])
    date_show = query.data.split(' | ')[1]
    dict_of_shows = context.user_data['dict_of_shows']
    dict_of_date_and_time = context.user_data['dict_of_date_and_time']

    # Получение названия спектакля по ключу
    # TODO придумать вариант проще без прохода по всему словарю, возможно
    #  передавать вместе с callback_data
    name_show = '---'
    for key, item in dict_of_shows.items():
        if item == key_of_name_show:
            name_show = key

    keyboard = []

    # Определение кнопок для inline клавиатуры с исключением вариантов где
    # свободных мест уже не осталось
    for time in dict_of_date_and_time[key_of_name_show][date_show].keys():
        if dict_of_date_and_time[key_of_name_show][date_show][time][0][1] == 0:
            continue
        number = dict_of_date_and_time[key_of_name_show][date_show][time][0][1]
        button_tmp = InlineKeyboardButton(
            text=time + ' | ' + str(number) + ' шт свободно',
            callback_data=time
        )
        keyboard.append([button_tmp])

    keyboard.append(utilites.add_btn_back_and_cancel())
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправка сообщения пользователю
    text = f'Вы выбрали:\n {name_show}\n' \
           'Выберите удобное время.\n' \
           '1 ребенок = 1 место'
    await query.message.edit_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['key_of_name_show'] = key_of_name_show
    context.user_data['date_show'] = date_show
    context.user_data['name_show'] = name_show

    # Контекст для возврата назад
    context.user_data['text_time'] = text
    context.user_data['keyboard_time'] = reply_markup

    return 'TIME'


async def choice_option_of_reserve(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю сообщения по выбранному спектаклю,
    дате, времени и варианты бронирования

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state ORDER
    """
    query = update.callback_query
    await query.answer()

    logging.info(": ".join(
        [
            'Пользователь',
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
            'выбрал',
            query.data,
        ]
    ))
    context.user_data["STATE"] = 'TIME'

    key = context.user_data['key_of_name_show']
    date = context.user_data['date_show']
    dict_of_date_and_time = context.user_data['dict_of_date_and_time']
    time = query.data

    row_in_googlesheet = dict_of_date_and_time[key][date][time][1]

    availibale_number_of_seats_now = googlesheets.update_quality_of_seats(
        row_in_googlesheet, 4)

    # Определение кнопок для inline клавиатуры
    keyboard = []
    list_btn_of_numbers = []
    for key, item in DICT_OF_OPTION_FOR_RESERVE.items():
        quality_of_children = DICT_OF_OPTION_FOR_RESERVE[key].get(
            'quality_of_children')

        # Если свободных мест меньше, чем требуется для варианта
        # бронирования, то кнопку с этим вариантом не предлагать
        if int(quality_of_children) <= int(availibale_number_of_seats_now):
            button_tmp = InlineKeyboardButton(
                text=str(key),
                callback_data=str(key)
            )
            list_btn_of_numbers.append(button_tmp)

            # Позволяет управлять кол-вом кнопок в ряду
            # Максимальное кол-во кнопок в ряду равно 8
            if key % 5 == 0:
                keyboard.append(list_btn_of_numbers)
                list_btn_of_numbers = []
    keyboard.append(list_btn_of_numbers)

    keyboard.append(utilites.add_btn_back_and_cancel())
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправка сообщения пользователю
    text = 'Выберите подходящий вариант бронирования:\n'
    for key, item in DICT_OF_OPTION_FOR_RESERVE.items():
        text += f'*{key}* \| {item.get("name")} \| {item.get("price")}руб\n'
        if item.get('name') == 'Индивидуальный запрос':
            text += """\_\_\_\_\_\_\_\_\_\_
Варианты со скидками:\n"""
    text += """\_\_\_\_\_\_\_\_\_\_
_Если вы хотите оформить несколько билетов, то каждая бронь оформляется отдельно\._
\_\_\_\_\_\_\_\_\_\_
_Если нет желаемых вариантов для выбора, значит нехватает мест для их оформления\. 
В таком случае вернитесь назад и выберете другое время\._
"""

    await query.message.edit_text(
        text=text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup
    )

    context.user_data['time_of_show'] = time

    context.user_data['row_in_googlesheet'] = row_in_googlesheet

    return 'ORDER'


async def check_and_send_buy_info(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """
    Проверяет кол-во доступных мест, для выбранного варианта пользователем и
    отправляет сообщение об оплате или о необходимости выбрать другое время с
    двумя кнопками "Назад" или "Отмена"

    :return:
        возвращает state PAID,
        если проверка не пройдена, то state ORDER
    """
    query = update.callback_query
    await query.answer()

    context.user_data['STATE'] = 'ORDER'

    date = context.user_data['date_show']
    time = context.user_data['time_of_show']
    name_show = context.user_data['name_show']
    key_option_for_reserve = int(query.data)
    chose_reserve_option = DICT_OF_OPTION_FOR_RESERVE.get(
        key_option_for_reserve)
    price = chose_reserve_option.get('price')

    logging.info(": ".join(
        [
            'Пользователь',
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
            'выбрал',
            chose_reserve_option.get('name'),
        ]
    ))

    # Если пользователь выбрал не стандартный вариант
    if chose_reserve_option.get('flag_individual'):
        text = 'Для оформления данного варианта обращайтесь в ЛС в telegram ' \
               'или по телефону:\n Татьяна Бурганова @Tanya_domik +79159383529'
        await query.message.edit_text(
            text=text
        )

        logging.info(
            f'Обработчик завершился на этапе {context.user_data["STATE"]}')
        context.user_data.clear()

        return ConversationHandler.END
    # Для все стандартных вариантов
    else:
        # Отправляем сообщение пользователю, которое он будет использовать как
        # памятку
        text = f'Вы выбрали:\n' \
               f'{name_show}\n' \
               f'{date}\n' \
               f'В {time}\n' \
               f'Вариант бронирования: \n' \
               f'{chose_reserve_option.get("name")} ' \
               f'{price}руб\n'

        context.user_data['text_for_notification_massage'] = text

        await query.message.edit_text(
            text=text
        )

        # Номер строки для извлечения актуального числа доступных мест
        row_in_googlesheet = context.user_data['row_in_googlesheet']

        # Обновляем кол-во доступных мест
        availibale_number_of_seats_now = googlesheets.update_quality_of_seats(
            row_in_googlesheet, 4)
        nonconfirm_number_of_seats_now = googlesheets.update_quality_of_seats(
            row_in_googlesheet, 5)

        # Проверка доступности нужного кол-ва мест, за время взаимодействия с
        # ботом, могли изменить базу в ручную или забронировать места раньше
        if int(availibale_number_of_seats_now) < int(chose_reserve_option.get(
                'quality_of_children')):
            logging.info(": ".join(
                [
                    'Мест не достаточно',
                    'Кол-во доступных мест',
                    availibale_number_of_seats_now,
                    'Для',
                    f'{name_show} {date} в {time}',
                ]
            ))

            keyboard = []
            keyboard.append(utilites.add_btn_back_and_cancel())
            reply_markup = InlineKeyboardMarkup(keyboard)

            text = f'К сожалению места уже забронировали и свободных мест ' \
                   f'Для {name_show}\n' \
                   f'{date} в {time}\n осталось: ' \
                   f'{availibale_number_of_seats_now}шт' \
                   f'Пожалуйста выберите другое время.'
            await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup
            )
            return 'ORDER'
        else:
            logging.info(": ".join(
                [
                    'Пользователь',
                    str(context.user_data['user'].id),
                    str(context.user_data['user'].full_name),
                    'получил разрешение на бронирование'
                ]
            ))

            new_number_of_seats = int(
                availibale_number_of_seats_now) - int(
                chose_reserve_option.get('quality_of_children'))
            new_nonconfirm_number_of_seats = int(
                nonconfirm_number_of_seats_now) + int(
                chose_reserve_option.get('quality_of_children'))

            googlesheets.confirm(
                row_in_googlesheet,
                [new_number_of_seats, new_nonconfirm_number_of_seats]
            )

        # TODO перенести отправку кнопок в хэндлер с получением фото или
        #  сделать проверку перед отправкой опроса
        keyboard = []
        button_approve = InlineKeyboardButton(
            "Подтвердить",
            callback_data=f'Подтвердить|{query.message.chat_id} {query.message.message_id}'
        )

        button_cancel = InlineKeyboardButton(
            "Отменить",
            callback_data=f'Отменить|'
                          f'{query.message.chat_id} {query.message.message_id}'
        )
        keyboard.append([button_approve, button_cancel])
        reply_markup = InlineKeyboardMarkup(keyboard)

        price = chose_reserve_option.get("price")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"""Забронировать билет можно только по 100% предоплате.
Но вы не переживайте, если вдруг вы не сможете придти, просто сообщите нам об этом за 24 часа, мы перенесём вашу дату визита. 
    
    К оплате {price} руб
Оплатить можно переводом на карту Сбербанка по номеру телефона +79159383529 - Татьяна Александровна Б.
    
ВАЖНО! Прислать сюда электронный чек об оплате (или скриншот)
    
Вам необходимо сделать оплату в течении 15 мин, после нажать кнопку "Подтвердить" или бронь будет отменена.
Затем необходимо:
    Пройти опрос (он поступит автоматически), чтобы мы знали на кого оформлена бронь и как свами связаться.""",
            reply_markup=reply_markup
        )

        context.user_data['chose_reserve_option'] = chose_reserve_option
        context.user_data['key_option_for_reserve'] = key_option_for_reserve
        context.user_data['quality_of_children'] = chose_reserve_option.get(
            'quality_of_children')

    return 'PAID'


async def forward_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = context.user_data['user']

    await context.bot.send_message(
        chat_id=CHAT_ID_GROUP_ADMIN,
        text=f'Квитанция пользователя @{user.username} {user.full_name}\n',
    )
    await update.effective_message.forward(
        chat_id=CHAT_ID_GROUP_ADMIN,
    )

    if context.user_data['STATE'] == 'ORDER':
        context.user_data['STATE'] = 'PAID'
        return 'PAID'
    if context.user_data['STATE'] == 'PAID':
        context.user_data['STATE'] = 'FORMA'
        return 'FORMA'


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запускает цепочку вопросов для клиентской базы, если пользователь нажал
    кнопку подтвердить.
    """
    query = update.callback_query
    await query.answer()

    context.user_data['STATE'] = 'PAID'

    # Сообщение для опроса
    await query.edit_message_text("""Для подтверждения брони осталось ответить на несколько вопросов.

Напишите фамилию и имя (взрослого) на кого оформляете бронь""")

    # Сообщение для администратора
    row_in_googlesheet = context.user_data['row_in_googlesheet']
    key_option_for_reserve = context.user_data['key_option_for_reserve']
    keyboard = []
    button_approve = InlineKeyboardButton(
        "Подтвердить",
        callback_data=f'Разрешить|'
                      f'{query.message.chat_id} {query.message.message_id} '
                      f'{row_in_googlesheet} {key_option_for_reserve}'
    )

    button_cancel = InlineKeyboardButton(
        "Отклонить",
        callback_data=f'Отклонить|'
                      f'{query.message.chat_id} {query.message.message_id} '
                      f'{row_in_googlesheet} {key_option_for_reserve}'
    )
    keyboard.append([button_approve, button_cancel])
    reply_markup = InlineKeyboardMarkup(keyboard)

    user = context.user_data['user']
    chose_reserve_option = context.user_data['chose_reserve_option']
    price = chose_reserve_option.get("price")

    answer = await context.bot.send_message(
        chat_id=CHAT_ID_GROUP_ADMIN,
        text=f'Пользователь @{user.username} {user.full_name}\n'
             f'Запросил подтверждение брони на сумму {price} руб\n',
        reply_markup=reply_markup
    )

    context.user_data['message_id_for_admin'] = answer.message_id

    return 'FORMA'


async def get_name_adult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["STATE"] = 'PHONE'

    text = update.effective_message.text

    context.user_data['client_data'] = {}
    context.user_data['client_data']['name_adult'] = text

    await update.effective_chat.send_message(
        text='Напишите ваш номер телефона с +7'
    )

    return 'PHONE'


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["STATE"] = 'PHONE'

    text = update.effective_message.text

    context.user_data['client_data']['phone'] = text

    await update.effective_chat.send_message(
        text='Напишите, имя ребенка и через дефис год рождения.\nЕсли детей '
             'несколько, то напишите каждого ребенка с новой строки\n'
             'Формат записи:\n'
             'Имя - ДД.ММ.ГГГГ\n'
             'Имя - ДД.ММ.ГГГГ'
    )

    return 'CHILDREN'


async def get_name_children(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["STATE"] = 'CHILDREN'

    text = update.effective_message.text

    context.user_data['client_data']['data_children'] = text

    # TODO Сделать парсер данных + если детей несколько, чтобы в таблицу
    #  заносилось соответсвующее кол-во строк и добавить доп информацию,
    #  для списка
    googlesheets.write_client(context.user_data['client_data'])

    logging.info(": ".join(
        [
            'Пользователь',
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
            'отправил:',
        ],
    ))
    logging.info(context.user_data['client_data'])

    text = ' '.join([
        context.user_data['client_data']['name_adult'],
        context.user_data['client_data']['phone']
    ])
    # Возникла ошибка, когда сообщение удалено, то бот по кругу находится в
    # 'CHILDREN' state, написал обходной путь для этого
    try:
        await context.bot.send_message(
            chat_id=CHAT_ID_GROUP_ADMIN,
            text=text,
            reply_to_message_id=context.user_data['message_id_for_admin']
        )
    except BadRequest:
        logging.info('Сообщение на которое нужно ответить, уже удалено')
        await context.bot.send_message(
            chat_id=CHAT_ID_GROUP_ADMIN,
            text=text,
        )

    await update.effective_chat.send_message(
        'Благодарим за ответы.\nОжидайте, когда администратор подтвердить '
        'бронь.\nЕсли всё хорошо, то вам придет сообщение: "Ваша бронь '
        'подтверждена"\n'
        'В противном случае с вами свяжутся для уточнения деталей')

    text = context.user_data['text_for_notification_massage']
    text += """__________
Место проведения:
Офис-центр Малая Покровская, д18, 2 этаж
__________
По вопросам обращайтесь в ЛС в telegram или по телефону:
Татьяна Бурганова @Tanya_domik +79159383529
__________
Если вы хотите оформить еще одну бронь, используйте команду /reserve"""
    answer = await update.effective_chat.send_message(
        text=text
    )
    await update.effective_chat.pin_message(answer.message_id)

    logging.info(f'Обработчик завершился на этапе {context.user_data["STATE"]}')
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


    logging.info(": ".join(
        [
            'Для пользователя',
            f'@{username} + " " + {full_name}',
            'Номер строки, которая должна быть обновлена',
            row_in_googlesheet,
        ]
    ))


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

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
from settings import (
    DICT_OF_OPTION_FOR_RESERVE,
    CHAT_ID_GROUP_ADMIN,
    COMMAND_DICT,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Приветственная команда при первом запуске бота,
    при перезапуске бота или при использовании команды start
    """
    await update.effective_chat.send_message(
        text='Отлично! Мы рады, что вы с нами. Воспользуйтесь командой '
             f'/{COMMAND_DICT["RESERVE"]}, чтобы выбрать спектакль.'
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
    try:
        dict_of_shows, dict_of_date_and_time = utilites.load_data()
    except ConnectionError or ValueError:
        logging.info(
            f'Обработчик завершился на этапе {context.user_data["STATE"]}')

        await update.effective_chat.send_message(
            'К сожалению я сегодня на техническом обслуживании\n'
            'Но вы можете забронировать по старинке в ЛС telegram или по '
            'телефону:\n'
            'Татьяна Бурганова @Tanya_domik +79159383529'
        )

        return ConversationHandler.END

    # Определение кнопок для inline клавиатуры
    # TODO Заменить использование ключа на итератор
    #  с проверкой по имени спектакля
    keyboard = []
    list_btn_of_numbers = []
    date_now = datetime.datetime.now()
    for key in dict_of_date_and_time.keys():
        i = 0
        for date in dict_of_date_and_time[key].keys():
            date_tmp = date.split()[0] + f'.{date_now.year}'
            date_tmp = datetime.datetime.strptime(date_tmp, f'%d.%m.%Y')

            if date_tmp > date_now:
                button_tmp = InlineKeyboardButton(
                    text=str(key) + ' | ' + date,
                    callback_data=str(key) + ' | ' + date
                )
                list_btn_of_numbers.append(button_tmp)

                i += 1
                # Три кнопки так как для телефонов уже дни недели обрезаются
                if i % 3 == 0:
                    i = 1
                    keyboard.append(list_btn_of_numbers)
                    list_btn_of_numbers = []

        keyboard.append(list_btn_of_numbers)
        list_btn_of_numbers = []

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

    number = dict_of_date_and_time[key][date][time][0][1]
    if number == 0:
        answer = await update.effective_chat.send_message(
            'Выберете другое время')
        context.job_queue.run_once(
            utilites.delete_message_for_job_in_callback,
            3,  # 3 секунды
            answer.message_id,
            chat_id=answer.chat_id,
        )
        return 'TIME'

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

        keyboard = []
        button_cancel = InlineKeyboardButton(
            "Отменить",
            callback_data=f'Отменить|'
                          f'{query.message.chat_id} {query.message.message_id}'
        )
        keyboard.append([button_cancel])
        reply_markup = InlineKeyboardMarkup(keyboard)

        price = chose_reserve_option.get("price")
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"""Забронировать билет можно только по 100% предоплате.
Но вы не переживайте, если вдруг вы не сможете придти, просто сообщите нам об этом за 24 часа, мы перенесём вашу дату визита. 
    
    К оплате {price} руб
Оплатить можно переводом на карту Сбербанка по номеру телефона +79159383529 - Татьяна Александровна Б.
    
ВАЖНО! Прислать сюда электронный чек об оплате (или скриншот)
Вам необходимо сделать оплату в течении 15 мин, или бронь будет отменена.""",
            reply_markup=reply_markup
        )

        context.user_data['chose_reserve_option'] = chose_reserve_option
        context.user_data['key_option_for_reserve'] = key_option_for_reserve
        context.user_data['quality_of_children'] = chose_reserve_option.get(
            'quality_of_children')
        context.chat_data['message_id'] = message.message_id

    return 'PAID'


async def forward_photo_or_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Пересылает картинку или файл.
    Запускает цепочку вопросов для клиентской базы, если пользователь нажал
    кнопку подтвердить.
    """
    context.user_data['STATE'] = 'PAID'

    message_id = context.chat_data['message_id']
    chat_id = update.effective_chat.id

    # Убираем у старого сообщения кнопки
    await context.bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=message_id
    )

    user = context.user_data['user']

    await context.bot.send_message(
        chat_id=CHAT_ID_GROUP_ADMIN,
        text=f'Квитанция пользователя @{user.username} {user.full_name}\n',
    )
    await update.effective_message.forward(
        chat_id=CHAT_ID_GROUP_ADMIN,
    )

    # Сообщение для опроса
    await update.effective_chat.send_message("""Для подтверждения брони 
заполните пожалуйста анкету.
Чтобы мы знали на кого оформлена бронь и как с вами связаться.

Напишите фамилию и имя (взрослого) на кого оформляете бронь""")

    # Сообщение для администратора
    row_in_googlesheet = context.user_data['row_in_googlesheet']
    key_option_for_reserve = context.user_data['key_option_for_reserve']
    keyboard = []
    button_approve = InlineKeyboardButton(
        "Подтвердить",
        callback_data=f'Разрешить|'
                      f'{chat_id} {message_id} '
                      f'{row_in_googlesheet} {key_option_for_reserve}'
    )

    button_cancel = InlineKeyboardButton(
        "Отклонить",
        callback_data=f'Отклонить|'
                      f'{chat_id} {message_id} '
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
             f'Запросил подтверждение брони на сумму {price} руб\n'
             f'Ждем заполнения анкеты, если всё хорошо, то только после '
             f'нажимаем подтвердить',
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

    context.user_data['client_data']['phone'] = "'" + text

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
    tmp_text = []
    if '\n' in text:
        text = text.split('\n')
        for item in text:
            tmp_text.append(item.split(' - '))
    else:
        text = text.split(' - ')
        tmp_text.append(text)

    text = tmp_text

    context.user_data['client_data']['data_children'] = text

    googlesheets.write_client(
        context.user_data['client_data'],
        context.user_data['row_in_googlesheet'],
        context.user_data['chose_reserve_option']
    )

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
Если вы хотите оформить еще одну бронь, используйте команду /{COMMAND_DICT[
"RESERVE"]}"""
    answer = await update.effective_chat.send_message(
        text=text
    )
    await update.effective_chat.pin_message(answer.message_id)

    logging.info(f'Обработчик завершился на этапе {context.user_data["STATE"]}')
    context.user_data.clear()

    return ConversationHandler.END


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет оповещение о подтверждении в бронировании, удаляет сообщение
    используемое в ConversationHandler и возвращает свободные места для
    доступа к бронированию
    """
    query = update.callback_query
    await query.answer()

    key_option_for_reserve = int(query.data.split('|')[1].split()[3])
    chose_reserve_option = DICT_OF_OPTION_FOR_RESERVE.get(
        key_option_for_reserve)

    row_in_googlesheet = query.data.split('|')[1].split()[2]

    nonconfirm_number_of_seats_now = googlesheets.update_quality_of_seats(
        row_in_googlesheet, 5)

    new_nonconfirm_number_of_seats = int(
        nonconfirm_number_of_seats_now) - int(
        chose_reserve_option.get('quality_of_children'))
    googlesheets.confirm(
        row_in_googlesheet,
        [new_nonconfirm_number_of_seats]
    )

    username = query.message.text.split('\n')[0].split(' ')[1]
    full_name = query.message.text.split('\n')[0].split(' ')[2] + ' ' + \
                query.message.text.split('\n')[0].split(' ')[3]
    await query.edit_message_text(
        text=f'Пользователю {username} {full_name} подтверждена бронь'
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
        logging.info(
            f'Cообщение уже удалено'
        )

    logging.info(": ".join(
        [
            'Для пользователя',
            f'{username} {full_name}',
            'Номер строки для обновления',
            row_in_googlesheet,
        ]
    ))


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет оповещение об отказе в бронировании, удаляет сообщение
    используемое в ConversationHandler и уменьшает кол-во неподтвержденных мест
    """
    query = update.callback_query
    await query.answer()

    key_option_for_reserve = int(query.data.split('|')[1].split()[3])
    chose_reserve_option = DICT_OF_OPTION_FOR_RESERVE.get(
        key_option_for_reserve)

    # Номер строки для извлечения актуального числа доступных мест
    row_in_googlesheet = query.data.split('|')[1].split()[2]

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
        logging.info(
            f'Cообщение {message_id}, которое должно быть удалено'
        )

    logging.info(": ".join(
        [
            'Для пользователя',
            f'{username} + " " + {full_name}',
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
    Хэндлер отмены, может использоваться на этапе бронирования и оплаты,
    для отмены действий и выхода из ConversationHandler
    """
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        text='Вы выбрали отмену, для повтора используйте команду '
             f'/{COMMAND_DICT["RESERVE"]}'
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

    logging.info(f'Обработчик завершился на этапе {context.user_data["STATE"]}')
    context.user_data.clear()

    return ConversationHandler.END


def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Название не должно быть просто help
    # TODO прописать логику использования help
    pass


async def conversation_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Informs the user that the operation has timed out, calls :meth:`remove_reply_markup` and
    ends the conversation.
    :return:
        int: :attr:`telegram.ext.ConversationHandler.END`.
    """

    if context.user_data['STATE'] == 'ORDER':
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, бронь отменена, пожалуйста выполните '
            'новый запрос'
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
        # TODO Прописать дополнительную обработку states, для этапов опроса
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

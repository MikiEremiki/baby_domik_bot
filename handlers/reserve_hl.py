import logging
import re

from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    TypeHandler
)
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

import googlesheets
import utilites
from settings import (
    CHAT_ID_GROUP_ADMIN,
    COMMAND_DICT,
    DICT_OF_EMOJI_FOR_BUTTON,
)

reserve_hl_logger = logging.getLogger('bot.reserve_hl')


async def choice_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функция отправляет пользователю список спектаклей с датами.

    С сообщением передается inline клавиатура для выбора подходящего варианта
    :return: возвращает state DATE
    """

    reserve_hl_logger.info(f'Пользователь начал выбор спектакля:'
                              f' {update.message.from_user}')
    context.user_data['STATE'] = 'START'
    context.user_data['user'] = update.message.from_user

    answer = await update.effective_chat.send_message(
        text='Загружаем данные спектаклей',
        reply_markup=ReplyKeyboardRemove()
    )

    # Загрузка базы спектаклей из гугл-таблицы
    try:
        (
            dict_of_shows,
            dict_of_name_show,
            dict_of_name_show_flip,
            dict_of_date_show
        ) = utilites.load_data()
    except ConnectionError or ValueError:
        reserve_hl_logger.info(
            f'Для пользователя {context.user_data["user"]}')
        reserve_hl_logger.info(
            f'Обработчик завершился на этапе {context.user_data["STATE"]}')

        await update.effective_chat.send_message(
            'К сожалению я сегодня на техническом обслуживании\n'
            'Но вы можете забронировать место по старинке в ЛС telegram или по '
            'телефону:\n'
            'Татьяна Бурганова @Tanya_domik +79159383529'
        )

        return ConversationHandler.END
    except TimeoutError:
        await update.effective_chat.send_message(
            'Произошел разрыв соединения, попробуйте еще раз\n'
            'Если проблема повторится вы можете забронировать место в ЛС '
            'telegram или по телефону:\n'
            'Татьяна Бурганова @Tanya_domik +79159383529'
        )
        return ConversationHandler.END

    # Определение кнопок для inline клавиатуры
    keyboard = []
    list_btn_of_numbers = []

    i = 0
    for key, item in dict_of_date_show.items():
        button_tmp = InlineKeyboardButton(
            text=key + ' ' + DICT_OF_EMOJI_FOR_BUTTON[item],
            callback_data=str(item) + ' | ' + key
        )
        list_btn_of_numbers.append(button_tmp)

        i += 1
        # Две кнопки в строке так как для узких экранов телефонов дни недели
        # обрезаются
        if i % 2 == 0:
            i = 0
            keyboard.append(list_btn_of_numbers)
            list_btn_of_numbers = []
    if len(list_btn_of_numbers):
        keyboard.append(list_btn_of_numbers)

    button_tmp = InlineKeyboardButton(
        "Отменить",
        callback_data='Отменить'
    )
    keyboard.append([button_tmp])
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправка сообщения пользователю
    text = 'Выберите спектакль и дату\n'
    for key, item in dict_of_name_show.items():
        text += f'{DICT_OF_EMOJI_FOR_BUTTON[item]} {key}\n'

    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=answer.message_id
    )
    answer = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['message_id'] = answer.message_id

    # Контекст для возврата назад
    context.user_data['text_date'] = text
    context.user_data['keyboard_date'] = reply_markup

    # Вместо считывания базы спектаклей каждый раз из гугл-таблицы, прокидываем
    # Базу в контекст пользователя
    context.user_data['dict_of_shows'] = dict_of_shows
    context.user_data['dict_of_name_show'] = dict_of_name_show
    context.user_data['dict_of_name_show_flip'] = dict_of_name_show_flip

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

    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
            'выбрал',
            query.data,
        ]
    ))
    context.user_data["STATE"] = 'DATE'

    key_of_name_show, date_show = query.data.split(' | ')
    key_of_name_show = int(key_of_name_show)

    dict_of_shows: dict = context.user_data['dict_of_shows']
    dict_of_name_show_flip = context.user_data['dict_of_name_show_flip']
    name_show: str = dict_of_name_show_flip[key_of_name_show]

    keyboard = []

    # Определение кнопок для inline клавиатуры с исключением вариантов где
    # свободных мест уже не осталось
    for key, item in dict_of_shows.items():
        if item['name_of_show'] == name_show and item['date'] == date_show:
            time = item['time']
            number = item['available_children_seats']
            button_tmp = InlineKeyboardButton(
                text=time + ' | ' + str(number) + ' шт свободно',
                callback_data=time + ' | ' + str(key) + ' | ' + str(number)
            )
            keyboard.append([button_tmp])

    keyboard.append(utilites.add_btn_back_and_cancel())
    reply_markup = InlineKeyboardMarkup(keyboard)

    name = escape_markdown(name_show, 2)
    date = escape_markdown(date_show, 2)

    if update.effective_chat.id == CHAT_ID_GROUP_ADMIN:
        # Отправка сообщения в админский чат
        text = f'Вы выбрали:\n *{name} {date}*\n' \
               'Выберите время\.\n'
    else:
        # Отправка сообщения пользователю
        text = f'Вы выбрали:\n *{name}*\n' \
               '_Выберите удобное время\.\n' \
               '1 ребенок \= 1 место_\n\n' \
               'Вы также можете выбрать вариант с 0 кол\-вом мест ' \
               'и записаться в лист ожидания на данное время'

    await query.message.edit_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

    context.user_data['key_of_name_show'] = key_of_name_show
    context.user_data['date_show'] = date_show
    context.user_data['name_show'] = name_show

    # Контекст для возврата назад
    context.user_data['text_time'] = text
    context.user_data['keyboard_time'] = reply_markup

    if update.effective_chat.id == CHAT_ID_GROUP_ADMIN:
        return 'LIST'
    else:
        return 'TIME'


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

    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
            'выбрал',
            query.data,
        ]
    ))
    context.user_data["STATE"] = 'TIME'

    time, row_in_googlesheet, number = query.data.split(' | ')

    context.user_data['row_in_googlesheet'] = row_in_googlesheet
    context.user_data['time_of_show'] = time

    if int(number) == 0:
        reserve_hl_logger.info('Мест нет')

        await query.edit_message_reply_markup()

        date = context.user_data['date_show']
        name_show = context.user_data['name_show']
        text = f'Вы выбрали:\n' \
               f'{name_show}\n' \
               f'{date}\n' \
               f'В {time}\n'
        context.user_data['text_for_list_waiting'] = text
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
            text='Вы хотите выбрать другое время '
                 'или записаться в лист ожидания на эту дату и время?',
            reply_markup=reply_markup
        )
        return 'CHOOSING'

    availibale_number_of_seats_now = googlesheets.update_quality_of_seats(
        row_in_googlesheet, 4)

    dict_of_option_for_reserve = utilites.load_option_buy_data()
    # Определение кнопок для inline клавиатуры
    keyboard = []
    list_btn_of_numbers = []
    for key, item in dict_of_option_for_reserve.items():
        quality_of_children = dict_of_option_for_reserve[key].get(
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
    if len(list_btn_of_numbers):
        keyboard.append(list_btn_of_numbers)

    keyboard.append(utilites.add_btn_back_and_cancel())
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправка сообщения пользователю
    text = 'Выберите подходящий вариант бронирования:\n'
    for key, item in dict_of_option_for_reserve.items():
        name = item.get("name")
        name = escape_markdown(name, 2)
        text += f'{DICT_OF_EMOJI_FOR_BUTTON[key]} {name} \| ' \
                f'{item.get("price")} руб\n'
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

    context.bot_data['dict_of_option_for_reserve'] = dict_of_option_for_reserve

    return 'ORDER'


async def check_and_send_buy_info(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
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
    dict_of_option_for_reserve = context.bot_data['dict_of_option_for_reserve']
    chose_reserve_option = dict_of_option_for_reserve.get(
        key_option_for_reserve)
    price = chose_reserve_option.get('price')

    reserve_hl_logger.info(": ".join(
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

        reserve_hl_logger.info(
            f'Для пользователя {context.user_data["user"]}')
        reserve_hl_logger.info(
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
            reserve_hl_logger.info(": ".join(
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
                   f'{availibale_number_of_seats_now}шт\n' \
                   f'Пожалуйста нажмите "Назад" и выберите другое время.'
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup
            )
            return 'ORDER'
        else:
            reserve_hl_logger.info(": ".join(
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

            try:
                googlesheets.confirm(
                    row_in_googlesheet,
                    [new_number_of_seats, new_nonconfirm_number_of_seats]
                )
            except TimeoutError:
                reserve_hl_logger.error(": ".join(
                    [
                        'Для пользователя подтверждение не сработало, гугл не отвечает',
                        str(context.user_data['user'].id),
                        str(context.user_data['user'].full_name),
                        'Номер строки для обновления',
                        row_in_googlesheet,
                    ]
                ))

                keyboard = []
                keyboard.append(utilites.add_btn_back_and_cancel())
                reply_markup = InlineKeyboardMarkup(keyboard)

                text = 'К сожалению произошла непредвиденная ошибка\n' \
                       'Нажмите "Назад" и выберите время повторно.\n' \
                       'Если ошибка повторяется напишите в ЛС в telegram или по ' \
                       'телефону:\n' \
                       'Татьяна Бурганова @Tanya_domik +79159383529'
                await query.message.edit_text(
                    text=text,
                    reply_markup=reply_markup
                )
                return 'ORDER'

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
Вам необходимо сделать оплату в течении 15 мин, или бронь будет отменена.
__________
Для успешного подтверждения брони, после отправки квитанции, необходимо 
заполнить анкету (она придет автоматически)""",
            reply_markup=reply_markup
        )

        context.user_data['chose_reserve_option'] = chose_reserve_option
        context.user_data['key_option_for_reserve'] = key_option_for_reserve
        context.user_data['quality_of_children'] = chose_reserve_option.get(
            'quality_of_children')
        context.chat_data['message_id'] = message.message_id

    return 'PAID'


async def forward_photo_or_file(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
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
    text = context.user_data['text_for_notification_massage']

    res = await context.bot.send_message(
        chat_id=CHAT_ID_GROUP_ADMIN,
        text=f'Квитанция пользователя @{user.username} {user.full_name}\n',
    )
    await update.effective_message.forward(
        chat_id=CHAT_ID_GROUP_ADMIN,
    )
    message_id_for_admin = res.message_id
    await utilites.send_message_to_admin(text, message_id_for_admin, context)

    # Сообщение для опроса
    await update.effective_chat.send_message("""Для подтверждения брони 
заполните пожалуйста анкету.
Чтобы мы знали на кого оформлена бронь и как с вами связаться.
__________
Пожалуйста не пишите лишней информации/дополнительных слов в сообщении. 
Вопросы будут приходить последовательно (их будет всего 3)""")
    await update.effective_chat.send_message(
        'Напишите фамилию и имя (взрослого) на кого оформляете бронь'
    )

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


async def get_name_adult(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["STATE"] = 'PHONE'

    text = update.effective_message.text

    context.user_data['client_data'] = {}
    context.user_data['client_data']['name_adult'] = text

    await update.effective_chat.send_message(
        text='Напишите контактный номер телефона'
    )

    return 'PHONE'


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["STATE"] = 'PHONE'

    text = update.effective_message.text
    text = re.sub(r'[-\s)(+]', '', text)
    text = re.sub(r'^[78]{,2}(?=9)', '', text)

    if len(text) != 10 or text[0] != '9':
        await update.effective_chat.send_message(
            text=f'Возможно вы ошиблись, вы указали {text} \n'
                 'Напишите ваш номер телефона еще раз пожалуйста\n'
                 'Идеальный пример из 10 цифр: 9991234455'
        )
        return 'PHONE'

    context.user_data['client_data']['phone'] = text

    await update.effective_chat.send_message(
        text="""Напишите, имя и возраст ребенка.
Возможные форматы записи:
Сергей 26.08.2019
Иван 1.5
Юля 1г10м
Оля 1год 8мес
__________
Если детей несколько, то напишите пожалуйста всех в одном сообщении (один ребенок = одна строка)
Пожалуйста не используйте дополнительные слова и пунктуацию, кроме тех, что указаны в примерах"""
    )

    return 'CHILDREN'


async def get_name_children(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["STATE"] = 'CHILDREN'

    text = update.effective_message.text
    text_for_message = """Проверьте, что указали дату или возраст правильно
Возможные форматы записи:
Сергей 26.08.2019
Иван 1.5
Юля 1г10м
__________
Если детей несколько, то напишите пожалуйста всех в одном сообщении (один ребенок = одна строка)
Пожалуйста не используйте дополнительные слова и пунктуацию, кроме тех, что указаны в примерах"""

    # Проверка корректности ввода
    count = text.count('\n')
    result = re.findall(
        r'(^\w+ \d ?\w+ ?и? ?\d ?\w+)+|(\w+ (\d+(?:[.,]\d+){0,2}))+',
        text
    )

    if len(result) < count + 1:
        reserve_hl_logger.info('Не верный формат текста')
        await update.effective_chat.send_message(text=text_for_message)
        return 'CHILDREN'

    reserve_hl_logger.info('Проверка пройдена успешно')

    list_message_text = []
    if '\n' in text:
        message_text = text.split('\n')
        for item in message_text:
            list_message_text.append(item.split())
    else:
        message_text = text.split()
        list_message_text.append(message_text)

    if not isinstance(list_message_text[0], list):
        await update.effective_chat.send_message(text=text_for_message)
        return 'CHILDREN'

    context.user_data['client_data']['data_children'] = list_message_text

    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
            'отправил:',
        ],
    ))
    reserve_hl_logger.info(context.user_data['client_data'])

    googlesheets.write_client(
        context.user_data['client_data'],
        context.user_data['row_in_googlesheet'],
        context.user_data['chose_reserve_option']
    )

    text = '\n'.join([
        context.user_data['client_data']['name_adult'],
        context.user_data['client_data']['phone'],
        text,
    ])
    message_id = context.user_data['message_id_for_admin']
    # Возникла ошибка, когда сообщение удалено, то бот по кругу находится в
    # 'CHILDREN' state, написал обходной путь для этого
    await utilites.send_message_to_admin(text, message_id, context)

    await update.effective_chat.send_message(
        'Благодарим за ответы.\nОжидайте, когда администратор подтвердить '
        'бронь.\nЕсли всё хорошо, то вам придет сообщение: "Ваша бронь '
        'подтверждена"\n'
        'В противном случае с вами свяжутся для уточнения деталей')

    text = context.user_data['text_for_notification_massage']
    text += f"""__________
Место проведения:
Офис-центр Малая Покровская, д18, 2 этаж
__________
По вопросам обращайтесь в ЛС в telegram или по телефону:
Татьяна Бурганова @Tanya_domik +79159383529
__________
Если вы хотите оформить еще одну бронь, используйте команду /{COMMAND_DICT[
        "RESERVE"][0]}"""
    answer = await update.effective_chat.send_message(
        text=text
    )
    await update.effective_chat.pin_message(answer.message_id)

    reserve_hl_logger.info(f'Для пользователя {context.user_data["user"]}')
    reserve_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data["STATE"]}')
    context.user_data.clear()

    return ConversationHandler.END


async def conversation_timeout(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
) -> int:
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
        try:
            googlesheets.confirm(
                row_in_googlesheet,
                [old_number_of_seats, old_nonconfirm_number_of_seats]
            )

            reserve_hl_logger.info(": ".join(
                [
                    'Для пользователя',
                    f'{context.user_data["user"]}',
                    'Номер строки для обновления',
                    row_in_googlesheet,
                ]
            ))
        except TimeoutError:
            await update.effective_chat.send_message(
                text=f'Для пользователя {context.user_data["user"]} отклонение в '
                     f'авто-режиме не сработало\n'
                     f'Номер строки для обновления:\n{row_in_googlesheet}'
            )
            reserve_hl_logger.error(TimeoutError)
            reserve_hl_logger.error(": ".join(
                [
                    f'Для пользователя {context.user_data["user"]} отклонение в '
                    f'авто-режиме не сработало',
                    f'{context.user_data["user"]}',
                    'Номер строки для обновления',
                    row_in_googlesheet,
                ]
            ))
    else:
        # TODO Прописать дополнительную обработку states, для этапов опроса
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос'
        )

    reserve_hl_logger.info(": ".join(
        [
            'Пользователь',
            str(context.user_data['user'].id),
            str(context.user_data['user'].full_name),
            'AFK уже 15 мин'
        ]
    ))
    reserve_hl_logger.info(f'Для пользователя {context.user_data["user"]}')
    reserve_hl_logger.info(f'Обработчик завершился на этапе {context.user_data["STATE"]}')

    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)


async def send_clients_data(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    name = context.user_data['name_show']
    date = context.user_data['date_show']
    time = query.data.split(' | ')[0]

    clients_data = utilites.load_clients_data(name, date, time)
    text = f'Список людей для\n{name}\n{date}\n{time}\nОбщее кол-во детей: '
    text += str(len(clients_data))
    for i, item1 in enumerate(clients_data):
        text += '\n__________\n'
        text += str(i + 1) + '| '
        text += item1[1]
        text += '\n+7' + item1[2]
        if item1[3] != '':
            text += '\nИмя ребенка: '
            text += item1[3] + ' '
        if item1[5] != '':
            text += '\nВозраст: '
            text += item1[5] + ' '
        if item1[10] != '':
            text += '\nСпособ брони:\n'
            text += item1[10] + ' '
    await query.edit_message_text(
        text=text
    )
    return ConversationHandler.END


async def write_list_of_waiting(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        text='Напишите контактный номер телефона',
        reply_markup=ReplyKeyboardRemove()
    )
    return 'PHONE_FOR_WAITING'


async def get_phone_for_waiting(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = update.effective_message.text
    text = re.sub(r'[-\s)(+]', '', text)
    text = re.sub(r'^[78]{,2}(?=9)', '', text)

    if len(text) != 10 or text[0] != '9':
        await update.effective_chat.send_message(
            text=f'Возможно вы ошиблись, вы указали {text} \n'
                 'Напишите ваш номер телефона еще раз пожалуйста\n'
                 'Идеальный пример из 10 цифр: 9991234455'
        )
        return 'PHONE'

    text = context.user_data['text_for_list_waiting'] + '+7' + text

    user = update.effective_user
    text = f'Пользователь @{user.username} {user.full_name}\n' \
           f'Запросил добавление в лист ожидания\n' + text
    await context.bot.send_message(
        chat_id=CHAT_ID_GROUP_ADMIN,
        text=text,
    )
    await update.effective_chat.send_message(
        text="""Вы добавлены в лист ожидания, если место освободится, то с вами свяжутся.
    Если у вас есть вопросы, вы можете связаться самостоятельно в telegram @Tanya_domik или по телефону +79159383529"""
    )

    return ConversationHandler.END

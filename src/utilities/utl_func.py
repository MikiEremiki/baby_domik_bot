import logging
import os
import re
from pprint import pformat
from typing import List, Union, Optional

from telegram import (
    Update,
    BotCommand, BotCommandScopeDefault,
    BotCommandScopeChat, BotCommandScopeChatAdministrators,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup,
    constants,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
    ExtBot,
    Application,
)
from telegram.error import BadRequest

from db.db_googlesheets import (
    load_date_show_data, load_ticket_data, load_list_show
)
from settings.settings import (
    COMMAND_DICT, CHAT_ID_MIKIEREMIKI,
    ADMIN_CHAT_ID, ADMIN_GROUP_ID, ADMIN_ID, SUPERADMIN_CHAT_ID,
    LIST_TOPICS_NAME,
)
from utilities.schemas.context_user_data import context_user_data

utilites_logger = logging.getLogger('bot.utilites')


def add_btn_back_and_cancel(
        add_cancel_btn=True,
        postfix_for_cancel=None,
        add_back_btn=True,
        postfix_for_back=None
) -> List[InlineKeyboardButton]:
    """
    :param add_cancel_btn: Опциональное добавление кнопки Отменить
    :param add_back_btn: Опциональное добавление кнопки Назад
    :param postfix_for_cancel: Добавление дополнительной приписки для
    корректного определения случая при использовании Отменить
    :param postfix_for_back: Добавление дополнительной приписки для
    корректного определения случая при использовании Назад
    :return: List[InlineKeyboardButton]
    """
    list_btn = []

    if add_back_btn:
        list_btn.append(create_btn('Назад', postfix_for_back))
    if add_cancel_btn:
        list_btn.append(create_btn('Отменить', postfix_for_cancel))
    return list_btn


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    utilites_logger.info(
        f'{update.effective_user.id}: '
        f'{update.effective_user.full_name} '
        f'Вызвал команду echo'
    )
    text = ('chat_id = <code>' +
            str(update.effective_chat.id) + '</code>\n' +
            'user_id = <code>' +
            str(update.effective_user.id) + '</code>\n' +
            'is_forum = <code>' +
            str(update.effective_chat.is_forum) + '</code>\n' +
            'message_thread_id = <code>' +
            str(update.message.message_thread_id) + '</code>')
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode=constants.ParseMode.HTML,
        message_thread_id=update.effective_message.message_thread_id
    )


async def clean_context_on_end_handler(logger, context):
    logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')
    if context.user_data.get('common_data', False):
        context.user_data['common_data'].clear()
    if context.user_data.get('birthday_user_data', False):
        context.user_data['birthday_user_data'].clear()
    if context.user_data.get('reserve_user_data', False):
        context.user_data['reserve_user_data'].clear()
    context.user_data.pop('STATE')
    context.user_data.pop('command')
    if context.user_data.get('STATE', False):
        context.user_data['STATE'].clear()
    if context.user_data.get('command', False):
        context.user_data['command'].clear()


async def delete_message_for_job_in_callback(
        context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.delete_message(
        chat_id=context.job.chat_id,
        message_id=context.job.data
    )


async def set_menu(bot: ExtBot) -> None:
    utilites_logger.info('Начало настройки команд')
    default_commands = [
        BotCommand(COMMAND_DICT['START'][0],
                   COMMAND_DICT['START'][1]),
        BotCommand(COMMAND_DICT['RESERVE'][0],
                   COMMAND_DICT['RESERVE'][1]),
        BotCommand(COMMAND_DICT['BD_ORDER'][0],
                   COMMAND_DICT['BD_ORDER'][1]),
    ]
    admin_group_commands = [
        BotCommand(COMMAND_DICT['LIST'][0],
                   COMMAND_DICT['LIST'][1]),
        BotCommand(COMMAND_DICT['LIST_WAIT'][0],
                   COMMAND_DICT['LIST_WAIT'][1]),
    ]
    sub_admin_commands = default_commands + admin_group_commands
    admin_commands = sub_admin_commands + [
        BotCommand(COMMAND_DICT['RESERVE_ADMIN'][0],
                   COMMAND_DICT['RESERVE_ADMIN'][1]),
        BotCommand(COMMAND_DICT['AFISHA'][0],
                   COMMAND_DICT['AFISHA'][1]),
        BotCommand(COMMAND_DICT['ADM_INFO'][0],
                   COMMAND_DICT['ADM_INFO'][1]),
        BotCommand(COMMAND_DICT['UP_T_DATA'][0],
                   COMMAND_DICT['UP_T_DATA'][1]),
        BotCommand(COMMAND_DICT['UP_S_DATA'][0],
                   COMMAND_DICT['UP_S_DATA'][1]),
        BotCommand(COMMAND_DICT['UP_BD_PRICE'][0],
                   COMMAND_DICT['UP_BD_PRICE'][1]),
        BotCommand(COMMAND_DICT['CB_TW'][0],
                   COMMAND_DICT['CB_TW'][1]),
    ]
    backend_commands = [
        BotCommand(COMMAND_DICT['TOPIC_START'][0],
                   COMMAND_DICT['TOPIC_START'][1]),
        BotCommand(COMMAND_DICT['TOPIC_DEL'][0],
                   COMMAND_DICT['TOPIC_DEL'][1]),
        BotCommand(COMMAND_DICT['LOG'][0],
                   COMMAND_DICT['LOG'][1]),
        BotCommand(COMMAND_DICT['ECHO'][0],
                   COMMAND_DICT['ECHO'][1]),
    ]

    superadmin_commands = admin_commands + backend_commands

    for chat_id in ADMIN_GROUP_ID:
        try:
            await bot.set_my_commands(
                commands=admin_group_commands,
                scope=BotCommandScopeChatAdministrators(chat_id=chat_id)
            )
            utilites_logger.info('Команды для админ группы настроены')
        except BadRequest:
            utilites_logger.error(f'Бот не состоит в группе {chat_id}')
    for chat_id in ADMIN_GROUP_ID:
        await bot.set_my_commands(
            commands=sub_admin_commands,
            scope=BotCommandScopeChat(chat_id=chat_id)
        )
    utilites_logger.info('Команды для суб_администраторов настроены')
    for chat_id in ADMIN_CHAT_ID:
        await bot.set_my_commands(
            commands=admin_commands,
            scope=BotCommandScopeChat(chat_id=chat_id)
        )
    utilites_logger.info('Команды для администраторов настроены')
    for chat_id in SUPERADMIN_CHAT_ID:
        await bot.set_my_commands(
            commands=superadmin_commands,
            scope=BotCommandScopeChat(chat_id=chat_id)
        )
    utilites_logger.info('Команды для суперадмина настроены')
    await bot.set_my_commands(
        commands=default_commands,
        scope=BotCommandScopeDefault()
    )
    utilites_logger.info('Команды для всех пользователей настроены')


async def set_description(bot: ExtBot) -> None:
    await bot.set_my_description(
        'Вас приветствует Бот Бэби-театра «Домик»!\n\n'
        'Этот бот поможет вам:\n\n'
        '- забронировать билет на спектакль\n'
        '- приобрести абонемент\n'
        '- посмотреть наличие свободных мест\n'
        '- записаться в лист ожидания\n'
        '- забронировать День рождения с театром «Домик»')
    await bot.set_my_short_description(
        'Бот-помощник в Бэби-театр «Домик»\n\n'
        'Группа в контакте\n'
        'vk.com/baby_theater_domik\n\n'
        'Канал в телеграм\n'
        't.me/babytheater')
    utilites_logger.info('Описания для бота установлены')


def set_ticket_data(application: Application):
    application.bot_data['list_of_tickets'] = load_ticket_data()


def set_show_data(application: Application):
    application.bot_data['dict_show_data'] = load_list_show()


async def send_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document='log/archive/log.txt'
    )
    if context.args[0] == all:
        i = 1
        while os.path.exists(f'log/archive/log.txt.{i}'):
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f'log/archive/log.txt.{i}'
            )
            i += 1


async def send_message_to_admin(
        chat_id: Union[int, str],
        text: str,
        message_id: Optional[Union[int, str]],
        context: ContextTypes.DEFAULT_TYPE,
        thread_id: Optional[int]
) -> None:
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id,
            message_thread_id=thread_id
        )
    except BadRequest as e:
        utilites_logger.error(e)
        utilites_logger.info(": ".join(
            [
                'Для пользователя',
                str(context.user_data['user'].id),
                str(context.user_data['user'].full_name),
                'сообщение на которое нужно ответить, удалено'
            ],
        ))
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            message_thread_id=thread_id
        )


def extract_phone_number_from_text(phone):
    phone = re.sub(r'[-\s)(+]', '', phone)
    return re.sub(r'^[78]{,2}(?=9)', '', phone)


def yrange(n):
    i = 0
    while i < n:
        yield i
        i += 1


async def print_ud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    max_text_len = constants.MessageLimit.MAX_TEXT_LENGTH
    if context.args and update.effective_user.id == CHAT_ID_MIKIEREMIKI:
        chat_id = int(context.args[0])
        context_format = pformat(context.application.user_data.get(chat_id))
        for i in range(len(context_format) // max_text_len + 1):
            start = i * max_text_len
            end = (i + 1) * max_text_len
            if i == len(context_format) // max_text_len:
                await update.effective_chat.send_message(
                    text=context_format[start:]
                )
                break
            await update.effective_chat.send_message(
                text=context_format[start:end]
            )
    elif update.effective_user.id == CHAT_ID_MIKIEREMIKI:
        message = pformat(context.user_data)
        await split_message(context, message)


async def clean_ud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == CHAT_ID_MIKIEREMIKI:
        user_ids = []
        qty_users = len(context.application.user_data)
        for i, key, item in enumerate(context.application.user_data.items()):
            await update.effective_chat.send_message(f'{i} из {qty_users}')
            clean_context(item)
            user_ids.append(key)
        context.application.mark_data_for_update_persistence(user_ids=user_ids)
        await context.application.update_persistence()


async def clean_bd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    param = context.args
    if len(param) == 0:
        await update.effective_chat.send_message(
            'Не было передано ни какого ключа'
        )
    else:
        try:
            del context.bot_data[context.args[0]]
            await update.effective_chat.send_message(
                f'{context.args[0]} ключ успешно удален'
            )
        except KeyError:
            await update.effective_chat.send_message(
                f'{context.args[0]} ключа не существует в bot_data'
            )


def create_keys_for_sort(item):
    a, b = item.split()[0].split('.')
    return b + a


def load_and_concat_date_of_shows():
    list_of_date_show = sorted(load_date_show_data(),
                               key=create_keys_for_sort)
    text_date = '\n'.join(item for item in list_of_date_show)
    return ('\n__________\nВ следующие даты проводятся спектакли, поэтому их '
            'не указывайте:'
            f'\n{text_date}')


async def request_contact_location(
        update: Update,
        _: ContextTypes.DEFAULT_TYPE
):
    location_keyboard = KeyboardButton(text="send_location",
                                       request_location=True)
    contact_keyboard = KeyboardButton(text="send_contact",
                                      request_contact=True)
    custom_keyboard = [[location_keyboard, contact_keyboard]]
    reply_markup = ReplyKeyboardMarkup(custom_keyboard,
                                       resize_keyboard=True,
                                       one_time_keyboard=True)
    await update.effective_user.send_message(
        text="Не могли бы вы поделиться со мной своими местоположением и "
             "контактами?",
        reply_markup=reply_markup
    )


async def get_location(
        update: Update,
        _: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        'Вы можете выбрать другую команду',
        reply_markup=ReplyKeyboardRemove()
    )
    print(update.message.location)


async def get_contact(
        update: Update,
        _: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        'Вы можете выбрать другую команду',
        reply_markup=ReplyKeyboardRemove()
    )
    print(update.message.contact)


def create_btn(text, postfix_for_callback):
    callback_data = text
    if postfix_for_callback:
        callback_data += f'-{postfix_for_callback}'
    btn = InlineKeyboardButton(
        text,
        callback_data=callback_data
    )
    return btn


def is_admin(update: Update):
    is_admin_flag = update.effective_user.id in ADMIN_ID
    text = ": ".join(
        [
            'Пользователь',
            str(update.effective_user.id),
            str(update.effective_user.full_name),
        ],
    )
    if is_admin_flag:
        text += ': Является администратором'
    else:
        text += ': Не является администратором'
    utilites_logger.info(text)

    return is_admin_flag


async def _bot_is_admin(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    admins = await update.effective_chat.get_administrators()
    admins = [admin.user.id for admin in admins]
    if context.bot.id not in admins:
        await update.effective_message.reply_text(
            text='Предоставьте боту права на управление темами',
            reply_to_message_id=update.message.id,
            message_thread_id=update.message.message_thread_id
        )
        return False
    return True


async def create_or_connect_topic(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    if not await _bot_is_admin(update, context):
        return

    dict_topics_name = context.bot_data.setdefault('dict_topics_name', {})
    if context.args:
        topic_id = int(context.args[0])
        name = ' '.join([item for item in context.args[1:]])
        try:
            await update.effective_chat.send_message(
                text='Топик готов к работе',
                message_thread_id=topic_id
            )
            context.bot_data['dict_topics_name'][name] = topic_id
        except Exception as e:
            utilites_logger.error(e)
    elif len(dict_topics_name) == 0:
        try:
            for name in LIST_TOPICS_NAME:
                topic = await update.effective_chat.create_forum_topic(
                    name=name
                )
                context.bot_data[
                    'dict_topics_name'][name] = topic.message_thread_id
        except Exception as e:
            utilites_logger.error(e)
    else:
        text = f'Используемые топики:\n{context.bot_data['dict_topics_name']}'
        text_bad_topic = '\n\nНе рабочие топики:'
        for name, topic_id in context.bot_data['dict_topics_name'].items():
            try:
                await update.effective_chat.send_message(
                    text='Топик готов к работе',
                    message_thread_id=topic_id
                )
            except Exception as e:
                utilites_logger.error(e)
                text_bad_topic += f'\n{name}: {topic_id}'
        if text_bad_topic != '\n\nНе рабочие топики:':
            text = text + text_bad_topic
        await update.effective_message.reply_text(
            text=text,
            reply_to_message_id=update.message.id,
            message_thread_id=update.message.message_thread_id
        )


async def del_topic(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    if not await _bot_is_admin(update, context):
        return

    if context.args:
        name = ' '.join([item for item in context.args])
        try:
            context.bot_data['dict_topics_name'].pop(name)
            await update.effective_chat.send_message(
                text=f'Удален ключ: {name}',
                message_thread_id=update.message.message_thread_id
            )
        except KeyError as e:
            await update.effective_chat.send_message(
                text=f'{e}\nПроверьте ключ',
                message_thread_id=update.message.message_thread_id
            )
    else:
        await update.effective_chat.send_message(
            text='Необходимо указать ключ, который требуется удалить'
        )


def set_back_context(
        context: ContextTypes.DEFAULT_TYPE,
        state,
        text,
        reply_markup: InlineKeyboardMarkup,
):
    context.user_data['reserve_user_data']['back'][state] = {}
    dict_back = context.user_data['reserve_user_data']['back'][state]
    dict_back['text'] = text
    dict_back['keyboard'] = reply_markup


def get_back_context(
        context: ContextTypes.DEFAULT_TYPE,
        state,
):
    dict_back = context.user_data['reserve_user_data']['back'][state]
    return dict_back['text'], dict_back['keyboard']


def clean_context(context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context, dict):
        list_keys = list(context.keys())
        tmp_context = context
    else:
        list_keys = list(context.user_data.keys())
        tmp_context = context.user_data
    for key in list_keys:
        if key not in context_user_data:
            value = tmp_context.pop(key)
            utilites_logger.info(f'{key}: {value} больше не используется')


def extract_command(text):
    if '@' in text:
        text = text.split('@')[0]
    return text.replace('/', '')


async def split_message(context, message: str):
    max_text_len = constants.MessageLimit.MAX_TEXT_LENGTH
    if len(message) >= max_text_len:
        for i in range(len(message) // max_text_len + 1):
            start = i * max_text_len
            end = (i + 1) * max_text_len
            if i == len(message) // max_text_len:
                await context.bot.send_message(
                    chat_id=CHAT_ID_MIKIEREMIKI,
                    text='<pre>' + message[start:] + '</pre>',
                    parse_mode=ParseMode.HTML
                )
                break
            await context.bot.send_message(
                chat_id=CHAT_ID_MIKIEREMIKI,
                text='<pre>' + message[start:end] + '</pre>',
                parse_mode=ParseMode.HTML
            )
    else:
        await context.bot.send_message(
            chat_id=CHAT_ID_MIKIEREMIKI,
            text='<pre>' + message + '</pre>',
            parse_mode=ParseMode.HTML
        )

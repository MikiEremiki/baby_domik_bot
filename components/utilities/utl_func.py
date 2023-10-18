import logging
import os
import re
from pprint import pprint
from typing import List, Union

from telegram import (
    Update,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    BotCommandScopeChatAdministrators,
    constants,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    ExtBot,
)
from telegram.error import BadRequest

from db.db_googlesheets import load_date_show_data
from utilities.settings import (
    COMMAND_DICT,
    CHAT_ID_MIKIEREMIKI,
    ADMIN_GROUP_ID,
    ADMIN_CHAT_ID,
)

utilites_logger = logging.getLogger('bot.utilites')


def add_btn_back_and_cancel(
        postfix_for_callback=None
) -> List[InlineKeyboardButton]:
    """
    :param postfix_for_callback: Добавление дополнительной приписки для
    корректного определения случая при использовании отмены
    :return: List
    """
    callback_data = 'Отменить'
    if postfix_for_callback:
        callback_data += f'-{postfix_for_callback}'
    button_back = InlineKeyboardButton(
        'Назад',
        callback_data='Назад'
    )
    button_cancel = InlineKeyboardButton(
        'Отменить',
        callback_data=callback_data
    )
    return [button_back, button_cancel]


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
        parse_mode=constants.ParseMode.HTML
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> -1:
    utilites_logger.info(
        f'{update.effective_user.id}: '
        f'{update.effective_user.full_name}\n'
        f'Вызвал команду reset'
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text='Попробуйте выполнить новый запрос'
    )
    utilites_logger.info(
        f'Обработчик завершился на этапе {context.user_data["STATE"]}')

    context.user_data.clear()
    return ConversationHandler.END


async def delete_message_for_job_in_callback(
        context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.delete_message(
        chat_id=context.job.chat_id,
        message_id=context.job.data
    )


async def set_menu(bot: ExtBot) -> None:
    utilites_logger.info('Начало настройки команд')
    default_commands = [
        BotCommand(COMMAND_DICT['START'][0], COMMAND_DICT['START'][1]),
        BotCommand(COMMAND_DICT['RESERVE'][0], COMMAND_DICT['RESERVE'][1]),
        BotCommand(COMMAND_DICT['BD_ORDER'][0], COMMAND_DICT['BD_ORDER'][1]),
    ]
    admin_group_commands = [
        BotCommand(COMMAND_DICT['LIST'][0], COMMAND_DICT['LIST'][1]),
        BotCommand(COMMAND_DICT['LOG'][0], COMMAND_DICT['LOG'][1]),
        BotCommand(COMMAND_DICT['ECHO'][0], COMMAND_DICT['ECHO'][1]),
    ]
    admin_commands = default_commands + admin_group_commands
    admin_commands += [
        BotCommand(COMMAND_DICT['CB_TW'][0], COMMAND_DICT['CB_TW'][1]),
        BotCommand(COMMAND_DICT['AFISHA'][0], COMMAND_DICT['AFISHA'][1]),
    ]

    for chat_id in ADMIN_GROUP_ID:
        try:
            await bot.set_my_commands(
                commands=admin_group_commands,
                scope=BotCommandScopeChatAdministrators(chat_id=chat_id)
            )
            utilites_logger.info('Команды для админ группы настроены')
        except BadRequest:
            utilites_logger.error(f'Бот не состоит в группе {chat_id}')
    for chat_id in ADMIN_CHAT_ID:
        await bot.set_my_commands(
            commands=admin_commands,
            scope=BotCommandScopeChat(chat_id=chat_id)
        )
        utilites_logger.info('Команды для администраторов настроены')
    await bot.set_my_commands(
        commands=default_commands,
        scope=BotCommandScopeDefault()
    )
    utilites_logger.info('Команды для всех пользователей настроены')


async def set_description(bot: ExtBot) -> None:
    await bot.set_my_description("""Вас приветствует Бэби-театре Домик!

    Этот бот поможет вам:

    - забронировать билет на спектакль
    - приобрести абонемент
    - посмотреть наличие свободных мест
    - записаться в лист ожидания 
    - забронировать День рождения с театром «Домик»""")
    await bot.set_my_short_description(
        'Бот-помощник в Бэби-театр «Домик»')
    utilites_logger.info('Описания для бота установлены')


async def send_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document='log/log.txt'
        )
        i = 1
        while os.path.exists(f'log/log.txt.{i}'):
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f'log/log.txt.{i}'
            )
            i += 1
    except FileExistsError:
        utilites_logger.info('Файл логов не найден')


async def send_message_to_admin(
        chat_id: Union[int, str],
        text: str,
        message_id: Union[int, str],
        context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=message_id
        )
    except BadRequest:
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
    if update.effective_user.id == CHAT_ID_MIKIEREMIKI:
        pprint(context.application.user_data)


async def clean_ud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == CHAT_ID_MIKIEREMIKI:
        for key, item in context.application.user_data.items():
            if context.application.user_data[key].get('dict_of_name_show_v2'):
                del context.application.user_data[key]['dict_of_name_show_v2']
            if context.application.user_data[key].get('dict_of_shows'):
                del context.application.user_data[key]['dict_of_shows']
            if context.application.user_data[key].get('date_show'):
                del context.application.user_data[key]['date_show']
            if context.application.user_data[key].get('name_show'):
                del context.application.user_data[key]['name_show']
            if context.application.user_data[key].get('dict_of_name_show_flip'):
                del context.application.user_data[key]['dict_of_name_show_flip']
            if context.application.user_data[key].get('text_date'):
                del context.application.user_data[key]['text_date']
            if context.application.user_data[key].get('keyboard_date'):
                del context.application.user_data[key]['keyboard_date']
            if context.application.user_data[key].get('keyboard_time'):
                del context.application.user_data[key]['keyboard_time']
            if context.application.user_data[key].get(
                    'text_for_notification_massage'):
                del context.application.user_data[key][
                    'text_for_notification_massage']
            if context.application.user_data[key].get('text_time'):
                del context.application.user_data[key]['text_time']
            if context.application.user_data[key].get('birthday_data'):
                del context.application.user_data[key]['birthday_data']
            utilites_logger.info(key)
            utilites_logger.info(item.get('user', 'Нет такого'))
            context.application.mark_data_for_update_persistence(key)
            await context.application.update_persistence()


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
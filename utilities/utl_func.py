import logging
import os
import re
from typing import List, Union

from telegram import (
    Update,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    BotCommandScopeChatAdministrators,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler
)
from telegram.error import BadRequest

from db.db_googlesheets import load_date_show_data
from utilities.settings import (
    COMMAND_DICT,
    CHAT_ID_MIKIEREMIKI,
    ADMIN_GROUP_ID,
    ADMIN_CHAT_ID,
    ADMIN_ID,
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
        f'{update.effective_user.full_name}\n'
        f'Вызвал команду echo'
    )
    text = ' '.join([
        str(update.effective_chat.id),
        'from',
        str(update.effective_user.id)
    ])
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text
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


async def set_menu(context: ContextTypes.DEFAULT_TYPE) -> None:
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
    ]

    for chat_id in ADMIN_GROUP_ID:
        try:
            await context.bot.set_my_commands(
                commands=admin_group_commands,
                scope=BotCommandScopeChatAdministrators(chat_id=chat_id)
            )
        except BadRequest:
            utilites_logger.error(f'Бот не состоит в группе {chat_id}')
    for chat_id in ADMIN_CHAT_ID:
        await context.bot.set_my_commands(
            commands=admin_commands,
            scope=BotCommandScopeChat(chat_id=chat_id)
        )
    await context.bot.set_my_commands(
        commands=default_commands,
        scope=BotCommandScopeDefault()
    )


async def set_description(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.set_my_description("""Вас приветствует Бэби-театре Домик!

    Этот бот поможет вам:

    - забронировать билет на спектакль
    - приобрести абонемент
    - посмотреть наличие свободных мест
    - записаться в лист ожидания 
    - забронировать День рождения с театром «Домик»""")
    await context.bot.set_my_short_description(
        'Бот-помощник в Бэби-театр «Домик»')


async def send_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id in ADMIN_ID:
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


def print_ud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == CHAT_ID_MIKIEREMIKI:
        print(context.application.user_data.keys())


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

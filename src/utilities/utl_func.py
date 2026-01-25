import datetime
import logging
import os
import re
from datetime import time
from pprint import pformat
from typing import List, Sequence, Tuple, Optional

import pytz
from telegram import (
    Update,
    BotCommand, BotCommandScopeDefault,
    BotCommandScopeChat, BotCommandScopeChatAdministrators,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup,
    constants,
)
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, ExtBot
from telegram.error import BadRequest

from db import ScheduleEvent, db_postgres, TheaterEvent, Ticket, BaseTicket
from db.enum import TicketStatus
from settings import parse_settings
from settings.settings import (
    COMMAND_DICT, CHAT_ID_MIKIEREMIKI,
    ADMIN_CHAT_ID, ADMIN_GROUP_ID, ADMIN_ID, SUPERADMIN_CHAT_ID,
    LIST_TOPICS_NAME, SUPPORT_DATA,
    DICT_CONVERT_WEEKDAY_NUMBER_TO_STR, DICT_OF_EMOJI_FOR_BUTTON
)
from utilities.schemas import context_user_data

utilites_logger = logging.getLogger('bot.utilites')


async def echo(update: Update, context: 'ContextTypes.DEFAULT_TYPE') -> None:
    utilites_logger.info(
        f'{update.effective_user.id}: '
        f'{update.effective_user.full_name} '
        f'Вызвал команду echo'
    )

    chat = update.effective_chat
    user = update.effective_user
    chat_id = str(chat.id)
    user_id = str(user.id)
    is_forum = str(chat.is_forum)

    text = 'chat_id = <code>' + chat_id + '</code>\n'
    text += 'user_id = <code>' + user_id + '</code>\n'
    text += 'is_forum = <code>' + is_forum + '</code>\n'

    try:
        message = update.effective_message
        message_thread_id = str(message.message_thread_id)
        topic_name = str(message.reply_to_message.forum_topic_created.name)

        text += 'message_thread_id = <code>' + message_thread_id + '</code>\n'
        text += 'topic_name = <code>' + topic_name + '</code>\n'

        message_thread_id = message.message_thread_id
    except (AttributeError, BadRequest):
        message_thread_id = None

    await context.bot.send_message(
        chat_id=chat.id,
        text=text,
        message_thread_id=message_thread_id
    )


async def clean_context_on_end_handler(logger, context):
    if context.user_data.get('STATE', False):
        logger.info(
            f'Обработчик завершился на этапе {context.user_data['STATE']}')
        context.user_data.pop('STATE')
    else:
        logger.info('STATE не задан')

    if context.user_data.get('command', False):
        context.user_data.pop('command')
    if context.user_data.get('common_data', False):
        context.user_data.pop('common_data')
    if context.user_data.get('birthday_user_data', False):
        context.user_data.pop('birthday_user_data')
    if context.user_data.get('reserve_user_data', False):
        context.user_data.pop('reserve_user_data')
    if context.user_data.get('reserve_admin_data', False):
        context.user_data.pop('reserve_admin_data')


async def delete_message_for_job_in_callback(
        context: 'ContextTypes.DEFAULT_TYPE') -> None:
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
        BotCommand(COMMAND_DICT['MIGRATION_ADMIN'][0],
                   COMMAND_DICT['MIGRATION_ADMIN'][1]),
        BotCommand(COMMAND_DICT['AFISHA'][0],
                   COMMAND_DICT['AFISHA'][1]),
        BotCommand(COMMAND_DICT['ADM_INFO'][0],
                   COMMAND_DICT['ADM_INFO'][1]),
        BotCommand(COMMAND_DICT['UP_BD_PRICE'][0],
                   COMMAND_DICT['UP_BD_PRICE'][1]),
        BotCommand(COMMAND_DICT['CB_TW'][0],
                   COMMAND_DICT['CB_TW'][1]),
        BotCommand(COMMAND_DICT['SETTINGS'][0],
                   COMMAND_DICT['SETTINGS'][1]),
    ]
    backend_commands = [
        BotCommand(COMMAND_DICT['TOPIC'][0],
                   COMMAND_DICT['TOPIC'][1]),
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
        '- забронировать билет на мероприятие\n'
        '- приобрести абонемент\n'
        '- посмотреть наличие свободных мест\n'
        '- записаться в лист ожидания\n'
        '- забронировать День рождения с театром «Домик»\n\n'
        'https://t.me/theater_domik\nКанал театра в телеграмм'
        ' с удобным делением по темам\n\n'
        'Для начала работы с ботом нажмите /start')
    await bot.set_my_short_description(
        'Бот-помощник в Бэби-театр «Домик»\n\n'
        'Канал в телеграм\n'
        'https://t.me/theater_domik')
    utilites_logger.info('Описания для бота установлены')


async def send_log(update: Update, context: 'ContextTypes.DEFAULT_TYPE') -> None:
    caption = [0]
    i = 1
    while os.path.exists(f'log/archive/log.txt.{i}'):
        caption.append(i)
        i += 1
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document='log/archive/log.txt',
        caption=caption
    )
    if context.args:
        try:
            num = int(context.args[0])
            if os.path.exists(f'log/archive/log.txt.{num}'):
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f'log/archive/log.txt.{num}'
                )
        except ValueError:
            pass
        if context.args[0] == 'all':
            i = 1
            while os.path.exists(f'log/archive/log.txt.{i}'):
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f'log/archive/log.txt.{i}'
                )
                i += 1


async def send_postgres_log(update: Update,
                            context: 'ContextTypes.DEFAULT_TYPE') -> None:
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document='log/archive/postgres_log.txt'
    )
    if context.args:
        if context.args[0] == 'all':
            i = 1
            while os.path.exists(f'log/archive/postgres_log.txt.{i}'):
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f'log/archive/postgres_log.txt.{i}'
                )
                i += 1


def extract_phone_number_from_text(phone):
    phone = re.sub(r'[-\s)(+]', '', phone)
    return re.sub(r'^[78]{,2}(?=9)', '', phone)


def yrange(n):
    i = 0
    while i < n:
        yield i
        i += 1


async def print_ud(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
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


async def clean_ud(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    if update.effective_user.id == CHAT_ID_MIKIEREMIKI:
        user_ids = []
        qty_users = len(context.application.user_data)
        i = 1
        for key, item in context.application.user_data.items():
            await update.effective_chat.send_message(
                f'{key}:{i} из {qty_users}')
            await clean_context(item)
            user_ids.append(key)
            i += 1
        context.application.mark_data_for_update_persistence(user_ids=user_ids)
        await context.application.update_persistence()


async def clean_bd(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
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


async def request_contact_location(
        update: Update,
        _: 'ContextTypes.DEFAULT_TYPE'
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
        _: 'ContextTypes.DEFAULT_TYPE'
):
    await update.effective_chat.send_message(
        'Вы можете выбрать другую команду',
        reply_markup=ReplyKeyboardRemove()
    )
    print(update.message.location)


async def get_contact(
        update: Update,
        _: 'ContextTypes.DEFAULT_TYPE'
):
    await update.effective_chat.send_message(
        'Вы можете выбрать другую команду',
        reply_markup=ReplyKeyboardRemove()
    )
    print(update.message.contact)


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
        context: 'ContextTypes.DEFAULT_TYPE'
):
    admins = await update.effective_chat.get_administrators()
    admins = [admin.user.id for admin in admins]
    if context.bot.id not in admins:
        await update.effective_message.reply_text(
            text='Предоставьте боту права на управление темами',
            reply_to_message_id=update.message.id,
            message_thread_id=update.effective_message.message_thread_id
        )
        return False
    return True


async def create_or_connect_topic(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    if not await _bot_is_admin(update, context):
        return

    dict_topics_name = context.bot_data.setdefault('dict_topics_name', {})
    topic_ready = 'Топик готов к работе'
    if len(context.args) == 2:
        topic_id = int(context.args[0])
        name = ' '.join([item for item in context.args[1:]])
        try:
            await update.effective_chat.send_message(
                text=topic_ready,
                message_thread_id=topic_id
            )
            context.bot_data['dict_topics_name'][name] = topic_id
        except Exception as e:
            utilites_logger.error(e)
    elif len(context.args) == 0:
        text = f'Используемые топики:\n{context.bot_data['dict_topics_name']}'
        text_bad_topic = '\n\nНе рабочие топики:'
        for name, topic_id in context.bot_data['dict_topics_name'].items():
            try:
                await update.effective_chat.send_message(
                    text=topic_ready,
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
            message_thread_id=update.effective_message.message_thread_id
        )
    elif context.args[0] == 'create' and len(dict_topics_name) == 0:
        try:
            for name in LIST_TOPICS_NAME:
                topic = await update.effective_chat.create_forum_topic(
                    name=name
                )
                topic_id = topic.message_thread_id
                context.bot_data['dict_topics_name'][name] = topic_id
                await update.effective_chat.send_message(
                    text=topic_ready,
                    message_thread_id=topic_id
                )
        except Exception as e:
            utilites_logger.error(e)
    elif context.args[0] == 'connect':
        name = update.effective_message.reply_to_message.forum_topic_created.name
        topic_id = update.effective_message.message_thread_id
        if name in LIST_TOPICS_NAME:
            context.bot_data['dict_topics_name'][name] = topic_id
            await update.effective_chat.send_message(
                text=topic_ready,
                message_thread_id=topic_id
            )


async def del_topic(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    if not await _bot_is_admin(update, context):
        return

    if context.args:
        name = ' '.join([item for item in context.args])
        message_thread_id = update.effective_message.message_thread_id
        try:
            context.bot_data['dict_topics_name'].pop(name)
            await update.effective_chat.send_message(
                text=f'Удален ключ: {name}',
                message_thread_id=message_thread_id
            )
        except KeyError as e:
            await update.effective_chat.send_message(
                text=f'{e}\nПроверьте ключ',
                message_thread_id=message_thread_id
            )
    else:
        await update.effective_chat.send_message(
            text='Необходимо указать ключ, который требуется удалить'
        )


async def set_back_context(
        context: 'ContextTypes.DEFAULT_TYPE',
        state,
        text,
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup,
        del_message_ids: List[int] = None
):
    context.user_data['reserve_user_data']['back'][state] = {}
    dict_back = context.user_data['reserve_user_data']['back'][state]
    dict_back['text'] = text
    dict_back['keyboard'] = reply_markup
    dict_back['del_message_ids'] = del_message_ids if del_message_ids else []


async def get_back_context(
        context: 'ContextTypes.DEFAULT_TYPE',
        state,
):
    dict_back = context.user_data['reserve_user_data']['back'][state]
    return (
        dict_back['text'],
        dict_back['keyboard'],
        dict_back['del_message_ids']
    )


async def append_message_ids_back_context(
        context: 'ContextTypes.DEFAULT_TYPE',
        del_message_ids: List[int] = None
):
    state = context.user_data['STATE']
    dict_back = context.user_data['reserve_user_data']['back'][state]
    if del_message_ids:
        dict_back['del_message_ids'].extend(del_message_ids)


async def clean_context(context: 'ContextTypes.DEFAULT_TYPE'):
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
    if not text.startswith('/'):
        return
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
                )
                break
            await context.bot.send_message(
                chat_id=CHAT_ID_MIKIEREMIKI,
                text='<pre>' + message[start:end] + '</pre>',
            )
    else:
        await context.bot.send_message(
            chat_id=CHAT_ID_MIKIEREMIKI,
            text='<pre>' + message + '</pre>',
        )


async def update_config(_: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    config = parse_settings()
    context.config = config
    utilites_logger.info(
        'Параметры из settings.yml загружены')


async def update_settings(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    from utilities.settings_parser import sync_settings_to_db, load_bot_settings
    from utilities.utl_db import open_session

    session = await open_session(context.config)
    try:
        await sync_settings_to_db(session)
        await load_bot_settings(context.application)
        await update.effective_chat.send_message(
            "Настройки синхронизированы из файла и загружены в бота.")
    except Exception as e:
        await update.effective_chat.send_message(
            f"Ошибка при синхронизации настроек: {e}")
    finally:
        await session.close()


def check_phone_number(phone):
    if len(phone) != 10 or phone[0] != '9':
        return True
    else:
        return False


def create_approve_and_reject_replay(
        callback_name,
        data: str
):
    keyboard = []

    button_approve = InlineKeyboardButton(
        "Подтвердить",
        callback_data=f'confirm-{callback_name}|{data}'
    )

    button_cancel = InlineKeyboardButton(
        "Отклонить",
        callback_data=f'reject-{callback_name}|{data}'
    )
    keyboard.append([button_approve, button_cancel])
    return InlineKeyboardMarkup(keyboard)


def add_text_of_show_and_numerate(
        text,
        dict_of_name_show: dict,
        filter_theater_event_id: dict,
        dict_show_data: dict = None,
):
    for key in filter_theater_event_id.keys():
        for name, item in dict_of_name_show.items():
            if key == item:
                for show in dict_show_data.values():
                    if show['name'] == name:
                        text += (
                            f'{DICT_OF_EMOJI_FOR_BUTTON[filter_theater_event_id[item]]}'
                            f' {show['full_name']}\n')
    return text


async def clean_replay_kb_and_send_typing_action(update):
    message = await send_and_del_message_to_remove_kb(update)
    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)
    return message


async def render_text_for_choice_time(theater_event, schedule_events):
    full_name = get_full_name_event(theater_event)
    event = schedule_events[0]
    weekday = int(event.datetime_event.strftime('%w'))
    date_event = (event.datetime_event.strftime('%d.%m ') +
                  f'({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]})')
    text = (f'Вы выбрали:\n'
            f'<b>{full_name}\n'
            f'{date_event}</b>\n\n')
    return text


async def send_and_del_message_to_remove_kb(update: Update):
    return await update.effective_chat.send_message(
        text='Загружаем данные',
        reply_markup=ReplyKeyboardRemove(),
        message_thread_id=update.effective_message.message_thread_id
    )


def get_unique_months(events: Sequence[ScheduleEvent]):
    unique_sorted_months = []
    months = {}
    years = set()
    for event in events:
        year = event.datetime_event.year
        month = event.datetime_event.month
        years.add(year)
        months.setdefault(year, set())
        months[year].add(month)
    years = sorted(years)
    for year in years:
        unique_sorted_months.extend(sorted(months[year]))
    return unique_sorted_months


def _format_age_banner(min_age_child: int, max_age_child: Optional[int]) -> str:
    banner = ''
    if min_age_child > 0:
        banner += '👶🏼' + str(min_age_child)
    if max_age_child is not None and max_age_child > 0:
        banner += '-' + str(max_age_child)
    elif min_age_child > 0:
        # если есть минимальный возраст, но нет максимального
        banner += '+'
    return banner

def _format_duration(duration: Optional[time]) -> str:
    if duration is None:
        return ''
    if isinstance(duration, time):
        duration_minutes = duration.hour * 60 + duration.minute
    else:
        return ''
    if duration_minutes <= 0:
        return ''
    parts = ['⏳']
    hours = duration_minutes // 60
    minutes = duration_minutes % 60
    if hours > 0:
        parts.append(f'{hours}ч')
    if minutes > 0:
        parts.append(f'{minutes}мин')
    return ''.join(parts)

def get_full_name_event(event: TheaterEvent, add_note=False):
    name = event.name
    flag_premiere = event.flag_premier
    min_age_child = event.min_age_child
    max_age_child = event.max_age_child
    duration = event.duration
    note = event.note

    full_name: str = name
    full_name += '\n'
    if flag_premiere:
        full_name += '📍'
    age_banner = _format_age_banner(min_age_child, max_age_child)
    if age_banner:
        full_name += age_banner
    duration_banner = _format_duration(duration)
    if duration_banner:
        full_name += duration_banner
    if note and add_note:
        full_name += f'\n<i>{note}</i>'
    return full_name


async def get_time_with_timezone(event, tz_name='Europe/Moscow'):
    text = event.datetime_event.astimezone(
        pytz.timezone(tz_name)).strftime('%H:%M')
    return text


async def get_formatted_date_and_time_of_event(
        schedule_event: ScheduleEvent) -> Tuple[str, str]:
    event = schedule_event
    weekday = int(event.datetime_event.strftime('%w'))
    date_event = (event.datetime_event.strftime('%d.%m ') +
                  f'({DICT_CONVERT_WEEKDAY_NUMBER_TO_STR[weekday]})')
    time_event = await get_time_with_timezone(event)
    return date_event, time_event


async def filter_schedule_event(
        schedule_events: Sequence[ScheduleEvent],
        selected_date,
        theater_event_id,
        only_active=True
) -> Sequence[ScheduleEvent]:
    schedule_events_tmp = []
    for event in schedule_events:
        if (event.datetime_event.date() == selected_date and
                event.theater_event_id == int(theater_event_id) and
                event.flag_turn_in_bot == only_active):
            schedule_events_tmp.append(event)
    schedule_events = schedule_events_tmp
    return schedule_events


async def filter_schedule_event_by_active(
        schedule_events: Sequence[ScheduleEvent],
        only_active=True
) -> Sequence[ScheduleEvent]:
    schedule_events_tmp = []
    for event in schedule_events:
        if only_active and not event.flag_turn_in_bot:
            continue

        schedule_events_tmp.append(event)
    return schedule_events_tmp


async def create_event_names_text(enum_theater_events, text):
    for i, event in enum_theater_events:
        full_name = get_full_name_event(event)
        text += f'{DICT_OF_EMOJI_FOR_BUTTON[i]} {full_name}\n\n'
    return text


async def get_events_for_time_hl(theater_event_id, selected_date, context):
    utilites_logger.info(f'Пользователь выбрал дату: {selected_date}')

    reserve_user_data = context.user_data['reserve_user_data']
    state = context.user_data['STATE']
    schedule_event_ids = reserve_user_data[state]['schedule_event_ids']

    schedule_events = await db_postgres.get_schedule_events_by_ids(
        context.session, schedule_event_ids)
    selected_date = datetime.date.fromisoformat(selected_date)
    schedule_events = await filter_schedule_event(
        schedule_events, selected_date, theater_event_id)
    theater_event: TheaterEvent = await db_postgres.get_theater_event(
        context.session, theater_event_id)
    return schedule_events, theater_event


async def cancel_common(update, text):
    query = update.callback_query
    try:
        await query.delete_message()
    except BadRequest as e:
        utilites_logger.error(e)
    await update.effective_chat.send_message(
        text=text,
        message_thread_id=update.effective_message.message_thread_id,
        reply_markup=ReplyKeyboardRemove()
    )


async def del_messages(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE',
        del_message_ids=None,
):
    ok_del_message_ids = del_message_ids.copy()
    for message_id in ok_del_message_ids:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=message_id
            )
        except BadRequest as e:
            utilites_logger.error(e)
            utilites_logger.info('Сообщение уже удалено')
        del_message_ids.remove(message_id)


async def del_keyboard_messages(update: Update,
                                context: 'ContextTypes.DEFAULT_TYPE'):
    del_keyboard_message_ids = context.user_data['common_data'][
        'del_keyboard_message_ids']
    ok_del_message_ids = del_keyboard_message_ids.copy()
    for message_id in ok_del_message_ids:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=message_id
            )
        except BadRequest as e:
            utilites_logger.error(e)
            utilites_logger.info('Сообщение уже удалено')
        del_keyboard_message_ids.remove(message_id)


async def get_type_event_ids_by_command(command):
    usual = 1
    new_year = 2
    studio = 12
    invited = 14
    mk = 15
    all_types = [usual, new_year, invited, studio, mk]

    type_event_ids = []
    if 'reserve' in command:
        type_event_ids = [usual, new_year, invited, mk]
    if 'studio' in command:
        type_event_ids = [studio]
    if '_admin' in command or 'list' in command:
        type_event_ids = all_types
    return type_event_ids


async def get_emoji(schedule_event: ScheduleEvent):
    text_emoji = ''
    if schedule_event.flag_gift:
        text_emoji += f'{SUPPORT_DATA['Подарок'][0]}'
    if schedule_event.flag_christmas_tree:
        text_emoji += f'{SUPPORT_DATA['Елка'][0]}'
    if schedule_event.flag_santa:
        text_emoji += f'{SUPPORT_DATA['Дед'][0]}'
    return text_emoji


async def add_clients_data_to_text(
        tickets_info: List[Tuple[BaseTicket, Ticket]]):
    text = ''
    for base_ticket, ticket in tickets_info:
        adult_str, child_str = await get_child_and_adult_from_ticket(
            ticket)

        text += '\n__________\n'
        text += f'<code>{ticket.id}</code> | {base_ticket.name}'
        text += f'\n<b>{adult_str}</b>'
        text += f'Дети: {child_str}'
        text += f'Статус билета: {ticket.status.value}'
        if ticket.notes:
            text += f'\nПримечание: {ticket.notes}'
    return text


async def get_child_and_adult_from_ticket(ticket):
    people = ticket.people
    adult_str = ''
    child_str = ''
    for person in people:
        if hasattr(person.adult, 'phone'):
            adult_str = f'{person.name}\n+7{person.adult.phone}\n'
        elif hasattr(person.child, 'age'):
            child_str += f'{person.name} {person.child.age}\n'
    return adult_str, child_str


async def add_qty_visitors_to_text(
        tickets_info: List[Tuple[BaseTicket, Ticket]]):
    text = ''
    qty_child = 0
    qty_adult = 0
    for base_ticket, ticket in tickets_info:
        if ticket.status in [TicketStatus.PAID, TicketStatus.APPROVED]:
            qty_child += base_ticket.quality_of_children
            qty_adult += (base_ticket.quality_of_adult +
                          base_ticket.quality_of_add_adult)

    text += '<i>Кол-во посетителей: '
    text += f"д={qty_child}|в={qty_adult}</i>"
    return text


async def create_str_info_by_schedule_event_id(context, choice_event_id):
    schedule_event = await db_postgres.get_schedule_event(
        context.session, choice_event_id)
    theater_event = await db_postgres.get_theater_event(
        context.session, schedule_event.theater_event_id)
    date_event, time_event = await get_formatted_date_and_time_of_event(
        schedule_event)
    full_name = get_full_name_event(theater_event)
    text_emoji = await get_emoji(schedule_event)
    text_select_event = (f'Мероприятие:\n'
                         f'<b>{full_name}\n'
                         f'{date_event}\n'
                         f'{time_event}</b>\n')
    text_select_event += f'{text_emoji}\n' if text_emoji else ''
    return text_select_event


async def get_schedule_event_ids_studio(context):
    studio = context.bot_data['studio']
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    choose_schedule_event_ids = [schedule_event_id]
    if chose_base_ticket.flag_season_ticket:
        for v in studio['Театральный интенсив']:
            if schedule_event_id in v:
                choose_schedule_event_ids = v

    reserve_user_data['choose_schedule_event_ids'] = choose_schedule_event_ids
    return choose_schedule_event_ids

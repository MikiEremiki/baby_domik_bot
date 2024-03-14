import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, TypeHandler, ConversationHandler

from db import db_postgres
from db.enum import PriceType, TicketPriceType
from settings.settings import RESERVE_TIMEOUT
from utilities.schemas.schedule_event import kv_name_attr_schedule_event
from utilities.schemas.theater_event import kv_name_attr_theater_event
from utilities.utl_func import add_btn_back_and_cancel

support_hl_logger = logging.getLogger('bot.support_hl')


def create_keyboard_crud(name: str):
    button_create = InlineKeyboardButton(text='Добавить',
                                         callback_data=f'{name}_event_create')
    button_update = InlineKeyboardButton(text='Изменить',
                                         callback_data=f'{name}_event_update')
    button_delete = InlineKeyboardButton(text='Удалить',
                                         callback_data=f'{name}_event_delete')
    button_select = InlineKeyboardButton(text='Посмотреть',
                                         callback_data=f'{name}_event_select')
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=False)
    keyboard = [
        [button_create, ],
        [button_update, ],
        [button_delete, ],
        [button_select, ],
        [*button_cancel, ],
    ]

    return InlineKeyboardMarkup(keyboard)


def create_keyboard_confirm():
    button_accept = InlineKeyboardButton(text='Подтвердить',
                                         callback_data='accept')
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=False)
    keyboard = [
        [button_accept, ],
        [*button_cancel, ],
    ]

    return InlineKeyboardMarkup(keyboard)


def get_validated_data(string, option):
    query = string.split('\n')
    data = {}
    for kv in query:
        key, value = kv.split('=')
        validated_value = validate_value(value, option)
        for k, v in kv_name_attr_schedule_event.items():
            if key == v:
                data[k] = validated_value
    return data


async def start_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    button_db = InlineKeyboardButton(text='База данных', callback_data='db')
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=False)
    keyboard = [
        [button_db, ],
        [*button_cancel, ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите что хотите настроить'
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    return 1


async def choice_db_settings(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    button_event = InlineKeyboardButton(text='Репертуар',
                                        callback_data='theater_event')
    button_schedule = InlineKeyboardButton(text='Расписание',
                                           callback_data='schedule_event')
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=False)
    keyboard = [
        [button_event, button_schedule],
        [*button_cancel, ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите что хотите настроить'
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    return 2


async def theater_event_settings(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    reply_markup = create_keyboard_crud('theater')

    text = 'Выберите что хотите настроить'
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['reply_markup'] = reply_markup
    return 3


async def schedule_event_settings(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    reply_markup = create_keyboard_crud('schedule')

    text = 'Выберите что хотите настроить'
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['reply_markup'] = reply_markup
    return 3


async def theater_event_select(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    res = await db_postgres.get_all_theater_events(context.session)
    text = ''
    for row in res:
        text += str(row[0]) + '\n'

    reply_markup = context.user_data['reply_markup']
    await query.edit_message_text(text,
                                  reply_markup=reply_markup)
    return 3


async def schedule_event_select(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    res = await db_postgres.get_all_schedule_events(context.session)
    text = ''
    for row in res:
        text += str(row[0]) + '\n'

    reply_markup = context.user_data['reply_markup']
    await query.edit_message_text(text,
                                  reply_markup=reply_markup)
    return 3


async def theater_event_preview(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    text = (f'{kv_name_attr_theater_event['name']}=Название\n'
            f'{kv_name_attr_theater_event['min_age_child']}=1\n'
            f'{kv_name_attr_theater_event['max_age_child']}=0\n'
            f'{kv_name_attr_theater_event['show_emoji']}=\n'
            f'{kv_name_attr_theater_event['flag_premier']}=Нет\n'
            f'{kv_name_attr_theater_event['flag_active_repertoire']}=Да\n'
            f'{kv_name_attr_theater_event['flag_active_bd']}=Нет\n'
            f'{kv_name_attr_theater_event['max_num_child_bd']}=8\n'
            f'{kv_name_attr_theater_event['max_num_adult_bd']}=10\n'
            f'{kv_name_attr_theater_event['flag_indiv_cost']}=Нет\n'
            f'{kv_name_attr_theater_event['price_type']}=По умолчанию')
    await query.edit_message_text(text)

    return 41


async def schedule_event_preview(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    text = (f'{kv_name_attr_schedule_event['type_event_id']}=\n'
            f'{kv_name_attr_schedule_event['theater_events_id']}=\n'
            f'{kv_name_attr_schedule_event['flag_turn_in_bot']}=Нет\n'
            f'{kv_name_attr_schedule_event['datetime_event']}=2024-01-01T00:00 +3\n'
            f'{kv_name_attr_schedule_event['qty_child']}=8\n'
            f'{kv_name_attr_schedule_event['qty_adult']}=10\n'
            f'{kv_name_attr_schedule_event['flag_gift']}=Нет\n'
            f'{kv_name_attr_schedule_event['flag_christmas_tree']}=Нет\n'
            f'{kv_name_attr_schedule_event['flag_santa']}=Нет\n'
            f'{kv_name_attr_schedule_event['ticket_price_type']}=По умолчанию/будни/выходные\n')
    await query.edit_message_text(text)

    return 42


def validate_value(value, option):
    if value == 'Да':
        value = True
    if value == 'Нет':
        value = False
    if option == 'theater':
        if value == 'По умолчанию':
            value = PriceType.NONE
        if value == 'Базовая стоимость':
            value = PriceType.BASE_PRICE
        if value == 'Опции':
            value = PriceType.OPTIONS
        if value == 'Индивидуальная':
            value = PriceType.INDIVIDUAL
    if option == 'schedule':
        if value == 'По умолчанию':
            value = TicketPriceType.NONE
        if value == 'будни':
            value = TicketPriceType.weekday
        if value == 'выходные':
            value = TicketPriceType.weekend

    return value


async def theater_event_check(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        'Проверьте и отправьте текст еще раз или нажмите подтвердить')

    reply_markup = create_keyboard_confirm()

    text = update.effective_message.text
    await update.effective_chat.send_message(text, reply_markup=reply_markup)

    context.user_data['theater_event'] = get_validated_data(text, 'theater')
    return 41


async def schedule_event_check(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        'Проверьте и отправьте текст еще раз или нажмите подтвердить')

    reply_markup = create_keyboard_confirm()

    text = update.effective_message.text
    await update.effective_chat.send_message(text, reply_markup=reply_markup)

    context.user_data['schedule_event'] = get_validated_data(text, 'schedule')
    return 42


async def theater_event_create(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    theater_event = context.user_data['theater_event']
    reply_markup = context.user_data['reply_markup']

    res = await db_postgres.create_theater_event(
        context.session,
        name=theater_event['name'],
        min_age_child=theater_event['min_age_child'],
        max_age_child=theater_event['max_age_child'],
        show_emoji=theater_event['show_emoji'],
        flag_premier=theater_event['flag_premier'],
        flag_active_repertoire=theater_event['flag_active_repertoire'],
        flag_active_bd=theater_event['flag_active_bd'],
        max_num_child_bd=theater_event['max_num_child_bd'],
        max_num_adult_bd=theater_event['max_num_adult_bd'],
        flag_indiv_cost=theater_event['flag_indiv_cost'],
        price_type=theater_event['price_type'],
    )

    context.user_data.pop('theater_event')
    if res:
        await query.edit_message_text(
            text=f'{theater_event['name']}\nУспешно добавлено',
            reply_markup=reply_markup
        )
        return 3
    else:
        await query.edit_message_text(
            'Попробуйте еще раз или обратитесь в тех поддержку')
        return 41


async def schedule_event_create(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    schedule_event = context.user_data['schedule_event']
    reply_markup = context.user_data['reply_markup']

    res = await db_postgres.create_schedule_event(
        context.session,
        type_event_id=schedule_event['type_event_id'],
        theater_events_id=schedule_event['theater_events_id'],
        flag_turn_in_bot=schedule_event['flag_turn_in_bot'],
        datetime_event=schedule_event['datetime_event'],
        qty_child=schedule_event['qty_child'],
        qty_child_free_seat=schedule_event['qty_child'],
        qty_adult=schedule_event['qty_adult'],
        qty_adult_free_seat=schedule_event['qty_adult'],
        flag_gift=schedule_event['flag_gift'],
        flag_christmas_tree=schedule_event['flag_christmas_tree'],
        flag_santa=schedule_event['flag_santa'],
        ticket_price_type=schedule_event['ticket_price_type'],
    )

    context.user_data.pop('schedule_event')
    if res:
        res = await db_postgres.get_theater_event(
            context.session,
            schedule_event['theater_events_id'])
        await query.edit_message_text(
            text=f'{res.name}\nУспешно добавлено',
            reply_markup=reply_markup
        )
        return 3
    else:
        await query.edit_message_text(
            'Попробуйте еще раз или обратитесь в тех поддержку')
        return 42


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

    await update.effective_chat.send_message(
        'От Вас долго не было ответа, пожалуйста выполните новый запрос',
        message_thread_id=update.effective_message.message_thread_id
    )

    support_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            f'AFK уже {RESERVE_TIMEOUT} мин'
        ]
    ))

    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)

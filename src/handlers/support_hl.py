import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, TypeHandler, ConversationHandler

from db import db_postgres
from db.enum import PriceType, TicketPriceType
from handlers import init_conv_hl_dialog
from settings.settings import RESERVE_TIMEOUT, COMMAND_DICT
from utilities.schemas.schedule_event import kv_name_attr_schedule_event
from utilities.schemas.theater_event import kv_name_attr_theater_event
from utilities.utl_func import add_btn_back_and_cancel, set_back_context
from utilities.utl_kbd import create_kbd_crud, create_kbd_confirm

support_hl_logger = logging.getLogger('bot.support_hl')


def get_validated_data(string, option):
    query = string.split('\n')
    data = {}
    for kv in query:
        key, value = kv.split('=')
        validated_value = validate_value(value, option)
        if option == 'theater':
            for k, v in kv_name_attr_theater_event.items():
                if key == v:
                    data[k] = validated_value
        if option == 'schedule':
            for k, v in kv_name_attr_schedule_event.items():
                if key == v:
                    data[k] = validated_value
    return data


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


async def start_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await init_conv_hl_dialog(update, context)
    button_db = InlineKeyboardButton(text='База данных', callback_data='db')
    button_updates = InlineKeyboardButton(text='Обновление данных',
                                          callback_data='update_data')
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=False)
    keyboard = [
        [button_db, ],
        [button_updates, ],
        [*button_cancel, ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите что хотите настроить'
    await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup
    )

    state = 1
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def choice_db_settings(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    button_base_ticket = InlineKeyboardButton(text='Базовые билеты',
                                              callback_data='base_ticket')
    button_event_type = InlineKeyboardButton(text='Типы показов',
                                             callback_data='event_type')
    button_event = InlineKeyboardButton(text='Репертуар',
                                        callback_data='theater_event')
    button_schedule = InlineKeyboardButton(text='Расписание',
                                           callback_data='schedule_event')
    button_promotion = InlineKeyboardButton(text='Акции',
                                            callback_data='promotion')
    button_back_and_cancel = add_btn_back_and_cancel(
        postfix_for_cancel='settings',
        postfix_for_back='1')
    keyboard = [
        [
            button_base_ticket,
            button_event_type,
        ],
        [
            button_event,
            button_schedule,
        ],
        [
            button_promotion,
        ],
        [*button_back_and_cancel, ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите что хотите настроить'
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    state = 2
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def get_updates_option(update: Update,
                             _: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    btn_update_base_ticket_data = InlineKeyboardButton(
        COMMAND_DICT['UP_BT_DATA'][1],
        callback_data=COMMAND_DICT['UP_BT_DATA'][0])
    btn_update_special_ticket_price = InlineKeyboardButton(
        COMMAND_DICT['UP_SPEC_PRICE'][1],
        callback_data=COMMAND_DICT['UP_SPEC_PRICE'][0])
    btn_update_schedule_event_data = InlineKeyboardButton(
        COMMAND_DICT['UP_SE_DATA'][1],
        callback_data=COMMAND_DICT['UP_SE_DATA'][0])
    btn_update_theater_event_data = InlineKeyboardButton(
        COMMAND_DICT['UP_TE_DATA'][1],
        callback_data=COMMAND_DICT['UP_TE_DATA'][0])
    btn_update_custom_made_format_data = InlineKeyboardButton(
        COMMAND_DICT['UP_CMF_DATA'][1],
        callback_data=COMMAND_DICT['UP_CMF_DATA'][0])
    button_cancel = add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            postfix_for_back='1')
    keyboard = [
        [btn_update_base_ticket_data,
         btn_update_special_ticket_price],
        [btn_update_schedule_event_data,
         btn_update_theater_event_data],
        [btn_update_custom_made_format_data],
        [*button_cancel, ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = 'Выберите что хотите настроить\n\n'
    text += (
        f'{COMMAND_DICT['UP_BT_DATA'][1]}\n'
        f'{COMMAND_DICT['UP_SPEC_PRICE'][1]}\n'
        f'{COMMAND_DICT['UP_SE_DATA'][1]}\n'
        f'{COMMAND_DICT['UP_TE_DATA'][1]}\n'
        f'{COMMAND_DICT['UP_CMF_DATA'][1]}\n'
    )
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    await query.answer()
    return 'updates'


async def get_settings(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    reply_markup = create_kbd_crud(query.data)

    text = 'Выберите что хотите настроить'
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )

    context.user_data['reply_markup'] = reply_markup
    await query.answer()
    return 3


async def theater_event_select(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    res = await db_postgres.get_all_theater_events(context.session)
    text = ''
    for row in res:
        text += str(row[0]) + '\n'

    reply_markup = context.user_data['reply_markup']
    await query.edit_message_text(text, reply_markup=reply_markup)
    await query.answer()
    return 3


async def schedule_event_select(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    res = await db_postgres.get_all_schedule_events(context.session)
    text = ''
    for row in res:
        text += str(row[0]) + '\n'

    reply_markup = context.user_data['reply_markup']
    await query.edit_message_text(text, reply_markup=reply_markup)
    await query.answer()
    return 3


async def theater_event_preview(
        update: Update,
        _: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

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
            f'{kv_name_attr_theater_event['price_type']}=По умолчанию/Базовая стоимость/Опции/Индивидуальная\n')
    await query.edit_message_text(text)
    await query.answer()

    return 41


async def schedule_event_preview(
        update: Update,
        _: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    text = (f'{kv_name_attr_schedule_event['type_event_id']}=\n'
            f'{kv_name_attr_schedule_event['theater_event_id']}=\n'
            f'{kv_name_attr_schedule_event['flag_turn_in_bot']}=Нет\n'
            f'{kv_name_attr_schedule_event['datetime_event']}=2024-01-01T00:00 +3\n'
            f'{kv_name_attr_schedule_event['qty_child']}=8\n'
            f'{kv_name_attr_schedule_event['qty_adult']}=10\n'
            f'{kv_name_attr_schedule_event['flag_gift']}=Нет\n'
            f'{kv_name_attr_schedule_event['flag_christmas_tree']}=Нет\n'
            f'{kv_name_attr_schedule_event['flag_santa']}=Нет\n'
            f'{kv_name_attr_schedule_event['ticket_price_type']}=По умолчанию/будни/выходные\n')
    await query.edit_message_text(text)
    await query.answer()

    return 42


async def theater_event_check(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_chat.send_message(
        'Проверьте и отправьте текст еще раз или нажмите подтвердить')

    reply_markup = create_kbd_confirm()

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

    reply_markup = create_kbd_confirm()

    text = update.effective_message.text
    await update.effective_chat.send_message(text, reply_markup=reply_markup)

    context.user_data['schedule_event'] = get_validated_data(text, 'schedule')
    return 42


async def theater_event_create(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    theater_event = context.user_data['theater_event']
    reply_markup = context.user_data['reply_markup']

    res = await db_postgres.create_theater_event(
        context.session,
        **theater_event
    )

    context.user_data.pop('theater_event')
    await query.answer()
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

    schedule_event = context.user_data['schedule_event']
    reply_markup = context.user_data['reply_markup']

    res = await db_postgres.create_schedule_event(
        context.session,
        **schedule_event
    )

    context.user_data.pop('schedule_event')
    await query.answer()
    if res:
        # Получаю элемент репертуара, так как название есть только в репертуаре
        res = await db_postgres.get_theater_event(
            context.session,
            schedule_event['theater_event_id'])
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

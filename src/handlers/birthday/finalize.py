import logging

from sulguk import transform_html

from telegram.ext import ContextTypes, ConversationHandler
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from db import db_postgres
from api.googlesheets import write_client_cme
from settings.settings import (
    ADMIN_CME_GROUP,
    COMMAND_DICT,
)
from utilities.utl_func import (
    create_approve_and_reject_replay,
    del_keyboard_messages,
)

birthday_hl_logger = logging.getLogger('bot.birthday_hl')

async def get_confirm(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    await query.delete_message()
    await del_keyboard_messages(update, context)
    user_id = update.effective_user.id

    context.user_data['birthday_user_data']['user_id'] = user_id
    custom_made_event_data = context.user_data['birthday_user_data']
    custom_made_event = await db_postgres.create_custom_made_event(
        context.session,
        **custom_made_event_data
    )

    common_data = context.user_data['common_data']
    message_id_for_reply = common_data['message_id_for_reply']

    text = (f'\n\nВаша заявка: {custom_made_event.id}\n\n'
            f'Заявка находится на рассмотрении.\n'
            'После вам придет подтверждение '
            'или администратор свяжется с вами для уточнения деталей.')
    await update.effective_chat.send_message(
        text, reply_to_message_id=message_id_for_reply)

    reply_markup = create_approve_and_reject_replay(
        'birthday-1',
        f'{user_id} {message_id_for_reply} {custom_made_event.id}'
    )

    user = context.user_data.get('user', update.effective_user)
    text = ('#День_рождения<br>'
            f'Запрос пользователя @{user.username} {user.full_name}<br>')
    text += f'Номер заявки: {custom_made_event.id}<br><br>'
    text += context.user_data['common_data'][
        'text_for_notification_massage']
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Выездные мероприятия', None))

    res_text = transform_html(text)
    message = await context.bot.send_message(
        text=res_text.text,
        entities=res_text.entities,
        chat_id=ADMIN_CME_GROUP,
        reply_markup=reply_markup,
        message_thread_id=thread_id,
        parse_mode=None
    )

    context.user_data['common_data'][
        'message_id_for_admin'] = message.message_id
    context.user_data['birthday_user_data'][
            'custom_made_event_id'] = custom_made_event.id

    sheet_id_cme = context.config.sheets.sheet_id_cme
    await write_client_cme(sheet_id_cme, custom_made_event)

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    await query.answer()
    return state


async def paid_info(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    state = 'START'
    context.user_data['STATE'] = state

    keyboard = []
    button_cancel = InlineKeyboardButton(
        "Отменить",
        callback_data=f'Отменить-{context.user_data['postfix_for_cancel']}'
    )
    keyboard.append([button_cancel])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = ('    Внесите предоплату 5000 руб<br><br>'
            'Оплатить можно:<br>'
            ' - Переводом на карту Сбербанка по номеру телефона'
            '+79159383529 Татьяна Александровна Б.<br><br>'
            'ВАЖНО! Прислать сюда электронный чек об оплате (или скриншот)<br>'
            'Пожалуйста внесите оплату в течении 30 минут или нажмите '
            'отмена и повторите в другое удобное для вас время<br><br>'
            '__________<br>'
            'В случае переноса или отмены свяжитесь с Администратором:<br>'
            f'{context.bot_data['cme_admin']['contacts']}')

    res_text = transform_html(text)
    message = await update.effective_chat.send_message(
        text=res_text.text,
        entities=res_text.entities,
        reply_markup=reply_markup,
        parse_mode=None
    )

    context.user_data['common_data']['message_id_buy_info'] = message.message_id

    state = 'PAID'
    context.user_data['STATE'] = state
    return state


async def forward_photo_or_file(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    """
    Пересылает картинку или файл.
    """
    user = context.user_data.get('user', update.effective_user)
    common_data = context.user_data['common_data']
    message_id = common_data['message_id_buy_info']
    chat_id = update.effective_chat.id

    # Убираем у старого сообщения кнопку отмены
    await context.bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=message_id
    )

    try:
        message_id_for_reply = common_data['message_id_for_reply']
        cme_id = context.user_data['birthday_user_data']['custom_made_event_id']
        text = (f'Предоплата по заявке {cme_id} принята\n'
                f'В ближайшее время вам так же поступит подтверждение о '
                f'забронированном мероприятии')
        await update.effective_chat.send_message(
            text=text,
            reply_to_message_id=message_id_for_reply
        )
        await update.effective_chat.pin_message(message_id_for_reply)

        thread_id = (context.bot_data['dict_topics_name']
                     .get('Выездные мероприятия', None))
        message_id_for_admin = context.user_data['common_data'][
            'message_id_for_admin']

        reply_markup = create_approve_and_reject_replay(
            'birthday-2',
            f'{update.effective_user.id} {message_id} {cme_id}'
        )

        caption = (f'Квитанция покупателя @{user.username} {user.full_name}\n'
                   f'Запросил подтверждение брони на сумму 5000 руб\n'
                   f'Номер заявки: {cme_id}')

        await update.effective_message.copy(
            chat_id=ADMIN_CME_GROUP,
            caption=caption,
            reply_markup=reply_markup,
            message_thread_id=thread_id,
            reply_to_message_id=message_id_for_admin
        )

    except KeyError as err:
        birthday_hl_logger.error(err)

        await update.effective_chat.send_message(
            'Сначала необходимо оформить запрос\n'
            f'Это можно сделать по команде /{COMMAND_DICT['BD_ORDER'][0]}'
        )
        birthday_hl_logger.error(
            f'Пользователь {user}: '
            'Не оформил заявку, '
            f'а сразу использовал команду /{COMMAND_DICT['BD_PAID'][0]}'
        )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def conversation_timeout(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
) -> int:
    """Informs the user that the operation has timed out,
    calls :meth:`remove_reply_markup` and ends the conversation.
    :return:
        int: :attr:`telegram.ext.ConversationHandler.END`.
    """
    user = context.user_data.get('user', update.effective_user)
    if context.user_data['STATE'] == 'PAID':
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, бронь отменена, пожалуйста выполните '
            'новый запрос'
        )
    else:
        # TODO Прописать дополнительную обработку states, для этапов опроса
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос'
        )

    birthday_hl_logger.info(": ".join(
        [
            'Пользователь',
            f'{user}',
            'AFK уже 30 мин'
        ]
    ))
    birthday_hl_logger.info(f'Для пользователя {user}')
    birthday_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')
    context.user_data['common_data'].clear()
    context.user_data['birthday_user_data'].clear()
    return ConversationHandler.END

import logging
import pprint
from datetime import datetime

from sulguk import transform_html
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.error import TimedOut, BadRequest
from telegram.ext import ContextTypes, ConversationHandler, TypeHandler
from telegram.constants import ChatAction

from api.gspread_pub import (
    publish_write_client_reserve)

from db import db_postgres, Promotion
from db.db_googlesheets import decrease_free_seat
from db.enum import TicketStatus, PromotionDiscountType
from handlers.reserve.common import (
    promo_requires_verification,
    process_successful_payment_with_verification,
    request_discount_verification,
)
from handlers.sub_hl import (
    remove_button_from_last_message,
    create_and_send_payment, processing_successful_payment,
    forward_message_to_admin,
)
from api.googlesheets import write_client_reserve
from utilities.utl_date import to_naive
from utilities.utl_func import (
    set_back_context,
    get_full_name_event, get_formatted_date_and_time_of_event,
    clean_context,
    add_reserve_clients_data_to_text,
    get_schedule_event_ids_studio,
    clean_context_on_end_handler,
)
from utilities.utl_googlesheets import update_ticket_db_and_gspread
from utilities.utl_ticket import (
    cancel_tickets_db_and_gspread, create_tickets_and_people)
from utilities.utl_kbd import add_btn_back_and_cancel
from settings.settings import (
    COMMAND_DICT, RESERVE_TIMEOUT
)

reserve_hl_logger = logging.getLogger('bot.reserve_hl')


async def reset_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data.pop('applied_promo_id', None)
    reserve_user_data.pop('applied_promo_code', None)
    reserve_user_data.pop('discounted_price', None)

    return await show_reservation_summary(update, context)


async def check_promo_restrictions(
        promo: Promotion,
        reserve_user_data: dict,
        session
) -> tuple[bool, str]:
    schedule_event_id = reserve_user_data.get('chose_schedule_event_id')
    base_ticket_id = reserve_user_data.get('chose_base_ticket_id')

    if not schedule_event_id:
        return True, ""

    schedule_event = await db_postgres.get_schedule_event(
        session, schedule_event_id)
    if not schedule_event:
        return True, ""

    # Проверка по типу события
    if promo.type_events:
        type_event_ids = [te.id for te in promo.type_events]
        if schedule_event.type_event_id not in type_event_ids:
            return False, "Этот промокод не действует на данный тип мероприятий."

    # Проверка по репертуару (спектакли)
    if promo.theater_events:
        theater_event_ids = [te.id for te in promo.theater_events]
        if schedule_event.theater_event_id not in theater_event_ids:
            return False, "Этот промокод не действует на данный спектакль."

    # Проверка по сеансам
    if promo.schedule_events:
        schedule_ids = [se.id for se in promo.schedule_events]
        if schedule_event.id not in schedule_ids:
            return False, "Этот промокод не действует на выбранный сеанс."

    # Проверка по дням недели
    if promo.weekdays is not None:
        event_weekday = schedule_event.datetime_event.weekday()
        if not (promo.weekdays & (1 << event_weekday)):
            return False, "Этот промокод не действует в данный день недели."

    # Проверка по типам билетов
    if promo.base_tickets:
        ticket_ids = [bt.base_ticket_id for bt in promo.base_tickets]
        if base_ticket_id not in ticket_ids:
            return False, "Этот промокод не действует на выбранный тип билета."

    # Проверка лимита использования на пользователя
    if promo.max_usage_per_user > 0:
        user_id = reserve_user_data.get('user_id')
        if user_id:
            usage_count = await db_postgres.get_promotion_usage_count_by_user(
                session, promo.id, user_id)
            if usage_count >= promo.max_usage_per_user:
                return False, f"Вы уже использовали этот промокод максимально доступное количество раз."

    return True, ""


async def compute_discounted_price(price: int, promo: Promotion) -> int:
    if promo.discount_type == PromotionDiscountType.percentage:
        new_price = price * (100 - promo.discount) / 100
    else:
        new_price = price - promo.discount

    # Округление до 10 рублей
    # 1761 -> 1760, 1768 -> 1770
    rounded_price = int(round(new_price / 10) * 10)
    return max(rounded_price, 10)


async def show_reservation_summary(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    reserve_user_data = context.user_data['reserve_user_data']
    chose_price = reserve_user_data['chose_price']
    discounted_price = reserve_user_data.get('discounted_price')
    applied_promo_code = reserve_user_data.get('applied_promo_code')

    # Сбор данных о мероприятии
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    schedule_event = await db_postgres.get_schedule_event(
        context.session, schedule_event_id)
    theater_event = await db_postgres.get_theater_event(
        context.session, schedule_event.theater_event_id)

    full_name_event = get_full_name_event(theater_event)
    date_event, time_event = await get_formatted_date_and_time_of_event(
        schedule_event)

    text = (
        f"<b>Подтверждение бронирования</b><br><br>"
        f"<b>Мероприятие:</b> {full_name_event}<br>"
        f"<b>Дата и время:</b> {date_event} в {time_event}<br>"
    )

    # Добавляем инфу о гостях
    text = add_reserve_clients_data_to_text(text, reserve_user_data)

    text += "<br>"
    price_to_pay = discounted_price if discounted_price else chose_price
    if discounted_price:
        text += (
            f"<b>Стоимость:</b> <s>{int(chose_price)}</s> {int(discounted_price)} руб.<br>"
            f"✅ Применен промокод: <code>{applied_promo_code}</code>"
        )
        # Проверяем, требует ли промокод верификации
        applied_promo_id = reserve_user_data.get('applied_promo_id')
        if applied_promo_id:
            promo = await db_postgres.get_promotion(
                context.session, applied_promo_id)
            if promo and promo.requires_verification:
                v_text = promo.verification_text or (
                    "Фото документа, подтверждающего право на льготу, "
                    "вы сможете прикрепить после оплаты. Без него билет "
                    "может быть отклонен, а средства возвращены.")
                text += f"<br><br><b>Внимание!</b><br>{v_text}"
    else:
        text += f"<b>Стоимость:</b> {int(chose_price)} руб."

    text += "<br><br>Если вас всё устраивает, вы можете переходить к оплате."
    refund = context.bot_data.get('settings', {}).get('REFUND_INFO', '')
    if refund:
        text += f"<br><br>{refund}"

    # Обновляем текст для уведомления админа и пользователя
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)
    text_select_event = reserve_user_data['text_select_event']
    notification_text = (f'{text_select_event}<br>'
                         f'Вариант бронирования:<br>'
                         f'{chose_base_ticket.name} '
                         f'{int(price_to_pay)}руб<br>')
    if applied_promo_code:
        notification_text += f'Применен промокод: <code>{applied_promo_code}</code><br><br>'
    context.user_data['common_data'][
        'text_for_notification_massage'] = notification_text

    # Клавиатура
    keyboard = [
        [InlineKeyboardButton("💳 Перейти к оплате", callback_data='PAY')]
    ]

    command = context.user_data.get('command', '')
    if '_admin' in command:
        keyboard.append([InlineKeyboardButton(
            "✅ Подтвердить без оплаты", callback_data='CONFIRM_WITHOUT_PAY')])

    if applied_promo_code:
        keyboard.append([InlineKeyboardButton(
            "❌ Сбросить промокод", callback_data='RESET_PROMO')])
    else:
        keyboard.append(
            [InlineKeyboardButton("🎟 Ввести промокод", callback_data='PROMO')])

    # Льготы (is_visible_as_option=True)
    promos_as_options = await db_postgres.get_active_promotions_as_options(
        context.session)
    for promo in promos_as_options:
        # Проверяем условия применимости (min_purchase_sum)
        if chose_price < promo.min_purchase_sum:
            continue

        # Проверяем остальные ограничения
        is_valid, _ = await check_promo_restrictions(
            promo, reserve_user_data, context.session)
        if not is_valid:
            continue

        btn_text = promo.description_user or promo.name or f"Льгота: {promo.code}"
        keyboard.append([InlineKeyboardButton(
            btn_text, callback_data=f'PROMO_OPTION|{promo.id}')])

    # Назад / Отмена
    keyboard.append(add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
        add_back_btn=True,
        postfix_for_back='CHILDREN'
    ))

    reply_markup = InlineKeyboardMarkup(keyboard)
    res_text = transform_html(text)

    if query:
        try:
            message = await query.edit_message_text(
                text=res_text.text,
                entities=res_text.entities,
                parse_mode=None,
                reply_markup=reply_markup
            )
        except BadRequest:
            message = await update.effective_chat.send_message(
                text=res_text.text,
                entities=res_text.entities,
                parse_mode=None,
                reply_markup=reply_markup
            )
    else:
        message = await update.effective_chat.send_message(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None,
            reply_markup=reply_markup
        )

    reserve_user_data['message_id'] = message.message_id
    state = 'CONFIRM_RESERVATION'
    await set_back_context(context, state, res_text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def confirm_go_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Удаляем клавиатуру из текущего сообщения
    try:
        await query.edit_message_reply_markup()
    except BadRequest:
        pass

    # Переходим к стандартному созданию платежа
    state = await create_and_send_payment(update, context)
    if state is None:
        state = 'PAID'
    context.user_data['STATE'] = state
    return state


async def confirm_admin_without_payment(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    reserve_user_data = context.user_data['reserve_user_data']
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    await get_schedule_event_ids_studio(context)
    await update.effective_chat.send_action(ChatAction.TYPING)

    text = 'Создаю новые билеты в бд...'
    reserve_hl_logger.info(text)
    message = await update.effective_chat.send_message(text)
    ticket_ids = await create_tickets_and_people(
        update, context, TicketStatus.CREATED)

    text += '\nЗаписываю новый билет в клиентскую базу...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        reserve_hl_logger.error(e)
        reserve_hl_logger.info(text)
    sheet_id_domik = context.config.sheets.sheet_id_domik
    chat_id = update.effective_chat.id
    base_ticket_dto = chose_base_ticket.to_dto()
    ticket_status_value = str(TicketStatus.CREATED.value)
    reserve_user_data = context.user_data['reserve_user_data']
    try:
        await publish_write_client_reserve(
            sheet_id_domik,
            reserve_user_data,
            chat_id,
            base_ticket_dto,
            ticket_status_value
        )
    except Exception as e:
        reserve_hl_logger.exception(
            f'Failed to publish gspread task, fallback to direct call: {e}')
        res = await write_client_reserve(sheet_id_domik,
                                         reserve_user_data,
                                         chat_id,
                                         base_ticket_dto,
                                         ticket_status_value)
        if res:
            text += '\nЗапись успешно создана'
        else:
            text += '\nОшибка при создании записи'
        await message.edit_text(text)

    for ticket_id in ticket_ids:
        result = await decrease_free_seat(
            context, schedule_event_id, chose_base_ticket_id)
        if not result:
            await update_ticket_db_and_gspread(
                context, ticket_id, status=TicketStatus.CANCELED)
            text += ('\nНе уменьшились свободные места'
                     '\nНовый билет отменен'
                     '\nНеобходимо повторить резервирование заново')
            try:
                await message.edit_text(text)
            except TimedOut as e:
                reserve_hl_logger.error(e)
                reserve_hl_logger.info(text)
            await clean_context_on_end_handler(reserve_hl_logger, context)
            return ConversationHandler.END

    text += '\nПоследняя проверка...'
    try:
        await message.edit_text(text)
    except TimedOut as e:
        reserve_hl_logger.error(e)
        reserve_hl_logger.info(text)
    await processing_successful_payment(update, context)

    await update.effective_chat.send_message(
        'Билеты успешно созданы и оплачены')

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def handle_receipt_file(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    return await process_successful_payment_with_verification(
        update,
        context,
        state_on_success=ConversationHandler.END,
    )


async def handle_certificate_file(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    # Пересылаем удостоверение админу
    await forward_message_to_admin(
        update, context, doc_type="Подтверждение льготы")

    await update.effective_chat.send_message(
        "Спасибо! Документ получен и передан администратору."
    )

    # Теперь отправляем финальное сообщение с правилами
    from handlers.sub_hl import send_by_ticket_info
    reserve_user_data = context.user_data['reserve_user_data']
    if reserve_user_data.get('flag_send_ticket_info'):
        await send_by_ticket_info(update, context)

    context.user_data['STATE'] = ConversationHandler.END
    return ConversationHandler.END


async def ask_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = "Введите промокод:"
    keyboard = [add_btn_back_and_cancel(
        add_cancel_btn=False,
        add_back_btn=True,
        postfix_for_back='CONFIRM_RESERVATION'
    )]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text=text, reply_markup=reply_markup)

    state = 'PROMOCODE_INPUT'
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_promo_code_input(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    reserve_user_data = context.user_data['reserve_user_data']
    try:
        await context.bot.edit_message_reply_markup(
            update.effective_chat.id,
            message_id=reserve_user_data['message_id']
        )
    except BadRequest as e:
        reserve_hl_logger.error(e)

    code = update.effective_message.text.strip().upper()
    chose_price = reserve_user_data['chose_price']

    promo = await db_postgres.get_promotion_by_code(context.session, code)

    if not promo or not promo.flag_active:
        text = "Промокод не найден или неактивен. Попробуйте другой или продолжите без него."
        await update.effective_chat.send_message(text)
        return await show_reservation_summary(update, context)

    # Проверка даты
    now = datetime.now()
    start_date = to_naive(promo.start_date)
    if start_date and now < start_date:
        text = "Срок действия этого промокода еще не начался."
        await update.effective_chat.send_message(text)
        return await show_reservation_summary(update, context)
    expire_date = to_naive(promo.expire_date)
    if expire_date and now > expire_date:
        text = "Срок действия этого промокода истек."
        await update.effective_chat.send_message(text)
        return await show_reservation_summary(update, context)

    # Проверка лимита использования
    if 0 < promo.max_count_of_usage <= promo.count_of_usage:
        text = "Лимит использований этого промокода исчерпан."
        await update.effective_chat.send_message(text)
        return await show_reservation_summary(update, context)

    # Проверка минимальной суммы
    if chose_price < promo.min_purchase_sum:
        text = f"Этот промокод действует при сумме заказа от {promo.min_purchase_sum} руб."
        await update.effective_chat.send_message(text)
        return await show_reservation_summary(update, context)

    # Проверка ограничений
    is_valid, error_msg = await check_promo_restrictions(
        promo, reserve_user_data, context.session)
    if not is_valid:
        await update.effective_chat.send_message(error_msg)
        return await show_reservation_summary(update, context)

    # Применение
    discounted_price = await compute_discounted_price(chose_price, promo)
    reserve_user_data['applied_promo_id'] = promo.id
    reserve_user_data['applied_promo_code'] = promo.code
    reserve_user_data['discounted_price'] = discounted_price

    return await show_reservation_summary(update, context)


async def apply_option_promo(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    promo_id = int(query.data.split('|')[1])
    promo = await db_postgres.get_promotion(context.session, promo_id)
    reserve_user_data = context.user_data['reserve_user_data']
    chose_price = reserve_user_data['chose_price']

    if promo and promo.flag_active:
        # Проверка ограничений
        is_valid, error_msg = await check_promo_restrictions(
            promo, reserve_user_data, context.session)
        if not is_valid:
            await query.answer(error_msg, show_alert=True)
            return await show_reservation_summary(update, context)

        discounted_price = await compute_discounted_price(chose_price, promo)
        reserve_user_data['applied_promo_id'] = promo.id
        reserve_user_data['applied_promo_code'] = promo.code
        reserve_user_data['discounted_price'] = discounted_price

    return await show_reservation_summary(update, context)


async def forward_photo_or_file(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    await remove_button_from_last_message(update, context)
    return await process_successful_payment_with_verification(
        update,
        context,
        replace_paid_state_with_end=True,
    )


async def processing_successful_notification(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    await processing_successful_payment(update, context)

    if await promo_requires_verification(context):
        return await request_discount_verification(update, context)

    state = context.user_data.get('STATE', ConversationHandler.END)
    if state == 'PAID':
        state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Удаляем кнопки
    await query.edit_message_reply_markup()

    text = "Пожалуйста, отправьте файл или фото квитанции об оплате."
    await update.effective_chat.send_message(text)

    context.user_data['STATE'] = 'WAIT_RECEIPT'
    return 'WAIT_RECEIPT'


async def conversation_timeout(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
) -> int:
    """Informs the user that the operation has timed out,
    calls: meth:`remove_reply_markup` and ends the conversation.
    :return:
        Int: attr:`telegram.ext.ConversationHandler.END`.
    """
    user = context.user_data.get('user', update.effective_user)
    if context.user_data['STATE'] == 'PAID':
        reserve_hl_logger.info('Отправка чека об оплате не была совершена')
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['common_data']['message_id_buy_info']
        )
        text = (
            'От Вас долго не было ответа, бронь отменена, '
            'пожалуйста выполните новый запрос<br>'
            'Если вы уже сделали оплату, но не отправили чек об оплате, '
            'выполните оформление повторно и приложите данный чек<br>'
            f'/{COMMAND_DICT['RESERVE'][0]}<br><br>'
            'Если свободных мест не будет свяжитесь с Администратором:<br>'
            f'{context.bot_data['admin']['contacts']}'
        )
        res_text = transform_html(text)
        await update.effective_chat.send_message(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None
        )
        reserve_hl_logger.info(pprint.pformat(context.user_data))

    else:
        # TODO Прописать дополнительную обработку states, для этапов опроса
        await update.effective_chat.send_message(
            'От Вас долго не было ответа, пожалуйста выполните новый запрос',
            message_thread_id=update.effective_message.message_thread_id
        )

    reserve_hl_logger.info(
        f'Пользователь: {user}: AFK уже {RESERVE_TIMEOUT} мин')
    reserve_hl_logger.info(
        f'Обработчик завершился на этапе {context.user_data['STATE']}')

    await cancel_tickets_db_and_gspread(update, context)

    await clean_context(context)
    return ConversationHandler.END


TIMEOUT_HANDLER = TypeHandler(Update, conversation_timeout)

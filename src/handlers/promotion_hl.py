import logging
import random
import string
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from db import db_postgres
from db.enum import PromotionDiscountType, GroupOfPeopleByDiscountType
from handlers.support_hl import send_settings_menu
from utilities.utl_func import set_back_context
from utilities.utl_kbd import create_kbd_confirm, add_btn_back_and_cancel
from db import db_postgres

logger = logging.getLogger('bot.promotion_hl')

# Определяем состояния для диалога создания промокода
(
    PROM_NAME,
    PROM_CODE,
    PROM_DTYPE,
    PROM_VALUE,
    PROM_MIN_SUM,
    PROM_VISIBLE,
    PROM_VERIFY,
    PROM_VTEXT,
    PROM_START,
    PROM_EXPIRE,
    PROM_MAX_USAGE,
    PROM_DESC,
    PROM_CONFIRM,
    PROM_RESTRICT_TYPE,
    PROM_RESTRICT_THEATER,
    PROM_RESTRICT_TICKET,
    PROM_RESTRICT_SCHEDULE,
) = range(50, 67)
PROM_MAX_USAGE_USER = 67

async def promotion_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    context.user_data['new_promotion'] = {'data': {}, 'service': {}}
    
    return await handle_prom_name_start(update, context)

async def promotion_update_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    promotions = await db_postgres.get_all_promotions(context.session)
    if not promotions:
        text = "Нет промокодов для редактирования."
        reply_markup = InlineKeyboardMarkup([add_btn_back_and_cancel(postfix_for_cancel='settings',
                                                                    add_back_btn=True,
                                                                    postfix_for_back='3')])
        await query.edit_message_text(text, reply_markup=reply_markup)
        return 3

    text = "Выберите промокод для редактирования:"
    keyboard = []
    for promo in promotions:
        display_name = (promo.name[:20] + '...') if len(promo.name) > 20 else promo.name
        keyboard.append([InlineKeyboardButton(f"{promo.code} ({display_name})",
                                              callback_data=f"upd_prom_{promo.id}")])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back='3'))

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)

    return 3


async def handle_promotion_to_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    promo_id = int(query.data.replace('upd_prom_', ''))
    promo = await db_postgres.get_promotion(context.session, promo_id)

    if not promo:
        await query.edit_message_text("Промокод не найден.")
        return 3

    context.user_data['new_promotion'] = {
        'data': {
            'id': promo.id,
            'name': promo.name,
            'code': promo.code,
            'discount': promo.discount,
            'discount_type': promo.discount_type,
            'min_purchase_sum': promo.min_purchase_sum,
            'is_visible_as_option': promo.is_visible_as_option,
            'requires_verification': promo.requires_verification,
            'verification_text': promo.verification_text,
            'start_date': promo.start_date,
            'expire_date': promo.expire_date,
            'max_count_of_usage': promo.max_count_of_usage,
            'max_usage_per_user': promo.max_usage_per_user,
            'description_user': promo.description_user,
            'flag_active': promo.flag_active,
            'count_of_usage': promo.count_of_usage,
            'for_who_discount': promo.for_who_discount,
            'type_event_ids': [te.id for te in promo.type_events],
            'theater_event_ids': [te.id for te in promo.theater_events],
            'base_ticket_ids': [bt.base_ticket_id for bt in promo.base_tickets],
            'schedule_event_ids': [se.id for se in promo.schedule_events],
        },
        'service': {
            'message_id': query.message.message_id,
            'is_update': True
        }
    }

    return await ask_promotion_summary(update, context)


async def promotion_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    promotions = await db_postgres.get_all_promotions(context.session)
    if not promotions:
        text = "Нет промокодов для удаления."
        reply_markup = InlineKeyboardMarkup([add_btn_back_and_cancel(postfix_for_cancel='settings',
                                                                    add_back_btn=True,
                                                                    postfix_for_back='3')])
        await query.edit_message_text(text, reply_markup=reply_markup)
        return 3

    text = "Выберите промокод для УДАЛЕНИЯ:"
    keyboard = []
    for promo in promotions:
        display_name = (promo.name[:20] + '...') if len(promo.name) > 20 else promo.name
        keyboard.append([InlineKeyboardButton(f"❌ {promo.code} ({display_name})",
                                              callback_data=f"del_prom_{promo.id}")])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back='3'))

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)

    return 3


async def handle_promotion_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    promo_id = int(query.data.replace('del_prom_', ''))
    promo = await db_postgres.get_promotion(context.session, promo_id)

    if not promo:
        await query.edit_message_text("Промокод не найден.")
        return 3

    text = f"Вы уверены, что хотите удалить промокод <b>{promo.code}</b> ({promo.name})?"
    keyboard = [
        [InlineKeyboardButton("ДА, УДАЛИТЬ", callback_data=f"confirm_del_prom_{promo.id}")],
        [InlineKeyboardButton("Отмена", callback_data="promotion_delete")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return 3


async def confirm_promotion_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    promo_id = int(query.data.replace('confirm_del_prom_', ''))
    
    try:
        await db_postgres.del_promotion(context.session, promo_id)
        await query.answer("Промокод удален")
    except Exception as e:
        logger.exception(f"Ошибка при удалении промокода: {e}")
        await query.answer(f"Ошибка при удалении: {e}", show_alert=True)
        
    return await promotion_delete_start(update, context)


async def handle_prom_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)
    current_name = promotion_['data'].get('name', 'Не указано')

    text = f"Введите название акции (текущее: '{current_name}'):" if is_update else "Введите название акции:"

    # Кнопки
    keyboard = []
    if promotion_['data'].get('name'):
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else '3'))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)

    promotion_['service']['message_id'] = message.message_id
    state = PROM_NAME
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=promotion_['service']['message_id']
        )
    except Exception:
        pass

    name = update.effective_message.text
    promotion_['data']['name'] = name

    if is_update:
        return await ask_promotion_summary(update, context)

    current_code = promotion_['data'].get('code')
    text = (f"Введите промокод\n"
            f"<i>(буквы, цифры, символы '_' и '-'. без пробелов, например:</i>\n"
            f"<code>MNOGODET</code>\n"
            f"<code>PROMO10</code>\n"
            f"<code>SALE2024</code>\n"
            f"<code>S-8</code>\n"
            f"<code>НОВЫЙ_ГОД_2026</code>\n"
            f"<code>SALE_12</code>\n")

    if current_code:
        text = f"Текущий код: <code>{current_code}</code>\n\n" + text

    keyboard = [
        [InlineKeyboardButton("Сгенерировать случайный", callback_data='generate_code')],
        add_btn_back_and_cancel(postfix_for_cancel='settings',
                                add_back_btn=True,
                                postfix_for_back=PROM_NAME)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_CODE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

async def handle_prom_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = (f"Введите промокод\n"
            f"<i>(буквы, цифры, символы '_' и '-'. без пробелов, например:</i>\n"
            f"<code>MNOGODET</code>\n"
            f"<code>PROMO10</code>\n"
            f"<code>SALE2024</code>\n"
            f"<code>S-8</code>\n"
            f"<code>НОВЫЙ_ГОД_2026</code>\n"
            f"<code>SALE_12</code>\n")

    if is_update:
        text = f"Текущий код: <code>{promotion_['data']['code']}</code>\n\n" + text

    keyboard = []
    keyboard.append([InlineKeyboardButton("Сгенерировать случайный", callback_data='generate_code')])
    if promotion_['data'].get('code'):
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_NAME))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_CODE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)
    current_id = promotion_['data'].get('id')

    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=promotion_['service']['message_id']
        )
    except Exception:
        pass

    code = update.effective_message.text.strip().upper()
    
    # Проверка на уникальность кода
    existing = await db_postgres.get_promotion_by_code(context.session, code)
    if existing and existing.id != current_id:
        await update.effective_chat.send_message(f"Промокод '{code}' уже существует. Введите другой:")
        return PROM_CODE

    promotion_['data']['code'] = code

    if is_update:
        return await ask_promotion_summary(update, context)
    
    return await ask_prom_type(update, context)

async def generate_prom_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Генерируем уникальный код
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        existing = await db_postgres.get_promotion_by_code(context.session, code)
        if not existing:
            break

    promotion_ = context.user_data['new_promotion']
    promotion_['data']['code'] = code
    message = await query.message.reply_text(f"Сгенерирован код: <code>{code}</code>")
    # Мы не обновляем message_id здесь, так как ask_prom_type отправит следующее сообщение с кнопками
    
    return await ask_prom_type(update, context)

async def ask_prom_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Выберите тип скидки:"
    current_type = promotion_['data'].get('discount_type')
    if current_type:
        type_str = 'Процент %' if current_type == PromotionDiscountType.percentage else 'Фиксированная ₽'
        text = f"Текущий тип: <b>{type_str}</b>\n\n" + text

    keyboard = [
        [
            InlineKeyboardButton("Процент %", callback_data='percentage'),
            InlineKeyboardButton("Фиксированная ₽", callback_data='fixed')
        ],
    ]
    if promotion_['data'].get('discount_type'):
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_CODE))
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        message = await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)

    promotion_ = context.user_data['new_promotion']
    promotion_['service']['message_id'] = message.message_id
    state = PROM_DTYPE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

async def handle_prom_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    dtype = query.data
    promotion_ = context.user_data['new_promotion']
    promotion_['data']['discount_type'] = PromotionDiscountType(dtype)
    
    current_val = promotion_['data'].get('discount')
    if dtype == 'percentage':
        text = "Введите размер скидки в процентах (число от 1 до 100)"
        if current_val:
            text += f" (текущее: {current_val}%)"
        text += ":"
    else:
        text = "Введите размер скидки в рублях (число)"
        if current_val:
            text += f" (текущее: {current_val} ₽)"
        text += ":"
        
    await query.edit_message_text(text)
    
    state = PROM_VALUE
    await set_back_context(context, state, text, None)
    context.user_data['STATE'] = state
    return state

async def handle_prom_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=promotion_['service']['message_id']
        )
    except Exception:
        pass

    try:
        value = int(update.effective_message.text)
        if promotion_['data']['discount_type'] == PromotionDiscountType.percentage:
            if not (1 <= value <= 100):
                raise ValueError
    except ValueError:
        text = "Пожалуйста, введите корректное число:"
        await update.effective_chat.send_message(text)
        return PROM_VALUE
        
    promotion_['data']['discount'] = value
    
    is_update = promotion_['service'].get('is_update', False)
    if is_update:
        return await ask_promotion_summary(update, context)

    text = "Введите минимальную сумму заказа, при которой сработает промокод (0 если ограничений нет):"
    current_min_sum = promotion_['data'].get('min_purchase_sum')
    if current_min_sum is not None:
        text = f"Текущая сумма: {current_min_sum}\n\n" + text

    message = await update.effective_chat.send_message(text)
    promotion_['service']['message_id'] = message.message_id
    
    state = PROM_MIN_SUM
    await set_back_context(context, state, text, None)
    context.user_data['STATE'] = state
    return state

async def handle_prom_min_sum_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Введите минимальную сумму заказа, при которой сработает промокод (0 если ограничений нет):"
    if is_update:
        text = f"Текущая сумма: {promotion_['data']['min_purchase_sum']}\n\n" + text

    keyboard = []
    if promotion_['data'].get('min_purchase_sum') is not None:
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_VALUE))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_MIN_SUM
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_min_sum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=promotion_['service']['message_id']
        )
    except Exception:
        pass

    try:
        value = int(update.effective_message.text)
    except ValueError:
        text = "Пожалуйста, введите корректное число:"
        await update.effective_chat.send_message(text)
        return PROM_MIN_SUM
        
    promotion_['data']['min_purchase_sum'] = value
    
    is_update = promotion_['service'].get('is_update', False)
    if is_update:
        return await ask_promotion_summary(update, context)

    text = "Показывать этот промокод как кнопку выбора льготы для пользователя?"
    current_visible = promotion_['data'].get('is_visible_as_option')
    if current_visible is not None:
        val_str = 'Да' if current_visible else 'Нет'
        text = f"Текущее значение: <b>{val_str}</b>\n\n" + text

    keyboard = [
        [
            InlineKeyboardButton("Да", callback_data='yes'),
            InlineKeyboardButton("Нет", callback_data='no')
        ],
        add_btn_back_and_cancel(postfix_for_cancel='settings',
                                add_back_btn=True,
                                postfix_for_back=PROM_MIN_SUM)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id
    
    state = PROM_VISIBLE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

async def handle_prom_visible_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Показывать этот промокод как кнопку выбора льготы для пользователя?"
    current_visible = promotion_['data'].get('is_visible_as_option')
    if current_visible is not None:
        val_str = 'Да' if current_visible else 'Нет'
        text = f"Текущее значение: <b>{val_str}</b>\n\n" + text

    keyboard = [
        [
            InlineKeyboardButton("Да", callback_data='yes'),
            InlineKeyboardButton("Нет", callback_data='no')
        ]
    ]
    if promotion_['data'].get('is_visible_as_option') is not None:
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_MIN_SUM))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_VISIBLE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_visible(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    visible = query.data == 'yes'
    promotion_ = context.user_data['new_promotion']
    promotion_['data']['is_visible_as_option'] = visible

    is_update = promotion_['service'].get('is_update', False)
    if is_update:
        return await ask_promotion_summary(update, context)

    text = "Требовать подтверждение статуса (загрузку документа) от пользователя?"
    current_verify = promotion_['data'].get('requires_verification')
    if current_verify is not None:
        val_str = 'Да' if current_verify else 'Нет'
        text = f"Текущее значение: <b>{val_str}</b>\n\n" + text

    keyboard = [
        [
            InlineKeyboardButton("Да", callback_data='yes'),
            InlineKeyboardButton("Нет", callback_data='no')
        ],
        add_btn_back_and_cancel(postfix_for_cancel='settings',
                                add_back_btn=True,
                                postfix_for_back=PROM_VISIBLE)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup)

    state = PROM_VERIFY
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

async def handle_prom_verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Требовать подтверждение статуса (загрузку документа) от пользователя?"
    current_verify = promotion_['data'].get('requires_verification')
    if current_verify is not None:
        val_str = 'Да' if current_verify else 'Нет'
        text = f"Текущее значение: <b>{val_str}</b>\n\n" + text

    keyboard = [
        [
            InlineKeyboardButton("Да", callback_data='yes'),
            InlineKeyboardButton("Нет", callback_data='no')
        ]
    ]
    if promotion_['data'].get('requires_verification') is not None:
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_VISIBLE))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_VERIFY
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    verify = query.data == 'yes'
    promotion_ = context.user_data['new_promotion']
    promotion_['data']['requires_verification'] = verify

    is_update = promotion_['service'].get('is_update', False)
    if is_update:
        return await ask_promotion_summary(update, context)

    return await handle_prom_vtext_start(update, context)


async def handle_prom_vtext_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Введите текст, который будет выводиться пользователю при запросе документов (или нажмите 'Пропустить'):"
    current_vtext = promotion_['data'].get('verification_text')
    if current_vtext:
        text = f"Текущий текст: {current_vtext}\n\n" + text

    keyboard = [
        [InlineKeyboardButton("Пропустить", callback_data='skip')],
    ]
    if promotion_['data'].get('verification_text') is not None:
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_VERIFY))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_VTEXT
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_vtext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=promotion_['service']['message_id']
        )
    except Exception:
        pass

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == 'skip':
            promotion_['data']['verification_text'] = None
        elif query.data == 'skip_to_confirm':
            pass
        else:
            return PROM_VTEXT
    else:
        promotion_['data']['verification_text'] = update.effective_message.text

    is_update = promotion_['service'].get('is_update', False)
    if is_update:
        return await ask_promotion_summary(update, context)

    return await handle_prom_start_start(update, context)

async def handle_prom_start_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Введите дату начала действия промокода в формате ДД.ММ.ГГГГ (или нажмите кнопку 'Пропустить'):"
    if is_update and promotion_['data'].get('start_date'):
        text = f"Текущая дата начала: {promotion_['data']['start_date'].strftime('%d.%m.%Y')}\n\n" + text

    keyboard = [
        [InlineKeyboardButton("Пропустить", callback_data='skip')],
    ]
    if promotion_['data'].get('start_date') is not None:
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_VTEXT))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_START
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_reply_markup()
        if query.data == 'skip':
            promotion_['data']['start_date'] = None
        else:
            return PROM_START # Не должно случаться при корректном UI
    else:
        try:
            date_str = update.effective_message.text
            promotion_['data']['start_date'] = datetime.strptime(date_str, '%d.%m.%Y')
        except ValueError:
            text = "Неверный формат даты. Используйте ДД.ММ.ГГГГ или пропустите:"
            await update.effective_chat.send_message(text)
            return PROM_START

    is_update = promotion_['service'].get('is_update', False)
    if is_update:
        return await ask_promotion_summary(update, context)
            
    text = "Введите дату окончания действия промокода в формате ДД.ММ.ГГГГ (или нажмите кнопку 'Пропустить'):"
    current_expire = promotion_['data'].get('expire_date')
    if current_expire:
        text = f"Текущая дата окончания: {current_expire.strftime('%d.%m.%Y')}\n\n" + text

    keyboard = [
        [InlineKeyboardButton("Пропустить", callback_data='skip')],
        add_btn_back_and_cancel(postfix_for_cancel='settings',
                                add_back_btn=True,
                                postfix_for_back=PROM_START)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.effective_chat.send_message(text, reply_markup=reply_markup)
    
    state = PROM_EXPIRE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

async def handle_prom_expire_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Введите дату окончания действия промокода в формате ДД.ММ.ГГГГ (или нажмите кнопку 'Пропустить'):"
    if is_update and promotion_['data'].get('expire_date'):
        text = f"Текущая дата окончания: {promotion_['data']['expire_date'].strftime('%d.%m.%Y')}\n\n" + text

    keyboard = [
        [InlineKeyboardButton("Пропустить", callback_data='skip')],
    ]
    if promotion_['data'].get('expire_date') is not None:
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_START))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_EXPIRE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_expire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_reply_markup()
        if query.data == 'skip':
            promotion_['data']['expire_date'] = None
        else:
            return PROM_EXPIRE
    else:
        try:
            date_str = update.effective_message.text
            promotion_['data']['expire_date'] = datetime.strptime(date_str, '%d.%m.%Y')
        except ValueError:
            text = "Неверный формат даты. Используйте ДД.ММ.ГГГГ или пропустите:"
            await update.effective_chat.send_message(text)
            return PROM_EXPIRE

    is_update = promotion_['service'].get('is_update', False)
    if is_update:
        return await ask_promotion_summary(update, context)

    text = "Введите максимальное количество использований (0 для бесконечного использования):"
    current_max_usage = promotion_['data'].get('max_count_of_usage')
    if current_max_usage is not None:
        text = f"Текущее ограничение: {current_max_usage}\n\n" + text

    await update.effective_chat.send_message(text)
    
    state = PROM_MAX_USAGE
    context.user_data['STATE'] = state
    return state

async def handle_prom_max_usage_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Введите максимальное количество использований (0 для бесконечного использования):"
    if is_update:
        text = f"Текущее ограничение: {promotion_['data']['max_count_of_usage']}\n\n" + text

    keyboard = []
    if promotion_['data'].get('max_count_of_usage') is not None:
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_EXPIRE))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_MAX_USAGE
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_max_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=promotion_['service']['message_id']
        )
    except Exception:
        pass

    try:
        value = int(update.effective_message.text)
    except ValueError:
        text = "Пожалуйста, введите целое число:"
        await update.effective_chat.send_message(text)
        return PROM_MAX_USAGE
        
    promotion_['data']['max_count_of_usage'] = value
    
    is_update = promotion_['service'].get('is_update', False)
    if is_update:
        return await ask_promotion_summary(update, context)

    return await handle_prom_max_usage_user_start(update, context)


async def handle_prom_max_usage_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Введите максимальное количество использований на одного пользователя (0 для бесконечного использования):"
    if is_update:
        text = f"Текущее ограничение на пользователя: {promotion_['data'].get('max_usage_per_user', 0)}\n\n" + text

    keyboard = []
    if promotion_['data'].get('max_usage_per_user') is not None:
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_MAX_USAGE))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_MAX_USAGE_USER
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_max_usage_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=promotion_['service']['message_id']
        )
    except Exception:
        pass

    try:
        value = int(update.effective_message.text)
    except ValueError:
        text = "Пожалуйста, введите целое число:"
        await update.effective_chat.send_message(text)
        return PROM_MAX_USAGE_USER

    promotion_['data']['max_usage_per_user'] = value

    is_update = promotion_['service'].get('is_update', False)
    if is_update:
        return await ask_promotion_summary(update, context)

    text = "Введите описание для пользователя (отображается на кнопке льготы или в подтверждении, например: 'Скидка 10% для многодетных'):"
    current_desc = promotion_['data'].get('description_user')
    if current_desc:
        text = f"Текущее описание: {current_desc}\n\n" + text

    keyboard = [
        [InlineKeyboardButton("Пропустить (использовать название)", callback_data='skip')],
        add_btn_back_and_cancel(postfix_for_cancel='settings',
                                add_back_btn=True,
                                postfix_for_back=PROM_MAX_USAGE_USER)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id
    
    state = PROM_DESC
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state

async def handle_prom_desc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    promotion_ = context.user_data['new_promotion']
    is_update = promotion_['service'].get('is_update', False)

    text = "Введите описание для пользователя (отображается на кнопке льготы или в подтверждении, например: 'Скидка 10% для многодетных'):"
    if is_update:
        text = f"Текущее описание: {promotion_['data']['description_user']}\n\n" + text

    keyboard = [
        [InlineKeyboardButton("Пропустить (использовать название)", callback_data='skip')],
    ]
    if promotion_['data'].get('description_user'):
        keyboard.append([InlineKeyboardButton("✅ К подтверждению", callback_data='skip_to_confirm')])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings',
                                            add_back_btn=True,
                                            postfix_for_back=PROM_CONFIRM if is_update else PROM_MAX_USAGE))
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    promotion_['service']['message_id'] = message.message_id

    state = PROM_DESC
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def ask_promotion_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    promo = promotion_['data']
    is_update = promotion_['service'].get('is_update', False)

    discount_type_label = 'Процент' if promo.get('discount_type') == PromotionDiscountType.percentage else 'Фиксированная'
    currency_symbol = '%' if promo.get('discount_type') == PromotionDiscountType.percentage else '₽'
    is_visible_button = 'Да' if promo.get('is_visible_as_option') else 'Нет'
    is_verify_required = 'Да' if promo.get('requires_verification') else 'Нет'
    start_date = promo.get('start_date').strftime('%d.%m.%Y') if promo.get('start_date') else 'Нет'
    expire_date = promo.get('expire_date').strftime('%d.%m.%Y') if promo.get('expire_date') else 'Нет'
    max_usage_count = promo.get('max_count_of_usage') if promo.get('max_count_of_usage', 0) > 0 else 'Бесконечно'
    max_usage_per_user = promo.get('max_usage_per_user') if promo.get('max_usage_per_user', 0) > 0 else 'Бесконечно'
    
    summary = (
        f"<b>{'Редактирование' if is_update else 'Проверка'} промокода</b>\n\n"
        f"1. 📝 <b>Название:</b> {promo.get('name', 'Не указано')}\n"
        f"2. 🔑 <b>Код:</b> <code>{promo.get('code', 'Не указано')}</code>\n"
        f"3. 💰 <b>Тип скидки:</b> {discount_type_label}\n"
        f"4. 📊 <b>Размер:</b> {promo.get('discount', 0)}{currency_symbol}\n"
        f"5. 💳 <b>Мин. сумма:</b> {promo.get('min_purchase_sum', 0)} ₽\n"
        f"6. 👁 <b>Кнопка выбора:</b> {is_visible_button}\n"
        f"7. 📄 <b>Требовать документ:</b> {is_verify_required}\n"
        f"8. 📅 <b>Дата начала:</b> {start_date}\n"
        f"9. 📆 <b>Дата окончания:</b> {expire_date}\n"
        f"10. ♾ <b>Общий лимит:</b> {max_usage_count}\n"
        f"11. 👤 <b>Лимит на пользователя:</b> {max_usage_per_user}\n"
        f"12. 💬 <b>Описание:</b> {promo.get('description_user', 'Не указано')}\n"
        f"13. 📝 <b>Текст верификации:</b> {promo.get('verification_text', 'Не указано')}\n"
    )

    if promo.get('type_event_ids'):
        summary += f"\n🎭 <b>Ограничение по типам событий:</b> {len(promo['type_event_ids'])} шт."
    if promo.get('theater_event_ids'):
        summary += f"\n🎬 <b>Ограничение по репертуару:</b> {len(promo['theater_event_ids'])} шт."
    if promo.get('base_ticket_ids'):
        summary += f"\n🎟 <b>Ограничение по билетам:</b> {len(promo['base_ticket_ids'])} шт."
    if promo.get('schedule_event_ids'):
        summary += f"\n📅 <b>Ограничение по сеансам:</b> {len(promo['schedule_event_ids'])} шт."

    keyboard = [
        [
            InlineKeyboardButton("1. Название", callback_data='prom_edit_name'),
            InlineKeyboardButton("2. Код", callback_data='prom_edit_code'),
        ],
        [
            InlineKeyboardButton("3, 4. Тип и размер", callback_data='prom_edit_type'),
            InlineKeyboardButton("5. Мин. сумма", callback_data='prom_edit_min_sum'),
        ],
        [
            InlineKeyboardButton("6. Кнопка выбора", callback_data='prom_edit_visible'),
            InlineKeyboardButton("7. Документ", callback_data='prom_edit_verify'),
        ],
        [
            InlineKeyboardButton("8. Дата начала", callback_data='prom_edit_start_date'),
            InlineKeyboardButton("9. Дата окончания", callback_data='prom_edit_expire_date'),
        ],
        [
            InlineKeyboardButton("10. Общий лимит", callback_data='prom_edit_max_usage'),
            InlineKeyboardButton("11. Лимит на пользователя", callback_data='prom_edit_max_usage_user'),
        ],
        [
            InlineKeyboardButton("12. Описание", callback_data='prom_edit_desc'),
            InlineKeyboardButton("13. Текст верификации", callback_data='prom_edit_vtext'),
        ],
        [
            InlineKeyboardButton("🎭 Типы событий", callback_data='prom_restrict_type'),
            InlineKeyboardButton("🎬 Репертуар", callback_data='prom_restrict_theater'),
        ],
        [
            InlineKeyboardButton("🎟 Билеты", callback_data='prom_restrict_ticket'),
            InlineKeyboardButton("📅 Сеансы", callback_data='prom_restrict_schedule'),
        ],
        [InlineKeyboardButton("✅ Подтвердить и сохранить", callback_data='accept')],
        add_btn_back_and_cancel(postfix_for_cancel='settings',
                                add_back_btn=True,
                                postfix_for_back='3')
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        message = await update.callback_query.edit_message_text(summary, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(summary, reply_markup=reply_markup)
    
    promotion_['service']['message_id'] = message.message_id
    state = PROM_CONFIRM
    await set_back_context(context, state, summary, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_prom_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promotion_ = context.user_data['new_promotion']
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=promotion_['service']['message_id']
        )
    except Exception:
        pass

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == 'skip':
            promotion_['data']['description_user'] = promotion_['data']['name']
        elif query.data == 'skip_to_confirm':
            pass
        else:
            return PROM_DESC
    else:
        promotion_['data']['description_user'] = update.effective_message.text

    return await ask_promotion_summary(update, context)


# ===== Helpers for restrictions multi-select =====
async def _render_multi_select(update: Update,
                               context: ContextTypes.DEFAULT_TYPE,
                               items,
                               selected_ids: list[int],
                               page: int,
                               per_page: int,
                               prefix: str,
                               label_getter) -> None:
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    end = start + per_page
    subset = items[start:end]

    keyboard = []
    for it in subset:
        it_id = getattr(it, 'id', getattr(it, 'base_ticket_id', None))
        mark = '✅' if it_id in selected_ids else '▫️'
        label = label_getter(it)
        keyboard.append([
            InlineKeyboardButton(f"{mark} {label}", callback_data=f"{prefix}_t_{it_id}_{page}")
        ])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton('⬅️ Назад', callback_data=f"{prefix}_p_{page-1}"))
    if end < total:
        nav_row.append(InlineKeyboardButton('Вперед ➡️', callback_data=f"{prefix}_p_{page+1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([
        InlineKeyboardButton('Готово', callback_data=f"{prefix}_done")
    ])
    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='62'))

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_reply_markup(reply_markup)
    else:
        await update.effective_chat.send_message('Выберите элементы', reply_markup=reply_markup)


# ---- TypeEvent restrictions ----
async def open_restrict_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    data = context.user_data.get('new_promotion', {}).get('data', {})
    selected = data.get('type_event_ids', []) or []

    items = await db_postgres.get_all_type_events(context.session)

    await _render_multi_select(
        update, context, items, selected, page=0, per_page=10,
        prefix='prm_rt',
        label_getter=lambda x: f"#{x.id} {x.name}"
    )
    state = PROM_RESTRICT_TYPE
    await set_back_context(context, state, 'restrict_type', None)
    context.user_data['STATE'] = state
    return state


async def handle_restrict_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data['new_promotion']['data']
    selected = data.get('type_event_ids', []) or []

    parts = query.data.split('_')
    # patterns: prm_rt_t_{id}_{page}; prm_rt_p_{page}; prm_rt_done
    if query.data.startswith('prm_rt_t_'):
        it_id = int(parts[3])
        page = int(parts[4]) if len(parts) > 4 else 0
        if it_id in selected:
            selected.remove(it_id)
        else:
            selected.append(it_id)
        data['type_event_ids'] = selected
        items = await db_postgres.get_all_type_events(context.session)
        await _render_multi_select(update, context, items, selected, page, 10, 'prm_rt', lambda x: f"#{x.id} {x.name}")
        return PROM_RESTRICT_TYPE
    elif query.data.startswith('prm_rt_p_'):
        page = int(parts[3])
        items = await db_postgres.get_all_type_events(context.session)
        await _render_multi_select(update, context, items, selected, page, 10, 'prm_rt', lambda x: f"#{x.id} {x.name}")
        return PROM_RESTRICT_TYPE
    else:  # done
        return await ask_promotion_summary(update, context)


# ---- TheaterEvent restrictions ----
async def open_restrict_theater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    data = context.user_data.get('new_promotion', {}).get('data', {})
    selected = data.get('theater_event_ids', []) or []

    items = await db_postgres.get_all_theater_events(context.session)

    await _render_multi_select(
        update, context, items, selected, page=0, per_page=10,
        prefix='prm_rth',
        label_getter=lambda x: f"#{x.id} {x.name}"
    )
    state = PROM_RESTRICT_THEATER
    await set_back_context(context, state, 'restrict_theater', None)
    context.user_data['STATE'] = state
    return state


async def handle_restrict_theater_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data['new_promotion']['data']
    selected = data.get('theater_event_ids', []) or []

    parts = query.data.split('_')
    if query.data.startswith('prm_rth_t_'):
        it_id = int(parts[3])
        page = int(parts[4]) if len(parts) > 4 else 0
        if it_id in selected:
            selected.remove(it_id)
        else:
            selected.append(it_id)
        data['theater_event_ids'] = selected
        items = await db_postgres.get_all_theater_events(context.session)
        await _render_multi_select(update, context, items, selected, page, 10, 'prm_rth', lambda x: f"#{x.id} {x.name}")
        return PROM_RESTRICT_THEATER
    elif query.data.startswith('prm_rth_p_'):
        page = int(parts[3])
        items = await db_postgres.get_all_theater_events(context.session)
        await _render_multi_select(update, context, items, selected, page, 10, 'prm_rth', lambda x: f"#{x.id} {x.name}")
        return PROM_RESTRICT_THEATER
    else:
        return await ask_promotion_summary(update, context)


# ---- BaseTicket restrictions ----
async def open_restrict_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    data = context.user_data.get('new_promotion', {}).get('data', {})
    selected = data.get('base_ticket_ids', []) or []

    items = await db_postgres.get_all_base_tickets(context.session)

    await _render_multi_select(
        update, context, items, selected, page=0, per_page=10,
        prefix='prm_rbt',
        label_getter=lambda x: f"#{x.base_ticket_id} {x.name}"
    )
    state = PROM_RESTRICT_TICKET
    await set_back_context(context, state, 'restrict_ticket', None)
    context.user_data['STATE'] = state
    return state


async def handle_restrict_ticket_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data['new_promotion']['data']
    selected = data.get('base_ticket_ids', []) or []

    parts = query.data.split('_')
    if query.data.startswith('prm_rbt_t_'):
        it_id = int(parts[3])
        page = int(parts[4]) if len(parts) > 4 else 0
        if it_id in selected:
            selected.remove(it_id)
        else:
            selected.append(it_id)
        data['base_ticket_ids'] = selected
        items = await db_postgres.get_all_base_tickets(context.session)
        await _render_multi_select(update, context, items, selected, page, 10, 'prm_rbt', lambda x: f"#{x.base_ticket_id} {x.name}")
        return PROM_RESTRICT_TICKET
    elif query.data.startswith('prm_rbt_p_'):
        page = int(parts[3])
        items = await db_postgres.get_all_base_tickets(context.session)
        await _render_multi_select(update, context, items, selected, page, 10, 'prm_rbt', lambda x: f"#{x.base_ticket_id} {x.name}")
        return PROM_RESTRICT_TICKET
    else:
        return await ask_promotion_summary(update, context)


# ---- ScheduleEvent restrictions ----
async def open_restrict_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    data = context.user_data.get('new_promotion', {}).get('data', {})
    selected = data.get('schedule_event_ids', []) or []

    items = await db_postgres.get_all_schedule_events_actual(context.session)

    await _render_multi_select(
        update, context, items, selected, page=0, per_page=10,
        prefix='prm_rse',
        label_getter=lambda x: f"#{x.id} [{x.theater_event.name if x.theater_event else '?'}] {x.datetime_event.strftime('%d.%m %H:%M')}"
    )
    state = PROM_RESTRICT_SCHEDULE
    await set_back_context(context, state, 'restrict_schedule', None)
    context.user_data['STATE'] = state
    return state


async def handle_restrict_schedule_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data['new_promotion']['data']
    selected = data.get('schedule_event_ids', []) or []

    parts = query.data.split('_')
    if query.data.startswith('prm_rse_t_'):
        it_id = int(parts[3])
        page = int(parts[4]) if len(parts) > 4 else 0
        if it_id in selected:
            selected.remove(it_id)
        else:
            selected.append(it_id)
        data['schedule_event_ids'] = selected
        items = await db_postgres.get_all_schedule_events_actual(context.session)
        await _render_multi_select(update, context, items, selected, page, 10, 'prm_rse', lambda x: f"#{x.id} [{x.theater_event.name if x.theater_event else '?'}] {x.datetime_event.strftime('%d.%m %H:%M')}")
        return PROM_RESTRICT_SCHEDULE
    elif query.data.startswith('prm_rse_p_'):
        page = int(parts[3])
        items = await db_postgres.get_all_schedule_events_actual(context.session)
        await _render_multi_select(update, context, items, selected, page, 10, 'prm_rse', lambda x: f"#{x.id} [{x.theater_event.name if x.theater_event else '?'}] {x.datetime_event.strftime('%d.%m %H:%M')}")
        return PROM_RESTRICT_SCHEDULE
    else:
        return await ask_promotion_summary(update, context)


async def promotion_confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    promotion_data = context.user_data['new_promotion']['data']
    is_update = context.user_data['new_promotion']['service'].get('is_update', False)
    
    try:
        if is_update:
            promo_id = promotion_data.pop('id')
            await db_postgres.update_promotion(context.session, promo_id, promotion_data)
            await query.answer("Промокод успешно обновлен!")
        else:
            # Добавляем недостающие поля
            promotion_data['flag_active'] = True
            promotion_data['count_of_usage'] = 0
            promotion_data['for_who_discount'] = GroupOfPeopleByDiscountType.all
            
            await db_postgres.create_promotion(context.session, promotion_data)
            await query.answer("Промокод успешно создан!")
    except Exception as e:
        logger.exception(f"Ошибка при сохранении промокода: {e}")
        await query.answer(f"Ошибка при сохранении: {e}", show_alert=True)
        
    return await send_settings_menu(update, context, 'promotion')

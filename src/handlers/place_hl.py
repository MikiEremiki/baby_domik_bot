import logging
import re
from typing import Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from db import db_postgres
from handlers import support_hl
from utilities.utl_func import set_back_context
from utilities.utl_kbd import add_btn_back_and_cancel

logger = logging.getLogger('bot.place_hl')

# Состояния мастера создания/редактирования локаций
(
    PLACE_NAME,
    PLACE_ADDRESS,
    PLACE_YNDX,
    PLACE_ABOUT,
    PLACE_CONFIRM,
    PLACE_EDIT_FIELD,
) = range(80, 86)


async def place_select(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except BadRequest:
            pass
        data = query.data or ""
    else:
        data = ""

    page = 0
    match_p = re.search(r'_p_(\d+)', data)
    if match_p:
        page = int(match_p.group(1))

    places = await db_postgres.get_places(context.session)
    default_place = await db_postgres.get_default_place(context.session)
    default_id = default_place.id if default_place else None

    def place_formatter(row):
        is_def = " ⭐️ (по умолчанию)" if row.id == default_id else ""
        maps = f"\n  🗺 {row.link_on_yndx_maps}" if row.link_on_yndx_maps else ""
        about = f"\n  ℹ️ {row.link_about}" if row.link_about else ""
        return f"• ID {row.id}: <b>{row.name}</b>{is_def}\n  📍 {row.address}{maps}{about}\n"

    return await support_hl._paginated_select(
        update, context, places,
        'Справочник локаций',
        place_formatter,
        'place_select',
        page
    )


async def place_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    context.user_data['place_form'] = {
        'name': '',
        'address': '',
        'link_on_yndx_maps': None,
        'link_about': None,
        'is_update': False,
        'place_id': None,
    }

    text = "<b>Создание новой локации</b>\n\nШаг 1/4. Введите название локации (например, <i>Домик</i> или <i>Театр на Покровке</i>):"
    keyboard = [
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3')
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)

    context.user_data['place_form']['message_id'] = message.message_id
    state = PLACE_NAME
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def place_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_message.text.strip()
    if not name:
        await update.effective_chat.send_message("Название не может быть пустым. Введите название:")
        return PLACE_NAME

    context.user_data['place_form']['name'] = name
    text = f"Название: <b>{name}</b>\n\nШаг 2/4. Введите фактический адрес локации:"
    keyboard = [
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=str(PLACE_NAME))
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    context.user_data['place_form']['message_id'] = message.message_id

    state = PLACE_ADDRESS
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def place_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.effective_message.text.strip()
    if not address:
        await update.effective_chat.send_message("Адрес не может быть пустым. Введите адрес:")
        return PLACE_ADDRESS

    context.user_data['place_form']['address'] = address
    text = (
        f"Адрес: <b>{address}</b>\n\n"
        "Шаг 3/4. Введите ссылку на Яндекс Карты (начинается с http:// или https://) "
        "или нажмите «Пропустить»:"
    )
    keyboard = [
        [InlineKeyboardButton("Пропустить ➡️", callback_data="place_skip_yndx")],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=str(PLACE_ADDRESS))
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.effective_chat.send_message(text, reply_markup=reply_markup)
    context.user_data['place_form']['message_id'] = message.message_id

    state = PLACE_YNDX
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def place_get_yndx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        url = None
    else:
        url = update.effective_message.text.strip()
        if not (url.startswith('http://') or url.startswith('https://')):
            await update.effective_chat.send_message(
                "Ссылка должна начинаться с http:// или https://. Введите корректную ссылку или нажмите Пропустить:"
            )
            return PLACE_YNDX

    context.user_data['place_form']['link_on_yndx_maps'] = url

    text = (
        "Шаг 4/4. Введите ссылку «Подробнее» о площадке (начинается с http:// или https://) "
        "или нажмите «Пропустить»:"
    )
    keyboard = [
        [InlineKeyboardButton("Пропустить ➡️", callback_data="place_skip_about")],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=str(PLACE_YNDX))
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        message = await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        message = await update.effective_chat.send_message(text, reply_markup=reply_markup)

    context.user_data['place_form']['message_id'] = message.message_id
    state = PLACE_ABOUT
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def place_get_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        url = None
    else:
        url = update.effective_message.text.strip()
        if not (url.startswith('http://') or url.startswith('https://')):
            await update.effective_chat.send_message(
                "Ссылка должна начинаться с http:// или https://. Введите корректную ссылку или нажмите Пропустить:"
            )
            return PLACE_ABOUT

    context.user_data['place_form']['link_about'] = url
    return await place_show_confirm(update, context)


async def place_show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    form = context.user_data['place_form']
    is_update = form.get('is_update', False)

    summary = (
        f"<b>{'Редактирование' if is_update else 'Проверка данных'} локации</b>\n\n"
        f"1. 🏷 <b>Название:</b> {form['name']}\n"
        f"2. 📍 <b>Адрес:</b> {form['address']}\n"
        f"3. 🗺 <b>Яндекс Карты:</b> {form['link_on_yndx_maps'] or 'не указано'}\n"
        f"4. ℹ️ <b>Подробнее:</b> {form['link_about'] or 'не указано'}\n"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Сохранить", callback_data="place_save_confirm")],
        add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3')
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=reply_markup)
    else:
        await update.effective_chat.send_message(summary, reply_markup=reply_markup)

    state = PLACE_CONFIRM
    await set_back_context(context, state, summary, reply_markup)
    context.user_data['STATE'] = state
    return state


async def place_confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    form = context.user_data['place_form']
    is_update = form.get('is_update', False)

    if is_update and form.get('place_id'):
        place = await db_postgres.update_place(
            context.session,
            place_id=form['place_id'],
            name=form['name'],
            address=form['address'],
            link_on_yndx_maps=form['link_on_yndx_maps'],
            link_about=form['link_about'],
        )
        msg_text = f"✅ Локация «{place.name}» (ID {place.id}) успешно обновлена!"
    else:
        place = await db_postgres.create_place(
            context.session,
            name=form['name'],
            address=form['address'],
            link_on_yndx_maps=form['link_on_yndx_maps'],
            link_about=form['link_about'],
        )
        msg_text = f"✅ Локация «{place.name}» (ID {place.id}) успешно создана!"

    await update.effective_chat.send_message(msg_text)
    return await place_select(update, context)


async def place_update_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    match = re.search(r'place_edit_(\d+)', query.data)
    if not match:
        return 3
    place_id = int(match.group(1))
    place = await db_postgres.get_place(context.session, place_id)
    if not place:
        await query.edit_message_text("Локация не найдена.")
        return 3

    default_place = await db_postgres.get_default_place(context.session)
    is_default = (default_place and default_place.id == place.id)

    context.user_data['place_form'] = {
        'place_id': place.id,
        'name': place.name,
        'address': place.address,
        'link_on_yndx_maps': place.link_on_yndx_maps,
        'link_about': place.link_about,
        'is_update': True,
    }

    text = (
        f"<b>Редактирование локации ID {place.id}</b>\n\n"
        f"1. 🏷 <b>Название:</b> {place.name}\n"
        f"2. 📍 <b>Адрес:</b> {place.address}\n"
        f"3. 🗺 <b>Яндекс Карты:</b> {place.link_on_yndx_maps or 'не указано'}\n"
        f"4. ℹ️ <b>Подробнее:</b> {place.link_about or 'не указано'}\n"
        f"⭐️ <b>По умолчанию:</b> {'Да' if is_default else 'Нет'}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("1. Название", callback_data=f"place_ch_name_{place.id}"),
            InlineKeyboardButton("2. Адрес", callback_data=f"place_ch_addr_{place.id}"),
        ],
        [
            InlineKeyboardButton("3. Яндекс Карты", callback_data=f"place_ch_yndx_{place.id}"),
            InlineKeyboardButton("4. Подробнее", callback_data=f"place_ch_about_{place.id}"),
        ],
    ]
    if not is_default:
        keyboard.append([InlineKeyboardButton("⭐️ Сделать локацией по умолчанию", callback_data=f"place_set_def_{place.id}")])

    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back='3'))
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup)
    state = PLACE_CONFIRM
    await set_back_context(context, state, text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def place_set_default(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    match = re.search(r'place_set_def_(\d+)', query.data)
    if match:
        place_id = int(match.group(1))
        await db_postgres.update_bot_setting(context.session, 'DEFAULT_PLACE_ID', str(place_id))
        await update.effective_chat.send_message(f"⭐️ Локация ID {place_id} установлена по умолчанию!")
    return await place_select(update, context)


async def place_edit_field_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if 'place_ch_name_' in data:
        field = 'name'
        field_prompt = "Введите новое название локации:"
        state = PLACE_NAME
    elif 'place_ch_addr_' in data:
        field = 'address'
        field_prompt = "Введите новый адрес локации:"
        state = PLACE_ADDRESS
    elif 'place_ch_yndx_' in data:
        field = 'link_on_yndx_maps'
        field_prompt = "Введите новую ссылку на Яндекс Карты (или нажмите Пропустить/Очистить):"
        state = PLACE_YNDX
    elif 'place_ch_about_' in data:
        field = 'link_about'
        field_prompt = "Введите новую ссылку Подробнее (или нажмите Пропустить/Очистить):"
        state = PLACE_ABOUT
    else:
        return 3

    keyboard = []
    if field in ('link_on_yndx_maps', 'link_about'):
        keyboard.append([InlineKeyboardButton("Очистить поле ❌", callback_data=f"place_skip_{'yndx' if field=='link_on_yndx_maps' else 'about'}")])
    keyboard.append(add_btn_back_and_cancel(postfix_for_cancel='settings', add_back_btn=True, postfix_for_back=str(PLACE_CONFIRM)))
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(field_prompt, reply_markup=reply_markup)
    await set_back_context(context, state, field_prompt, reply_markup)
    context.user_data['STATE'] = state
    return state

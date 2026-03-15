import logging

from sulguk import transform_html
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.error import TimedOut, NetworkError, BadRequest
from telegram.ext import (
    ContextTypes, ConversationHandler, ApplicationHandlerStop)
from telegram.constants import ChatAction

from api.gspread_pub import (
    publish_write_client_list_waiting)

from db import db_postgres
from handlers.common_hl import validate_phone_or_request
from handlers.reserve.common import (
    get_child_text_and_reply,
    send_msg_get_child,
    send_msg_get_phone,
)
from handlers.email_hl import check_email_and_update_user
from handlers.reserve.payment import show_reservation_summary
from handlers.sub_hl import (
    request_phone_number,
    send_breaf_message, send_message_about_list_waiting,
)
from api.googlesheets import write_client_list_waiting
from utilities.utl_check import (
    check_available_ticket_by_free_seat,
    check_entered_command, is_skip_ticket
)
from utilities.utl_func import (
    set_back_context,
    get_formatted_date_and_time_of_event,
    add_clients_data_to_text, add_qty_visitors_to_text,
)
from utilities.utl_kbd import (
    add_btn_back_and_cancel,
    create_replay_markup,
    remove_intent_id,
    create_phone_confirm_btn, create_kbd_edit_children,
)
from settings.settings import (
    ADMIN_GROUP, COMMAND_DICT,
)

reserve_hl_logger = logging.getLogger('bot.reserve_hl')


async def get_email(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    query = update.callback_query
    reserve_user_data = context.user_data['reserve_user_data']
    if not query:
        try:
            await context.bot.edit_message_reply_markup(
                update.effective_chat.id,
                message_id=reserve_user_data['message_id']
            )
        except BadRequest as e:
            reserve_hl_logger.error(e)
        await check_email_and_update_user(update, context)

    reserve_user_data = context.user_data['reserve_user_data']

    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    price = reserve_user_data['chose_price']
    text_select_event = reserve_user_data['text_select_event']

    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)
    text = (f'{text_select_event}<br>'
            f'Вариант бронирования:<br>'
            f'{chose_base_ticket.name} '
            f'{int(price)}руб<br>')

    context.user_data['common_data']['text_for_notification_massage'] = text

    res_text = transform_html(text)
    await update.effective_chat.send_message(
        text=res_text.text, entities=res_text.entities, parse_mode=None)
    message = await update.effective_chat.send_message(
        'Проверяю наличие свободных мест...')
    await update.effective_chat.send_action(ChatAction.TYPING)

    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    schedule_event = await db_postgres.get_schedule_event(
        context.session, schedule_event_id)
    context.session.add(schedule_event)
    await context.session.refresh(schedule_event)
    theater_event = await db_postgres.get_theater_event(context.session,
                                                        schedule_event.theater_event_id)
    type_event = await db_postgres.get_type_event(context.session,
                                                  schedule_event.type_event_id)

    check_command = check_entered_command(context, 'reserve')
    only_child = None
    if check_command:
        only_child = False
    check_command = check_entered_command(context, 'studio')
    if check_command:
        only_child = True
    if only_child is None:
        reserve_hl_logger.error(f'{only_child=}')
        raise ApplicationHandlerStop

    check_ticket = check_available_ticket_by_free_seat(
        schedule_event,
        theater_event,
        type_event,
        chose_base_ticket,
        only_child
    )
    if query:
        try:
            await query.answer()
        except TimedOut as e:
            reserve_hl_logger.error(e)

        text = f'{update.effective_message.text}\n\nДа'
        entities = update.effective_message.entities
        await query.edit_message_text(text, entities=entities)
    if check_command and not check_ticket:
        await message.delete()
        await send_message_about_list_waiting(update, context)

        state = 'CHOOSING'
        context.user_data['STATE'] = state
        return state

    reserve_hl_logger.info('Получено разрешение на бронирование')

    message = await message.edit_text(
        'Проверка пройдена, готовлю дальнейшие шаги...')
    await update.effective_chat.send_action(ChatAction.TYPING)

    await message.delete()
    message = await send_breaf_message(update, context)

    reserve_user_data['message_id'] = message.message_id
    state = 'FORMA'
    context.user_data['STATE'] = state
    return state


async def get_adult(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    reserve_user_data = context.user_data['reserve_user_data']

    await context.bot.edit_message_reply_markup(
        update.effective_chat.id,
        message_id=reserve_user_data['message_id']
    )
    text = update.effective_message.text

    reserve_user_data['client_data']['name_adult'] = text
    message = await send_msg_get_phone(update, context)

    reserve_user_data['message_id'] = message.message_id
    state = 'PHONE'
    context.user_data['STATE'] = state
    return state


async def get_phone(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    reserve_user_data = context.user_data['reserve_user_data']

    await context.bot.edit_message_reply_markup(
        update.effective_chat.id,
        message_id=reserve_user_data['message_id']
    )
    phone, message = await validate_phone_or_request(
        update,
        context,
        update.effective_message.text,
    )
    if phone is None:
        reserve_user_data['message_id'] = message.message_id
        return context.user_data['STATE']

    reserve_user_data['client_data']['phone'] = phone
    message = await send_msg_get_child(update, context)

    reserve_user_data['message_id'] = message.message_id
    state = 'CHILDREN'
    context.user_data['STATE'] = state
    return state


async def _finish_get_children(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE',
        processed_data_on_children,
        original_child_text
):
    reserve_user_data = context.user_data['reserve_user_data']
    client_data = reserve_user_data['client_data']
    client_data['data_children'] = processed_data_on_children
    reserve_user_data['original_child_text'] = original_child_text

    return await show_reservation_summary(update, context)


async def _handle_chld_edit_callback(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    data = query.data
    reserve_user_data = context.user_data['reserve_user_data']
    children = reserve_user_data.get('children', [])

    if data == 'CHLD_EDIT':
        reserve_user_data['is_editing_children'] = True
        reserve_user_data['is_adding_child'] = False
        reserve_user_data['is_editing_child_data'] = False
        # Сброс на первую страницу
        reserve_user_data['children_page'] = 0
    elif data == 'CHLD_ADD':
        reserve_user_data['is_adding_child'] = True
        text = ('<b>Добавление ребенка</b>\n\n'
                'Напишите имя и сколько полных лет ребенку в формате:\n'
                '<code>Имя Возраст</code>\n'
                'Например: <code>Сергей 2</code>')
        # Кнопка отмены возвращает в основное меню
        keyboard = [[InlineKeyboardButton("Назад", callback_data="CHLD_EDIT")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=text, reply_markup=reply_markup)
        return 'CHILDREN'
    elif data.startswith('CHLD_EDIT_ONE|'):
        try:
            person_id = int(data.split('|')[1])
        except (IndexError, ValueError):
            return 'CHILDREN'
        # Определяем индекс текущего ребенка в списке для совместимости с дальнейшей логикой
        idx = None
        for i, c in enumerate(children):
            if c[2] == person_id:
                idx = i
                break
        # Если не нашли (например, изменился фильтр), перезагрузим список по активному фильтру
        if idx is None:
            children = await _update_children(update, context)
            reserve_user_data['children'] = children
            for i, c in enumerate(children):
                if c[2] == person_id:
                    idx = i
                    break
        if idx is None:
            # Не удалось найти ребенка — просто обновим экран
            chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
            chose_base_ticket = await db_postgres.get_base_ticket(
                context.session, chose_base_ticket_id)
            text, reply_markup = await get_child_text_and_reply(
                update, chose_base_ticket, children, context)
            try:
                await query.edit_message_text(text=text, reply_markup=reply_markup)
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise e
            await set_back_context(context, 'CHILDREN', text, reply_markup)
            return 'CHILDREN'

        # Сохраняем редактируемого ребенка по ID
        reserve_user_data['edit_person_id'] = person_id
        child = children[idx]

        # Получаем расширенную информацию о родителе
        child_person = await db_postgres.get_person(context.session, person_id)
        parent_info = ""
        if child_person and child_person.parent:
            parent = child_person.parent
            phone = parent.adult.phone if parent.adult else None
            if phone and not phone.startswith('+7'):
                pretty_phone = f'+7{phone}'
            else:
                pretty_phone = phone
            parent_info = f"Родитель: <b>{parent.name}</b>"
            if pretty_phone:
                parent_info += f" (<code>{pretty_phone}</code>)"
            parent_info = f"\n{parent_info}\n"

        text = (f'<b>Редактирование: {child[0]} {int(child[1])}</b>\n'
                f'{parent_info}\n'
                f'Выберите действие:')
        keyboard = [
            [InlineKeyboardButton(
                "✏️ Изменить", callback_data=f"CHLD_EDIT_START|{person_id}")],
            [InlineKeyboardButton(
                "❌ Удалить", callback_data=f"CHLD_DEL|{person_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="CHLD_EDIT")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=text, reply_markup=reply_markup)
        return 'CHILDREN'
    elif data.startswith('CHLD_EDIT_PAGE|'):
        page = int(data.split('|')[1])
        reserve_user_data['children_page'] = page
    elif data.startswith('CHLD_DEL|'):
        person_id = int(data.split('|')[1])
        await db_postgres.delete_person(context.session, person_id)
        # Обновляем список детей в контексте согласно активному фильтру
        children = await _update_children(update, context)
        reserve_user_data['children'] = children
        # Сбрасываем выбранных детей, так как список изменился
        reserve_user_data['selected_children'] = []

    elif data.startswith('CHLD_EDIT_START|'):
        try:
            person_id = int(data.split('|')[1])
        except (IndexError, ValueError):
            return 'CHILDREN'
        reserve_user_data['is_editing_child_data'] = True
        reserve_user_data['edit_person_id'] = person_id
        text = ('Напишите новое имя и сколько полных лет ребенку в формате: '
                '<code>Имя Возраст</code>\nНапример: <code>Сергей 3</code>')
        keyboard = [[InlineKeyboardButton("Отмена", callback_data="CHLD_EDIT")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=text, reply_markup=reply_markup)
        return 'CHILDREN'

    # Обновляем сообщение для всех случаев (EDIT, PAGE, DEL, EDIT_START)
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)
    text, reply_markup = await get_child_text_and_reply(
        update, chose_base_ticket, children, context)
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise e
    await set_back_context(context, 'CHILDREN', text, reply_markup)
    return 'CHILDREN'


async def _update_children(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reserve_user_data = context.user_data
    mode = reserve_user_data.get('child_filter_mode', 'PHONE')
    if (
            mode == 'PHONE' and
            reserve_user_data.get('client_data', {}).get('phone')
    ):
        phone = reserve_user_data['client_data']['phone']
        children = await db_postgres.get_children_by_phone(
            context.session, phone)
    else:
        children = await db_postgres.get_children(
            context.session, update.effective_user.id)
    return children


async def _handle_chld_selection_callback(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chose_base_ticket
):
    query = update.callback_query
    data = query.data
    reserve_user_data = context.user_data['reserve_user_data']
    children = reserve_user_data.get('children', [])

    if data.startswith('CHLD_SEL|'):
        try:
            person_id = int(data.split('|')[1])
        except (IndexError, ValueError):
            return 'CHILDREN'
        # Если требуется выбрать одного ребенка — завершаем сразу
        if chose_base_ticket.quality_of_children == 1:
            # Находим ребенка по person_id
            child = next((c for c in children if c[2] == person_id), None)
            if child is None:
                text = "Не удалось найти выбранного ребенка"
                await query.answer(text, show_alert=True)
                return 'CHILDREN'
            processed_data_on_children = [[child[0], str(child[1])]]
            original_text = f"{child[0]} {int(child[1])}"
            await query.edit_message_reply_markup()
            return await _finish_get_children(
                update, context, processed_data_on_children, original_text)
        # Иначе режим множественного выбора
        selected = reserve_user_data.get('selected_children', [])
        if person_id in selected:
            selected.remove(person_id)
        else:
            if len(selected) < chose_base_ticket.quality_of_children:
                selected.append(person_id)
            else:
                text = f"Выбрано максимум детей: {chose_base_ticket.quality_of_children}"
                await query.answer(text, show_alert=True)
                return 'CHILDREN'
        reserve_user_data['selected_children'] = selected
    elif data.startswith('CHLD_FLTR|'):
        mode = data.split('|')[1]
        reserve_user_data['child_filter_mode'] = mode
        # Перезагружаем список детей в соответствии с фильтром
        children = await _update_children(update, context)
        reserve_user_data['children'] = children
        # Очищаем выбор от отсутствующих ID
        available_ids = {c[2] for c in children}
        selected = [
            pid for pid in reserve_user_data.get('selected_children', []) if pid in available_ids
        ]
        reserve_user_data['selected_children'] = selected
    elif data.startswith('CHLD_PAGE|'):
        page = int(data.split('|')[1])
        reserve_user_data['children_page'] = page
    elif data == 'CHLD_CONFIRM':
        selected = reserve_user_data.get('selected_children', [])
        processed_data_on_children = []
        original_text_parts = []
        # Быстрый доступ по person_id
        child_by_id = {c[2]: c for c in children}
        for pid in selected:
            child = child_by_id.get(pid)
            if not child:
                # Перестраховка: пропускаем отсутствующих
                continue
            processed_data_on_children.append([child[0], str(child[1])])
            original_text_parts.append(f"{child[0]} {int(child[1])}")

        await query.edit_message_reply_markup()
        return await _finish_get_children(
            update,
            context,
            processed_data_on_children,
            "\n".join(original_text_parts)
        )
    elif data == 'Далее':
        await query.edit_message_reply_markup()
        return await _finish_get_children(
            update, context, [['0', '0']], 'Далее')
    # Обновляем сообщение для SEL и PAGE
    text, reply_markup = await get_child_text_and_reply(
        update, chose_base_ticket, children, context)
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise e
    await set_back_context(context, 'CHILDREN', text, reply_markup)
    return 'CHILDREN'


async def get_children(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    reserve_user_data = context.user_data['reserve_user_data']
    chose_base_ticket_id = reserve_user_data['chose_base_ticket_id']
    chose_base_ticket = await db_postgres.get_base_ticket(
        context.session, chose_base_ticket_id)

    if query:
        try:
            await query.answer()
        except TimedOut as e:
            reserve_hl_logger.error(e)
        data = query.data

        if (
                data.startswith('CHLD_EDIT') or
                data.startswith('CHLD_DEL') or data == 'CHLD_ADD'
        ):
            return await _handle_chld_edit_callback(update, context)

        if data.startswith('CHLD_') or data == 'Далее':
            return await _handle_chld_selection_callback(
                update, context, chose_base_ticket)

        return 'CHILDREN'

    try:
        await context.bot.edit_message_reply_markup(
            update.effective_chat.id,
            message_id=reserve_user_data['message_id']
        )
    except BadRequest as e:
        reserve_hl_logger.error(e)
    await update.effective_chat.send_action(ChatAction.TYPING)

    if (
            reserve_user_data.get('is_adding_child', False) or
            reserve_user_data.get('is_editing_child_data', False)
    ):
        text = update.effective_message.text
        parts = text.split()
        if (
                len(parts) >= 2 and
                parts[-1].replace('.', '', 1).replace(',', '', 1).isdigit()
        ):
            name = " ".join(parts[:-1])
            try:
                age = float(parts[-1].replace(',', '.'))
            except ValueError:
                age = 0

            is_editing = reserve_user_data.get('is_editing_child_data', False)
            command = context.user_data.get('command', '')
            if is_editing:
                # Пытаемся взять person_id из контекста; если нет — по старому индексу
                person_id = reserve_user_data.get('edit_person_id')
                if not person_id:
                    index = reserve_user_data.get('edit_child_index')
                    if (
                            index is not None and
                            0 <= index < len(reserve_user_data.get('children', []))
                    ):
                        person_id = reserve_user_data['children'][index][2]
                if not person_id:
                    # Если не удалось определить, прерываем операцию
                    text_error = '<b>Не удалось определить запись ребенка для обновления.</b>'
                    keyboard = [[InlineKeyboardButton(
                        "Отмена", callback_data="CHLD_EDIT")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    message = await update.effective_chat.send_message(
                        text=text_error, reply_markup=reply_markup)
                    reserve_user_data['message_id'] = message.message_id
                    return 'CHILDREN'
                await db_postgres.update_person(
                    context.session, person_id, name=name)
                await db_postgres.update_child_by_person_id(
                    context.session, person_id, age=age)
                text_success = f'<b>Ребенок {name} {int(age)} обновлен!</b>'
            else:
                parent_id = None
                mode = reserve_user_data.get('child_filter_mode', 'PHONE')
                has_phone = (reserve_user_data
                             .get('client_data', {})
                             .get('phone'))
                if has_phone and (('_admin' in command) or (mode == 'PHONE')):
                    phone = reserve_user_data['client_data']['phone']
                    # Ищем взрослого по телефону
                    parent_id = await db_postgres.get_adult_person_id_by_phone(
                        context.session, phone)
                    if parent_id is None:
                        # Если взрослого с таким телефоном еще нет — создаем,
                        # чтобы новый ребенок сразу попал в выборку get_children_by_phone
                        name_adult = (reserve_user_data
                                      .get('client_data', {})
                                      .get('name_adult'))
                        if name_adult:
                            adult = await db_postgres.create_adult(
                                context.session,
                                update.effective_user.id,
                                name_adult,
                                phone
                            )
                            parent_id = adult.person_id

                await db_postgres.create_child(
                    context.session,
                    update.effective_user.id,
                    name,
                    age,
                    parent_id=parent_id
                )
                text_success = f'<b>Ребенок {name} {int(age)} добавлен!</b>'

            # Обновляем список детей согласно активному фильтру
            children = await _update_children(update, context)
            reserve_user_data['children'] = children
            reserve_user_data['is_adding_child'] = False
            reserve_user_data['is_editing_child_data'] = False

            # Сообщаем об успехе и показываем меню настроек
            selected_children = reserve_user_data.get('selected_children', [])
            limit = chose_base_ticket.quality_of_children
            command = context.user_data.get('command', '')
            is_admin = '_admin' in command
            mode = reserve_user_data.get('child_filter_mode', 'PHONE')

            # Считаем количество телефонов у пользователя
            phone_count = await db_postgres.count_adult_phones(
                context.session, update.effective_user.id)

            # Показываем фильтры если админ ИЛИ (есть телефон в сессии И телефонов больше 1)
            show_filters = (
                    is_admin or
                    (bool(reserve_user_data.get('client_data', {}).get('phone')) and
                    phone_count > 1)
            )
            keyboard = create_kbd_edit_children(
                children,
                selected_children=selected_children,
                limit=limit,
                current_filter=mode,
                is_admin=is_admin,
                show_filters=show_filters
            )
            keyboard.append(add_btn_back_and_cancel(
                postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
                add_back_btn=True,
                postfix_for_back='PHONE'))
            reply_markup = InlineKeyboardMarkup(keyboard)

            selected_count = len(selected_children)
            text_success += '\n\n'
            mode = reserve_user_data.get('child_filter_mode', 'PHONE')
            if (
                    mode == 'PHONE' and
                    reserve_user_data.get('client_data', {}).get('phone')
            ):
                phone = reserve_user_data['client_data']['phone']
                if not phone.startswith('+7'):
                    pretty_phone = f'+7{phone}'
                else:
                    pretty_phone = phone
                text_success += f'Список детей для клиента: <code>{pretty_phone}</code>\n\n'

            text_success += (f'<b>НАЖМИТЕ КНОПКУ С ИМЕНЕМ</b>\n\n'
                             f'Нужно выбрать: {limit}\n'
                             f'Выбрано: {selected_count} из {limit}\n\n'
                             f'<b>📝 изм.</b> - изменить данные по ребенку.')
            message = await update.effective_chat.send_message(
                text=text_success, reply_markup=reply_markup)
            reserve_user_data['message_id'] = message.message_id
            await set_back_context(
                context, 'CHILDREN', text_success, reply_markup)
            # Очистим идентификатор редактируемого ребенка
            reserve_user_data.pop('edit_person_id', None)
            reserve_user_data.pop('edit_child_index', None)
            return 'CHILDREN'
        else:
            text_error = '<b>Неверный формат!</b>\n\nНапишите имя и возраст через пробел.\nНапример: <code>Сергей 2</code>'
            keyboard = [[InlineKeyboardButton("Отмена", callback_data="CHLD_EDIT")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = await update.effective_chat.send_message(
                text=text_error, reply_markup=reply_markup)
            reserve_user_data['message_id'] = message.message_id
            return 'CHILDREN'

    # Если мы не в режиме добавления/редактирования, игнорируем текстовый ввод
    text_notice = ('<b>НАЖМИТЕ КНОПКУ С ИМЕНЕМ</b>\n '
                   'или нажмите <b>➕ Добавить ребенка</b>.')
    await update.effective_chat.send_message(text=text_notice)
    # Удаляем предыдущую клавиатуру и переотправляем актуальную, чтобы она была внизу
    try:
        await context.bot.delete_message(
            update.effective_chat.id, reserve_user_data['message_id'])
    except BadRequest as e:
        reserve_hl_logger.error(e)

    children = await _update_children(update, context)
    reserve_user_data['children'] = children
    text, reply_markup = await get_child_text_and_reply(
        update, chose_base_ticket, children, context)
    message = await update.effective_chat.send_message(
        text=text, reply_markup=reply_markup)
    reserve_user_data['message_id'] = message.message_id
    await set_back_context(context, 'CHILDREN', text, reply_markup)

    return 'CHILDREN'


async def send_clients_data(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query

    thread_id = update.effective_message.message_thread_id
    await update.effective_chat.send_action(ChatAction.TYPING,
                                            message_thread_id=thread_id)

    _, callback_data = remove_intent_id(query.data)
    event_id = int(callback_data)
    schedule_event = await db_postgres.get_schedule_event(
        context.session, event_id)
    theater_event = await db_postgres.get_theater_event(
        context.session, schedule_event.theater_event_id)
    date_event, time_event = await get_formatted_date_and_time_of_event(
        schedule_event)
    tickets = schedule_event.tickets
    base_ticket_and_tickets = []
    for ticket in tickets:
        base_ticket = await db_postgres.get_base_ticket(context.session,
                                                        ticket.base_ticket_id)
        if not is_skip_ticket(ticket.status):
            base_ticket_and_tickets.append((base_ticket, ticket))

    try:
        await query.edit_message_text('Загружаю данные покупателей')
    except TimedOut as e:
        reserve_hl_logger.error(e)

    text = f'#Мероприятие <code>{event_id}</code><br>'
    text += (f'Список людей на<br>'
             f'<b>{theater_event.name}<br>'
             f'{date_event} в '
             f'{time_event}</b><br>')

    text += await add_qty_visitors_to_text(base_ticket_and_tickets)

    text += await add_clients_data_to_text(base_ticket_and_tickets)

    res_text = transform_html(text)
    await query.edit_message_text(
        text=res_text.text,
        entities=res_text.entities,
        parse_mode=None
    )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    try:
        await query.answer()
    except NetworkError as e:
        reserve_hl_logger.error(e)
    return state


async def write_list_of_waiting(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    query = update.callback_query
    await query.answer()
    reserve_user_data = context.user_data['reserve_user_data']

    # Предложим последний введенный телефон (если есть)
    text_prompt = '<b>Напишите номер телефона</b><br><br>'
    phone = await db_postgres.get_phone(context.session,
                                        update.effective_user.id)
    phone_confirm_btn, text_prompt = await create_phone_confirm_btn(
        text_prompt, phone)

    state = 'PHONE_FOR_WAITING'
    res_text = transform_html(text_prompt)
    if phone_confirm_btn:
        reply_markup = await create_replay_markup(
            phone_confirm_btn,
            state,
            postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=True,
            postfix_for_back=context.user_data['STATE']
        )
        message = await query.edit_message_text(
            text=res_text.text,
            entities=res_text.entities,
            reply_markup=reply_markup,
            parse_mode=None
        )
        reserve_user_data['message_id'] = message.message_id
    else:
        message = await query.edit_message_text(
            text=res_text.text,
            entities=res_text.entities,
            parse_mode=None
        )
        reserve_user_data['message_id'] = message.message_id

    context.user_data['STATE'] = state
    return state


async def adult_confirm(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Обработчик подтверждения ранее введенного имени (inline-button).
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)

    text = f'{update.effective_message.text}\n\nДа'
    entities = update.effective_message.entities
    await query.edit_message_text(text, entities=entities)

    reserve_user_data = context.user_data['reserve_user_data']
    try:
        await context.bot.edit_message_reply_markup(
            update.effective_chat.id,
            message_id=reserve_user_data['message_id']
        )
    except BadRequest as e:
        reserve_hl_logger.error(e)

    message = await send_msg_get_phone(update, context)

    reserve_user_data['message_id'] = message.message_id
    state = 'PHONE'
    context.user_data['STATE'] = state
    return state


async def phone_confirm(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Обработчик подтверждения ранее введенного телефона (inline-button).
    Работает в двух состояниях:
    - PHONE: подставляет телефон и переходит к CHILDREN (как в get_phone)
    - PHONE_FOR_WAITING: подставляет телефон и оформляет запись в лист ожидания
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)

    text = f'{update.effective_message.text}\n\nДа'
    entities = update.effective_message.entities
    await query.edit_message_text(text, entities=entities)

    data = query.data
    _, callback_data = remove_intent_id(data)
    phone = None
    if '|' in callback_data:
        phone = callback_data.split('|', maxsplit=2)[-1]

    state = context.user_data.get('STATE')
    reserve_user_data = context.user_data['reserve_user_data']
    if not phone:
        message = await request_phone_number(update, context)
        reserve_user_data['message_id'] = message.message_id
        return state

    if state == 'PHONE_FOR_WAITING':
        # Лист ожидания: отправляем сразу
        await send_admin_info_add_list_wait(context, phone)

        text_user = ('Вы добавлены в лист ожидания, '
                     'если место освободится, то с вами свяжутся. '
                     'Если у вас есть вопросы, вы можете связаться с Администратором:\n'
                     f"{context.bot_data['admin']['contacts']}\n\n")
        use_command_text = 'Используйте команды:\n'
        reserve_text = (f'/{COMMAND_DICT['RESERVE'][0]} - для повторного '
                        f'резервирования свободных мест на мероприятие\n')
        text = f'{text_user}{use_command_text}{reserve_text}'
        await query.edit_message_text(text)

        state = ConversationHandler.END
        context.user_data['STATE'] = state
        return state

    if state == 'PHONE':
        # Удалим клавиатуру с предыдущего сообщения запроса телефона
        try:
            await context.bot.edit_message_reply_markup(
                update.effective_chat.id,
                message_id=reserve_user_data['message_id']
            )
        except BadRequest as e:
            reserve_hl_logger.error(e)

        reserve_user_data['client_data']['phone'] = phone
        message = await send_msg_get_child(update, context)

        reserve_user_data['message_id'] = message.message_id
        state = 'CHILDREN'
        context.user_data['STATE'] = state
        return state

    # Иначе остаемся в текущем состоянии
    return state


async def child_confirm(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
    """
    Обработчик подтверждения ранее введенного имени (inline-button).
    """
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut as e:
        reserve_hl_logger.error(e)

    text = f'{update.effective_message.text}\n\nДа'
    entities = update.effective_message.entities
    await query.edit_message_text(text, entities=entities)

    data = query.data
    child = None
    if '|' in data:
        child = data.split('|', maxsplit=1)[1]
    processed_data_on_children = [item.split() for item in child.split('\n')]

    return await _finish_get_children(
        update, context, processed_data_on_children, child)


async def _publish_write_client_list_waiting(sheet_id_domik,
                                             context: 'ContextTypes.DEFAULT_TYPE'):
    reserve_user_data = context.user_data['reserve_user_data']
    schedule_event_id = reserve_user_data['choose_schedule_event_id']
    user = context.user_data.get('user')
    user_id = user.id
    username = user.username
    full_name = user.full_name
    phone = reserve_user_data['client_data']['phone']
    ctx = {
        'user_id': user_id,
        'username': username,
        'full_name': full_name,
        'phone': phone,
        'schedule_event_id': schedule_event_id
    }
    try:
        await publish_write_client_list_waiting(sheet_id_domik, ctx)
    except Exception as e:
        reserve_hl_logger.exception(
            f"Failed to publish gspread task, fallback to direct call: {e}")
        await write_client_list_waiting(sheet_id_domik, ctx)


async def get_phone_for_waiting(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
):
    reserve_user_data = context.user_data['reserve_user_data']
    try:
        await context.bot.edit_message_reply_markup(
            update.effective_chat.id,
            message_id=reserve_user_data['message_id']
        )
    except BadRequest as e:
        reserve_hl_logger.error(e)

    phone, message = await validate_phone_or_request(
        update,
        context,
        update.effective_message.text,
    )
    if phone is None:
        reserve_user_data['message_id'] = message.message_id
        return context.user_data['STATE']

    await send_admin_info_add_list_wait(context, phone)

    text = ('Вы добавлены в лист ожидания.\n'
            'Если место освободится, то мы с вами свяжемся.\n'
            'Если вам подходят разные даты и время, то '
            'запишитесь пожалуйста на каждое мероприятие\n\n'
            'Если у вас есть вопросы, вы можете написать их в '
            'свободной форме боту или связаться с Администратором:\n'
            f'{context.bot_data['admin']['contacts']}\n\n')
    use_command_text = 'Используйте команды:\n'
    reserve_text = (f'/{COMMAND_DICT['RESERVE'][0]} - для повторного '
                    f'резервирования свободных мест на мероприятие\n')
    await update.effective_chat.send_message(
        text=f'{text}{use_command_text}{reserve_text}'
    )

    state = ConversationHandler.END
    context.user_data['STATE'] = state
    return state


async def send_admin_info_add_list_wait(context: 'ContextTypes.DEFAULT_TYPE',
                                        phone: str):
    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['client_data']['phone'] = phone
    text = f'{reserve_user_data['text_select_event']}+7{phone}'

    user = context.user_data.get('user')
    thread_id = (context.bot_data['dict_topics_name']
                 .get('Лист ожидания', None))
    text = (f'#Лист_ожидания<br>'
            f'Пользователь @{user.username} {user.full_name}<br>'
            f'Запросил добавление в лист ожидания<br>{text}')

    res_text = transform_html(text)
    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=res_text.text,
        entities=res_text.entities,
        parse_mode=None,
        message_thread_id=thread_id
    )
    sheet_id_domik = context.config.sheets.sheet_id_domik
    await _publish_write_client_list_waiting(sheet_id_domik, context)

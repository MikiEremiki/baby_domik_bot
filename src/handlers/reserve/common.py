from sulguk import transform_html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from db import BaseTicket, db_postgres
from handlers.sub_hl import processing_successful_payment
from utilities.utl_func import set_back_context
from utilities.utl_kbd import (
    add_btn_back_and_cancel,
    create_kbd_edit_children,
    create_phone_confirm_btn,
    create_replay_markup,
)


VERIFICATION_REQUEST_TEXT = (
    "Отправьте файл или фото, подтверждающее ваше право "
    "воспользоваться выбранной скидкой/акцией."
)


async def get_child_text_and_reply(
        update: Update,
        base_ticket: BaseTicket,
        children,
        context: 'ContextTypes.DEFAULT_TYPE'
) -> tuple[str, InlineKeyboardMarkup]:
    reserve_user_data = context.user_data['reserve_user_data']

    reserve_user_data['is_editing_children'] = True

    back_and_cancel = add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
        add_back_btn=True,
        postfix_for_back='PHONE')

    if base_ticket.quality_of_children > 0:
        if 'selected_children' not in reserve_user_data:
            reserve_user_data['selected_children'] = []
        if 'children_page' not in reserve_user_data:
            reserve_user_data['children_page'] = 0
        if 'child_filter_mode' not in reserve_user_data:
            reserve_user_data['child_filter_mode'] = 'PHONE'

        limit = base_ticket.quality_of_children
        current_selected = reserve_user_data['selected_children']

        available_ids = {c[2] for c in children}
        current_selected = [pid for pid in current_selected if pid in available_ids]

        if len(current_selected) > limit:
            current_selected = current_selected[:limit]

        reserve_user_data['selected_children'] = current_selected

        selected_count = len(reserve_user_data['selected_children'])

        text = '<b>Укажите детей для бронирования</b>\n\n'
        text += '<b>НАЖМИТЕ КНОПКУ С ИМЕНЕМ</b>\n'
        text += '<b>или ➕ Добавить ребенка</b>\n\n'

        text += f'Нужно выбрать: {limit}\n'
        text += f'<i>Выбрано: {selected_count} из {limit}</i>\n\n'

        text += '<b>📝 изм.</b> - изменить данные по ребенку.\n\n'

        mode = reserve_user_data.get('child_filter_mode', 'PHONE')
        if mode == 'PHONE' and reserve_user_data.get('client_data', {}).get('phone'):
            phone = reserve_user_data['client_data']['phone']
            pretty_phone = f'+7{phone}' if not phone.startswith('+7') else phone
            text += f'<i>Список детей для клиента:</i> <code>{pretty_phone}</code>\n\n'
        else:
            text += '<i>Показаны все ваши дети</i>\n\n'

        command = context.user_data.get('command', '')
        is_admin = '_admin' in command

        phone_count = await db_postgres.count_adult_phones(
            context.session, update.effective_user.id)

        show_filters = is_admin or (
            bool(reserve_user_data.get('client_data', {}).get('phone')) and
            phone_count > 1
        )
        keyboard = create_kbd_edit_children(
            children,
            page=reserve_user_data['children_page'],
            selected_children=reserve_user_data['selected_children'],
            limit=limit,
            current_filter=mode,
            is_admin=is_admin,
            show_filters=show_filters
        )
        keyboard.append(back_and_cancel)
    else:
        text = 'Нажмите <b>Далее</b>'
        next_btn = InlineKeyboardButton(
            'Далее',
            callback_data='Далее'
        )
        keyboard = [[next_btn], [back_and_cancel]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    return text, reply_markup


async def send_msg_get_child(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
) -> Message:
    reserve_user_data = context.user_data['reserve_user_data']
    base_ticket_id = reserve_user_data['chose_base_ticket_id']
    base_ticket = await db_postgres.get_base_ticket(
        context.session,
        base_ticket_id,
    )

    command = context.user_data.get('command', '')
    if 'child_filter_mode' not in reserve_user_data:
        if ('_admin' in command) or reserve_user_data.get('client_data', {}).get('phone'):
            reserve_user_data['child_filter_mode'] = 'PHONE'
        else:
            reserve_user_data['child_filter_mode'] = 'MY'

    mode = reserve_user_data['child_filter_mode']
    if mode == 'PHONE' and reserve_user_data.get('client_data', {}).get('phone'):
        phone = reserve_user_data['client_data']['phone']
        children = await db_postgres.get_children_by_phone(context.session, phone)
        if not children:
            reserve_user_data['child_filter_mode'] = 'MY'
            children = await db_postgres.get_children(context.session, update.effective_user.id)
    else:
        children = await db_postgres.get_children(context.session, update.effective_user.id)

    reserve_user_data['children'] = children
    text, reply_markup = await get_child_text_and_reply(
        update,
        base_ticket,
        children,
        context,
    )

    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
    )
    await set_back_context(context, 'CHILDREN', text, reply_markup)
    return message


async def send_msg_get_phone(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
) -> Message:
    text_prompt = '<b>Напишите номер телефона</b><br><br>'
    phone = await db_postgres.get_phone(context.session, update.effective_user.id)
    phone_confirm_btn, text_prompt = await create_phone_confirm_btn(text_prompt, phone)

    if phone_confirm_btn:
        reply_markup = await create_replay_markup(
            phone_confirm_btn,
            'PHONE',
            postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=True,
            postfix_for_back='FORMA',
        )
    else:
        keyboard = [
            add_btn_back_and_cancel(
                postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
                add_back_btn=True,
                postfix_for_back='FORMA',
            )
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

    res_text = transform_html(text_prompt)
    message = await update.effective_chat.send_message(
        text=res_text.text,
        entities=res_text.entities,
        reply_markup=reply_markup,
        parse_mode=None,
    )
    await set_back_context(context, 'PHONE', text_prompt, reply_markup)
    return message


async def process_successful_payment_with_verification(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE',
        *,
        state_on_success=None,
        replace_paid_state_with_end: bool = False,
) -> int | str:
    reserve_user_data = context.user_data['reserve_user_data']
    requires_verify = await promo_requires_verification(context)

    original_flag = reserve_user_data.get('flag_send_ticket_info', False)
    if requires_verify:
        reserve_user_data['flag_send_ticket_info'] = False

    await processing_successful_payment(update, context)

    if requires_verify:
        await request_discount_verification(update, context)
        reserve_user_data['flag_send_ticket_info'] = original_flag
        return 'WAIT_DOCUMENT'

    if state_on_success is None:
        state = context.user_data.get('STATE', ConversationHandler.END)
        if replace_paid_state_with_end and state == 'PAID':
            state = ConversationHandler.END
    else:
        state = state_on_success

    context.user_data['STATE'] = state
    return state


async def promo_requires_verification(
        context: 'ContextTypes.DEFAULT_TYPE'
) -> bool:
    reserve_user_data = context.user_data['reserve_user_data']
    promo_id = reserve_user_data.get('applied_promo_id')
    if not promo_id:
        return False

    promo = await db_postgres.get_promotion(context.session, promo_id)
    return bool(promo and promo.requires_verification)


async def request_discount_verification(
        update: Update,
        context: 'ContextTypes.DEFAULT_TYPE'
) -> str:
    await update.effective_chat.send_message(VERIFICATION_REQUEST_TEXT)
    context.user_data['STATE'] = 'WAIT_DOCUMENT'
    return 'WAIT_DOCUMENT'
from sulguk import transform_html
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from conv_hl.common_conv_hl import (
    F_text_and_no_command,
    back_callback_handler,
    cancel_callback_handler,
)
from db import db_postgres
from handlers import main_hl, reserve_hl
from utilities.utl_func import set_back_context
from utilities.utl_kbd import (
    add_btn_back_and_cancel,
    create_adult_confirm_btn,
    create_email_confirm_btn,
    remove_intent_id,
)
from utilities.utl_text import check_email


EMAIL_PROMPT = 'Напишите email покупателя, на который будет направлен чек<br><br>'


async def create_email_keyboard(
    email: str | None,
    postfix_for_cancel: str,
    postfix_for_back: str,
) -> InlineKeyboardMarkup:
    """Создаёт клавиатуру шага EMAIL: email_confirm (если есть) + back_and_cancel."""
    email_confirm_btn, _ = await create_email_confirm_btn('', email)
    back_and_cancel = add_btn_back_and_cancel(
        postfix_for_cancel=postfix_for_cancel + '|',
        add_back_btn=True,
        postfix_for_back=postfix_for_back,
    )
    if email_confirm_btn:
        keyboard = [email_confirm_btn, back_and_cancel]
    else:
        keyboard = [back_and_cancel]
    return InlineKeyboardMarkup(keyboard)


async def send_email_step(
    update,
    context: 'ContextTypes.DEFAULT_TYPE',
    postfix_for_back: str = 'TICKET',
    edit_message: bool = False,
):
    """Отправляет шаг запроса email с предзаполнением из профиля админа.
    
    Возвращает tuple (message, state) где state = 'EMAIL'.
    Если edit_message=True, редактирует существующее сообщение вместо отправки нового.
    """
    reserve_user_data = context.user_data['reserve_user_data']
    admin_email = await db_postgres.get_email(
        context.session, update.effective_user.id
    )
    text = EMAIL_PROMPT
    email_confirm_btn, text = await create_email_confirm_btn(text, admin_email)
    reply_markup = await create_email_keyboard(
        admin_email,
        context.user_data['postfix_for_cancel'],
        postfix_for_back,
    )
    res_text = transform_html(text)
    if edit_message and update.callback_query:
        message = await update.callback_query.edit_message_text(
            text=res_text.text,
            entities=res_text.entities,
            reply_markup=reply_markup,
            parse_mode=None,
        )
    else:
        message = await update.effective_chat.send_message(
            text=res_text.text,
            entities=res_text.entities,
            reply_markup=reply_markup,
            parse_mode=None,
        )
    reserve_user_data['message_id'] = message.message_id
    state = 'EMAIL'
    await set_back_context(context, state, res_text.text, reply_markup)
    return message, state


async def proceed_to_forma_step(
    update,
    context: 'ContextTypes.DEFAULT_TYPE',
    reserve_user_data: dict,
    edit_message: bool = False,
):
    """Переход от EMAIL к FORMA: запрос фамилии и имени взрослого.
    
    Если edit_message=True, редактирует существующее сообщение (callback).
    """
    text = '<b>Напишите фамилию и имя (взрослого)</b><br><br>'
    adult_name = await db_postgres.get_adult_name(
        context.session, update.effective_user.id
    )
    adult_confirm_btn, text = await create_adult_confirm_btn(text, adult_name)
    back_and_cancel = add_btn_back_and_cancel(
        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
        add_back_btn=True,
        postfix_for_back='EMAIL',
    )
    if adult_confirm_btn:
        keyboard = [adult_confirm_btn, back_and_cancel]
        reserve_user_data['client_data']['name_adult'] = adult_name
    else:
        keyboard = [back_and_cancel]
    reply_markup = InlineKeyboardMarkup(keyboard)
    res_text = transform_html(text)
    if edit_message and update.callback_query:
        message = await update.callback_query.edit_message_text(
            text=res_text.text,
            entities=res_text.entities,
            reply_markup=reply_markup,
            parse_mode=None,
        )
    else:
        message = await update.effective_chat.send_message(
            text=res_text.text,
            entities=res_text.entities,
            reply_markup=reply_markup,
            parse_mode=None,
        )
    reserve_user_data['message_id'] = message.message_id
    state = 'FORMA'
    await set_back_context(context, state, res_text.text, reply_markup)
    context.user_data['STATE'] = state
    return state


async def handle_email_input(
    update,
    context: 'ContextTypes.DEFAULT_TYPE',
    postfix_for_back: str = 'TICKET',
):
    """Обработка ввода email в админской брони.
    
    Валидирует email, сохраняет в reserve_user_data, переходит к FORMA.
    Возвращает state ('EMAIL' при ошибке, 'FORMA' при успехе).
    """
    reserve_user_data = context.user_data['reserve_user_data']
    try:
        await context.bot.edit_message_reply_markup(
            update.effective_chat.id,
            message_id=reserve_user_data['message_id']
        )
    except Exception:
        pass

    email_text = update.effective_message.text.strip().lower()
    if not check_email(email_text):
        # Re-prompt with validation error
        text = f'Вы написали: {update.effective_message.text}\n' \
               f'Пожалуйста проверьте и введите email еще раз.'
        keyboard = [add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=True,
            postfix_for_back=postfix_for_back,
        )]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await update.effective_chat.send_message(
            text=text, reply_markup=reply_markup)
        reserve_user_data['message_id'] = message.message_id
        return 'EMAIL'

    reserve_user_data['buyer_email'] = email_text
    return await proceed_to_forma_step(update, context, reserve_user_data)


async def handle_email_confirm_callback(
    update,
    context: 'ContextTypes.DEFAULT_TYPE',
    postfix_for_back: str = 'TICKET',
):
    """Обработка callback email_confirm в админской брони.
    
    Извлекает email из callback_data, валидирует, сохраняет, переходит к FORMA.
    Если email невалидный — возвращает к ручному вводу.
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    _, callback_data = remove_intent_id(query.data)
    email = None
    if callback_data.startswith('email_confirm|'):
        email = callback_data.split('|', maxsplit=1)[-1]
    elif '|' in callback_data:
        # Fallback: if intent_id was already stripped, callback_data may be just the email
        # But we also handle the case where callback_data is like "email_confirm|user@x.com"
        # after intent removal from "intent|email_confirm|user@x.com"
        pass
    # If callback_data is just an email (intent_id consumed "email_confirm|"), treat it as email
    if email is None and check_email(callback_data):
        email = callback_data

    if not email or not check_email(email):
        # Fall through to manual input
        text = EMAIL_PROMPT
        keyboard = [add_btn_back_and_cancel(
            postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
            add_back_btn=True,
            postfix_for_back=postfix_for_back,
        )]
        reply_markup = InlineKeyboardMarkup(keyboard)
        res_text = transform_html(text)
        message = await query.edit_message_text(
            text=res_text.text,
            entities=res_text.entities,
            reply_markup=reply_markup,
            parse_mode=None,
        )
        reserve_user_data = context.user_data['reserve_user_data']
        reserve_user_data['message_id'] = message.message_id
        return 'EMAIL'

    reserve_user_data = context.user_data['reserve_user_data']
    reserve_user_data['buyer_email'] = email
    return await proceed_to_forma_step(update, context, reserve_user_data, edit_message=True)

handlers_event_selection = {
    'MONTH': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MODE'),
        CallbackQueryHandler(reserve_hl.choice_show, pattern='^MONTH'),
        CallbackQueryHandler(reserve_hl.choice_month_rep_continue, pattern='^MONTH_REP'),
    ],
    'SHOW': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MODE'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-REP_GROUP'),
        CallbackQueryHandler(reserve_hl.choice_show, pattern='^SHOW_PAGE'),
        CallbackQueryHandler(reserve_hl.choice_date, pattern='^SHOW'),
    ],
    'DATE': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-MONTH'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-SHOW'),
        CallbackQueryHandler(reserve_hl.choice_time, pattern='^DATE'),
    ],
    'PLACE': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-DATE'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-SHOW'),
        CallbackQueryHandler(reserve_hl.choice_place, pattern='^PLACE'),
    ],
    'TIME': [
        cancel_callback_handler,
        CallbackQueryHandler(main_hl.back, pattern='^Назад-PLACE'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-DATE'),
        CallbackQueryHandler(main_hl.back, pattern='^Назад-SHOW'),
        CallbackQueryHandler(reserve_hl.choice_option_of_reserve, pattern='^TIME'),
    ],
}

handlers_client_data_selection = {
    'FORMA': [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.adult_confirm, pattern=r'.*adult_confirm'),
        MessageHandler(F_text_and_no_command, reserve_hl.get_adult),
    ],
    'PHONE': [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.phone_confirm, pattern=r'.*phone_confirm'),
        MessageHandler(F_text_and_no_command, reserve_hl.get_phone),
    ],
    'CHILDREN': [
        back_callback_handler,
        cancel_callback_handler,
        CallbackQueryHandler(reserve_hl.child_confirm, pattern=r'.*child_confirm'),
        MessageHandler(F_text_and_no_command, reserve_hl.get_children),
        CallbackQueryHandler(reserve_hl.get_children, pattern=r'^Далее'),
        CallbackQueryHandler(reserve_hl.get_children, pattern=r'^CHLD_'),
    ],
}
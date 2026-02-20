import logging
import datetime
from typing import Optional

from telegram import Update
from telegram.ext import (
    ContextTypes, TypeHandler, ApplicationHandlerStop, ConversationHandler)

from db import db_postgres
from handlers.reserve_hl import choice_mode, conversation_timeout
from settings.settings import RESERVE_TIMEOUT, CHAT_ID_KOCHETKOVA

reserve_check_md_logger = logging.getLogger('bot.md.reserve_check')

# Состояния анкеты, в которых не нужно прерывать пользователя
PROTECTED_STATES = {
    'OFFER',      # согласие с офертой
    'EMAIL',      # ввод/подтверждение email
    'FORMA',      # ввод ФИО взрослого
    'PHONE',      # ввод/подтверждение телефона
    'CHILDREN',   # ввод данных детей
    'PAID',       # этап отправки чека/подтверждения оплаты
    'PHONE_FOR_WAITING',  # ввод телефона для ожидания
    'CONFIRM_RESERVATION', # подтверждение бронирования (итоговый экран перед оплатой)
    'PROMOCODE_INPUT',     # ввод промокода
    'WAIT_RECEIPT',        # ожидание квитанции об оплате (ручное подтверждение)
    'WAIT_DOCUMENT',       # ожидание подтверждающего документа (для льгот)
}


def to_naive(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Приводит datetime к naive (без tzinfo) в локальном времени."""
    if dt is None:
        return None
    if dt.tzinfo:
        return dt.astimezone().replace(tzinfo=None)
    return dt


async def reset_conversation_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает состояние диалога 'reserve' в 'MODE'."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    conv_key = (chat_id, user_id)

    # 1. Сбрасываем в памяти (живой объект)
    for group in context.application.handlers.values():
        for handler in group:
            if isinstance(handler, ConversationHandler) and handler.name == 'reserve':
                handler._conversations[conv_key] = 'MODE'

    # 2. Сбрасываем в persistence
    if context.application.persistence:
        await context.application.persistence.update_conversation('reserve', conv_key, 'MODE')
        await context.application.update_persistence()


def add_reserve_check_middleware(application, config):
    async def check_reserve_actual_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Middleware для проверки актуальности данных бронирования и таймаута сессии.
        """
        if not update.effective_user or update.effective_user.is_bot:
            return

        # Нас интересует только активный процесс бронирования
        if context.user_data.get('command') != 'reserve':
            return

        # Не проверяем в админских чатах
        if update.effective_chat.id in [config.bot.admin_group, CHAT_ID_KOCHETKOVA]:
            return

        # Проверку делаем только при переходах по кнопкам (CallbackQuery)
        if not update.callback_query:
            return

        # Не сбрасываем при нажатии кнопок подтверждения/отклонения (админские или системные)
        callback_data = update.callback_query.data
        if callback_data.startswith(('confirm', 'reject', 'accept', 'Next')):
            return

        now = datetime.datetime.now()
        user_id = update.effective_user.id
        current_state = context.user_data.get('STATE')

        # Пропускаем проверку для защищенных состояний (этап ввода данных)
        if current_state in PROTECTED_STATES:
            reserve_check_md_logger.info(
                f'Skip reserve_check in protected state: {current_state} for user {user_id}')
            context.user_data['last_interaction_time'] = now
            return

        last_interaction = to_naive(context.user_data.get('last_interaction_time'))

        if last_interaction:
            # 1. Проверка на таймаут
            if (now - last_interaction).total_seconds() > RESERVE_TIMEOUT * 60:
                reserve_check_md_logger.info(f'User {user_id} session timed out.')
                await update.callback_query.answer()
                await conversation_timeout(update, context)
                await reset_conversation_state(update, context)
                await update.callback_query.edit_message_reply_markup()
                context.user_data['last_interaction_time'] = now
                raise ApplicationHandlerStop

            last_db_update = to_naive(await db_postgres.get_last_schedule_update_time(context.session))
            # 2. Проверка актуальности данных расписания
            if last_db_update and last_db_update > last_interaction:
                reserve_check_md_logger.info(f'User {user_id} has outdated data. Resetting.')
                text = 'Расписание обновилось. Повторите выбор.'
                await update.callback_query.answer(text, show_alert=True)
                await choice_mode(update, context)
                await reset_conversation_state(update, context)
                raise ApplicationHandlerStop

        # Если все проверки пройдены, обновляем время последнего взаимодействия
        context.user_data['last_interaction_time'] = now

    # Группа -40 гарантирует выполнение после открытия сессии БД, но до основных хендлеров
    application.add_handler(TypeHandler(Update, check_reserve_actual_middleware), group=-40)

from telegram import Update
from telegram.ext import ContextTypes, TypeHandler, ApplicationHandlerStop
from utilities.utl_func import get_actual_last_update_time
from handlers.reserve_hl import choice_mode
import datetime

async def check_reserve_actual_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем только сообщения от пользователей
    if not update.effective_user or update.effective_user.is_bot:
        return

    # Нас интересует только активный процесс бронирования
    if context.user_data.get('command') != 'reserve':
        return

    # Проверку делаем только при переходах по кнопкам (CallbackQuery)
    if not update.callback_query:
        return

    last_db_update = await get_actual_last_update_time(context)
    last_user_load = context.user_data.get('last_data_load', datetime.datetime.min)

    if last_db_update > last_user_load:
        # 1. Уведомляем пользователя через всплывающее окно
        await update.callback_query.answer(
            "Расписание обновилось. Возвращаемся в начало для актуализации данных.", 
            show_alert=True
        )
        
        # 2. Вызываем начальный экран выбора (эмуляция вызова /reserve)
        await choice_mode(update, context)
        
        # 3. Сбрасываем состояние ConversationHandler в 'MODE' (начальное состояние после выбора)
        # Имя 'reserve' соответствует названию ConversationHandler в reserve_conv_hl.py
        await context.application.persistence.update_conversation(
            'reserve', 
            (update.effective_chat.id, update.effective_user.id), 
            'MODE'
        )
        
        # 4. Прерываем выполнение текущего хендлера, так как данные устарели
        raise ApplicationHandlerStop

def add_reserve_check_middleware(application):
    # Группа -40 гарантирует выполнение после открытия сессии БД, но до основных хендлеров
    application.add_handler(TypeHandler(Update, check_reserve_actual_middleware), group=-40)

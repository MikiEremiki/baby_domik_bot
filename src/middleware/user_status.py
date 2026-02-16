import logging

from sulguk import transform_html
from telegram import Update
from telegram.ext import (
    ContextTypes, TypeHandler, ApplicationHandlerStop, Application)

from db.db_postgres import get_or_create_user_status
from handlers import check_user_db

user_status_md_logger = logging.getLogger('bot.md.user_status')

def add_user_status_middleware(application: Application, config):
    async def check_user_status(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
        if not update.effective_user or update.effective_user.is_bot or not update.effective_chat:
            return

        try:
            user_id = update.effective_user.id

            # Гарантируем наличие пользователя в таблице users перед проверкой статуса
            await check_user_db(update, context)

            status = await get_or_create_user_status(context.session,
                                                     user_id)
            await context.session.commit()
            blacklisted = status.is_blacklisted
            is_blocked_by_user = status.is_blocked_by_user

            if blacklisted or is_blocked_by_user:
                user_status_md_logger.info(
                    f'{user_id=} is {blacklisted=} or {is_blocked_by_user=}. Stop handling.')
                raise ApplicationHandlerStop

            if status.is_blocked_by_admin:
                user_status_md_logger.info(f'{user_id=} is blocked by admin. Stop handling.')
                admin_contacts = context.bot_data.get('admin', {}).get('contacts', '')
                text = (
                    'Бот не может обработать от вас запросы.<br><br>'
                    'Для решения свяжитесь с Администратором:<br>'
                    f'{admin_contacts}'
                )
                res_text = transform_html(text)
                await update.effective_message.reply_text(
                    text=res_text.text,
                    entities=res_text.entities,
                    parse_mode=None,
                )
                raise ApplicationHandlerStop
        except ApplicationHandlerStop:
            raise
        except Exception as e:
            user_status_md_logger.error(f'user_status middleware error: {e}', exc_info=True)
            if hasattr(context, 'session'):
                await context.session.rollback()

    # Run after DB session is opened (-100) and before global on/off (-50)
    application.add_handler(TypeHandler(Update, check_user_status), group=-60)

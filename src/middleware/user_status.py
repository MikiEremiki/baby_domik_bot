import logging
from telegram import Update
from telegram.ext import ContextTypes, TypeHandler, ApplicationHandlerStop

from db.db_postgres import get_or_create_user_status

logger = logging.getLogger(__name__)


def add_user_status_middleware(application, config):
    async def check_user_status(update: Update, context: 'ContextTypes.DEFAULT_TYPE'):
        try:
            if not update or not update.effective_user:
                return
            # session is provided by add_db_handlers_middleware
            session = getattr(context, 'session', None)
            if session is None:
                return

            status = await get_or_create_user_status(session, update.effective_user.id)

            if status.is_blacklisted:
                # silently ignore any updates from blacklisted users
                raise ApplicationHandlerStop

            if status.is_blocked_by_admin:
                # inform user and stop processing
                admin_contacts = context.bot_data.get('admin', {}).get('contacts', '')
                await update.effective_message.reply_text(
                    'Бот не может обработать от вас запросы.\n\n'
                    f'Для решения свяжитесь с Администратором:\n'
                    f'{admin_contacts}'
                )
                raise ApplicationHandlerStop
        except ApplicationHandlerStop:
            raise
        except Exception as e:
            logger.error(f"user_status middleware error: {e}", exc_info=True)

    # Run after DB session is opened (-100) and before global on/off (-50)
    application.add_handler(TypeHandler(Update, check_user_status), group=-60)

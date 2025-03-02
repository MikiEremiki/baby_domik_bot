from telegram import Update
from telegram.ext import ContextTypes, TypeHandler, ApplicationHandlerStop

from utilities.utl_func import is_admin


def add_glob_on_off_middleware(application, config):
    async def check_permissions(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE
    ):
        if update.effective_chat.id == config.bot.admin_group:
            return
        if not is_admin(update) and not context.bot_data['global_on_off']:
            await update.effective_message.reply_text(
                'Проводятся технические работы, сроки устранения уточняются.\n'
                'Приносим свои извинения за возможные неудобства.\n'
                'Вы можете написать свой вопрос мне и я перешлю его '
                'администратору или вы можете написать в группах:\n'
                '- <a href="https://t.me/theater_domik">Телеграм</a>\n'
                '- <a href="https://vk.com/baby_theater_domik">ВКонтакте</a>'
            )
            raise ApplicationHandlerStop

    application.add_handler(TypeHandler(Update, check_permissions), group=-50)

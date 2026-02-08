from telegram import Update
from telegram.ext import ContextTypes, TypeHandler, ApplicationHandlerStop

from settings.settings import CHAT_ID_KOCHETKOVA
from utilities.utl_func import is_admin, reply_html


def add_glob_on_off_middleware(application, config):
    async def check_permissions(
            update: Update,
            context: 'ContextTypes.DEFAULT_TYPE'
    ):
        if update.effective_chat.id in [config.bot.admin_group, CHAT_ID_KOCHETKOVA]:
            return
        if not is_admin(update) and not context.bot_data['global_on_off']:
            text = (
                'Проводятся технические работы, сроки завершения уточняются.<br>'
                'Приносим свои извинения за возможные неудобства.<br><br>'
                'Вы можете написать свой вопрос мне и я перешлю его '
                'администратору или вы можете связаться с ним '
                'самостоятельно:<br>'
                f'{context.bot_data['admin']['contacts']}<br><br>'
                'или через группы:<br>'
                '<ul>'
                '<li><a href="https://t.me/theater_domik">Телеграм</a></li>'
                '<li><a href="https://vk.com/baby_theater_domik">ВКонтакте</a></li>'
                '</ul>'
            )
            await reply_html(update, text)
            raise ApplicationHandlerStop

    application.add_handler(TypeHandler(Update, check_permissions), group=-50)

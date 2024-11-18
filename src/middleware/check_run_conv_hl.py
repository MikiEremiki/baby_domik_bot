from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, TypeHandler, ApplicationHandlerStop

from settings.settings import COMMAND_DICT
from utilities.utl_func import add_btn_back_and_cancel, extract_command


def add_check_run_conv_hl_middleware(application):
    async def check_run_conv_hl(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE
    ):
        if update.effective_message.text:
            command = extract_command(update.effective_message.text)
        else:
            command = None
        if command and context.user_data.get('conv_hl_run', False):
            commands = [
                COMMAND_DICT['RESERVE'][0],
                COMMAND_DICT['STUDIO'][0],
                COMMAND_DICT['RESERVE_ADMIN'][0],
                COMMAND_DICT['STUDIO_ADMIN'][0],
                COMMAND_DICT['MIGRATION_ADMIN'][0],
                COMMAND_DICT['BD_ORDER'][0],
                COMMAND_DICT['BD_PAID'][0],
                COMMAND_DICT['LIST'][0],
                COMMAND_DICT['LIST_WAIT'][0],
                COMMAND_DICT['AFISHA'][0],
                COMMAND_DICT['SETTINGS'][0],
            ]
            if command in commands:
                keyboard = [add_btn_back_and_cancel(
                    postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
                    add_back_btn=False)]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.effective_chat.send_message(
                    'У вас запущен другой диалог.\n'
                    'Если вы хотите закончить с ним работу '
                    'нажмите кнопку Отмена и выполните новую команду',
                    reply_markup=reply_markup
                )
                raise ApplicationHandlerStop

    application.add_handler(TypeHandler(Update, check_run_conv_hl), group=-40)
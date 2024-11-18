from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, TypeHandler, ApplicationHandlerStop

from settings.settings import COMMAND_DICT
from utilities.utl_func import add_btn_back_and_cancel, extract_command


def add_check_run_conv_hl_middleware(application):
    async def check_run_conv_hl(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        if query:
            if 'Отменить' in query.data:
                return
        command = extract_command(update.effective_message.text)
        if command and context.user_data.get('conv_hl_run', False):
            for k, v in COMMAND_DICT.items():
                if command == v[0] and command != 'start':
                    keyboard = [add_btn_back_and_cancel(
                        postfix_for_cancel=context.user_data['postfix_for_cancel'] + '|',
                        add_back_btn=False)]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.effective_chat.send_message(
                        'У вас все еще запущен другой диалог.\n'
                        'Если вы хотите закончить с ним работу '
                        'нажмите кнопку Отмена и выполните новую команду',
                        reply_markup=reply_markup
                    )
                    raise ApplicationHandlerStop

    application.add_handler(TypeHandler(Update, check_run_conv_hl), group=-40)

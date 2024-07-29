from telegram.ext import Application

from settings.settings import ADDRESS_OFFICE
from utilities.utl_func import set_menu, set_description


async def post_init(app: Application, config):
    await set_menu(app.bot)
    await set_description(app.bot)

    app.bot_data.setdefault('texts', {})
    app.bot_data['texts']['description'] = (
        '<a href="https://t.me/theater_domik">Канал театра</a> в телеграмм'
        ' с удобным делением по темам\n\n'
    )
    app.bot_data['texts']['address'] = (
        f'Адрес:\n{ADDRESS_OFFICE}\n\n'
    )
    app.bot_data['texts']['ask_question'] = (
        '<i>Задать любой вопрос можно здесь, написав сообщение боту '
        '(можно прикреплять файлы/медиа)</i>\n\n'
    )
    app.bot_data.setdefault('admin', {})
    app.bot_data['admin'].setdefault('contacts', {})
    app.bot_data.setdefault('dict_topics_name', {})
    app.bot_data.setdefault('global_on_off', True)
    app.context_types.context.config = config

    # TODO Сделать команду для настройки списков по интенсивам
    studio = {
        'Театральный интенсив': [],
    }
    app.bot_data['studio'] = studio

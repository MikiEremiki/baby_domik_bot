from telegram.ext import Application

from settings.settings import ADDRESS_OFFICE
from utilities.utl_func import set_menu, set_description
from utilities.settings_parser import load_bot_settings
from schedule.worker_jobs import cancel_old_created_tickets


async def post_init(app: Application, config):
    await set_menu(app.bot)
    await set_description(app.bot)

    app.bot_data.setdefault('texts', {})
    app.bot_data['texts']['description'] = (
        '<a href="https://t.me/theater_domik">Канал театра</a> в телеграм'
        ' с удобным делением по темам\n'
        'ПОДПИСЫВАЙТЕСЬ, чтобы не пропустить новости театра\n\n'
    )
    app.bot_data['texts']['address'] = (
        f'Адрес:\n{ADDRESS_OFFICE}\n\n'
    )
    app.bot_data['texts']['ask_question'] = (
        '<i>Задать любой вопрос можно здесь, написав сообщение боту '
        '(можно прикреплять файлы/медиа)</i>\n\n'
    )
    app.bot_data['texts']['text_legend'] = (
        '📍 - Премьера\n'
        '👶🏼 - Рекомендованный возраст\n'
        '⏳ - Продолжительность\n'
        '\n'
    )

    app.bot_data.setdefault('admin', {})
    app.bot_data.setdefault('cme_admin', {})
    contacts = 'Театр Домик\ntelegram @Theater_Domik_admin\nтелефон +79159383529'
    app.bot_data['admin'].setdefault('contacts', contacts)
    app.bot_data['cme_admin'].setdefault('contacts', contacts)
    app.bot_data.setdefault('dict_topics_name', {})
    app.bot_data.setdefault('global_on_off', True)
    app.context_types.context.config = config

    await load_bot_settings(app)

    app.bot_data['feedback_group_id'] = app.bot_data['settings'].get(
        'FEEDBACK_GROUP_ID',
        app.bot_data['settings'].get('CHAT_ID_GROUP_ADMIN')
    )

    # Планировщик авто-отмены созданных билетов старше 30 минут
    app.job_queue.run_repeating(
        cancel_old_created_tickets,
        interval=3600,
        first=60,
        name='cancel_old_created_tickets',
        job_kwargs={'replace_existing': True, 'id': 'cancel_old_created_tickets'}
    )

    # TODO Сделать команду для настройки списков по интенсивам
    studio = {
        'Театральный интенсив': [],
    }
    app.bot_data['studio'] = studio

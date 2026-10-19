import logging

from telegram.ext import Application

from db import create_sessionmaker_and_engine
from db.db_postgres import get_all_active_auto_sendings
from settings.settings import ADDRESS_OFFICE, ADMIN_ID
from utilities.utl_func import set_menu, set_description
from utilities.settings_parser import load_bot_settings
from schedule.worker_jobs import cancel_old_created_tickets
from schedule.auto_sending import auto_sending_tick

_startup_logger = logging.getLogger('bot.startup')


async def post_init(app: Application, config):
    # Set menus with DB session for per-user grant-based menus
    try:
        sessionmaker = create_sessionmaker_and_engine(str(config.postgres.db_url))
        async with sessionmaker() as session:
            await set_menu(app.bot, session)
    except Exception:
        # Fallback: set menus without per-user grants if DB is unavailable
        _startup_logger.exception('Ошибка настройки меню с DB, используется fallback без грантов')
        await set_menu(app.bot)

    await set_description(app.bot)

    app.bot_data.setdefault('texts', {})
    app.bot_data['texts']['description'] = (
        '<a href="https://t.me/theater_domik">Канал театра</a> в телеграм'
        ' с удобным делением по темам\n'
        'ПОДПИСЫВАЙТЕСЬ, чтобы не пропустить новости театра\n\n'
    )
    app.bot_data['texts']['description_html'] = (
        '<a href="https://t.me/theater_domik">Канал театра</a> в телеграм'
        ' с удобным делением по темам<br>'
        'ПОДПИСЫВАЙТЕСЬ, чтобы не пропустить новости театра<br><br>'
    )
    app.bot_data['texts']['address'] = (
        f'Адрес:\n{ADDRESS_OFFICE}\n\n'
    )
    app.bot_data['texts']['address_html'] = (
        f'Адрес:<br>{ADDRESS_OFFICE}<br><br>'
    )
    app.bot_data['texts']['ask_question'] = (
        '<i>Задать любой вопрос можно здесь, написав сообщение боту '
        '(можно прикреплять файлы/медиа)</i>\n\n'
    )
    app.bot_data['texts']['ask_question_html'] = (
        '<i>Задать любой вопрос можно здесь, написав сообщение боту '
        '(можно прикреплять файлы/медиа)</i><br><br>'
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
    contacts_html = 'Театр Домик<br>telegram @Theater_Domik_admin<br>телефон +79159383529'
    app.bot_data['admin'].setdefault('contacts', contacts)
    app.bot_data['admin'].setdefault('contacts_html', contacts_html)
    app.bot_data['cme_admin'].setdefault('contacts', contacts)
    app.bot_data['cme_admin'].setdefault('contacts_html', contacts_html)
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
        job_kwargs={
            'replace_existing': True,
            'id': 'cancel_old_created_tickets',
            'misfire_grace_time': 120,  # 2 минут grace time
            'coalesce': True,  # объединять пропущенные запуски в один
        }
    )

    # Планировщик авторассылок (напоминания, отзывы и т.д.)
    app.job_queue.run_repeating(
        auto_sending_tick,
        interval=20,
        first=20,
        name='auto_sending_tick',
        job_kwargs={
            'replace_existing': True,
            'id': 'auto_sending_tick',
            'misfire_grace_time': 120,  # 2 минут grace time
            'coalesce': True,  # объединять пропущенные запуски в один
        }
    )

    # Проверка авторассылок: активная рассылка с пустым текстом → уведомление админу
    try:
        sessionmaker = create_sessionmaker_and_engine(str(config.postgres.db_url))
        async with sessionmaker() as session:
            sendings = await get_all_active_auto_sendings(session)
            empty_names = [s.name for s in sendings if not s.text or not s.text.strip()]
        if empty_names:
            for admin_id in ADMIN_ID:
                await app.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        '⚠️ При старте обнаружены активные рассылки с пустым текстом:\n'
                        + '\n'.join(f'• {n}' for n in empty_names)
                    ),
                )
            _startup_logger.warning(
                'Активные рассылки с пустым текстом: %s', empty_names
            )
    except Exception:
        _startup_logger.exception('Ошибка проверки рассылок при старте')

    # TODO Сделать команду для настройки списков по интенсивам
    studio = {
        'Театральный интенсив': [],
    }
    app.bot_data['studio'] = studio

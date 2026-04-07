import os
import pytz
from fastapi.templating import Jinja2Templates
from faststream.nats.fastapi import NatsBroker
from yookassa import Configuration
from db.database import create_sessionmaker_and_engine
from settings.config_loader import parse_settings
from settings.settings import nats_url as default_nats_url, URL_BOT

settings = parse_settings()
Configuration.configure(settings.yookassa.account_id, settings.yookassa.secret_key.get_secret_value())
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
session_factory = create_sessionmaker_and_engine(
    db_url=str(settings.postgres.db_url),
    echo=False
)
templates = Jinja2Templates(directory='templates')
templates.env.globals['bot_username'] = URL_BOT.split('/')[-1]
broker = NatsBroker(os.getenv('NATS_URL', default_nats_url))

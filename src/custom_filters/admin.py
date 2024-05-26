from telegram.ext import filters

from settings.settings import ADMIN_ID

filter_admin = filters.User(ADMIN_ID)
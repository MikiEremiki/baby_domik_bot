from telegram.ext import filters

from settings.settings import ADMIN_ID
from settings.settings import CHAT_ID_KOCHETKOVA

filter_admin = filters.User(ADMIN_ID)
filter_to_send_msg = filters.User(ADMIN_ID + [CHAT_ID_KOCHETKOVA])
from telegram.ext import filters

from settings.settings import ADMIN_ID, CHAT_ID_KOCHETKOVA

filter_admin = filters.User(ADMIN_ID)
filter_to_send_msg = filters.User(ADMIN_ID + [CHAT_ID_KOCHETKOVA])
filter_list_cmd = filters.User(ADMIN_ID + [CHAT_ID_KOCHETKOVA])
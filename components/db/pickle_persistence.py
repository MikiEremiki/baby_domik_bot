import pathlib
import os

from telegram.ext import PicklePersistence

db_folder_name = 'db'
PERSIST_FILENAME = db_folder_name + '/conversationbot'
if not pathlib.Path(f'{db_folder_name}/').exists():
    os.mkdir(db_folder_name)
pickle_persistence = PicklePersistence(filepath=PERSIST_FILENAME)

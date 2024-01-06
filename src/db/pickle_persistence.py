import pathlib
import os

from telegram.ext import PicklePersistence

db_folder_name = 'data'
persist_filename = 'conversationbot'
parent_dir = pathlib.Path(__file__).parent
absolute_path = pathlib.Path(pathlib.Path.joinpath(parent_dir,
                                                   db_folder_name))
PERSIST_FILENAME = pathlib.Path(pathlib.Path.joinpath(absolute_path,
                                                      persist_filename))
if not absolute_path.exists():
    os.mkdir(db_folder_name)
pickle_persistence = PicklePersistence(filepath=PERSIST_FILENAME,
                                       update_interval=10)

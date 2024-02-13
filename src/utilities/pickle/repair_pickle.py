import pickle
from pathlib import Path
from typing import Any


_REPLACED_KNOWN_BOT = "a known bot replaced by PTB's PicklePersistence"
_REPLACED_UNKNOWN_BOT = "an unknown bot replaced by PTB's PicklePersistence"


class _BotUnpickler(pickle.Unpickler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

    def persistent_load(self, pid: str):
        if pid == _REPLACED_KNOWN_BOT:
            return None
        if pid == _REPLACED_UNKNOWN_BOT:
            return None
        raise pickle.UnpicklingError(
            "Found unknown persistent id when unpickling!")


class _BotPickler(pickle.Pickler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)


objects = []
# path = r'D:\Develop\Python\baby_domik_bot\src\db\data\conversationbot'
path = r'D:\Temp\conversationbot'
new_path: Path = Path(r'D:\Temp\conversationbot2')
with open(path, "rb") as file:
    while True:
        try:
            objects.append(_BotUnpickler(file).load())
        except EOFError:
            break

exclude = []
flag = False
if not flag:
    with open('user_ids', 'r', encoding='utf8') as f:
        for item in f.readlines():
            exclude.append(int(item.replace('\n', '')))

objects_keys_ud = objects[0]['user_data'].keys()
for item in exclude:
    if item in objects_keys_ud:
        objects[0]['user_data'].pop(item, None)

with new_path.open("wb") as file:
    _BotPickler(file).dump(objects[0])

import json
import pickle
from datetime import datetime
from typing import Any

from pydantic import SecretStr
from pydantic_core import MultiHostUrl
from telegram import User, InlineKeyboardMarkup

from settings.config_loader import Settings
from utilities.schemas.ticket import BaseTicket

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


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, tuple):
            return list(obj)
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, Settings):
            return obj.model_dump(exclude_defaults=True)
        if isinstance(obj, BaseTicket):
            return {"base_ticket_id": obj.base_ticket_id, "price": obj.price}
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, InlineKeyboardMarkup):
            return obj.to_dict()
        if isinstance(obj, SecretStr):
            return obj.__str__()
        if isinstance(obj, MultiHostUrl):
            return obj.__str__()
        if isinstance(obj, User):
            return [obj.id, obj.full_name, obj.username]
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)


objects = []
path = r'D:\Develop\Python\baby_domik_bot\src\db\data\conversationbot'
# path = r'D:\conversationbot'
# path = r'D:\Temp\conversationbot'
with (open(path, "rb")) as file:
    while True:
        try:
            objects.append(_BotUnpickler(file).load())
        except EOFError:
            break

for key, item in objects[0].items():
    sort_keys = True
    if key == 'user_data':
        sort_keys = False

    if key == 'conversations':
        obj_to_serialize = {key: {}}
        for key_2, item_2 in item.items():
            obj_to_serialize[key][key_2] = {}
            for key_3, item_3 in objects[0][key][key_2].items():
                obj_to_serialize[key][key_2][key_3[0]] = item_3
    else:
        obj_to_serialize = item

    try:
        json.dump(obj_to_serialize,
                  open(f"json_files/{key}.json", 'w', encoding='utf-8'),
                  indent=4,
                  ensure_ascii=False,
                  cls=CustomEncoder,
                  sort_keys=sort_keys)
    except TypeError as e:
        print(key)
        # print(item)
        print(e)

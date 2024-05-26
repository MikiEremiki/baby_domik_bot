import pickle
from pathlib import Path
from typing import Any

import utilities.schemas.ticket as tic

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


fix_base_ticket = True
# path = r'D:\Develop\Python\baby_domik_bot\src\db\data\conversationbot'
# path = r'D:\Temp\conversationbot'
# path = r'src\db\data\conversationbot'
path = r'/opt/project/src/db/data/conversationbot'
new_path: Path = Path(r'D:\Temp\conversationbot2')
with open(path, "rb") as file:
    while True:
        try:
            objects = _BotUnpickler(file).load()
        except EOFError:
            break

exclude = []
flag = True
if not flag:
    with open('user_ids', 'r', encoding='utf8') as f:
        for item in f.readlines():
            exclude.append(int(item.replace('\n', '')))

objects_keys_ud = objects['user_data'].keys()
for item in exclude:
    if item in objects_keys_ud:
        objects['user_data'].pop(item, None)
if fix_base_ticket:
    for key1, item1 in objects.items():
        if key1 == 'user_data':
            for key2, item2 in item1.items():
                if 'reserve_admin_data' in item2.keys():
                    for key3, item3 in item2['reserve_admin_data'].items():
                        if isinstance(item3, dict) and isinstance(key3, int):
                            if isinstance(item3.get('chose_ticket', False),
                                          tic.BaseTicket):
                                ticket = item3['chose_ticket'].to_dto()
                                item3['chose_ticket'] = tic.BaseTicketDTO(
                                    **ticket)
        if key1 == 'bot_data':
            for i, base_ticket in enumerate(item1['list_of_tickets']):
                if isinstance(base_ticket, tic.BaseTicket):
                    ticket = base_ticket.to_dto()
                    item1['list_of_tickets'][i] = tic.BaseTicketDTO(**ticket)

with new_path.open("wb") as file:
    _BotPickler(file).dump(objects)

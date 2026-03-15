import pickle
import sys
import os
from typing import Any

# Константы, используемые в python-telegram-bot's PicklePersistence для замены Bot объекта
_REPLACED_KNOWN_BOT = "a known bot replaced by PTB's PicklePersistence"
_REPLACED_UNKNOWN_BOT = "an unknown bot replaced by PTB's PicklePersistence"

class BotUnpickler(pickle.Unpickler):
    """Кастомный Unpickler для обработки persistent_id от PTB."""
    def persistent_load(self, pid: str):
        if pid == _REPLACED_KNOWN_BOT or pid == _REPLACED_UNKNOWN_BOT:
            return None
        raise pickle.UnpicklingError(f"Found unknown persistent id: {pid}")

def get_size(obj: Any) -> int:
    """Приблизительно оценивает размер объекта в байтах через перепаковку в pickle."""
    try:
        return len(pickle.dumps(obj))
    except Exception:
        return 0

def analyze_pickle(file_path: str):
    if not os.path.exists(file_path):
        print(f"Ошибка: Файл не найден: {file_path}")
        return

    print(f"--- Анализ файла: {file_path} ---")
    print(f"Размер файла на диске: {os.path.getsize(file_path) / 1024 / 1024:.2f} MB")

    try:
        with open(file_path, "rb") as f:
            # PicklePersistence может содержать несколько объектов, если файл дописывался в конец
            # но обычно там один словарь.
            data = BotUnpickler(f).load()
    except Exception as e:
        print(f"Ошибка при чтении файла: {e}")
        return

    if not isinstance(data, dict):
        print("Ошибка: Содержимое файла не является словарем (ожидался формат PicklePersistence).")
        return

    for key, items in data.items():
        if not isinstance(items, dict):
            print(f"Ключ '{key}': не является словарем, размер: {get_size(items) / 1024:.2f} KB")
            continue

        total_size = 0
        sizes = []

        for sub_key, value in items.items():
            s = get_size(value)
            total_size += s
            sizes.append((sub_key, s))

        print(f"\nКлюч '{key}':")
        print(f"  Количество записей: {len(items)}")
        print(f"  Общий размер данных: {total_size / 1024 / 1024:.2f} MB")

        # Топ-5 самых тяжелых записей
        if sizes:
            sizes.sort(key=lambda x: x[1], reverse=True)
            print("  Топ-5 самых тяжелых записей:")
            for k, s in sizes[:5]:
                print(f"    - {k}: {s / 1024:.2f} KB")

if __name__ == "__main__":
    # Можно передать путь к файлу аргументом или использовать путь по умолчанию
    path = r"D:\Temp\conversationbot.bak_260315"
    if len(sys.argv) > 1:
        path = sys.argv[1]
    
    analyze_pickle(path)

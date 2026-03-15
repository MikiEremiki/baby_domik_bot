import pickle
import sys
import os
from typing import Any, Dict

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

def format_size(size_bytes: int) -> str:
    """Форматирует размер в байтах в человекочитаемый вид."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"

def analyze_heavy_users(file_path: str):
    if not os.path.exists(file_path):
        print(f"Ошибка: Файл не найден: {file_path}")
        return

    print(f"--- Детальный анализ ТОП-5 самых тяжелых записей в user_data ---")
    print(f"Файл: {file_path}")
    print(f"Размер файла: {os.path.getsize(file_path) / 1024 / 1024:.2f} MB")

    try:
        with open(file_path, "rb") as f:
            data = BotUnpickler(f).load()
    except Exception as e:
        print(f"Ошибка при чтении файла: {e}")
        return

    user_data = data.get('user_data', {})
    if not user_data:
        print("В файле нет 'user_data' или они пустые.")
        return

    # 1. Расчет размеров всех пользователей
    user_sizes = []
    for user_id, u_data in user_data.items():
        user_sizes.append((user_id, get_size(u_data), u_data))

    # 2. Сортировка по весу и выбор ТОП-5
    user_sizes.sort(key=lambda x: x[1], reverse=True)
    top_5 = user_sizes[:5]

    for user_id, total_size, u_data in top_5:
        print(f"\n" + "="*50)
        print(f"ПОЛЬЗОВАТЕЛЬ: {user_id}")
        print(f"Общий вес: {format_size(total_size)}")
        print("-" * 50)

        # 3. Анализ ключей верхнего уровня у пользователя
        for key, value in u_data.items():
            key_size = get_size(value)
            print(f"- {key}: {format_size(key_size)}")

            # 4. Если это reserve_user_data, анализируем глубже
            if key == 'reserve_user_data' and isinstance(value, dict):
                print(f"  └─ Детали reserve_user_data:")
                for r_key, r_value in value.items():
                    r_size = get_size(r_value)
                    if r_size > 1024: # Только то, что больше 1 KB
                        print(f"     ├─ {r_key}: {format_size(r_size)}")
                        
                        # Особое внимание истории 'back'
                        if r_key == 'back' and isinstance(r_value, dict):
                            print(f"     │  └─ Количество сохраненных состояний (back): {len(r_value)}")
                            # Посчитаем сколько в среднем весит один стейт в back
                            if len(r_value) > 0:
                                avg_state_size = r_size / len(r_value)
                                print(f"     │  └─ Средний вес одного состояния: {format_size(avg_state_size)}")
                                
                                # Если в back есть клавиатуры, это может быть причиной
                                heavy_states = sorted(
                                    [(s, get_size(v)) for s, v in r_value.items()],
                                    key=lambda x: x[1], reverse=True
                                )[:3]
                                if heavy_states:
                                    print(f"     │  └─ ТОП-3 тяжелых состояний:")
                                    for state_name, s_size in heavy_states:
                                        print(f"     │     - {state_name}: {format_size(s_size)}")

if __name__ == "__main__":
    path = r"D:\Temp\conversationbot.bak_260315"
    if len(sys.argv) > 1:
        path = sys.argv[1]
    
    analyze_heavy_users(path)

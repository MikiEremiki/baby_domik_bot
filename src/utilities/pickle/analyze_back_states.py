import pickle
import sys
import os
from typing import Any, List, Tuple

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

def analyze_back_states(file_path: str):
    if not os.path.exists(file_path):
        print(f"Ошибка: Файл не найден: {file_path}")
        return

    print(f"--- Глобальный анализ самых тяжелых состояний в ключе 'back' ---")
    print(f"Файл: {file_path}")
    
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

    all_back_states: List[Tuple[int, str, int, Any]] = []

    for user_id, u_data in user_data.items():
        if not isinstance(u_data, dict):
            continue
            
        reserve_data = u_data.get('reserve_user_data')
        if not isinstance(reserve_data, dict):
            continue
            
        back_dict = reserve_data.get('back')
        if not isinstance(back_dict, dict):
            continue
            
        for state_name, state_val in back_dict.items():
            size = get_size(state_val)
            all_back_states.append((user_id, state_name, size, state_val))

    if not all_back_states:
        print("В 'user_data' не найдено ни одного сохраненного состояния в ключе 'back'.")
        return

    # Сортировка по размеру (по убыванию)
    all_back_states.sort(key=lambda x: x[2], reverse=True)

    print(f"Всего найдено состояний в 'back': {len(all_back_states)}")
    print(f"\nТОП-10 самых тяжелых состояний:")
    print("-" * 80)
    print(f"{'#':<3} | {'User ID':<12} | {'State Name':<30} | {'Size':<10} | {'Keyboard?'}")
    print("-" * 80)

    for i, (user_id, state_name, size, val) in enumerate(all_back_states[:10], 1):
        has_kb = "Нет"
        if isinstance(val, dict) and val.get('keyboard'):
            has_kb = "Да"
            
        print(f"{i:<3} | {user_id:<12} | {state_name[:30]:<30} | {format_size(size):<10} | {has_kb}")

    print("-" * 80)
    
    # Детальный разбор ТОП-3
    print(f"\nДетальный разбор ТОП-3:")
    for i, (user_id, state_name, size, val) in enumerate(all_back_states[:3], 1):
        print(f"\n{i}. Пользователь: {user_id}, Состояние: {state_name}")
        print(f"   Общий размер: {format_size(size)}")
        if isinstance(val, dict):
            for k, v in val.items():
                v_size = get_size(v)
                print(f"   ├─ {k}: {format_size(v_size)}")
                # Если это клавиатура, заглянем в кнопки
                if k == 'keyboard' and hasattr(v, 'to_dict'):
                    kb_dict = v.to_dict()
                    buttons_count = 0
                    if 'inline_keyboard' in kb_dict:
                        buttons_count = sum(len(row) for row in kb_dict['inline_keyboard'])
                    print(f"   │  └─ Кнопок в клавиатуре: {buttons_count}")

if __name__ == "__main__":
    path = r"D:\Temp\conversationbot.bak_260315"
    if len(sys.argv) > 1:
        path = sys.argv[1]
    
    analyze_back_states(path)

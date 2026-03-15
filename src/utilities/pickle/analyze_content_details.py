import pickle
import sys
import os
from typing import Any, List, Tuple
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup

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

def analyze_keyboard(kb: Any) -> Tuple[int, int, List[str]]:
    """Анализирует структуру и содержимое клавиатуры."""
    rows_count = 0
    buttons_count = 0
    button_details = []
    
    if hasattr(kb, 'to_dict'):
        kb_dict = kb.to_dict()
        if 'inline_keyboard' in kb_dict:
            rows = kb_dict['inline_keyboard']
            rows_count = len(rows)
            for row in rows:
                buttons_count += len(row)
                for btn in row:
                    btn_text = btn.get('text', '')
                    btn_data = btn.get('callback_data') or btn.get('url') or ''
                    button_details.append(f"[{btn_text}]({btn_data})")
        elif 'keyboard' in kb_dict:
            rows = kb_dict['keyboard']
            rows_count = len(rows)
            for row in rows:
                buttons_count += len(row)
                for btn in row:
                    if isinstance(btn, dict):
                        btn_text = btn.get('text', '')
                    else:
                        btn_text = str(btn)
                    button_details.append(f"[{btn_text}]")
                    
    return rows_count, buttons_count, button_details

def analyze_content_details(file_path: str):
    if not os.path.exists(file_path):
        print(f"Ошибка: Файл не найден: {file_path}")
        return

    print(f"--- Детальный анализ содержимого (text и keyboard) в 'back' ---")
    print(f"Файл: {file_path}\n")
    
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

    all_back_states = []

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
            if isinstance(state_val, dict):
                size = get_size(state_val)
                all_back_states.append({
                    'user_id': user_id,
                    'state': state_name,
                    'size': size,
                    'val': state_val
                })

    if not all_back_states:
        print("Состояния в 'back' не найдены.")
        return

    # Сортировка по размеру
    all_back_states.sort(key=lambda x: x['size'], reverse=True)

    print(f"ТОП-5 самых тяжелых состояний для анализа:")
    
    for i, item in enumerate(all_back_states[:5], 1):
        val = item['val']
        text = val.get('text', '')
        kb = val.get('keyboard')
        
        print(f"\n{i}. USER_ID: {item['user_id']} | STATE: {item['state']}")
        print(f"   Общий размер: {format_size(item['size'])}")
        
        # Анализ текста
        text_size = get_size(text)
        print(f"   ├─ ТЕКСТ ({format_size(text_size)}):")
        if isinstance(text, str):
            clean_text = text.replace('\n', ' ')
            preview = clean_text[:100] + "..." if len(clean_text) > 100 else clean_text
            print(f"   │  └─ Содержание: {preview}")
            print(f"   │  └─ Длина строки: {len(text)} символов")
        else:
            print(f"   │  └─ Тип данных: {type(text)}")

        # Анализ клавиатуры
        kb_size = get_size(kb)
        print(f"   └─ КЛАВИАТУРА ({format_size(kb_size)}):")
        if kb:
            rows, btns, details = analyze_keyboard(kb)
            print(f"      ├─ Тип: {type(kb).__name__}")
            print(f"      ├─ Рядов: {rows}, Всего кнопок: {btns}")
            if btns > 0:
                print(f"      └─ Первые 10 кнопок (текст:данные):")
                for btn_info in details[:10]:
                    print(f"         • {btn_info}")
                if len(details) > 10:
                    print(f"         ... и еще {len(details)-10} кнопок")
        else:
            print(f"      └─ Отсутствует")
        print("-" * 60)

if __name__ == "__main__":
    path = r"D:\Temp\conversationbot.bak_260315"
    if len(sys.argv) > 1:
        path = sys.argv[1]
    
    analyze_content_details(path)

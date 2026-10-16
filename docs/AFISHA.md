# Система афиш

Обзор того, как работает загрузка, хранение и отображение афиш в боте и на веб-сайте.

---

## Хранение данных

### Таблица базы данных `Afisha`

Каждая афиша хранится в таблице `afishas` со следующими полями:

- `month` — номер месяца (1–12), **уникальный ключ** — одна афиша на один месяц
- `file_id` — Telegram `file_id` фотографии (для отправки в боте)
- `file_path` — путь к файлу на диске (для веб-сайта)
- `zones` — дополнительные зоны (опционально)

**Важно:** афиши хранятся **без привязки к году**. Поле `year` было удалено в рефакторинге rev_29, так как администратору достаточно привязки к номеру месяца. Афиша, загруженная в 2026 году, будет отображаться в 2027, 2028 и далее, пока не будет обновлена или удалена.

### Файлы на диске

Афиши сохраняются в папке `static/img/afisha/` с именем `{month:02d}.jpg`, например `01.jpg`.

### Двойное хранение

При загрузке афиши сохраняются **два** представления одного и того же файла:

1. **Telegram `file_id`** — идентификатор в кэше Telegram, используется ботом для быстрой отправки
2. **Файл на диске** — скачанная копия, используется веб-сайтом

---

## Загрузка афиши (`/afisha`)

**Файл:** `src/handlers/afisha_hl.py`

### Поток работы

1. Администратор вызывает `/afisha`
2. Бот показывает клавиатуру с месяцами (1–12), где 🖼 означает, что афиша уже загружена
3. Админ выбирает месяц
4. Если афиша уже существует:
   - Бот показывает кнопку «Посмотреть», «Обновить», «Удалить»
5. Если афиши нет:
   - Бот просит отправить фотографию

### Сохранение

```python
# Скачивание файла на диск
new_file = await context.bot.get_file(file_id)
file_name = f'{month:02d}.jpg'
file_path = STATIC_AFISHA_DIR / file_name
await new_file.download_to_drive(custom_path=str(file_path))

# Сохранение в БД
await db_postgres.create_or_update_afisha(
    context.session, month=month, file_id=file_id, file_path=stored_path
)
```

---

## Отображение в боте

**Файл:** `src/handlers/reserve/choice.py`

### Формирование списка месяцев

При бронировании бот формирует список доступных месяцев на основе `schedule_event`:

```python
months = get_unique_months(schedule_events)  # строка 407
```

Функция `get_unique_months` (`src/utilities/utl_func.py`, строка 716–729):

```python
def get_unique_months(events: Sequence[ScheduleEvent]):
    unique_sorted_months = []
    months = {}
    years = set()
    for event in events:
        year = event.datetime_event.year
        month = event.datetime_event.month
        years.add(year)
        months.setdefault(year, set())
        months[year].add(month)
    years = sorted(years)
    for year in years:
        unique_sorted_months.extend(sorted(months[year]))
    return unique_sorted_months
```

**Важно:** функция возвращает **только номера месяцев (1–12)**, игнорируя годы. Если есть события в январе 2026 и январе 2027, в списке будет одна кнопка «1» (январь).

### Получение и отправка афиши

Пользователь выбирает месяц → бот ищет афишу:

```python
afisha_record = await db_postgres.get_afisha(
    context.session, int(number_of_month_str)
)
```

Афиша ищется **только по номеру месяца** — год не учитывается.

Афиша отправляется через `file_id` из БД (кэш Telegram), а не с диска:

```python
await update.effective_chat.send_photo(
    photo=afisha_record.file_id,  # file_id из БД
    caption=text,
    reply_markup=reply_markup,
)  # строка 615-618
```

---

## Отображение на веб-сайте

**Файл:** `src/api/web/routes/pages.py`

### Формирование доступных месяцев

Веб-сайт формирует ключи месяцев в формате `YYYY-MM` на основе дат `schedule_event`:

```python
dt_moscow = dt.astimezone(MOSCOW_TZ)
m_key = dt_moscow.strftime('%Y-%m')  # формат "2027-01"  # строка 107
```

### Получение афиши

```python
afishas_db = await get_afishas(session)
```

Все афиши загружаются из БД без фильтрации по году. Фильтрация по месяцу происходит на уровне приложения:

```python
selected_month_int = int(month.split('-')[1]) if month else None
for a in afishas_db:
    if selected_month_int and a.month != selected_month_int:
        continue
    path = '/' + a.file_path if not a.file_path.startswith('/') else a.file_path
    afishas.append({
        'month': a.month,
        'image_url': path  # → /static/img/afisha/01.jpg
    })
```

---

## Удаление афиши

**Файл:** `src/handlers/afisha_hl.py`, функция `delete_afisha_action` (строка 139–169)

Удаление афиши из бота **мгновенно удаляет её и с сайта**, потому что бот и сайт используют единую БД и единую папку с файлами.

### Что происходит при удалении

1. **Удаление файла с диска:**
   ```python
   file_name = f'{month:02d}.jpg'
   file_path = STATIC_AFISHA_DIR / file_name
   if file_path.exists():
       os.remove(file_path)
   ```

2. **Удаление записи из БД:**
   ```python
   await db_postgres.delete_afisha(context.session, month)
   ```

---

## Сравнение: бот vs сайт

| Аспект | Бот | Веб-сайт |
|--------|-----|----------|
| **Источник картинки** | `file_id` из БД (кэш Telegram) | `file_path` из БД (файл на диске) |
| **Поиск афиши** | По номеру месяца (1–12) | По номеру месяца (1–12) |
| **Список месяцев** | Номера 1–12, год игнорируется | Формат `YYYY-MM` для фильтрации событий |
| **Отправка** | `send_photo(photo=file_id)` | `<img src="/static/img/afisha/01.jpg">` |

После рефакторинга rev_29 бот и сайт используют одинаковую логику поиска афиш — только по номеру месяца, без учёта года.

---

## История изменений

### rev_29: Удаление привязки к году (2026-10-16)

До этого изменения афиши были привязаны к году (`month + year`), что создавало проблему при смене года: все афиши, загруженные в 2026, переставали отображаться 1 января 2027.

После изменения:
- Поле `year` удалено из таблицы `afishas`.
- Уникальный ключ изменён с `uq_afisha_month_year` на `uq_afisha_month`.
- Файлы на диске переименованы: `{year}_{month:02d}.jpg` → `{month:02d}.jpg`.
- Афиша, загруженная в 2026, будет отображаться в 2027, 2028 и далее.

---

## Нюансы Telegram `file_id`

`file_id` в Telegram Bot API можно использовать бесконечно, но **файл может быть удалён Telegram**, если бот не отправлял его долгое время. На практике это редко происходит, но теоретически возможно.

Файл на диске (`static/img/afisha/`) — это **резервная копия** для сайта. Бот не использует файл с диска: он всегда ссыляется на `file_id` из БД.

---

## Архитектура данных

```
┌─────────────────────────────────────────────────────────┐
│                    Таблица Afisha                       │
├──────────┬──────────┬───────────────────────┤
│  month   │ file_id  │       file_path       │
├──────────┼──────────┼───────────────────────┤
│    1     │ AgAC...  │ /static/img/afisha/   │
│          │          │ 01.jpg                │
└──────────┴──────────┴───────────────────────┘
       │              │                    │
       │              │                    │
       ▼              ▼                    ▼
   Бот ищет      Бот ищет          Файл на диске
   по month     через file_id     (для веб-сайта)
                (кэш Telegram)
```

---

## Ключевые файлы

| Файл | Назначение |
|------|------------|
| `src/handlers/afisha_hl.py` | Загрузка, просмотр, обновление, удаление афиш через `/afisha` |
| `src/conv_hl/afisha_conv_hl.py` | Conversation handler для `/afisha` |
| `src/handlers/reserve/choice.py` | Отображение афиши при бронировании (функция `choice_show`) |
| `src/utilities/utl_func.py` | `get_unique_months()` — формирование списка месяцев |
| `src/api/web/routes/pages.py` | Отображение афиши на веб-сайте |
| `src/db/db_postgres.py` | CRUD-операции: `create_or_update_afisha`, `get_afisha`, `get_afishas`, `delete_afisha` |
| `static/img/afisha/` | Папка с файлами афиш на диске |

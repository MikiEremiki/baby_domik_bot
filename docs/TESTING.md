# Тестирование

## Запуск

```bash
# Все тесты
pytest test/

# Конкретная папка
pytest test/test_api/

# Конкретный файл
pytest test/test_api/test_fastapi_web_preview.py

# Конкретный тест
pytest test/test_api/test_fastapi_web_preview.py::test_index_page_is_rendered
```

## Структура

Тесты организованы по модулям проекта. Общие фикстуры и утилиты вынесены в `conftest.py`.

```
test/
├── conftest.py              # Общие фикстуры и утилиты
├── test_schedule/           # Расписание и авторассылки (7 файлов)
│   ├── test_auto_sending.py
│   ├── test_dynamic_seats.py
│   ├── test_schedule_changes.py
│   ├── test_schedule_creation_wizard.py
│   ├── test_schedule_msk_timezone.py
│   ├── test_schedule_reports.py
│   └── test_schedule_sync.py
├── test_handlers/           # Обработчики Telegram (8 файлов)
│   ├── test_command_access_ui.py
│   ├── test_command_permission_middleware.py
│   ├── test_glob_on_off_and_reserve_check.py
│   ├── test_reserve_admin_improvements.py
│   ├── test_reserve_refactor.py
│   ├── test_set_menu.py
│   ├── test_settings_access.py
│   └── test_tick_scheduler.py
├── test_api/                # FastAPI веб-сервис (5 файлов)
│   ├── test_fastapi_web_preview.py
│   ├── test_gspread_retry_and_timeout.py
│   ├── test_gspread_seats_sync.py
│   ├── test_issue_repro.py
│   └── test_yookassa_webhook.py
├── test_db/                 # БД и миграции (1 файл)
│   └── test_nats_migrate.py
├── test_permissions/        # Права доступа (1 файл)
│   └── test_permissions_settings_keys.py
├── test_tickets/            # Билеты и чеки (3 файла)
│   ├── test_receipts.py
│   ├── test_ticket_email.py
│   └── test_ticket_source.py
├── test_events/             # События и площадки (2 файла)
│   ├── test_list_past_events.py
│   └── test_multi_location_events.py
└── test_sales/              # Рассылки и продажи (1 файл)
    └── test_sales_children_age.py
```

## Общие фикстуры (`conftest.py`)

### Базы данных

**`AsyncSessionWrapper`** — обёртка синхронной сессии SQLAlchemy для асинхронного кода. Поддерживает `execute`, `get`, `merge`, `commit`, `flush`, `refresh`, `rollback`, `add`, `add_all`.

**`_run_with_db(test_coro)`** — создаёт in-memory SQLite БД, запускает асинхронный тест с `AsyncSessionWrapper`, затем уничтожает engine.

```python
from conftest import _run_with_db

async def test_something():
    async def _test(session):
        # используйте session.execute(), session.add(), session.commit()
        result = await session.execute(select(User))
    await _run_with_db(_test)
```

### Telegram-моки

**`mock_context`** (pytest fixture) — минимальный мок `context` с `session`, `bot`, `config`.

**`mock_seats`** (pytest fixture) — словарь доступных мест, возвращаемый `get_schedule_event_available_seats`.

**`_create_mock_update(...)`** — создаёт мок Telegram `Update` с NATS metadata. Параметры: `source`, `chat_id`, `message_id`, `ticket_ids`, `choose_schedule_event_ids`, `command`, `promo_id`.

**`_create_mock_context(has_persistence=True)`** — создаёт мок `context`, похожий на реальный PTB `ContextTypes.DEFAULT`, с `bot_data`, `persistence`, `config`.

```python
from conftest import _create_mock_update, _create_mock_context

update = _create_mock_update(command='reserve', chat_id='123')
context = _create_mock_context()
```

### FastAPI веб-моки

**`_create_web_client(monkeypatch, mock_default_place=True)`** — создаёт FastAPI `TestClient` с моками NATS, БД и `get_default_place`. Возвращает контекстный менеджер.

**`_create_mock_theater_event(...)`** — создаёт мок `TheaterEvent` с одним `ScheduleEvent`. Возвращает `(theater_event, schedule_event)`.

**`_create_mock_schedule_event(...)`** — создаёт мок `ScheduleEvent` с привязанным `TheaterEvent`. Возвращает `(schedule_event, theater_event)`.

```python
from conftest import _create_web_client, _create_mock_theater_event

def test_index(monkeypatch):
    mock_event, _ = _create_mock_theater_event(event_name="Мой спектакль")
    monkeypatch.setattr(pages, 'get_all_theater_events_actual',
                        AsyncMock(return_value=[mock_event]))
    with _create_web_client(monkeypatch) as client:
        response = client.get('/afisha')
    assert response.status_code == 200
```

## Конвенции

1. **Именование** — файлы `test_*.py`, функции `test_*.py`.
2. **Группировка** — тесты сгруппированы по модулю проекта (`test_schedule/` → `src/schedule/`, `test_handlers/` → `src/handlers/`).
3. **Общие фикстуры** — новый общий код, используемый в 2+ файлах, выносить в `conftest.py`.
4. **Моки** — использовать `_create_mock_*` функции из `conftest.py`, а не дублировать их в каждом файле.
5. **Без внешних зависимостей** — тесты не подключаются к реальному NATS, БД или YooKassa; всё мокается.
6. **pytest fixtures** — автоматические фикстуры (`mock_context`, `mock_seats`) подгружаются без явного импорта.

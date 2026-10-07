# Архитектура BabyDomikBot

Telegram-бот и сопутствующие сервисы для управления театральными мероприятиями: бронирование билетов, оплата через YooKassa, синхронизация с Google Sheets и рассылки.

---

### 1. Обзор слоёв и модулей (Layers & Modules)

```
baby_domik_bot/
│
+-- src/                        # ОСНОВНОЙ ИСХОДНЫЙ КОД
│   +-- api/                    # ВНЕШНИЕ ИНТЕГРАЦИИ И БРОКЕР
│   │   +-- web/                # FastAPI веб-сервис
│   │   │   +-- main.py         # Точка входа, инициализация приложения
│   │   │   +-- routes/         # Роутеры API и страниц
│   │   │   │   +-- api.py      # Вебхуки YooKassa и вспомогательные API
│   │   │   │   +-- auth.py     # Авторизация Telegram Login Widget
│   │   │   │   +-- booking.py  # Подтверждение бронирования и оплаты
│   │   │   │   L-- pages.py    # HTML-страницы: /, /afisha, /event/{id}, /custom-events, /studio
│   │   │   +-- site_content.py # Статический контент сайта (глобал `site` в шаблонах)
│   │   │   +-- services/       # Бизнес-логика веб-сервиса
│   │   │   │   L-- booking_service.py  # Расчёт цен, промокоды, очистка просроченных броней
│   │   │   +-- config.py       # Конфигурация NATS и веб-настройки
│   │   │   +-- deps.py         # Зависимости FastAPI (сессия БД)
│   │   │   +-- logger.py       # Логирование веб-сервиса
│   │   │   L-- schemas.py      # Pydantic-модели для валидации API
│   │   +-- broker_nats.py      # Подписчики NATS бота (yookassa, gspread_failed, sales_report)
│   │   +-- googlesheets.py     # Низкоуровневое взаимодействие с Google Sheets API (v4)
│   │   +-- gspread_pub.py      # Издатель задач в Google Sheets через NATS
│   │   +-- gspread_worker.py   # Воркер записи в Google Sheets
│   │   +-- sales_pub.py        # Издатель задач рассылки через NATS
│   │   +-- sales_worker.py     # Воркер рассылки сообщений
│   │   +-- timeweb.py          # Интеграция с API Timeweb (баланс)
│   │   L-- yookassa_connect.py # Формирование параметров платежей YooKassa
│   │
│   +-- db/                     # БАЗА ДАННЫХ
│   │   +-- models.py           # SQLAlchemy модели (User, Ticket, ScheduleEvent и др.)
│   │   +-- db_postgres.py      # CRUD-операции PostgreSQL (AsyncSession)
│   │   +-- enum.py             # Перечисления (TicketStatus, PriceType и др.)
│   │   L-- migrations/         # Миграции Alembic
│   │
│   +-- handlers/               # ОБРАБОТЧИКИ TELEGRAM
│   │   +-- set_handlers.py     # Регистрация всех обработчиков
│   │   +-- reserve_hl.py       # Бронирование билетов (основной хендлер)
│   │   +-- birthday_hl.py      # Заявки на дни рождения
│   │   L-- hooks/              # Обработчики событий из NATS
│   │       +-- yookassa_hl.py  # Обработка платежей YooKassa
│   │       +-- gspred_hl.py    # Уведомления об ошибках Google Sheets
│   │       +-- sales_hl.py     # Отчёты о рассылках
│   │       L-- schedule_sync_hl.py  # Результаты выгрузки расписания
│   │
│   +-- conv_hl/                # ДИАЛОГИ (ConversationHandlers)
│   │   L-- *_conv_hl.py        # Состояния и переходы для сложных диалогов
│   │
│   +-- middleware/             # ПРОМЕЖУТОЧНОЕ ПО
│   │   +-- db_handlers.py      # Прокидывание сессии БД
│   │   L-- reserve_check.py    # Проверка возможности бронирования
│   │
│   +-- settings/               # НАСТРОЙКИ
│   │   +-- config_loader.py    # Загрузка settings.yml
│   │   L-- settings.py         # Константы, ID чатов, настройки NATS
│   │
│   +-- utilities/              # ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
│   │   +-- utl_kbd.py          # Создание клавиатур Telegram
│   │   +-- utl_func.py         # Форматирование текста, даты
│   │   L-- utl_db.py           # Утилиты для сессий БД
│   │
│   +-- custom_filters/         # ПОЛЬЗОВАТЕЛЬСКИЕ ФИЛЬТРЫ
│   │   L-- filter_admin.py     # Фильтр админских команд
│   │
│   +-- log/                    # ЛОГИРОВАНИЕ
│   │   L-- logging_conf.py     # Конфигурация именованных логгеров
│   │
│   L-- schedule/               # РАСПИСАНИЕ
│       L-- scheduler_jobs.py   # Фоновые задачи (очистка просроченных броней и др.)
│
+-- templates/                  # WEB-ШАБЛОНЫ (JINJA2)
│   +-- home.html               # Главная страница
│   +-- custom_events.html      # Заказные мероприятия
│   +-- studio.html             # Студия
│   L-- ...                     # Афиша, события и др.
│
+-- static/                     # СТАТИЧЕСКИЕ ФАЙЛЫ
│   +-- css/
│   │   L-- site.css            # Стили веб-интерфейса
│   L-- img/                    # Изображения
│
+-- test/                       # ТЕСТЫ (pytest)
│   L-- test_timeweb.py         # Интеграционные тесты Timeweb API
│
+-- config/                     # КОНФИГУРАЦИЯ (игнорируется в Git)
│   +-- alembic.ini             # Конфигурация Alembic
│   +-- settings.yml            # Токены, пароли, пути
│   L-- credentials.json        # Google Sheets credentials
│
L-- docker-compose*.yaml        # Оркестрация контейнеров (профили: migration, bot, all)
```

---

### 2. Потоки данных (Data Flow)

#### 2.1 Бронирование билета

```
Пользователь → Telegram → python-telegram-bot
  → ConversationHandler (conv_hl/)
  → reserve_hl.py (выбор сеанса, билетов)
  → yookassa_connect.py (создание платежа)
  → YooKassa (перенаправление на оплату)
```

#### 2.2 Обработка платежа

```
YooKassa → POST /yookassa (FastAPI)
  → NATS (тема yookassa)
  → broker_nats.py (бот)
  → yookassa_hl.py (обновление статуса билета в БД)
  → gspread_pub.py → NATS (тема gspread)
  → gspread_worker.py → Google Sheets
```

#### 2.3 Синхронизация расписания

```
Админ → /sync_schedule (Telegram)
  → Срез изменений расписания (ScheduleChange)
  → NATS (тема gspread, sync_schedule)
  → gspread_worker.py → Google Sheets
  → NATS (тема schedule_sync_result)
  → schedule_sync_hl.py → Отчёт в топик «Изменения расписания»
```

#### 2.4 Рассылка сообщений

```
Админ → Команда рассылки (Telegram)
  → sales_pub.py → NATS (тема sales)
  → sales_worker.py (рассылка сообщений)
  → NATS (тема sales_report)
  → sales_hl.py → Отчёт админам
```

---

### 3. Правила изоляции слоёв

1. **FastAPI веб-сервис** (`src/api/web/`) не импортирует `python-telegram-bot` или `gspread`.
2. **Telegram-бот** (`src/handlers/`, `src/conv_hl/`) не зависит от FastAPI напрямую — связь через NATS.
3. **Воркеры** (`gspread_worker.py`, `sales_worker.py`) независимы от бота и FastAPI.
4. **Общие утилиты** (`src/utilities/`) не зависят от внешних сервисов.
5. **Модели БД** (`src/db/models.py`) и CRUD (`src/db/db_postgres.py`) доступны всем слоям.

---

### 4. NATS: темы и подписчики

| Тема | Издатель | Подписчик | Назначение |
|------|----------|-----------|------------|
| `yookassa` | FastAPI | Бот (broker_nats.py) | Вебхуки YooKassa |
| `gspread` | Бот | gspread_worker.py | Запись в Google Sheets |
| `gspread_failed` | gspread_worker.py | Бот (gspred_hl.py) | Ошибки записи |
| `schedule_sync_result` | gspread_worker.py | Бот (schedule_sync_hl.py) | Результаты выгрузки |
| `sales` | Бот | sales_worker.py | Рассылка сообщений |
| `sales_report` | sales_worker.py | Бот (sales_hl.py) | Отчёты о рассылках |

---

### 5. Развёртывание

- **Docker Compose профили:**
  - `migration` — только миграции Alembic
  - `bot` — Telegram-бот + NATS подписки
  - `all` — полный стек: бот, FastAPI, NATS, PostgreSQL, воркеры, nginx
- **nginx** — reverse proxy для FastAPI (порт 8443)
- **Хостинг:** Timeweb

> В профиле `all` обязательно поднимаются `gspread_worker` и `sales_worker` — без них NATS-задачи не будут обработаны.

---

### 6. Соглашения по разработке

#### 6.1. Работа с БД
- Всегда использовать `AsyncSession`.
- Новые методы доступа к данным добавлять в `src\db\db_postgres.py`.
- Модели описывать в `src\db\models.py` с использованием SQLAlchemy 2.0 style.
- Используй `lazy='raise'` для явной загрузки связанных сущностей (`joinedload`/`selectinload`).

#### 6.2. Обработка диалогов
- Использовать `ConversationHandler` из `python-telegram-bot`.
- Состояния (states) определять в модулях внутри `src\conv_hl\`.
- Бизнес-логику (обработку ввода) выносить в `src\handlers\`.

#### 6.3. Клавиатуры
- Для создания Inline-клавиатур использовать функции из `src\utilities\utl_kbd.py`.
- При добавлении кнопок "Назад" и "Отмена" использовать `add_btn_back_and_cancel`.

#### 6.4. Логирование
- Использовать именованные логгеры (например, `bot.reserve`, `bot.webhook`).
- Конфигурация логов находится в `src\log\logging_conf.py`.
- Стартовые middleware: `add_db_handlers_middleware`, `add_glob_on_off_middleware`, `add_user_status_middleware`, `add_reserve_check_middleware`, `add_tg_update_logging_middleware`.

#### 6.5. Работа с Google Sheets
- Все операции записи должны быть асинхронными через NATS (`gspread_worker.py`).
- Чтение данных (синхронизация) выполняется через `/update_*` команды.
- Путь к credentials: из `settings.sheets.credentials_path` или собирается из `CONFIG_PATH`. Scope: `https://www.googleapis.com/auth/spreadsheets`.
- Sheet IDs в `settings.yml`: `sheets.sheet_id_domik`, `sheets.sheet_id_cme`.
- Маппинг `RANGE_NAME` задаёт именованные вкладки/диапазоны: «Расписание», «Репертуар», «Клиентская база», «Заказные мероприятия», «Форматы ЗакМероп», «Лист ожидания», «Индив стоимости».
- Хелперы: `get_values`, `write_data_reserve`, `write_client_reserve`, `update_ticket_in_gspread`, `write_client_cme`, `write_client_list_waiting`, `update_cme_in_gspread`.

#### 6.6. YooKassa
- `create_param_payment(...)` (`src\api\yookassa_connect.py`) формирует запрос платежа; `payment_method_type` по умолчанию — `sbp`, тип подтверждения — `redirect` с `return_url=URL_BOT`.
- Обработка вебхука (`src\handlers\hooks\yookassa_hl.py`):
  - status `succeeded`: обновляет билеты в Google Sheets и PostgreSQL, удаляет inline-кнопки оплаты, уведомляет пользователя и постит в админский топик в зависимости от `metadata.command` (`reserve` или `studio`).
  - Предоплаченные счета определяются по `metadata.dashboardInvoiceOriginalNumber` и маршрутизируются в топик «Выездные мероприятия».
  - Используемые поля `metadata`: `message_id`, `chat_id`, `ticket_ids` (через `|`), `choose_schedule_event_ids` (через `|`), `command`.

#### 6.7. Handlers и команды
- Регистрация всех обработчиков централизована в `src\handlers\set_handlers.set_handlers`.
- Только для админов (через `custom_filters.filter_admin`): `/update_config`, `/send_approve_msg`, `/update_ticket`, `/log`, `/check_balance_on_timeweb`, `/topic`, `/topic_del`, `/global_on_off`, `/set_admin_info`, `/set_cme_admin_info`.
- Команды синхронизации данных из Google Sheets: `/update_base_ticket_data`, `/update_theater_event_data`, `/update_schedule_event_data`, `/update_spec_price`, `/update_cmf_data`, `/update_promotions`.
- `COMMAND_DICT` маппит имена команд на telegram-команды и подписи; при изменении — обновлять консистентно.
- Админские форумные топики: «Списки на показы», «Лист ожидания», «Выездные мероприятия», «Бронирования спектаклей», «Бронирования студия», «Изменения расписания».
- Команда выгрузки расписания: `/sync_schedule [event_id]` (только админы). Фиксирует срез накопленных правок, запрашивает подтверждение и публикует задачу в NATS `gspread`.
- При выгрузке проверяются конфликты со значениями в Google Таблице: конфликтующие сеансы не перезаписываются и требуют ручного разрешения.
- Обратный импорт `/update_schedule_event_data` защищает сеансы с несинхронизированными/конфликтными правками в боте от затирания.
- Пользователь может посмотреть свои билеты через `/tickets` (`src\handlers\profile_hl.py::show_tickets`).

#### 6.8. Timeweb
- Запрос: `GET https://api.timeweb.cloud/api/v1/account/finances` с `Authorization: Bearer <timeweb.token>`.
- Тесты (`test\test_timeweb.py`) ожидают: инстанс `Response`, `status_code == 200`, `finances.hours_left` — `int`. Требуется валидный токен в `settings.yml`. Интеграционные тесты гейтятся переменной окружения `TIMEWEB_TOKEN`.

#### 6.9. Правила именования
- Функции-обработчики: `choice_date`, `get_phone`, `handle_payment`.
- Функции утилиты: `utl_*`.
- Файлы диалогов: `*_conv_hl.py`.
- Файлы логики: `*_hl.py`.

#### 6.10. Конфигурация
- Настройки загружаются из `config\settings.yml` через `src\settings\config_loader.parse_settings()`. Можно переопределить через переменную окружения `CONFIG_PATH`.
- Обязательные ключи (pydantic-модели):
  - `bot`: `token`, `admin_group`, `developer_chat_id`
  - `timeweb`: `token`
  - `postgres`: `db_url` (SQLAlchemy DSN)
  - `sheets`: `credentials_path`, `sheet_id_domik`, `sheet_id_cme`
  - `yookassa`: `account_id`, `secret_key`, `payment_method_type`
- Runtime-константы — в `src\settings\settings.py` (ID чатов/админов, `COMMAND_DICT`, `RANGE_NAME` mapping, `nats_url`).

---

### 7. Команды разработки

#### Сборка и запуск через Docker Compose
- Запуск с профилем миграций:
  ```powershell
  docker compose --profile migration up -d --build
  ```
- Запуск всего стека с env-файлом:
  ```powershell
  docker compose --env-file config\.env --profile all up -d --build
  ```
- Запуск/остановка только бота:
  ```powershell
  docker compose --env-file config\.env --profile bot up -d
  docker compose --env-file config\.env --profile bot stop
  ```

#### Миграции Alembic
- Создание авто-миграции:
  ```powershell
  alembic -c "config\alembic.ini" revision --autogenerate -m "init"
  ```
- Применение миграций через compose:
  ```powershell
  docker compose --profile migration up -d
  ```
- Локально:
  ```powershell
  alembic -c "config\alembic.ini" upgrade head
  alembic -c "config\alembic.ini" downgrade base
  ```

#### Тесты
- Из корня проекта:
  ```powershell
  python -m pytest -q
  ```

#### NATS миграция
- Для автоматической синхронизации стрима и создания всех недостающих тем/консьюмеров:
  ```bash
  docker compose exec bot python -m api.nats_migrate
  ```

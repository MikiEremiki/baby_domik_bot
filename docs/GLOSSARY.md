# Словарь терминов проекта (Glossary)

> **Назначение:** Универсальный язык (ubiquitous language) для общения между разработчиком и AI-агентом. Все термины здесь — это те слова, которые мы используем одинаково в коде, в чате и в документации.
>
> **Обновляется:** интерактивно через `/grill-with-docs` и `/domain-modeling`.

---

## Основные сущности

| Термин | Описание |
|--------|----------|
| **User (Пользователь)** | Telegram-пользователь, взаимодействующий с ботом. |
| **Person (Персона)** | Профиль человека (имя, возрастная категория). Связан с `User`. Может быть `Adult` (Взрослый) или `Child` (Ребенок). |
| **TheaterEvent (Мероприятие)** | Описание спектакля или программы (название, возрастные ограничения, длительность). |
| **ScheduleEvent (Сеанс)** | Конкретный сеанс спектакля в расписании (дата, время, доступные места). |
| **BaseTicket (Шаблон билета)** | Определяет формат посещения (например, "1 взр + 1 реб") и стоимость. |
| **Ticket (Билет)** | Запись о бронировании конкретным пользователем на конкретный сеанс. |
| **ScheduleChange (Журнал изменений)** | Запись об атомарном создании или изменении сеанса (автор, источник, операция, снимки `before`/`after`, статус Telegram-отчёта и статус выгрузки в Google Sheets). |
| **ScheduleSyncRun (Запуск выгрузки)** | Запись об управляемом запуске выгрузки накопленных изменений расписания в Google Таблицу (UUID, инициатор, срез изменений, результаты по сеансам, статус доставки сводки). |

---

## Статусы билетов (`TicketStatus`)

| Термин | Описание |
|--------|----------|
| **CREATED** | Бронирование создано, ожидается оплата. |
| **PAID** | Оплата подтверждена платежной системой. |
| **APPROVED** | Подтверждено администратором или системой (места зафиксированы). |
| **REJECTED / CANCELED** | Отменено. |
| **REFUNDED** | Оформлен возврат. |

---

## Telegram-бот и python-telegram-bot

| Термин | Описание |
|--------|----------|
| **ConversationHandler** | Механизм `python-telegram-bot` для управления состоянием диалога с пользователем. Состояния определяются в `src\conv_hl\`, бизнес-логика — в `src\handlers\`. |
| **Handler (Обработчик)** | Функция, реагирующая на команду, callback или текст пользователя. Регистрация централизована в `src\handlers\set_handlers.py`. |
| **Inline Keyboard** | Клавиатура с кнопками под сообщением бота. Создаётся через `src\utilities\utl_kbd.py`. |
| **Middleware** | Промежуточный обработчик, выполняющийся до/после handler'а. Стартовые middleware: `add_db_handlers_middleware`, `add_glob_on_off_middleware`, `add_user_status_middleware`, `add_reserve_check_middleware`, `add_tg_update_logging_middleware`. |
| **Custom Filter** | Пользовательский фильтр для маршрутизации обновлений (например, `filter_admin` для админских команд). |

---

## NATS и FastStream

| Термин | Описание |
|--------|----------|
| **NATS** | Брокер сообщений для связи между FastAPI, Telegram-ботом и фоновыми воркерами. |
| **FastStream** | Фреймворк для работы с NATS в Python, используется для подписок и публикации. |
| **JetStream** | Персистентный слой NATS с именем `baby_domik` (max_msgs=100, max_age=7 days). |
| **Тема (Subject)** | Канал обмена сообщениями: `yookassa`, `gspread`, `gspread_failed`, `schedule_sync_result`, `sales`, `sales_report`. |
| **Durable Consumer** | Подписка NATS, сохраняющая состояние между перезапусками. |
| **Publisher (Издатель)** | Компонент, публикующий сообщения: FastAPI (вебхуки YooKassa), Gspread Pub, Sales Pub. |
| **Worker (Воркер)** | Фоновый процесс, подписанный на тему: Gspread Worker (запись в Google Sheets), Sales Worker (рассылки). |

---

## FastAPI и веб-интерфейс

| Термин | Описание |
|--------|----------|
| **FastAPI** | Веб-фреймворк для обработки вебхуков (YooKassa), авторизации (Telegram Login Widget) и отрисовки HTML-страниц. |
| **Webhook** | HTTP-колбэк от внешнего сервиса (YooKassa → `POST /yookassa`). |
| **Pydantic Schema** | Модель валидации данных API (`src\api\web\schemas.py`). |
| **Jinja2** | Шаблонизатор для HTML-страниц (`templates/`). |
| **Telegram Login Widget** | Авторизация на сайте через Telegram (`src\api\web\routes\auth.py`). |

---

## База данных

| Термин | Описание |
|--------|----------|
| **PostgreSQL** | Реляционная база данных для хранения пользователей, билетов, расписания и настроек. |
| **SQLAlchemy** | ORM для работы с БД, используется в асинхронном режиме (`AsyncSession`). Модели в `src\db\models.py`. |
| **Alembic** | Инструмент миграций БД, конфигурация в `config\alembic.ini`. |
| **Enum** | Перечисления (`src\db\enum.py`): `TicketStatus`, `PriceType`, `AgeType`, `CustomMadeStatus`, `GroupOfPeopleByDiscountType`. |

---

## Внешние интеграции

| Термин | Описание |
|--------|----------|
| **YooKassa** | Платёжная система. Создание платежа через `src\api\yookassa_connect.py`, обработка вебхука через `src\handlers\hooks\yookassa_hl.py`. |
| **Google Sheets** | Legacy / вспомогательное хранилище. Чтение через `/update_*` команды, запись асинхронно через NATS (`gspread_worker.py`). |
| **Timeweb** | API хостинга для проверки баланса (`src\api\timeweb.py`). |
| **gspread** | Библиотека для работы с Google Sheets API (v4). |

---

## Конфигурация и развёртывание

| Термин | Описание |
|--------|----------|
| **settings.yml** | Основной файл конфигурации (токены, пароли, пути). Загружается через `src\settings\config_loader.py`. |
| **CONFIG_PATH** | Переменная окружения, указывающая на директорию с `settings.yml` и `credentials.json`. |
| **Docker Compose** | Оркестрация контейнеров с профилями: `migration`, `bot`, `all`. |
| **nginx** | Reverse proxy для маршрутизации внешнего трафика на FastAPI. |
| **pytest** | Фреймворк тестирования, запуск из корня: `python -m pytest -q`. |

---

## Команды и администрирование

| Термин | Описание |
|--------|----------|
| **Админские команды** | `/update_config`, `/send_approve_msg`, `/update_ticket`, `/log`, `/check_balance_on_timeweb`, `/topic`, `/topic_del`, `/global_on_off`, `/set_admin_info`, `/set_cme_admin_info`, `/sync_schedule`. |
| **Команды синхронизации** | `/update_base_ticket_data`, `/update_theater_event_data`, `/update_schedule_event_data`, `/update_spec_price`, `/update_cmf_data`, `/update_promotions`. |
| **Forum Topics (Топики)** | Админские форумные топики: «Списки на показы», «Лист ожидания», «Выездные мероприятия», «Бронирования спектаклей», «Бронирования студия», «Изменения расписания». |
| **RANGE_NAME** | Маппинг именованных вкладок Google Sheets: «Расписание», «Репертуар», «Клиентская база», «Заказные мероприятия», «Форматы ЗакМероп», «Лист ожидания», «Индив стоимости». |

# Регрессионные заметки

> **Назначение:** Фиксирует исправленные баги, чтобы предотвратить регрессию при будущих изменениях.
> Обновляется автоматически при `/task-check --regression`.

---

## Активные

- **sales_hl.py** — `_safe_edit_message` делегирует в `utl_tg.safe_edit_text` / `safe_edit_caption` (исправлено 2026-11-09)
  - Что: Локальная функция `_safe_edit_message` в `sales_hl.py` переписана: вместо прямого try/except с `edit_message_text`/`edit_message_caption` теперь вызывает `safe_edit_text()` и `safe_edit_caption()` из `utl_tg.py`.
  - Почему важно: Унификация обработки `BadRequest: Message is not modified` через `utl_tg` — последний оставшийся дублирующий блок.
  - Как проверить: `/sales` → предпросмотр → «Запустить» / «Отменить» → сообщение редактируется без ошибки.
  - При будущих изменениях: При модификации `_safe_edit_message` проверять, что он делегирует в `utl_tg`, а не дублирует логику.

- **sales_hl.py** — `delete_message()` удалён из мастера `/sales`; переходы между шагами через `_show_step` (исправлено 2026-11-09)
  - Что: `delete_message()` убран из `pick_attach_theater`, `pick_theater`, `pick_scope` и `preview_action`. Переходы между шагами мастера теперь редактируют текущее сообщение через `_show_step()` с `step_msg_id`; при `Message to edit not found` отправляется новое сообщение с запоминанием ID.
  - Почему важно: Без этого `delete_message()` удалял сообщение, которое ещё не было заменено новым — Telegram API выбрасывал `Message to edit not found` при следующем callback. Баг проявлялся при выборе «Прикрепить спектакль» → «Да» → выбор спектакля.
  - Как проверить: `/sales` → тип 1 → «Прикрепить спектакль» → «Да» → выбор спектакля → шаг охвата отображается без ошибки. Возврат «Назад» из предпросмотра тоже без ошибки.
  - При будущих изменениях: При модификации переходов между шагами мастера `/sales` проверять, что `delete_message()` не используется, а новый шаг рендерится через `_show_step()`.

- **command_permission.py:137-139** — Callback ветка middleware выполняется первой с ранним return (исправлено 2026-10-18)
  - Что: В `check_command_permission` ветка `if update.callback_query:` стоит перед проверкой `effective_message.text`. Для callback-апдейта `effective_message` — это сообщение бота с кнопкой, у которого всегда есть текст. Без раннего return callback-ветка никогда не выполнялась.
  - Почему важно: Без этого middleware не проверяет права на callback-кнопки (`settings:*`, `acc|…`, `UP_*`). Пользователь без гранта мог нажать любую кнопку, если middleware не заблокировал. Хендлеры имеют собственную защиту, но второй слой из плана отсутствовал.
  - Как проверить: Пользователь без гранта на `settings:place` нажимает кнопку раздела → middleware блокирует с alert «У вас нет доступа».
  - При будущих изменениях: При модификации `check_command_permission` проверять, что callback-ветка остаётся первой и завершается `return`.

- **glob_usage_users.py:88-102** — raise ApplicationHandlerStop после сообщения о техработах (исправлено 2026-10-18)
  - Что: Раньше код использовал `return await reply_text(...)`, из-за чего `raise ApplicationHandlerStop` был недостижим. Теперь сообщение отправляется без `return`, затем обязательно `raise`. Для callback используется `answer`, для сообщения — `reply_text`. `effective_message=None` обработан.
  - Почему важно: Без этого режим техработ (`global_on_off` off) не блокировал клиентов. Пользователь видел сообщение о техработах, но апдейт доходил до хендлеров, и команды работали.
  - Как проверить: Выключить `global_on_off`, обычный пользователь отправляет `/start` → получает сообщение о техработах, команда не выполняется.
  - При будущих изменениях: При модификации `check_permissions` в glob_usage_users проверять, что после отправки сообщения всегда следует `raise ApplicationHandlerStop` без `return`.

- **glob_usage_users.py:29-53** — glob_usage_users решает через can(), без has_any_grant и is_privileged (исправлено 2026-10-18)
  - Что: Убраны вызовы `has_any_grant` и ранний выход `is_privileged`. Middleware парсит команду (callback-first, затем текст), получает entry через `get_command_entry()`, и если команда не public — проверяет `can()`. `can()` — единственная точка принятия решений: она проверяет root, super_admin, public и грант в БД.
  - Почему важно: Без этого `has_any_grant` делал лишний запрос к БД (can() тоже читает `user_command_access`), а `is_privileged` пропускал super_admin шире, чем `can()`, создавая расхождение логики.
  - Как проверить: Выключить `global_on_off`, пользователь с грантом `list` отправляет `/list` → команда работает через `can()`. Super_admin на `root_only` команде блокируется.
  - При будущих изменениях: При модификации `check_permissions` проверять, что `has_any_grant` и `is_privileged` не используются, а решение принимает `can()`.

- **permissions.py:88-90** — Fail-closed для неизвестных команд в can() (исправлено 2026-10-18)
  - Что: `can()` возвращает `False` для plain-команды, которой нет в `COMMAND_DICT` (кроме `ADMIN_ID`). Раньше неизвестные команды пропускались.
  - Почему важно: Без этого команда, которую забыли внести в `COMMAND_DICT`, стала бы доступна всем. Fail-closed — безопасная сторона ошибки. Тест полноты дополнительно гарантирует, что все зарегистрированные команды описаны.
  - Как проверить: Пользователь без гранта отправляет `/unknown_cmd` → middleware блокирует. Root (`ADMIN_ID`) проходит.
  - При будущих изменениях: При модификации `can()` проверять, что ветка `entry is None` возвращает `False` для непривилегированных пользователей.

- **permissions.py:68-73** — root_only проверяет ADMIN_ID, а не is_privileged (исправлено 2026-10-18)
  - Что: `root_only` команды доступны только `ADMIN_ID`. Super_admin (`SUPERADMIN_CHAT_ID`) получает все команды, кроме `root_only`. Раньше `is_privileged` включал и super_admin, и root, и технические команды были доступны обоим.
  - Почему важно: Без этого super_admin мог выполнить технические команды (`clean_bd`, `update_config` и т.п.), которые должны быть только у root.
  - Как проверить: Super_admin пытается выполнить `/clean_bd` → `can()` возвращает `False`. Root выполняет ту же команду → `True`.
  - При будущих изменениях: При модификации `can()` проверять, что `root_only` ветка использует `user_id in ADMIN_ID`, а не `is_privileged`.

- **command_mgmt_hl.py:188-204** — Производный грант settings в _apply_toggle (исправлено 2026-10-18)
  - Что: При выдаче первого `settings:*` раздела автоматически выдаётся команда `settings`. При снятии последнего раздела автоматически снимается `settings`. Команда `settings` исключена из `grantable_items` — отдельного тоггла в UI нет.
  - Почему важно: Без этого пользователь с `settings:place` не мог открыть `/settings`, потому что команда `settings` гейтится отдельно. Автовыдача связывает команду и разделы.
  - Как проверить: Выдать пользователю `settings:schedule_event` через UI → в БД появляются две записи: `settings:schedule_event` и `settings`. Снять последний раздел → `settings` снимается.
  - При будущих изменениях: При модификации `_apply_toggle` проверять, что блок `if item.key.startswith('settings:')` остаётся и обрабатывает оба направления.

- **command_permission.py:57-59** — access callback сопоставляется только при intent_id is None (исправлено 2026-10-18)
  - Что: В `_callback_to_command` условие `access` изменено на `intent_id == ACCESS_INTENT_ID or (intent_id is None and clean_data == ACCESS_ENTRY_CALLBACK)`. Чужие intent'ы вроде `other|access` больше не сопоставляются с `settings:database`.
  - Почему важно: Без этого любой callback с суффиксом `|access` (например `other|access`) ошибочно открывал экран управления доступом, минуя проверку прав.
  - Как проверить: Callback `other|access` → middleware не находит команду и блокирует. Callback `access` без intent → корректно открывает `settings:database`.
  - При будущих изменениях: При модификации `_callback_to_command` проверять, что `access` сопоставляется только при `intent_id is None` или `intent_id == ACCESS_INTENT_ID`.

- **utl_func.py:102-159** — set_menu определяет членство в админ-группе через get_chat_administrators (исправлено 2026-10-18)
  - Что: `_set_user_menus` получает администраторов каждой группы через `bot.get_chat_administrators(group_chat_id)`, а не сравнивает `user_id in ADMIN_GROUP_ID` (chat_id ≠ user_id). Per-user меню вынесено в отдельный хелпер.
  - Почему важно: Без этого `user_id in ADMIN_GROUP_ID` почти никогда не выполнялся, так как сравнивался ID пользователя со списком ID чатов. Администраторы группы не получали объединённое меню (admin_group + гранты).
  - Как проверить: Администратор группы с грантом в БД → при старте бота получает per-user меню с admin_group командами + команды по грантам.
  - При будущих изменениях: При модификации `_set_user_menus` проверять, что членство в админ-группе определяется через `bot.get_chat_administrators()`, а не через `user_id in ADMIN_GROUP_ID`.

- **utl_func.py:_set_user_menus** — Администраторы группы без грантов полагаются на scope-меню (известное ограничение, зафиксировано 2026-10-18)
  - Что: `_set_user_menus` итерирует только пользователей из `list_users_with_access()` — тех, у кого есть гранты в БД. Администратор группы без грантов не получает per-user меню, но получает команды через Telegram scope-механизм: `BotCommandScopeChatAdministrators` (admin_group команды) + `BotCommandScopeChat` (sub_admin команды) + `BotCommandScopeDefault` (публичные).
  - Почему важно: Это ожидаемое поведение, а не баг. Telegram объединяет меню из всех применимых scope. Админ группы без грантов видит все admin_group-команды через scope, per-user меню ему не нужно.
  - Как проверить: Администратор группы без грантов в БД → открывает меню бота → видит public + sub_admin + admin_group команды.
  - При будущих изменениях: При модификации `_set_user_menus` проверять, что scope-меню для админов группы (`BotCommandScopeChatAdministrators`) остаётся настроенным.

- **utl_func.py:_set_user_menus** — Сбой get_chat_administrators обрабатывается gracefully (известное ограничение, зафиксировано 2026-10-18)
  - Что: `bot.get_chat_administrators(group_chat_id)` может выбросить исключение, если бот не в группе, заблокирован или группа удалена. Исключение ловится, логируется, цикл продолжается с следующей группой.
  - Почему важно: Сбой влияет только на админов проблемной группы с грантами — они получают per-user меню только с командами по грантам, без admin_group-команд. Scope-меню для этой группы тоже может не сработать, если бот не в группе — это проблема интеграции, а не кода. Остальные группы работают.
  - Как проверить: Удалить бота из одной группы в `ADMIN_GROUP_ID` → перезапустить бота → админы этой группы с грантами получают неполное меню, остальные группы работают.
  - При будущих изменениях: При модификации `_set_user_menus` проверять, что исключение из `get_chat_administrators` ловится на уровне каждой группы, а не прерывает весь цикл.

- **reserve_check.py:61-63** — reserve_check больше не пропускает is_privileged и has_any_grant (исправлено 2026-10-18)
  - Что: Убраны ранние выходы для `is_privileged` и `has_any_grant`. Все пользователи теперь проходят проверку таймаута и актуальности данных. Пропуск для админ-группы через `config.bot.admin_group` остаётся.
  - Почему важно: Гранты дают доступ к командам, но не должны освобождать от проверки актуальности бронирования. Пользователь с грантом должен получать свежее расписание.
  - Как проверить: Пользователь с грантом начинает бронирование, расписание обновляется → middleware сбрасывает сессию и просит начать заново.
  - При будущих изменениях: При модификации `check_reserve_actual_middleware` проверять, что `is_privileged` и `has_any_grant` не используются.

- **auto_sending_hl.py:1252** — `group_tickets_by_user()` для группировки билетов в `_manual_send_by_session` (исправлено 2026-10-16)
  - Что: Заменён ручной цикл группировки билетов на общую функцию `group_tickets_by_user()`, которая пропускает билеты без `user`
  - Почему важно: Без этого бот падает с `AttributeError: 'NoneType' object has no attribute 'user_id'` при ручной рассылке, если есть билеты без привязки Telegram-пользователя
  - Как проверить: Ручная рассылка по сеансу с билетами где `user=None` → рассылка должна завершиться без ошибки, пропущенные билеты должны быть в отчёте
  - При будущих изменениях: При модификации `_manual_send_by_session` проверять, что `group_tickets_by_user()` используется, а не ручной цикл

- **auto_sending_hl.py:1209** — Guard clause для билета без пользователя в `_manual_send_by_ticket` (исправлено 2026-10-16)
  - Что: Добавлена проверка `if ticket.user is None` перед обращением к `user.chat_id`
  - Почему важно: Без этого бот падает с `AttributeError` при ручной рассылке по ID билета, если билет куплен без привязки Telegram-пользователя
  - Как проверить: Ручная рассылка по ID билета с `user=None` → должно вернуть сообщение об ошибке, не падать
  - При будущих изменениях: При модификации `_manual_send_by_ticket` проверять, что guard clause для `ticket.user is None` сохраняется

- **worker_jobs.py:84** — `group_tickets_by_user()` для группировки билетов в `send_reminder` (исправлено 2026-10-16)
  - Что: Заменён ручной цикл группировки билетов на общую функцию `group_tickets_by_user()`, которая пропускает билеты без `user`
  - Почему важно: Без этого воркер падает с `AttributeError` при отправке напоминаний, если есть билеты без привязки Telegram-пользователя
  - Как проверить: Отправка напоминаний для сеанса с билетами где `user=None` → воркер должен завершиться без ошибки
  - При будущих изменениях: При модификации `send_reminder` проверять, что `group_tickets_by_user()` используется, а не ручной цикл

- **utilities/utl_tg.py** — `is_not_modified()` центральный хелпер для `BadRequest: Message is not modified` (исправлено 2026-11-09)
  - Что: Все 11 дубликатов обработки «Message is not modified» в 6 файлах (`auto_sending_hl.py`, `command_mgmt_hl.py`, `support_hl.py`, `reserve/choice.py`, `reserve/input.py`, `sales_hl.py`) переведены на `is_not_modified()` из `utl_tg.py`. Локальные хелперы `_safe_edit_message_text()` и `_safe_edit_message_reply_markup()` в `reserve/input.py` продолжают работать, но используют `is_not_modified()` из `utl_tg.py`.
  - Почему важно: Дублирование логики обработки одной и той же ошибки в 11 местах создаёт риск расхождения поведения при будущих изменениях. Единая функция `is_not_modified()` гарантирует консистентность.
  - Как проверить: `grep 'Message is not modified' src/` — строка встречается только в `utl_tg.py` и в docstring `_edit()` в `command_mgmt_hl.py`.
  - При будущих изменениях: При добавлении нового обработчика `edit_message_*` с `BadRequest` проверять, что используется `is_not_modified()` из `utl_tg.py`, а не дублирующая проверка по подстроке.

- **utl_text.py:check_phone_number** — Инверсия return-значений: True = валиден, False = невалиден (исправлено 2026-11-08)
  - Что: `check_phone_number` теперь возвращает `True` для валидного номера и `False` для невалидного. Раньше логика была инвертирована — `True` означал невалидность. Все 4 места вызова (`booking.py`, `common_hl.py`, `profile_hl.py`) обновлены: `if check_phone_number(phone):` → `if not check_phone_number(phone):`.
  - Почему важно: Контринтуитивное имя функции с инвертированным return-значением ведёт к обратному поведению при любом новом использовании. Без обновления всех мест вызова валидация телефона на сайте и в боте сломается — невалидные номера будут приниматься, а валидные — отклоняться.
  - Как проверить: Ввести валидный номер `9123456789` → `check_phone_number()` возвращает `True`, ветка `if not check_phone_number()` не срабатывает. Ввести невалидный номер `123` → возвращает `False`, ветка `if not` срабатывает, ошибка показана.
  - При будущих изменениях: При модификации `check_phone_number` или добавлении нового вызова проверять, что `True` = валиден, и условие ошибки использует `if not check_phone_number(phone):`.

- **utl_ticket.py:165-166** — Телефон билета читается из `client_data['phone']`, не из `buyer_phone` (исправлено 2026-11-08)
  - Что: При создании билетов в боте (`create_tickets()`) `buyer_phone` берётся из `reserve_user_data['client_data']['phone']`, а не из несуществующего ключа `buyer_phone`. Добавлена защита `try/except ValueError` на случай некорректного значения.
  - Почему важно: Без этого `Ticket.phone` всегда был `None` для билетов из бота, так как ключ `buyer_phone` нигде не заполнялся. Снимок телефона при покупке — ключевое требование тикета 03.
  - Как проверить: Создать билет через бота с валидным телефоном в `client_data` → `ticket.phone` должен быть равен номеру (int). Без `client_data` → `phone = None`.
  - При будущих изменениях: При модификации `create_tickets()` проверять, что телефон читается из `client_data['phone']`, а не из `buyer_phone`.

- **reserve_admin_hl.py:execute_ticket_migration** — Перенос билета одной транзакцией БД (исправлено 2026-11-08)
  - Что: `execute_ticket_migration` выполняет изменения БД (статус → MIGRATED, новый билет, привязка) в одной транзакции с `auto_commit=False`. Google Sheets обновляется только после успешного commit. При ошибке БД — rollback, Google Sheets не затрагивается. Функция разбита на `_migrate_ticket_db()` и `_sync_gspread_migration()`.
  - Почему важно: Без одной транзакции при ошибке после commit части изменений (например, статус MIGRATED без нового билета) оставят БД в неконсистентном состоянии. Разделение на подфункции предотвращает Long Method и упрощает тестирование.
  - Как проверить: Перенести билет → старый статус MIGRATED, новый CREATED, phone/email/source скопированы. При ошибке создания нового билета → старый остаётся в исходном статусе.
  - При будущих изменениях: При модификации `execute_ticket_migration` проверять, что БД-изменения в одной транзакции, Google Sheets — после commit, rollback при ошибке БД.

- **booking_form.html:showToast** — XSS-защита: textContent вместо innerHTML (исправлено 2026-11-08)
  - Что: `showToast()` использует `textContent` вместо `innerHTML` для отображения сообщения об ошибке. Добавление ребёнка (`addEntry()`) использует `createElement`/`setAttribute`/`textContent` вместо `innerHTML`.
  - Почему важно: `innerHTML` с пользовательским вводом (телефон в сообщении об ошибке) позволяет инъекцию HTML/JS. Хотя `TemplateResponse` экранирует серверную сторону, клиентский JS с `innerHTML` — прямой XSS-вектор.
  - Как проверить: Ввести `<script>alert(1)</script>` в поле телефона → сообщение об ошибке отобразит текст как plain text, скрипт не выполнится.
  - При будущих изменениях: При модификации `showToast` или `addEntry` проверять, что `innerHTML` не используется с динамическим контентом.

- **models.py:Ticket.phone** — Тип phone — BIGINT, не INTEGER (исправлено 2026-11-08)
  - Что: `Ticket.phone` использует `BigInteger().with_variant(Integer, 'sqlite')`. 10-значные телефоны (до 9 999 999 999) превышают диапазон 32-bit INTEGER (max ~2.1 млрд). Миграция rev_31 создаёт колонку `BIGINT`.
  - Почему важно: Без этого вставка телефона `9200199870` (и большинства российских номеров) упадёт с `value is out of range for type integer`. Backfill и создание билетов будут ломаться.
  - Как проверить: Создать билет с телефоном `9200199870` → запись успешна, `phone = 9200199870`. Проверить тип колонки: `SELECT data_type FROM information_schema.columns WHERE column_name = 'phone'` → `bigint`.
  - При будущих изменениях: При модификации `Ticket.phone` проверять, что тип — `BigInteger`, а не `Integer`.

- **profile_hl.py / tickets_admin_conv_hl.py** — Фильтр «Актуальные» использует `datetime.now(timezone.utc)`, не `datetime.now()` (исправлено 2026-11-09)
  - Что: Сравнение `se.datetime_event > datetime.now()` заменено на `datetime.now(timezone.utc)`. `datetime_event` в PostgreSQL — `TIMESTAMP WITH TIME ZONE`, SQLAlchemy возвращает aware datetime. Сравнение с naive `datetime.now()` выбрасывает `TypeError: can't compare offset-naive and offset-aware datetimes`.
  - Почему важно: Без этого фильтр «Актуальные/Все» в `/tickets` и `/tickets_admin` полностью ломается — бот падает с `TypeError` при попытке показать список билетов.
  - Как проверить: Открыть `/tickets` или `/tickets_admin` → список билетов отображается без ошибки. Переключить фильтр «Все» → список обновляется.
  - При будущих изменениях: При работе с `datetime_event` или любыми `TIMESTAMP WITH TIME ZONE` полями проверять, что сравнение использует `datetime.now(timezone.utc)`.

- **profile_hl.py** — `edit_message_text` с `transform_html` entities падает, нужно `parse_mode='HTML'` (исправлено 2026-11-09)
  - Что: `edit_message_text(res.text, entities=res.entities, parse_mode=None)` заменён на `edit_message_text(text, parse_mode='HTML')`. `transform_html` (Sulguk) возвращает `MessageEntity` объекты, которые несовместимы с `edit_message_text` при `parse_mode=None` — Telegram API выбрасывает `BadRequest`.
  - Почему важно: Без этого фильтр «Все/Актуальные» в `/tickets` отправляет новое сообщение вместо редактирования текущего. Пользователь видит дублирующиеся сообщения, а не обновлённый список.
  - Как проверить: Нажать «Все» в `/tickets` → текущее сообщение редактируется, список обновляется. Новое сообщение не создаётся.
  - При будущих изменениях: При использовании `edit_message_text` с HTML-контентом проверять, что используется `parse_mode='HTML'`, а не `entities` от `transform_html`.

- **profile_hl.py** — `send_action(TYPING)` инвалидирует callback, `edit_message_text` падает (исправлено 2026-11-09)
  - Что: `send_action(ChatAction.TYPING)` больше не вызывается при `callback_query` в `show_tickets`. `send_action` сбрасывает callback-контекст, `edit_message_text` падает в `except`, и код идёт по ветке `send_message` — создаётся новое сообщение.
  - Почему важно: Без этого нажатие «Все» в `/tickets` создаёт новое сообщение вместо редактирования. Проблема была незаметна при команде (send_action там полезен), но критична при callback.
  - Как проверить: Нажать «Все» в `/tickets` → сообщение редактируется на месте. `send_action` вызывается только при `page` и `toggle_filter` в `tickets_callback` (до `show_tickets`), не внутри `show_tickets` при callback.
  - При будущих изменениях: При добавлении `send_action` в callback-обработчики проверять, что он не вызывается между `callback_query` и `edit_message_text`.

- **profile_hl.py** — `init_conv_hl_dialog` при callback стирает user_data (исправлено 2026-11-09)
  - Что: `init_conv_hl_dialog` вызывается только при `not update.callback_query`. Для callback-запросов `effective_message` всегда установлен (`callback_query.message`), поэтому проверка `effective_message is not None` не работала. `clean_context` внутри `init_conv_hl_dialog` стирал `tickets_relevant_filter` (сбрасываясь на `True` — актуальные) и `reserve_user_data['back']` (ломая кнопку «Назад»).
  - Почему важно: Без этого фильтр «Все» в `/tickets` сбрасывался обратно на «Актуальные», а кнопка «Назад» переставала работать. Правильная проверка — `not update.callback_query`.
  - Как проверить: Нажать «Все» в `/tickets` → список показывает все билеты кроме CANCELED. Нажать «Назад» из детали билета → возврат к списку.
  - При будущих изменениях: При вызове `init_conv_hl_dialog` или `clean_context` в callback-обработчиках проверять, что используется `not update.callback_query`, а не `effective_message is not None`.

- **tickets_admin_conv_hl.py** — `selectinload` для `user.tickets` предотвращает `MissingGreenlet` (исправлено 2026-11-09)
  - Что: Доступ к `user.tickets` (lazy relationship SQLAlchemy 2.0) теперь через `selectinload`. `select(User).options(selectinload(User.tickets))` загружает билеты eagerly. Без этого `user.tickets` пытался загрузиться вне async session context с `MissingGreenlet`.
  - Почему важно: Без этого поиск по пользователю и кнопка «Билеты покупателя» в `/tickets_admin` падают с `sqlalchemy.exc.MissingGreenlet`.
  - Как проверить: `/tickets_admin` → «По пользователю» → ввод `@username` → список билетов пользователя. Карточка билета → «Билеты покупателя» → список всех билетов.
  - При будущих изменениях: При доступе к relationship (`user.tickets`, `ticket.people`) в async session проверять, что используется `selectinload` или `joinedload`.

- **tickets_admin_conv_hl.py / profile_hl.py** — `\n` в тексте через `transform_html` заменён на `<br>` (исправлено 2026-11-09)
  - Что: Все `\n` в текстах, передаваемых через `transform_html` (Sulguk), заменены на `<br>`. `\n` не является HTML-тегом и игнорируется Telegram API при `parse_mode='HTML'`/`parse_mode=None` с Sulguk entities. `format_ticket_contacts` добавлен параметр `html=True` для `<br>` разделителей.
  - Почему важно: Без этого контакты и примечания билетов отображаются в одну строку без переносов. «Источник: Бот Покупатель: @user Телефон: +7... Email: ...» — всё слито.
  - Как проверить: Карточка билета в `/tickets_admin` → контакты на отдельных строках. Примечание с переносами → переносы видны.
  - При будущих изменениях: При использовании `transform_html` проверять, что `\n` заменён на `<br>`. При использовании `format_ticket_contacts` с `transform_html` передавать `html=True`.

- **tickets_admin_conv_hl.py** — Примечание при дополнении через один `\n`, не `\n\n` (исправлено 2026-11-09)
  - Что: В `handle_notes_input` разделитель между старым и новым текстом при режиме «Дополнить» изменён с `\n\n` на `\n`.
  - Почему важно: Без этого каждое дополнение примечания добавляло пустую строку, что визуально удваивало отступ.
  - Как проверить: Открыть билет в `/tickets_admin` → «Примечание» → «Дополнить» → ввести текст → новое примечание приклеено через один перенос строки.
  - При будущих изменениях: При модификации `handle_notes_input` проверять, что разделитель — `\n`.

- **utl_ticket.py** — `format_ticket_contacts` с параметром `html` для Sulguk совместимости (исправлено 2026-11-09)
  - Что: Добавлен параметр `html` (по умолчанию `False`). При `html=True` разделитель `<br>` вместо `\n`. Вызовы с `transform_html` используют `html=True`, остальные — `\n`.
  - Почему важно: Без этого контакты в админской карточке билета (где используется `transform_html`) отображались в одну строку. Вызовы без `transform_html` (migration_admin, sub_hl) продолжают работать с `\n`.
  - Как проверить: `/tickets_admin` карточка билета → контакты на отдельных строках. `/migration_admin` → контакты также корректны.
  - При будущих изменениях: При использовании `format_ticket_contacts` с `transform_html` передавать `html=True`.

---

## Архив

(устаревшие заметки после подтверждения стабильности)

---

## Формат заметки

```markdown
### [Дата] — [Краткое описание бага]

- **Файл:** `path/to/file.py:123`
- **Что:** Описание исправления
- **Почему важно:** Без этого [последствие]
- **Как проверить:** [шаги воспроизведения]
- **При будущих изменениях:** [что проверять]
```

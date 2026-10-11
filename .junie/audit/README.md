# Система аудитов проекта

Навигатор по файлам системы аудитов для AI-агента Junie.

---

## 📋 Шаблоны аудитов

13 чек-листов в [`checklists/`](checklists/) — эталоны для проверки, не меняются.

| # | Аудит | Приоритет |
|---|-------|-----------|
| 01 | [Безопасность](checklists/01_SECURITY_AUDIT.md) | 🔴 |
| 02 | [Тестовое покрытие](checklists/02_TEST_COVERAGE_AUDIT.md) | 🔴 |
| 03 | [Производительность](checklists/03_PERFORMANCE_AUDIT.md) | 🔴 |
| 04 | [Типизация](checklists/04_TYPE_HINTS_AUDIT.md) | 🟡 |
| 05 | [API-дизайн](checklists/05_API_DESIGN_AUDIT.md) | 🟡 |
| 06 | [Frontend-архитектура](checklists/06_FRONTEND_ARCHITECTURE_AUDIT.md) | 🟡 |
| 07 | [Обработка ошибок](checklists/07_ERROR_HANDLING_AUDIT.md) | 🟡 |
| 08 | [Документирование](checklists/08_DOCUMENTATION_AUDIT.md) | 🟢 |
| 09 | [Зависимости](checklists/09_DEPENDENCY_AUDIT.md) | 🟢 |
| 10 | [Конфигурация](checklists/10_CONFIGURATION_AUDIT.md) | 🟢 |
| 11 | [i18n](checklists/11_I18N_AUDIT.md) | 🟢 |
| 12 | [SOLID-принципы](checklists/12_SOLID_AUDIT.md) | 🟢 |
| 13 | [Telegram UI](checklists/13_TELEGRAM_UI_AUDIT.md) | 🟡 |

---

## 📊 Отчёты и статистика

- [`reports/`](reports/) — отчёты по задачам и аудиторам (создаются при каждом `/task-check` и `/audit`)
- [`STATISTICS.md`](STATISTICS.md) — сводная статистика по всем отчётам
- [`REPORT_TEMPLATE.md`](REPORT_TEMPLATE.md) — шаблон отчёта

---

## ⚡ Скиллы Junie

### Проверка задач

| Команда | Назначение |
|---------|------------|
| `/task-check` | Мини-аудит задачи: DRY, edge-кейсы, регрессии, рекомендация плана |
| `/task-check --full` | Полный аудит для крупных задач |
| `/task-check --regression` | Фиксация исправленного бага |

### Независимые аудиты проекта

| Команда | Назначение |
|---------|------------|
| `/audit [тип]` | Проверка всего проекта по шаблону из `checklists/` |
| `/audit [тип] --path путь` | Проверка части проекта (папки/файла) |

**Примеры:**

```
/audit solid                    # SOLID-аудит всего проекта
/audit security --path src/api/ # Безопасность только API
/audit type-hints --path src/handlers/  # Типизация хендлеров
```

**Доступные типы:** `security`, `test-coverage`, `performance`, `type-hints`, `api-design`, `frontend`, `error-handling`, `documentation`, `dependency`, `configuration`, `i18n`, `solid`, `telegram-ui`

**Планы из отчётов:** После аудита Junie предложит создать план устранения в `.junie/plans/fix-audit-[тип].md`. Вы сможете корректировать план перед выполнением.

### Управление сессиями

| Команда | Назначение |
|---------|------------|
| `/session-check` | Новая сессия или продолжить |

### Синхронизация отчётов

| Команда | Назначение |
|---------|------------|
| `/audit-sync` | Проверка актуальности отчётов против кода: сместились строки, код переехал, сигнатура изменилась |
| `/audit-conflicts` | Проверка отчётов на конфликты между собой: дубликаты, противоречия, пересечения |

**Когда использовать:**
- `/audit-sync` — после крупного рефакторинга, чтобы убедиться, что отчёты соответствуют текущему коду
- `/audit-conflicts` — перед созданием плана устранения, чтобы отчёты не противоречили друг другу

---

## 📚 Справочники

- [`terms/AUDIT_TYPES.md`](terms/AUDIT_TYPES.md) — каталог всех видов аудитов
- [`terms/REFACTORING_TYPES.md`](terms/REFACTORING_TYPES.md) — виды рефакторингов

---

## 📁 Рабочие файлы

| Файл | Назначение |
|------|------------|
| [REGRESSIONS.md](REGRESSIONS.md) | Фиксация исправленных багов |
| [PROJECT_AUDIT_TEMPLATE.md](PROJECT_AUDIT_TEMPLATE.md) | Шаблон для переноса на другой проект |

---


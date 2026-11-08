-- 01_backfill_ticket_source.sql
-- Перенос исторических данных: заполнение tickets.source по маркерам в notes.
-- Идемпотентен: повторный запуск безопасен.
-- Выполнить после: alembic upgrade head (rev_31 — добавление колонки tickets.source).

BEGIN;

-- Таблица для отслеживания ручных миграций (создаётся самими скриптами)
CREATE TABLE IF NOT EXISTS manual_migrations (
    migration_name TEXT PRIMARY KEY
);

-- Backfill: классификация исторических записей
UPDATE tickets
SET source = (CASE
    WHEN notes LIKE '%Сайт:%' THEN 'website'
    WHEN notes LIKE '%Web booking%' THEN 'website'
    WHEN notes LIKE '%Website booking%' THEN 'website'
    WHEN notes LIKE '%website%' THEN 'website'
    ELSE 'bot'
END)::ticket_source;

-- Маркер выполнения
INSERT INTO manual_migrations (migration_name)
VALUES ('01_backfill_ticket_source')
ON CONFLICT (migration_name) DO NOTHING;

COMMIT;

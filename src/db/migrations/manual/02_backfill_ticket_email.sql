-- 02_backfill_ticket_email.sql
-- Перенос email из notes в отдельную колонку tickets.email.
-- Идемпотентен: повторный запуск безопасен.
-- Выполнить после: alembic upgrade head (rev_31 — добавление колонок tickets.source и tickets.email).

BEGIN;

-- Таблица для отслеживания ручных миграций
CREATE TABLE IF NOT EXISTS manual_migrations (
    migration_name TEXT PRIMARY KEY
);

-- Извлекаем email из notes для билетов, созданных через сайт.
-- Формат notes: "Сайт: user@example.com\nPromo: None"
-- Для билетов бота (без маркера "Сайт:") ставим NULL.
UPDATE tickets
SET email = CASE
    WHEN notes LIKE '%Сайт:%' THEN
        TRIM(SPLIT_PART(SPLIT_PART(notes, 'Сайт:', 2), E'\n', 1))
    WHEN notes LIKE '%Web booking.%' THEN
        TRIM(SPLIT_PART(SPLIT_PART(notes, 'Web booking.', 2), E'\n', 1))
    ELSE NULL
END
WHERE email IS NULL;

-- Приводим к нижнему регистру
UPDATE tickets
SET email = LOWER(email)
WHERE email IS NOT NULL;

-- Маркер выполнения
INSERT INTO manual_migrations (migration_name)
VALUES ('02_backfill_ticket_email')
ON CONFLICT (migration_name) DO NOTHING;

COMMIT;

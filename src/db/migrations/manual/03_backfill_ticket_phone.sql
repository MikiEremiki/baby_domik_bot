-- 03_backfill_ticket_phone.sql
-- Перенос телефона из PersonTicket -> Person -> Adult в tickets.phone (INTEGER).
-- Идемпотентен: повторный запуск безопасен.
-- Выполнить после: alembic upgrade head (rev_31 — добавление колонки tickets.phone INTEGER).
--
-- Логика:
-- 1. Для каждого билета ищем связанные Person через people_tickets.
-- 2. Из Person ищем Adult (взрослых) с phone.
-- 3. Если найден ровно один уникальный корректный номер (^9[0-9]{9}$) — записываем его.
-- 4. Если неоднозначно (несколько разных номеров) или нет взрослых с телефоном — ставим NULL.

BEGIN;

-- Таблица для отслеживания ручных миграций
CREATE TABLE IF NOT EXISTS manual_migrations (
    migration_name TEXT PRIMARY KEY
);

-- Обновляем phone только для билетов, где он ещё не установлен.
UPDATE tickets
SET phone = sub.unique_phone
FROM (
    SELECT
        pt.ticket_id,
        -- Если ровно один уникальный корректный номер — берём его как INTEGER, иначе NULL
        CASE
            WHEN COUNT(DISTINCT a.phone) = 1
                 AND MAX(a.phone) ~ '^9[0-9]{9}$'
            THEN CAST(MAX(a.phone) AS INTEGER)
            ELSE NULL
        END AS unique_phone
    FROM people_tickets pt
    JOIN people p ON p.id = pt.person_id
    JOIN adults a ON a.person_id = p.id
    GROUP BY pt.ticket_id
) sub
WHERE tickets.id = sub.ticket_id
  AND tickets.phone IS NULL
  AND sub.unique_phone IS NOT NULL;

-- Маркер выполнения
INSERT INTO manual_migrations (migration_name)
VALUES ('03_backfill_ticket_phone')
ON CONFLICT (migration_name) DO NOTHING;

COMMIT;

-- 04_migrate_update_ticket_grant.sql
-- Перенос грантов update_ticket → tickets_admin в user_command_access.
-- Идемпотентен: повторный запуск безопасен.

BEGIN;

-- Обновление существующих грантов
UPDATE user_command_access
SET command = 'tickets_admin'
WHERE command = 'update_ticket';

-- Маркер выполнения
INSERT INTO manual_migrations (migration_name)
VALUES ('04_migrate_update_ticket_grant')
ON CONFLICT (migration_name) DO NOTHING;

COMMIT;

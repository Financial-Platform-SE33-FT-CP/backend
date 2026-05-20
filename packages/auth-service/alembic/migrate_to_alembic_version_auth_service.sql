-- One-time migration: auth-service now uses table "alembic_version_auth_service" instead of "alembic_version".
-- Run this ONCE on each shared PostgreSQL database BEFORE you run "alembic upgrade head"
-- with the updated env.py (or immediately after, if upgrade has not been run yet).
--
-- If you skip this while the old "alembic_version" row still only tracked auth,
-- the next auth upgrade may try to re-apply migrations from scratch and fail.

CREATE TABLE IF NOT EXISTS alembic_version_auth_service (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_auth_service_pkc PRIMARY KEY (version_num)
);

INSERT INTO alembic_version_auth_service (version_num)
SELECT a.version_num
FROM alembic_version AS a
WHERE EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'alembic_version'
)
  AND NOT EXISTS (SELECT 1 FROM alembic_version_auth_service)
LIMIT 1;

-- Optional cleanup (only when you are sure "alembic_version" is no longer needed):
-- DELETE FROM alembic_version;
-- DROP TABLE alembic_version;

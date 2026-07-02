-- Add the admin role flag to users (Postgres dialect).
-- Canonical for production; the SQLite test schema is built from the ORM models.

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin boolean NOT NULL DEFAULT false;

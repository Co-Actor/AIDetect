-- Auth + sharing schema (Postgres dialect).
-- Canonical for production; the SQLite test schema is built from the ORM models.

CREATE TABLE IF NOT EXISTS users (
    id              uuid PRIMARY KEY,
    email           text NOT NULL,
    name            text,
    password_hash   text,
    google_sub      text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email_lower ON users (lower(email));
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_google_sub ON users (google_sub)
    WHERE google_sub IS NOT NULL;

CREATE TABLE IF NOT EXISTS detections (
    id              uuid PRIMARY KEY,
    user_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    input_text      text NOT NULL,
    result_json     jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_detections_user_id ON detections (user_id);

CREATE TABLE IF NOT EXISTS share_links (
    token           text PRIMARY KEY,
    detection_id    uuid NOT NULL REFERENCES detections (id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    trial_used      integer NOT NULL DEFAULT 0,
    trial_limit     integer NOT NULL DEFAULT 3,
    revoked         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_share_links_detection_id ON share_links (detection_id);
CREATE INDEX IF NOT EXISTS ix_share_links_user_id ON share_links (user_id);

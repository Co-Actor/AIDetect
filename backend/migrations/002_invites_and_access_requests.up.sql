-- Invite-only registration schema (Postgres dialect).
-- Canonical for production; the SQLite test schema is built from the ORM models.

CREATE TABLE IF NOT EXISTS invitations (
    id              uuid PRIMARY KEY,
    email           text NOT NULL,
    token           text NOT NULL,
    status          text NOT NULL DEFAULT 'pending',
    invited_by      uuid,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz,
    accepted_at     timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_invitations_token ON invitations (token);
CREATE INDEX IF NOT EXISTS ix_invitations_email_lower ON invitations (lower(email));

CREATE TABLE IF NOT EXISTS access_requests (
    id                  uuid PRIMARY KEY,
    email               text NOT NULL,
    status              text NOT NULL DEFAULT 'pending',
    source_share_token  text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_access_requests_email_lower ON access_requests (lower(email));

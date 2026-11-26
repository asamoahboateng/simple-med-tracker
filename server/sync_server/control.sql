-- The control database (DATABASE_URL): companies, join codes and computers of every app.
-- Applied at every start; safe to run again. Each company's data is in its own database (company.sql).

CREATE TABLE IF NOT EXISTS tenants (            -- one row per company of an app
    app      TEXT      NOT NULL,
    company  TEXT      NOT NULL,
    database TEXT      NOT NULL UNIQUE,         -- apps.database_name(app, company)
    created  TIMESTAMP NOT NULL,
    disabled BOOLEAN   NOT NULL DEFAULT FALSE,
    PRIMARY KEY (app, company)
);

CREATE TABLE IF NOT EXISTS join_codes (
    code_hash TEXT PRIMARY KEY,                 -- SHA-256 of the code; the code itself is never stored
    app       TEXT      NOT NULL,
    company   TEXT      NOT NULL,
    expires   TIMESTAMP NOT NULL,
    used      BOOLEAN   NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS devices (            -- the computers that joined
    device     TEXT PRIMARY KEY,
    app        TEXT      NOT NULL,
    company    TEXT      NOT NULL,
    name       TEXT      NOT NULL,
    token_hash TEXT      NOT NULL UNIQUE,       -- SHA-256 of the token
    joined     TIMESTAMP NOT NULL,
    last_seen  TIMESTAMP NOT NULL,
    revoked    BOOLEAN   NOT NULL DEFAULT FALSE
);

-- The single-company version (before 2026-11-26) kept join_codes and devices without app/company,
-- and its data tables here. Nothing was live, so they are only brought up to date, never used.
ALTER TABLE join_codes ADD COLUMN IF NOT EXISTS app TEXT NOT NULL DEFAULT '';
ALTER TABLE join_codes ADD COLUMN IF NOT EXISTS company TEXT NOT NULL DEFAULT '';
ALTER TABLE devices ADD COLUMN IF NOT EXISTS app TEXT NOT NULL DEFAULT '';
ALTER TABLE devices ADD COLUMN IF NOT EXISTS company TEXT NOT NULL DEFAULT '';

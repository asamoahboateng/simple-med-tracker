-- The sync server's tables (applied at every start; safe to run again).

CREATE TABLE IF NOT EXISTS join_codes (
    code_hash TEXT PRIMARY KEY,                 -- SHA-256 of the code; the code itself is never stored
    expires   TIMESTAMP NOT NULL,
    used      BOOLEAN   NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS devices (            -- the computers that joined
    device     TEXT PRIMARY KEY,
    name       TEXT      NOT NULL,
    token_hash TEXT      NOT NULL UNIQUE,       -- SHA-256 of the token
    joined     TIMESTAMP NOT NULL,
    last_seen  TIMESTAMP NOT NULL,
    revoked    BOOLEAN   NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS seen_changes (       -- every change already handled, so repeats are ignored
    change_uid TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS changes (            -- the numbered change log computers fetch from
    seq         BIGINT PRIMARY KEY,
    change_uid  TEXT NOT NULL UNIQUE,
    table_name  TEXT NOT NULL,
    row_key     TEXT NOT NULL,
    op          TEXT NOT NULL,
    data        JSONB,
    into_key    TEXT,
    device      TEXT,                            -- NULL: made by the server (merge, restore)
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rows (               -- every row as it is now, for snapshots and checks
    table_name TEXT    NOT NULL,
    row_key    TEXT    NOT NULL,
    data       JSONB   NOT NULL,
    deleted    BOOLEAN NOT NULL,
    ord        BIGSERIAL,
    PRIMARY KEY (table_name, row_key)
);

CREATE TABLE IF NOT EXISTS aliases (            -- rows merged into another row
    table_name TEXT NOT NULL,
    row_key    TEXT NOT NULL,
    into_key   TEXT NOT NULL,
    PRIMARY KEY (table_name, row_key)
);

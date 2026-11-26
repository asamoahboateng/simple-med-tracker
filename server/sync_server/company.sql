-- One company's tables, in that company's own database (made by postgres.create_database;
-- applied again at every start: safe to run again).

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

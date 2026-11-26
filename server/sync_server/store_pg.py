"""
store_pg.py - Keeps the sync server's data in Postgres. Same methods as store_memory.py.

PostgresStore holds one company's changes and rows, in that company's own database
(company.sql); PostgresControlStore holds the companies, join codes and computers in the control
database (control.sql). Each transaction() opens a connection, takes one lock so writes happen one
at a time (plenty for a few computers per company), and commits, or rolls back if anything fails.
"""

import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sync_server.core import SyncError

LOCK_ID = 4242
UNAVAILABLE = "The company's data is not available right now."


class _Postgres:
    SCHEMA = ""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._local = threading.local()
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(Path(__file__).with_name(self.SCHEMA).read_text())

    @contextmanager
    def transaction(self):
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:   # commits, or rolls back on error
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
            self._local.conn = conn
            try:
                yield
            finally:
                self._local.conn = None

    def _q(self, sql, params=()):
        return self._local.conn.execute(sql, params)


class PostgresStore(_Postgres):
    """One company's data, in its own database."""
    SCHEMA = "company.sql"

    @contextmanager
    def transaction(self):
        try:
            with super().transaction():
                yield
        except psycopg.errors.InvalidCatalogName:      # the database was dropped
            raise SyncError(503, UNAVAILABLE) from None

    # --- changes -----------------------------------------------------------------

    def seen(self, change_uid) -> bool:
        return self._q("SELECT 1 FROM seen_changes WHERE change_uid = %s", (change_uid,)).fetchone() is not None

    def mark_seen(self, change_uid):
        self._q("INSERT INTO seen_changes VALUES (%s) ON CONFLICT DO NOTHING", (change_uid,))

    def append(self, change) -> int:
        seq = self.last_seq() + 1
        self._q("INSERT INTO changes (seq, change_uid, table_name, row_key, op, data, into_key, device) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (seq, change["change_uid"], change["table"], change["key"], change["op"],
                 None if change["data"] is None else Jsonb(change["data"]), change["into"],
                 change["device"]))
        self.mark_seen(change["change_uid"])
        return seq

    def changes_after(self, after, limit) -> list[dict]:
        rows = self._q("SELECT seq, change_uid, table_name, row_key, op, data, into_key, device "
                       "FROM changes WHERE seq > %s ORDER BY seq LIMIT %s", (after, limit)).fetchall()
        return [{"seq": r["seq"], "change_uid": r["change_uid"], "table": r["table_name"],
                 "key": r["row_key"], "op": r["op"], "data": r["data"], "into": r["into_key"],
                 "device": r["device"]} for r in rows]

    def last_seq(self) -> int:
        return self._q("SELECT COALESCE(MAX(seq), 0) AS seq FROM changes").fetchone()["seq"]

    # --- rows --------------------------------------------------------------------

    def get_row(self, table, key):
        row = self._q("SELECT data, deleted FROM rows WHERE table_name = %s AND row_key = %s",
                      (table, key)).fetchone()
        return None if row is None else (row["data"], row["deleted"])

    def put_row(self, table, key, data, deleted):
        self._q("INSERT INTO rows (table_name, row_key, data, deleted) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (table_name, row_key) DO UPDATE SET data = EXCLUDED.data, "
                "deleted = EXCLUDED.deleted", (table, key, Jsonb(data), deleted))

    def find_live(self, table, values, exclude_key):
        """The key of a live row whose `values` all match, ignoring case."""
        sql = "SELECT row_key FROM rows WHERE table_name = %s AND NOT deleted AND row_key <> %s"
        params = [table, exclude_key or ""]
        for field, value in values.items():
            sql += " AND lower(data->>%s) = lower(%s)"
            params += [field, str(value)]
        row = self._q(sql + " ORDER BY ord LIMIT 1", params).fetchone()
        return None if row is None else row["row_key"]

    def live_reference(self, table, field, key) -> bool:
        return self._q("SELECT 1 FROM rows WHERE table_name = %s AND NOT deleted "
                       "AND data->>%s = %s LIMIT 1", (table, field, key)).fetchone() is not None

    def live_rows(self, table) -> list[dict]:
        return [r["data"] for r in self._q("SELECT data FROM rows WHERE table_name = %s "
                                           "AND NOT deleted ORDER BY ord", (table,)).fetchall()]

    def is_empty(self) -> bool:
        return self._q("SELECT NOT EXISTS (SELECT 1 FROM rows) AND NOT EXISTS (SELECT 1 FROM changes) "
                       "AS empty").fetchone()["empty"]

    # --- merged rows -------------------------------------------------------------

    def alias(self, table, key):
        row = self._q("SELECT into_key FROM aliases WHERE table_name = %s AND row_key = %s",
                      (table, key)).fetchone()
        return None if row is None else row["into_key"]

    def set_alias(self, table, key, into):
        self._q("INSERT INTO aliases VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (table, key, into))

    # --- status page -------------------------------------------------------------

    def stats(self, since) -> dict:
        log = self._q("SELECT COALESCE(MAX(seq), 0) AS last_seq, MAX(received_at) AS last_change_at, "
                      "COUNT(*) FILTER (WHERE received_at >= %s) AS changes_24h FROM changes",
                      (since,)).fetchone()
        per_device = {r["device"]: [r["recent"], r["total"]] for r in self._q(
            "SELECT device, COUNT(*) FILTER (WHERE received_at >= %s) AS recent, COUNT(*) AS total "
            "FROM changes WHERE device IS NOT NULL GROUP BY device", (since,))}
        tables = {r["table_name"]: r["live"] for r in self._q(
            "SELECT table_name, COUNT(*) FILTER (WHERE NOT deleted) AS live FROM rows GROUP BY table_name")}
        return {**log, "per_device": per_device, "tables": tables}


class PostgresControlStore(_Postgres):
    """The companies, join codes and computers, in the control database."""
    SCHEMA = "control.sql"

    # --- companies ---------------------------------------------------------------

    def get_tenant(self, app, company):
        return self._q("SELECT * FROM tenants WHERE app = %s AND company = %s", (app, company)).fetchone()

    def add_tenant(self, app, company, database, now):
        self._q("INSERT INTO tenants (app, company, database, created) VALUES (%s, %s, %s, %s)",
                (app, company, database, now))

    def set_disabled(self, app, company, disabled) -> int:
        return self._q("UPDATE tenants SET disabled = %s WHERE app = %s AND company = %s",
                       (disabled, app, company)).rowcount

    def tenants(self) -> list[dict]:
        return self._q("SELECT * FROM tenants ORDER BY app, company").fetchall()

    # --- join codes --------------------------------------------------------------

    def add_code(self, code_hash, app, company, expires):
        self._q("INSERT INTO join_codes (code_hash, app, company, expires) VALUES (%s, %s, %s, %s)",
                (code_hash, app, company, expires))

    def use_code(self, code_hash, now):
        """(app, company) of a valid unused code, now marked used; None otherwise."""
        row = self._q("UPDATE join_codes SET used = TRUE WHERE code_hash = %s AND NOT used "
                      "AND expires >= %s RETURNING app, company", (code_hash, now)).fetchone()
        return None if row is None else (row["app"], row["company"])

    def open_codes(self, app, company, now) -> int:
        return self._q("SELECT COUNT(*) AS n FROM join_codes WHERE app = %s AND company = %s "
                       "AND NOT used AND expires >= %s", (app, company, now)).fetchone()["n"]

    # --- computers ---------------------------------------------------------------

    def add_device(self, device, app, company, name, token_hash, now):
        self._q("INSERT INTO devices (device, app, company, name, token_hash, joined, last_seen) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)", (device, app, company, name, token_hash, now, now))

    def device_by_token(self, token_hash):
        return self._q("SELECT device, app, company, name, revoked FROM devices WHERE token_hash = %s",
                       (token_hash,)).fetchone()

    def touch_device(self, device, now):
        self._q("UPDATE devices SET last_seen = %s WHERE device = %s", (now, device))

    def devices(self, app, company) -> list[dict]:
        return self._q("SELECT device, name, joined, last_seen, revoked FROM devices "
                       "WHERE app = %s AND company = %s ORDER BY joined", (app, company)).fetchall()

    def revoke(self, app, company, name) -> int:
        return self._q("UPDATE devices SET revoked = TRUE WHERE app = %s AND company = %s AND name = %s",
                       (app, company, name)).rowcount

"""
db.py - SQLite storage for MedTracker.

Design notes
------------
* Current stock is NEVER stored. It is always calculated from the transactions
  table: total STOCK_IN minus total DISPENSED and REMOVED (per medicine, or per
  batch). REMOVED is stock taken out without dispensing (expired, recalled...),
  with the reason in `reason`.
* Names and batch numbers use COLLATE NOCASE, so "Paracetamol" and
  "paracetamol" are treated as the same medicine. The text is stored exactly
  as first entered (after trimming spaces) for display.
* Rows saved together (for example one dispensing split across two batches)
  share the same `entry_group`, so "Undo last entry" removes them together.
* Dates are stored as ISO text: 'YYYY-MM-DD'. Timestamps as 'YYYY-MM-DD HH:MM:SS'.
* Each transaction records who entered it (`entered_by`, the user's display name).
  Rows saved before sign-in existed carry PRE_LOGIN_ENTERED_BY.
* User passwords are stored only as salted hashes (see auth.py).
* Every edit, delete or undo of a log entry is recorded in `audit_log`, with a
  copy of the entry, in the same database transaction as the change itself.
* The connection runs in autocommit mode; multi-row saves are wrapped in
  `with transaction(conn):` so a failure never leaves partial data.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from config import COMMON_UNITS

SCHEMA_VERSION = 8
PRE_LOGIN_ENTERED_BY = "Before sign-in"

TRANSACTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,
    medicine_id   INTEGER NOT NULL REFERENCES medicines(id) ON DELETE RESTRICT,
    batch_id      INTEGER NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    type          TEXT    NOT NULL CHECK (type IN ('STOCK_IN', 'DISPENSED', 'REMOVED')),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    patient_id    TEXT    NOT NULL DEFAULT '',
    prescriber    TEXT    NOT NULL DEFAULT '',
    balance_after INTEGER NOT NULL,
    entry_group   TEXT    NOT NULL,
    entered_at    TEXT    NOT NULL,
    entered_by    TEXT    NOT NULL DEFAULT '',
    reason        TEXT    NOT NULL DEFAULT ''     -- why stock was REMOVED
);
"""

# Columns copied when the transactions table is rebuilt (version 6 -> 7).
_V6_TRANSACTION_COLUMNS = ("id, date, medicine_id, batch_id, type, quantity, patient_id, "
                           "prescriber, balance_after, entry_group, entered_at, entered_by")

SCHEMA = """
CREATE TABLE IF NOT EXISTS medicines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL COLLATE NOCASE UNIQUE,
    unit          TEXT    NOT NULL,
    reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
    note          TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS batches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE RESTRICT,
    batch_no    TEXT    NOT NULL COLLATE NOCASE,   -- TEXT keeps leading zeros
    expiry_date TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (medicine_id, batch_no)
);

""" + TRANSACTIONS_TABLE + """

CREATE TABLE IF NOT EXISTS units (                 -- the choices in every Unit drop-down
    name       TEXT NOT NULL COLLATE NOCASE PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL COLLATE NOCASE UNIQUE,
    full_name     TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    pin_hash      TEXT    NOT NULL DEFAULT '',   -- optional 6-digit sign-in code
    can_delete_medicines INTEGER NOT NULL DEFAULT 0,   -- given by the superadmin
    role          TEXT    NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'useradmin')),
    status        TEXT    NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'active', 'revoked')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    decided_by    TEXT    NOT NULL DEFAULT '',   -- who last approved / revoked
    decided_at    TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (            -- a copy of the entry, so deleted ones stay readable
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at   TEXT    NOT NULL,
    changed_by   TEXT    NOT NULL,
    action       TEXT    NOT NULL CHECK (action IN ('EDITED', 'DELETED', 'UNDONE')),
    reason       TEXT    NOT NULL DEFAULT '',
    tx_id        INTEGER NOT NULL,                  -- no foreign key: the entry may be gone
    tx_date      TEXT    NOT NULL,
    tx_type      TEXT    NOT NULL,
    medicine     TEXT    NOT NULL,
    unit         TEXT    NOT NULL,
    batch_no     TEXT    NOT NULL,
    old_quantity INTEGER NOT NULL,
    new_quantity INTEGER,                           -- NULL when the entry was removed
    patient_id   TEXT    NOT NULL DEFAULT '',
    prescriber   TEXT    NOT NULL DEFAULT '',
    entered_at   TEXT    NOT NULL,
    entered_by   TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tx_medicine ON transactions(medicine_id);
CREATE INDEX IF NOT EXISTS idx_tx_batch    ON transactions(batch_id);
CREATE INDEX IF NOT EXISTS idx_tx_date     ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_group    ON transactions(entry_group);
"""

# Signed quantity: +quantity for stock in, -quantity for dispensed or removed.
SIGNED_QTY = "CASE t.type WHEN 'STOCK_IN' THEN t.quantity ELSE -t.quantity END"

REQUIRED_TABLES = {"medicines", "batches", "transactions"}


# --------------------------------------------------------------------------
# Connection helpers
# --------------------------------------------------------------------------

class NewerDatabaseError(Exception):
    """The data was saved by a newer MedTracker than this one."""

    def __init__(self, version: int):
        self.version = version
        super().__init__(
            f"This data was saved by a newer version of MedTracker (data format {version}). "
            f"Install the latest version to open it.")


def connect(path) -> sqlite3.Connection:
    """Open (and if needed create) the database at `path`."""
    conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit mode
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    try:
        init_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create missing tables and upgrade older databases (safe to call every start)."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:       # never touch data a newer app saved
        raise NewerDatabaseError(version)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(transactions)")}
    if columns and "entered_by" not in columns:
        # Version 1 had no sign-in: add the column and label the existing rows.
        conn.execute("ALTER TABLE transactions ADD COLUMN entered_by TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE transactions SET entered_by = ?", (PRE_LOGIN_ENTERED_BY,))
    user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if user_columns and "pin_hash" not in user_columns:
        # Version 2 had passwords only: add the optional 6-digit sign-in code.
        conn.execute("ALTER TABLE users ADD COLUMN pin_hash TEXT NOT NULL DEFAULT ''")
    if user_columns and "can_delete_medicines" not in user_columns:
        # Version 7 had no permission to delete medicines (nobody but the superadmin has it).
        conn.execute("ALTER TABLE users ADD COLUMN can_delete_medicines INTEGER NOT NULL DEFAULT 0")
    medicine_columns = {r["name"] for r in conn.execute("PRAGMA table_info(medicines)")}
    if medicine_columns and "note" not in medicine_columns:
        # Version 4 had no medicine notes.
        conn.execute("ALTER TABLE medicines ADD COLUMN note TEXT NOT NULL DEFAULT ''")
    _allow_removed_type(conn)
    had_units = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'units'").fetchone()
    conn.executescript(SCHEMA)
    if not had_units:
        # First time: start the list with the common units and every unit already in use.
        for name in COMMON_UNITS:
            add_unit(conn, name)
        for row in conn.execute("SELECT DISTINCT unit FROM medicines"):
            add_unit(conn, row["unit"])
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _allow_removed_type(conn: sqlite3.Connection) -> None:
    """
    Version 6 only allowed STOCK_IN and DISPENSED rows and had no `reason` column.
    SQLite can't change a CHECK rule in place, so the table is rebuilt with the
    same rows (and ids). The indexes are recreated by SCHEMA afterwards.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'transactions'").fetchone()
    if row is None or "'REMOVED'" in row["sql"]:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with transaction(conn):
            conn.execute("DROP TABLE IF EXISTS transactions_new")
            conn.execute(TRANSACTIONS_TABLE.replace("IF NOT EXISTS transactions",
                                                    "transactions_new"))
            conn.execute(f"INSERT INTO transactions_new ({_V6_TRANSACTION_COLUMNS}) "
                         f"SELECT {_V6_TRANSACTION_COLUMNS} FROM transactions")
            conn.execute("DROP TABLE transactions")
            conn.execute("ALTER TABLE transactions_new RENAME TO transactions")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


@contextmanager
def transaction(conn: sqlite3.Connection):
    """
    Run a block of writes as ONE database transaction.

        with transaction(conn):
            ...several inserts...

    If anything inside raises an error, every change is rolled back.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# --------------------------------------------------------------------------
# Medicines
# --------------------------------------------------------------------------

def find_medicine(conn, name: str):
    """Case-insensitive lookup by name. Returns a Row or None."""
    return conn.execute(
        "SELECT * FROM medicines WHERE name = ?", (name.strip(),)
    ).fetchone()


def get_medicine(conn, medicine_id: int):
    return conn.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()


def create_medicine(conn, name: str, unit: str, reorder_level: int, note: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO medicines (name, unit, reorder_level, note) VALUES (?, ?, ?, ?)",
        (name.strip(), unit.strip(), int(reorder_level), note.strip()),
    )
    return cur.lastrowid


def list_units(conn) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM units ORDER BY name COLLATE NOCASE")]


def add_unit(conn, name: str) -> None:
    """Add a unit to the list (nothing happens if it is already there, ignoring case)."""
    if name and name.strip():
        conn.execute("INSERT OR IGNORE INTO units (name) VALUES (?)", (name.strip(),))


def remove_unit(conn, name: str) -> None:
    conn.execute("DELETE FROM units WHERE name = ?", (name.strip(),))


def medicine_entry_count(conn, medicine_id: int) -> int:
    """How many log entries (transactions) a medicine has."""
    return conn.execute("SELECT COUNT(*) FROM transactions WHERE medicine_id = ?",
                        (medicine_id,)).fetchone()[0]


def delete_medicine(conn, medicine_id: int) -> None:
    """Delete a medicine and any empty batches. Only call it when it has no transactions."""
    conn.execute("DELETE FROM batches WHERE medicine_id = ?", (medicine_id,))
    conn.execute("DELETE FROM medicines WHERE id = ?", (medicine_id,))


def medicines_using_unit(conn, name: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM medicines WHERE unit = ? COLLATE NOCASE",
                        (name.strip(),)).fetchone()[0]


def list_medicines(conn):
    return conn.execute("SELECT * FROM medicines ORDER BY name COLLATE NOCASE").fetchall()


def medicine_names(conn) -> list[str]:
    return [r["name"] for r in list_medicines(conn)]


def update_medicine(conn, medicine_id: int, unit: str | None = None,
                    reorder_level: int | None = None, name: str | None = None,
                    note: str | None = None) -> None:
    if name is not None:
        conn.execute("UPDATE medicines SET name = ? WHERE id = ?", (name.strip(), medicine_id))
    if unit is not None:
        conn.execute("UPDATE medicines SET unit = ? WHERE id = ?", (unit.strip(), medicine_id))
    if reorder_level is not None:
        conn.execute("UPDATE medicines SET reorder_level = ? WHERE id = ?",
                     (int(reorder_level), medicine_id))
    if note is not None:
        conn.execute("UPDATE medicines SET note = ? WHERE id = ?", (note.strip(), medicine_id))


def medicine_stock(conn, medicine_id: int) -> int:
    """Current stock = received - dispensed (calculated, never stored)."""
    row = conn.execute(
        f"SELECT COALESCE(SUM({SIGNED_QTY}), 0) FROM transactions t WHERE t.medicine_id = ?",
        (medicine_id,),
    ).fetchone()
    return int(row[0])


# --------------------------------------------------------------------------
# Batches
# --------------------------------------------------------------------------

def find_batch(conn, medicine_id: int, batch_no: str):
    return conn.execute(
        "SELECT * FROM batches WHERE medicine_id = ? AND batch_no = ?",
        (medicine_id, batch_no.strip()),
    ).fetchone()


def create_batch(conn, medicine_id: int, batch_no: str, expiry_date: str) -> int:
    cur = conn.execute(
        "INSERT INTO batches (medicine_id, batch_no, expiry_date) VALUES (?, ?, ?)",
        (medicine_id, batch_no.strip(), expiry_date),
    )
    return cur.lastrowid


def get_batch(conn, batch_id: int):
    return conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()


def update_batch(conn, batch_id: int, batch_no: str | None = None,
                 expiry_date: str | None = None) -> None:
    if batch_no is not None:
        conn.execute("UPDATE batches SET batch_no = ? WHERE id = ?", (batch_no.strip(), batch_id))
    if expiry_date is not None:
        conn.execute("UPDATE batches SET expiry_date = ? WHERE id = ?", (expiry_date, batch_id))


def batch_stock(conn, batch_id: int) -> int:
    row = conn.execute(
        f"SELECT COALESCE(SUM({SIGNED_QTY}), 0) FROM transactions t WHERE t.batch_id = ?",
        (batch_id,),
    ).fetchone()
    return int(row[0])


def batches_for_medicine(conn, medicine_id: int):
    """All batches of one medicine with their remaining quantity."""
    return conn.execute(
        f"""
        SELECT b.id, b.batch_no, b.expiry_date,
               COALESCE(SUM({SIGNED_QTY}), 0) AS remaining
        FROM batches b
        LEFT JOIN transactions t ON t.batch_id = b.id
        WHERE b.medicine_id = ?
        GROUP BY b.id
        ORDER BY b.expiry_date, b.id
        """,
        (medicine_id,),
    ).fetchall()


def batch_numbers(conn, medicine_id: int) -> list[str]:
    return [r["batch_no"] for r in batches_for_medicine(conn, medicine_id)]


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------

def insert_transaction(conn, *, tx_date: str, medicine_id: int, batch_id: int, tx_type: str,
                       quantity: int, balance_after: int, entry_group: str, entered_at: str,
                       patient_id: str = "", prescriber: str = "", entered_by: str = "",
                       reason: str = "") -> int:
    cur = conn.execute(
        """
        INSERT INTO transactions
            (date, medicine_id, batch_id, type, quantity, patient_id, prescriber,
             balance_after, entry_group, entered_at, entered_by, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (tx_date, medicine_id, batch_id, tx_type, int(quantity), patient_id.strip(),
         prescriber.strip(), int(balance_after), entry_group, entered_at, entered_by.strip(),
         reason.strip()),
    )
    return cur.lastrowid


LOG_SELECT = """
    SELECT t.id, t.date, m.name AS medicine, m.unit, t.type, t.quantity,
           b.batch_no, b.expiry_date AS expiry, t.patient_id, t.prescriber,
           t.balance_after, t.entered_at, t.entered_by, t.entry_group, t.medicine_id,
           t.batch_id, t.reason
    FROM transactions t
    JOIN medicines m ON m.id = t.medicine_id
    JOIN batches   b ON b.id = t.batch_id
"""


def log_rows(conn):
    """Every transaction, newest first."""
    return conn.execute(LOG_SELECT + " ORDER BY t.date DESC, t.id DESC").fetchall()


def medicine_log_rows(conn, medicine_id: int):
    """One medicine's transactions, newest first."""
    return conn.execute(
        LOG_SELECT + " WHERE t.medicine_id = ? ORDER BY t.date DESC, t.id DESC", (medicine_id,)
    ).fetchall()


def last_entry_rows(conn):
    """All rows belonging to the most recently saved entry (highest id)."""
    last = conn.execute(
        "SELECT entry_group FROM transactions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last is None:
        return []
    return conn.execute(
        LOG_SELECT + " WHERE t.entry_group = ? ORDER BY t.id", (last["entry_group"],)
    ).fetchall()


def delete_entry_group(conn, entry_group: str) -> int:
    """Delete every row of one entry, plus any batch left with no transactions."""
    cur = conn.execute("DELETE FROM transactions WHERE entry_group = ?", (entry_group,))
    conn.execute(
        "DELETE FROM batches WHERE id NOT IN (SELECT DISTINCT batch_id FROM transactions)"
    )
    return cur.rowcount


def get_transaction(conn, tx_id: int):
    return conn.execute(LOG_SELECT + " WHERE t.id = ?", (tx_id,)).fetchone()


def batch_deliveries(conn, batch_id: int):
    """The STOCK_IN rows of one batch, oldest first."""
    return conn.execute(
        LOG_SELECT + " WHERE t.batch_id = ? AND t.type = 'STOCK_IN' ORDER BY t.id", (batch_id,)
    ).fetchall()


def batch_movements(conn, batch_id: int):
    """One batch's transactions in the order they were entered."""
    return conn.execute(
        "SELECT id, type, quantity FROM transactions WHERE batch_id = ? ORDER BY id",
        (batch_id,),
    ).fetchall()


def update_transaction_quantity(conn, tx_id: int, quantity: int, stock_change: int) -> None:
    """
    Set one row's quantity and shift `balance_after` by `stock_change` on that row
    and every later row of the same medicine.
    """
    conn.execute("UPDATE transactions SET quantity = ? WHERE id = ?", (int(quantity), tx_id))
    conn.execute(
        """
        UPDATE transactions SET balance_after = balance_after + ?
        WHERE id >= ? AND medicine_id = (SELECT medicine_id FROM transactions WHERE id = ?)
        """,
        (int(stock_change), tx_id, tx_id),
    )


def delete_transaction(conn, tx_id: int, stock_change: int) -> None:
    """
    Delete one row, shift `balance_after` by `stock_change` on every later row of
    the same medicine, and remove its batch if no transactions are left in it.
    """
    conn.execute(
        """
        UPDATE transactions SET balance_after = balance_after + ?
        WHERE id > ? AND medicine_id = (SELECT medicine_id FROM transactions WHERE id = ?)
        """,
        (int(stock_change), tx_id, tx_id),
    )
    conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    conn.execute(
        "DELETE FROM batches WHERE id NOT IN (SELECT DISTINCT batch_id FROM transactions)"
    )


def add_audit(conn, tx, *, action: str, changed_at: str, changed_by: str,
              new_quantity: int | None = None, reason: str = "") -> None:
    """Record a change to log row `tx` (a LOG_SELECT row, read BEFORE the change)."""
    conn.execute(
        """
        INSERT INTO audit_log
            (changed_at, changed_by, action, reason, tx_id, tx_date, tx_type, medicine, unit,
             batch_no, old_quantity, new_quantity, patient_id, prescriber, entered_at, entered_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (changed_at, changed_by.strip(), action, reason.strip(), tx["id"], tx["date"], tx["type"],
         tx["medicine"], tx["unit"], tx["batch_no"], int(tx["quantity"]), new_quantity,
         tx["patient_id"], tx["prescriber"], tx["entered_at"], tx["entered_by"]),
    )


def audit_rows(conn):
    """Every recorded change, newest first."""
    return conn.execute("SELECT * FROM audit_log ORDER BY id DESC").fetchall()


def prescribers(conn) -> list[str]:
    """Previously used prescriber names (for the drop-down)."""
    rows = conn.execute(
        """
        SELECT prescriber FROM transactions
        WHERE prescriber <> ''
        GROUP BY prescriber COLLATE NOCASE
        ORDER BY prescriber COLLATE NOCASE
        """
    ).fetchall()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------
# Summaries used by the Stock page, dashboard and reports
# --------------------------------------------------------------------------

def medicine_summary(conn):
    """One row per medicine with received / dispensed / stock / nearest expiry."""
    return conn.execute(
        f"""
        WITH batch_left AS (
            SELECT b.id, b.medicine_id, b.expiry_date,
                   COALESCE(SUM({SIGNED_QTY}), 0) AS remaining
            FROM batches b LEFT JOIN transactions t ON t.batch_id = b.id
            GROUP BY b.id
        )
        SELECT m.id, m.name, m.unit, m.reorder_level, m.note,
               COALESCE((SELECT SUM(quantity) FROM transactions
                         WHERE medicine_id = m.id AND type = 'STOCK_IN'), 0) AS received,
               COALESCE((SELECT SUM(quantity) FROM transactions
                         WHERE medicine_id = m.id AND type = 'DISPENSED'), 0) AS dispensed,
               COALESCE((SELECT SUM(quantity) FROM transactions
                         WHERE medicine_id = m.id AND type = 'REMOVED'), 0) AS removed,
               (SELECT MIN(expiry_date) FROM batch_left
                WHERE medicine_id = m.id AND remaining > 0) AS nearest_expiry
        FROM medicines m
        ORDER BY m.name COLLATE NOCASE
        """
    ).fetchall()


def batch_summary(conn):
    """One row per batch with received / dispensed / remaining."""
    return conn.execute(
        """
        SELECT b.id, b.medicine_id, m.name AS medicine, m.unit, b.batch_no, b.expiry_date,
               COALESCE(SUM(CASE WHEN t.type = 'STOCK_IN'  THEN t.quantity END), 0) AS received,
               COALESCE(SUM(CASE WHEN t.type = 'DISPENSED' THEN t.quantity END), 0) AS dispensed,
               COALESCE(SUM(CASE WHEN t.type = 'REMOVED'   THEN t.quantity END), 0) AS removed,
               COUNT(CASE WHEN t.type = 'STOCK_IN' THEN 1 END) AS deliveries
        FROM batches b
        JOIN medicines m ON m.id = b.medicine_id
        LEFT JOIN transactions t ON t.batch_id = b.id
        GROUP BY b.id
        ORDER BY b.expiry_date, m.name COLLATE NOCASE
        """
    ).fetchall()


def quantity_by_medicine(conn, tx_type: str, start: str, end: str):
    """Total quantity per medicine for one transaction type between two dates (inclusive)."""
    return conn.execute(
        """
        SELECT m.id, m.name, SUM(t.quantity) AS qty
        FROM transactions t JOIN medicines m ON m.id = t.medicine_id
        WHERE t.type = ? AND t.date BETWEEN ? AND ?
        GROUP BY m.id
        ORDER BY qty DESC, m.name COLLATE NOCASE
        """,
        (tx_type, start, end),
    ).fetchall()


def dispensed_by_day(conn, start: str, end: str):
    return conn.execute(
        """
        SELECT date, SUM(quantity) AS qty FROM transactions
        WHERE type = 'DISPENSED' AND date BETWEEN ? AND ?
        GROUP BY date ORDER BY date
        """,
        (start, end),
    ).fetchall()


def total_quantity(conn, tx_type: str, start: str, end: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM transactions "
        "WHERE type = ? AND date BETWEEN ? AND ?",
        (tx_type, start, end),
    ).fetchone()
    return int(row[0])


def dispensing_entry_count(conn, start: str, end: str) -> int:
    """Number of dispensing entries (a split across batches counts once)."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT entry_group) FROM transactions "
        "WHERE type = 'DISPENSED' AND date BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    return int(row[0])


def delivery_count(conn, start: str, end: str) -> int:
    """Number of stock-in entries (deliveries) between two dates."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT entry_group) FROM transactions "
        "WHERE type = 'STOCK_IN' AND date BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    return int(row[0])


def dispensing_entries_by_hour(conn, start: str, end: str) -> dict[int, int]:
    """Dispensing entries per hour of the day they were recorded (from entered_at)."""
    rows = conn.execute(
        """
        SELECT CAST(substr(entered_at, 12, 2) AS INTEGER) AS hour,
               COUNT(DISTINCT entry_group) AS entries
        FROM transactions
        WHERE type = 'DISPENSED' AND date BETWEEN ? AND ?
        GROUP BY hour
        """,
        (start, end),
    ).fetchall()
    return {int(r["hour"]): int(r["entries"]) for r in rows}


def first_transaction_date(conn) -> str | None:
    return conn.execute("SELECT MIN(date) FROM transactions").fetchone()[0]


def dispensed_by_prescriber(conn, start: str, end: str):
    return conn.execute(
        """
        SELECT CASE WHEN prescriber = '' THEN '(not recorded)' ELSE prescriber END AS prescriber,
               SUM(quantity) AS qty, COUNT(DISTINCT entry_group) AS entries
        FROM transactions
        WHERE type = 'DISPENSED' AND date BETWEEN ? AND ?
        GROUP BY prescriber COLLATE NOCASE
        ORDER BY qty DESC
        """,
        (start, end),
    ).fetchall()


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------

def find_user(conn, username: str):
    return conn.execute("SELECT * FROM users WHERE username = ?",
                        (username.strip(),)).fetchone()


def get_user(conn, user_id: int):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create_user(conn, username: str, full_name: str, password_hash: str,
                pin_hash: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO users (username, full_name, password_hash, pin_hash) VALUES (?, ?, ?, ?)",
        (username.strip(), full_name.strip(), password_hash, pin_hash))
    return cur.lastrowid


def list_users(conn):
    return conn.execute(
        """SELECT * FROM users
           ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 ELSE 2 END,
                    full_name COLLATE NOCASE""").fetchall()


def pending_user_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE status = 'pending'").fetchone()[0]


def set_user_status(conn, user_id: int, status: str, decided_by: str, decided_at: str) -> None:
    conn.execute("UPDATE users SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                 (status, decided_by, decided_at, user_id))


def set_user_role(conn, user_id: int, role: str) -> None:
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))


def set_user_delete_permission(conn, user_id: int, allowed: bool) -> None:
    conn.execute("UPDATE users SET can_delete_medicines = ? WHERE id = ?", (int(allowed), user_id))


def set_user_password(conn, user_id: int, password_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))


def set_user_pin(conn, user_id: int, pin_hash: str) -> None:
    """Set (or with "" remove) a user's 6-digit sign-in code."""
    conn.execute("UPDATE users SET pin_hash = ? WHERE id = ?", (pin_hash, user_id))


# --------------------------------------------------------------------------
# Backup / restore
# --------------------------------------------------------------------------

def backup_to(conn, dest_path) -> None:
    """Copy the whole live database into `dest_path` (safe while in use)."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        dest_path.unlink()
    dest = sqlite3.connect(str(dest_path))
    try:
        conn.backup(dest)
    finally:
        dest.close()


def backup_version(path) -> int:
    """The data format number stored in the file at `path` (0 if unreadable or new)."""
    try:
        src = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            return src.execute("PRAGMA user_version").fetchone()[0]
        finally:
            src.close()
    except sqlite3.Error:
        return 0


def is_valid_backup(path) -> bool:
    """True if `path` is a readable SQLite file with MedTracker's tables that this version can open."""
    try:
        src = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            names = {r[0] for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            ok = src.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            src.close()
        return ok and REQUIRED_TABLES.issubset(names) and backup_version(path) <= SCHEMA_VERSION
    except sqlite3.Error:
        return False


def restore_from(conn, src_path) -> None:
    """Replace the live database contents with the backup at `src_path`."""
    version = backup_version(src_path)
    if version > SCHEMA_VERSION:
        raise NewerDatabaseError(version)
    src = sqlite3.connect(str(src_path))
    try:
        src.backup(conn)
    finally:
        src.close()
    init_schema(conn)  # make sure indexes exist in older backups


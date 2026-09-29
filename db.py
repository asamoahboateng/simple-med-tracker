"""
db.py - SQLite storage for MedTracker.

Design notes
------------
* Current stock is NEVER stored. It is always calculated from the transactions
  table: total STOCK_IN minus total DISPENSED (per medicine, or per batch).
* Names and batch numbers use COLLATE NOCASE, so "Paracetamol" and
  "paracetamol" are treated as the same medicine. The text is stored exactly
  as first entered (after trimming spaces) for display.
* Rows saved together (for example one dispensing split across two batches)
  share the same `entry_group`, so "Undo last entry" removes them together.
* Dates are stored as ISO text: 'YYYY-MM-DD'. Timestamps as 'YYYY-MM-DD HH:MM:SS'.
* The connection runs in autocommit mode; multi-row saves are wrapped in
  `with transaction(conn):` so a failure never leaves partial data.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS medicines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL COLLATE NOCASE UNIQUE,
    unit          TEXT    NOT NULL,
    reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
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

CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,
    medicine_id   INTEGER NOT NULL REFERENCES medicines(id) ON DELETE RESTRICT,
    batch_id      INTEGER NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    type          TEXT    NOT NULL CHECK (type IN ('STOCK_IN', 'DISPENSED')),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    patient_id    TEXT    NOT NULL DEFAULT '',
    prescriber    TEXT    NOT NULL DEFAULT '',
    balance_after INTEGER NOT NULL,
    entry_group   TEXT    NOT NULL,
    entered_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_medicine ON transactions(medicine_id);
CREATE INDEX IF NOT EXISTS idx_tx_batch    ON transactions(batch_id);
CREATE INDEX IF NOT EXISTS idx_tx_date     ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_group    ON transactions(entry_group);
"""

# Signed quantity: +quantity for stock in, -quantity for dispensed.
SIGNED_QTY = "CASE t.type WHEN 'STOCK_IN' THEN t.quantity ELSE -t.quantity END"

REQUIRED_TABLES = {"medicines", "batches", "transactions"}


# --------------------------------------------------------------------------
# Connection helpers
# --------------------------------------------------------------------------

def connect(path) -> sqlite3.Connection:
    """Open (and if needed create) the database at `path`."""
    conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit mode
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they do not exist yet (safe to call every start)."""
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


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


def create_medicine(conn, name: str, unit: str, reorder_level: int) -> int:
    cur = conn.execute(
        "INSERT INTO medicines (name, unit, reorder_level) VALUES (?, ?, ?)",
        (name.strip(), unit.strip(), int(reorder_level)),
    )
    return cur.lastrowid


def list_medicines(conn):
    return conn.execute("SELECT * FROM medicines ORDER BY name COLLATE NOCASE").fetchall()


def medicine_names(conn) -> list[str]:
    return [r["name"] for r in list_medicines(conn)]


def update_medicine(conn, medicine_id: int, unit: str | None = None,
                    reorder_level: int | None = None) -> None:
    """Only the unit and reorder level may be edited."""
    if unit is not None:
        conn.execute("UPDATE medicines SET unit = ? WHERE id = ?", (unit.strip(), medicine_id))
    if reorder_level is not None:
        conn.execute("UPDATE medicines SET reorder_level = ? WHERE id = ?",
                     (int(reorder_level), medicine_id))


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
                       patient_id: str = "", prescriber: str = "") -> int:
    cur = conn.execute(
        """
        INSERT INTO transactions
            (date, medicine_id, batch_id, type, quantity, patient_id, prescriber,
             balance_after, entry_group, entered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (tx_date, medicine_id, batch_id, tx_type, int(quantity), patient_id.strip(),
         prescriber.strip(), int(balance_after), entry_group, entered_at),
    )
    return cur.lastrowid


LOG_SELECT = """
    SELECT t.id, t.date, m.name AS medicine, m.unit, t.type, t.quantity,
           b.batch_no, b.expiry_date AS expiry, t.patient_id, t.prescriber,
           t.balance_after, t.entered_at, t.entry_group, t.medicine_id, t.batch_id
    FROM transactions t
    JOIN medicines m ON m.id = t.medicine_id
    JOIN batches   b ON b.id = t.batch_id
"""


def log_rows(conn):
    """Every transaction, newest first."""
    return conn.execute(LOG_SELECT + " ORDER BY t.date DESC, t.id DESC").fetchall()


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
        SELECT m.id, m.name, m.unit, m.reorder_level,
               COALESCE((SELECT SUM(quantity) FROM transactions
                         WHERE medicine_id = m.id AND type = 'STOCK_IN'), 0) AS received,
               COALESCE((SELECT SUM(quantity) FROM transactions
                         WHERE medicine_id = m.id AND type = 'DISPENSED'), 0) AS dispensed,
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
        SELECT b.id, m.name AS medicine, m.unit, b.batch_no, b.expiry_date,
               COALESCE(SUM(CASE WHEN t.type = 'STOCK_IN'  THEN t.quantity END), 0) AS received,
               COALESCE(SUM(CASE WHEN t.type = 'DISPENSED' THEN t.quantity END), 0) AS dispensed
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


def is_valid_backup(path) -> bool:
    """True if `path` is a readable SQLite file containing MedTracker's tables."""
    try:
        src = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            names = {r[0] for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            ok = src.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            src.close()
        return ok and REQUIRED_TABLES.issubset(names)
    except sqlite3.Error:
        return False


def restore_from(conn, src_path) -> None:
    """Replace the live database contents with the backup at `src_path`."""
    src = sqlite3.connect(str(src_path))
    try:
        src.backup(conn)
    finally:
        src.close()
    init_schema(conn)  # make sure indexes exist in older backups


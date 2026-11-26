"""
sync_schema.py - The tables that sync between computers, as they travel over the network.

Shared by MedTracker and the sync server (server/), so both agree on every field.
Rows are identified by `uid` (made on the computer that created the row, the same everywhere),
except units, which are identified by their name. References to other rows travel as uids
(`medicine_uid`), never as the local integer ids. `balance_after` never travels: every
computer recalculates it.
"""

import uuid
from dataclasses import dataclass, field

FORMAT = 1                     # sent as X-MedTracker-Format; raise when the wire format changes

# Messages shown to the user (the server sends them, the app shows them).
OFFLINE = "Cannot reach the sync server. Changes are saved on this computer and will be sent later."
REVOKED = "This computer is no longer allowed to sync. Ask the person who runs the sync server."
TOO_OLD = "Update MedTracker to keep syncing."
BAD_CODE = "That join code is not valid or has expired."
USERNAME_TAKEN = "Username taken — register again"

TEXT, INT, INT_OR_NULL = "text", "int", "int_or_null"


@dataclass(frozen=True)
class Table:
    name: str
    key: str                                       # "uid", or "name" for units
    fields: dict[str, str]                         # wire field -> TEXT / INT / INT_OR_NULL
    refs: dict[str, tuple[str, str]] = field(default_factory=dict)   # wire field -> (table, local id column)
    choices: dict[str, tuple[str, ...]] = field(default_factory=dict)
    not_empty: tuple[str, ...] = ()
    unique: tuple[str, ...] = ()                   # fields that together must be unique (ignoring case)


TABLES: dict[str, Table] = {t.name: t for t in (
    Table("units", "name", {}, not_empty=("name",)),
    Table("users", "uid", {
        "username": TEXT, "full_name": TEXT, "password_hash": TEXT, "pin_hash": TEXT,
        "can_delete_medicines": INT, "role": TEXT, "status": TEXT, "created_at": TEXT,
        "decided_by": TEXT, "decided_at": TEXT},
        choices={"role": ("user", "useradmin"), "status": ("pending", "active", "revoked")},
        not_empty=("username", "full_name", "password_hash"), unique=("username",)),
    Table("medicines", "uid", {
        "name": TEXT, "unit": TEXT, "reorder_level": INT, "note": TEXT, "created_at": TEXT},
        not_empty=("name", "unit"), unique=("name",)),
    Table("batches", "uid", {
        "medicine_uid": TEXT, "batch_no": TEXT, "expiry_date": TEXT, "created_at": TEXT},
        refs={"medicine_uid": ("medicines", "medicine_id")},
        not_empty=("batch_no", "expiry_date"), unique=("medicine_uid", "batch_no")),
    Table("transactions", "uid", {
        "date": TEXT, "medicine_uid": TEXT, "batch_uid": TEXT, "type": TEXT, "quantity": INT,
        "patient_id": TEXT, "prescriber": TEXT, "entry_group": TEXT, "entered_at": TEXT,
        "entered_by": TEXT, "reason": TEXT, "made_on": TEXT},
        refs={"medicine_uid": ("medicines", "medicine_id"), "batch_uid": ("batches", "batch_id")},
        choices={"type": ("STOCK_IN", "DISPENSED", "REMOVED")},
        not_empty=("date", "entry_group", "entered_at")),
    Table("audit_log", "uid", {
        "changed_at": TEXT, "changed_by": TEXT, "action": TEXT, "reason": TEXT, "tx_id": INT,
        "tx_date": TEXT, "tx_type": TEXT, "medicine": TEXT, "unit": TEXT, "batch_no": TEXT,
        "old_quantity": INT, "new_quantity": INT_OR_NULL, "patient_id": TEXT, "prescriber": TEXT,
        "entered_at": TEXT, "entered_by": TEXT},
        choices={"action": ("EDITED", "DELETED", "UNDONE")}),
)}

OPS = ("upsert", "delete", "merge")


def new_uid() -> str:
    return uuid.uuid4().hex

"""
core.py - The sync server's rules, whatever stores the data (store_memory.py, store_pg.py).

Every change a computer sends is checked, numbered and stored once (repeats are ignored by
`change_uid`). The same medicine added on two computers becomes one: the second is merged into
the first. Unsafe changes are refused, with the row as the server has it, so the computer can
put it back. See docs/superpowers/specs/2026-11-25-multi-computer-sync-design.md.
"""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sync_schema import (
    BAD_CODE, INT, INT_OR_NULL, OPS, REVOKED, TABLES, TEXT, USERNAME_TAKEN, new_uid,
)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LIFETIME = timedelta(hours=24)
NAME_IN_USE = "That name is already used by another row."
IN_USE = "Still used by entries on another computer."
GONE = "Deleted on another computer."


class SyncError(Exception):
    """A request the server refuses; `message` is safe to show to the user."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normal_code(code: str) -> str:
    """'abcd efgh' / 'ABCD-EFGH' -> 'ABCD-EFGH'."""
    letters = re.sub(r"[^A-Z0-9]", "", code.upper())
    return f"{letters[:4]}-{letters[4:]}"


# Tables (and fields) that point at each table: a row still pointed at can't be deleted.
REFERENCED_BY = {name: [(t.name, f) for t in TABLES.values() for f, (target, _) in t.refs.items()
                        if target == name] for name in TABLES}


class Core:
    def __init__(self, store):
        self.store = store

    # --- joining -----------------------------------------------------------------

    def make_code(self, now: datetime) -> str:
        code = normal_code("".join(secrets.choice(CODE_ALPHABET) for _ in range(8)))
        with self.store.transaction():
            self.store.add_code(_hash(code), now + CODE_LIFETIME)
        return code

    def join(self, code: str, computer: str, now: datetime) -> dict:
        computer = computer.strip()[:80] or "unnamed"
        with self.store.transaction():
            if not self.store.use_code(_hash(normal_code(code)), now):
                raise SyncError(404, BAD_CODE)
            device, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
            empty = self.store.is_empty()
            self.store.add_device(device, computer, _hash(token), now)
        return {"device": device, "token": token, "empty": empty}

    def device_for(self, token: str, now: datetime) -> str:
        with self.store.transaction():
            found = self.store.device_by_token(_hash(token))
            if found is None:
                raise SyncError(401, "This computer is not joined to sync.")
            if found["revoked"]:
                raise SyncError(403, REVOKED)
            self.store.touch_device(found["device"], now)
        return found["device"]

    def computers(self) -> list[dict]:
        with self.store.transaction():
            return self.store.devices()

    def revoke(self, name: str) -> None:
        with self.store.transaction():
            if not self.store.revoke(name):
                raise SyncError(404, f"No computer called '{name}'.")

    def status(self, now: datetime) -> dict:
        """What the /status page shows. Counts and computer names only, never row data."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        with self.store.transaction():
            found = self.store.stats(since, now)
        found["tables"] = {name: found["tables"].get(name, 0) for name in TABLES}
        return found

    # --- changes -----------------------------------------------------------------

    def push(self, device: str, changes: list) -> dict:
        if not isinstance(changes, list):
            raise SyncError(400, "Expected a list of changes.")
        rejected = []
        with self.store.transaction():
            for change in changes:
                _check_shape(change)
                if self.store.seen(change["change_uid"]):
                    continue
                refusal = self._apply(device, change)
                if refusal is not None:
                    rejected.append(refusal)
                    self.store.mark_seen(change["change_uid"])
            return {"seq": self.store.last_seq(), "rejected": rejected}

    def pull(self, after: int, limit: int = 1000) -> dict:
        limit = max(1, min(int(limit), 1000))
        with self.store.transaction():
            found = self.store.changes_after(int(after), limit + 1)
        return {"changes": found[:limit], "more": len(found) > limit}

    def snapshot(self) -> dict:
        with self.store.transaction():
            return {"rows": {name: self.store.live_rows(name) for name in TABLES},
                    "seq": self.store.last_seq()}

    # --- rules -------------------------------------------------------------------

    def _apply(self, device, change) -> dict | None:
        table = TABLES[change["table"]]
        key = self.store.alias(table.name, change["key"]) or change["key"]
        if change["op"] == "delete":
            return self._delete(device, change, table, key)
        if change["op"] == "merge":
            raise SyncError(400, "Only the server merges rows.")
        data = _checked_data(table, change.get("data"), key)
        for field, (target, _) in table.refs.items():
            data[field] = self._live_target(target, data[field])

        if table.name == "units":
            if self.store.find_live("units", {"name": key}, None) is None:
                self._store(device, change, table, key, data)
            return None

        existing = self.store.get_row(table.name, key)
        if existing is not None and existing[1]:
            return _refusal(change, key, GONE, None)
        other = (self.store.find_live(table.name, {f: data[f] for f in table.unique}, key)
                 if table.unique else None)
        if other is not None:
            if existing is None and table.name in ("medicines", "batches"):
                self.store.set_alias(table.name, key, other)
                self.store.append({"change_uid": new_uid(), "table": table.name, "key": key,
                                   "op": "merge", "data": None, "into": other, "device": None})
                self.store.mark_seen(change["change_uid"])
                return None
            if existing is None:
                return _refusal(change, key, USERNAME_TAKEN, None)
            return _refusal(change, key, NAME_IN_USE, existing[0])
        self._store(device, change, table, key, data)
        return None

    def _delete(self, device, change, table, key) -> dict | None:
        existing = self.store.get_row(table.name, key)
        if existing is None or existing[1]:
            self.store.mark_seen(change["change_uid"])
            return None
        if any(self.store.live_reference(t, f, key) for t, f in REFERENCED_BY[table.name]):
            return _refusal(change, key, IN_USE, existing[0])
        self.store.put_row(table.name, key, existing[0], True)
        self.store.append({"change_uid": change["change_uid"], "table": table.name, "key": key,
                           "op": "delete", "data": None, "into": None, "device": device})
        return None

    def _live_target(self, table_name, key) -> str:
        """`key` after merges; a deleted row it points at comes back (the entry wins)."""
        key = self.store.alias(table_name, key) or key
        row = self.store.get_row(table_name, key)
        if row is None:
            raise SyncError(400, f"Unknown {table_name} row {key}.")
        data, deleted = row
        if deleted:
            for field, (target, _) in TABLES[table_name].refs.items():
                data[field] = self._live_target(target, data[field])
            self.store.put_row(table_name, key, data, False)
            self.store.append({"change_uid": new_uid(), "table": table_name, "key": key,
                               "op": "upsert", "data": data, "into": None, "device": None})
        return key

    def _store(self, device, change, table, key, data):
        self.store.put_row(table.name, key, data, False)
        self.store.append({"change_uid": change["change_uid"], "table": table.name, "key": key,
                           "op": "upsert", "data": data, "into": None, "device": device})


def _refusal(change, key, reason, current) -> dict:
    return {"change_uid": change["change_uid"], "table": change["table"], "key": key,
            "reason": reason, "current": current}


def _check_shape(change) -> None:
    if not isinstance(change, dict):
        raise SyncError(400, "A change must be an object.")
    for field in ("change_uid", "table", "key", "op"):
        if not isinstance(change.get(field), str) or not change[field].strip():
            raise SyncError(400, f"A change is missing '{field}'.")
    if change["table"] not in TABLES:
        raise SyncError(400, f"Unknown table '{change['table']}'.")
    if change["op"] not in OPS:
        raise SyncError(400, f"Unknown operation '{change['op']}'.")


def _checked_data(table, data, key) -> dict:
    """The row's fields, checked; raises SyncError(400) for anything a correct app never sends."""
    if not isinstance(data, dict):
        raise SyncError(400, f"A {table.name} change has no data.")
    data = {k: v for k, v in data.items() if k != table.key}
    if set(data) != set(table.fields):
        raise SyncError(400, f"A {table.name} change has the wrong fields.")
    for field, kind in table.fields.items():
        value = data[field]
        ok = (isinstance(value, str) if kind == TEXT
              else isinstance(value, int) and not isinstance(value, bool) if kind == INT
              else value is None or (isinstance(value, int) and not isinstance(value, bool))
              if kind == INT_OR_NULL else False)
        if not ok:
            raise SyncError(400, f"{table.name}.{field} has the wrong type.")
    for field in table.not_empty:
        if field != table.key and not data[field].strip():
            raise SyncError(400, f"{table.name}.{field} is empty.")
    if table.key == "name" and not key.strip():
        raise SyncError(400, f"{table.name} name is empty.")
    for field, allowed in table.choices.items():
        if data[field] not in allowed:
            raise SyncError(400, f"{table.name}.{field} is not allowed.")
    if table.name == "transactions" and data["quantity"] <= 0:
        raise SyncError(400, "A quantity must be more than zero.")
    if table.name == "medicines" and data["reorder_level"] < 0:
        raise SyncError(400, "A reorder level can't be below zero.")
    data[table.key] = key
    return data

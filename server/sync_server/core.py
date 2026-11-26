"""
core.py - One company's sync rules, whatever stores the data (store_memory.py, store_pg.py).

Companies, join codes and computers are control.py's job; Core gets the computer's id. Every change a computer sends is checked, numbered and stored once (repeats are ignored by
`change_uid`). The same medicine added on two computers becomes one: the second is merged into
the first. Unsafe changes are refused, with the row as the server has it, so the computer can
put it back. See docs/superpowers/specs/2026-11-25-multi-computer-sync-design.md.
"""

from datetime import datetime

from sync_schema import INT, INT_OR_NULL, OPS, TEXT, USERNAME_TAKEN, Table, new_uid

NAME_IN_USE = "That name is already used by another row."
IN_USE = "Still used by entries on another computer."
GONE = "Deleted on another computer."


class SyncError(Exception):
    """A request the server refuses; `message` is safe to show to the user."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Core:
    def __init__(self, store, tables: dict[str, Table]):
        self.store = store
        self.tables = tables            # the app's synced tables (apps.APPS)
        # Tables (and fields) that point at each table: a row still pointed at can't be deleted.
        self.referenced_by = {name: [(t.name, f) for t in tables.values()
                                     for f, (target, _) in t.refs.items() if target == name]
                              for name in tables}

    def is_empty(self) -> bool:
        with self.store.transaction():
            return self.store.is_empty()

    def stats(self, since: datetime) -> dict:
        """Counts for the status page (never row data): changes since `since` (UTC), changes per
        computer id as [since, total], and live rows per table."""
        with self.store.transaction():
            found = self.store.stats(since)
        found["tables"] = {name: found["tables"].get(name, 0) for name in self.tables}
        return found

    # --- changes -----------------------------------------------------------------

    def push(self, device: str, changes: list) -> dict:
        if not isinstance(changes, list):
            raise SyncError(400, "Expected a list of changes.")
        rejected = []
        with self.store.transaction():
            for change in changes:
                _check_shape(change, self.tables)
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
            return {"rows": {name: self.store.live_rows(name) for name in self.tables},
                    "seq": self.store.last_seq()}

    # --- rules -------------------------------------------------------------------

    def _apply(self, device, change) -> dict | None:
        table = self.tables[change["table"]]
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
        if any(self.store.live_reference(t, f, key) for t, f in self.referenced_by[table.name]):
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
            for field, (target, _) in self.tables[table_name].refs.items():
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


def _check_shape(change, tables) -> None:
    if not isinstance(change, dict):
        raise SyncError(400, "A change must be an object.")
    for field in ("change_uid", "table", "key", "op"):
        if not isinstance(change.get(field), str) or not change[field].strip():
            raise SyncError(400, f"A change is missing '{field}'.")
    if change["table"] not in tables:
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

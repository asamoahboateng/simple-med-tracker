"""
store_memory.py - Keeps the sync server's data in memory (tests, and the app's test server).

store_pg.py has the same methods for Postgres. Core calls them only inside transaction().
"""

import copy
import threading
from contextlib import contextmanager
from datetime import datetime, timezone


class MemoryStore:
    def __init__(self):
        self._lock = threading.RLock()
        self.state = {"codes": {}, "devices": {}, "seen": {}, "changes": [], "rows": {}, "aliases": {},
                      "received": []}   # when each change arrived (UTC), for the status page

    @contextmanager
    def transaction(self):
        """One push (or join) at a time; everything is undone if it fails."""
        with self._lock:
            saved = copy.deepcopy(self.state)
            try:
                yield
            except BaseException:
                self.state = saved
                raise

    # --- join codes and computers ------------------------------------------------

    def add_code(self, code_hash, expires):
        self.state["codes"][code_hash] = {"expires": expires, "used": False}

    def use_code(self, code_hash, now) -> bool:
        code = self.state["codes"].get(code_hash)
        if code is None or code["used"] or now > code["expires"]:
            return False
        code["used"] = True
        return True

    def add_device(self, device, name, token_hash, now):
        self.state["devices"][device] = {"device": device, "name": name, "token_hash": token_hash,
                                         "joined": now, "last_seen": now, "revoked": False}

    def device_by_token(self, token_hash):
        return next((dict(d) for d in self.state["devices"].values()
                     if d["token_hash"] == token_hash), None)

    def touch_device(self, device, now):
        self.state["devices"][device]["last_seen"] = now

    def devices(self) -> list[dict]:
        return [{k: d[k] for k in ("name", "joined", "last_seen", "revoked")}
                for d in self.state["devices"].values()]

    def revoke(self, name) -> int:
        found = [d for d in self.state["devices"].values() if d["name"] == name]
        for d in found:
            d["revoked"] = True
        return len(found)

    # --- changes -----------------------------------------------------------------

    def seen(self, change_uid) -> bool:
        return change_uid in self.state["seen"]

    def mark_seen(self, change_uid):
        self.state["seen"][change_uid] = True

    def append(self, change) -> int:
        seq = len(self.state["changes"]) + 1
        self.state["changes"].append(dict(change, seq=seq))
        self.state["received"].append(datetime.now(timezone.utc))
        self.mark_seen(change["change_uid"])
        return seq

    def changes_after(self, after, limit) -> list[dict]:
        return [dict(c) for c in self.state["changes"][after:after + limit]]

    def last_seq(self) -> int:
        return len(self.state["changes"])

    # --- rows --------------------------------------------------------------------

    def get_row(self, table, key):
        row = self.state["rows"].get((table, key))
        return None if row is None else (dict(row["data"]), row["deleted"])

    def put_row(self, table, key, data, deleted):
        old = self.state["rows"].get((table, key))
        order = old["order"] if old else len(self.state["rows"])
        self.state["rows"][(table, key)] = {"data": dict(data), "deleted": deleted, "order": order}

    def _live(self, table):
        rows = [(r["order"], k[1], r["data"]) for k, r in self.state["rows"].items()
                if k[0] == table and not r["deleted"]]
        return [(key, data) for _, key, data in sorted(rows, key=lambda r: r[0])]

    def find_live(self, table, values, exclude_key):
        """The key of a live row whose `values` all match, ignoring case."""
        wanted = {f: str(v).casefold() for f, v in values.items()}
        return next((key for key, data in self._live(table) if key != exclude_key
                     and all(str(data.get(f, "")).casefold() == v for f, v in wanted.items())), None)

    def live_reference(self, table, field, key) -> bool:
        return any(data.get(field) == key for _, data in self._live(table))

    def live_rows(self, table) -> list[dict]:
        return [dict(data) for _, data in self._live(table)]

    def is_empty(self) -> bool:
        return not self.state["rows"] and not self.state["changes"]

    # --- merged rows -------------------------------------------------------------

    def alias(self, table, key):
        return self.state["aliases"].get((table, key))

    def set_alias(self, table, key, into):
        self.state["aliases"][(table, key)] = into

    # --- status page -------------------------------------------------------------

    def stats(self, since, now) -> dict:
        """Counts for the status page: changes since `since` (UTC), computers, live rows, open codes."""
        received = self.state["received"]
        per_device = {}
        for change, at in zip(self.state["changes"], received):
            counts = per_device.setdefault(change["device"], [0, 0])
            counts[0] += at >= since
            counts[1] += 1
        tables = {}
        for (table, _), row in self.state["rows"].items():
            tables[table] = tables.get(table, 0) + (not row["deleted"])
        return {
            "last_seq": self.last_seq(),
            "last_change_at": received[-1] if received else None,
            "changes_24h": sum(at >= since for at in received),
            "computers": [{"name": d["name"], "joined": d["joined"], "last_seen": d["last_seen"],
                           "revoked": d["revoked"],
                           "changes_24h": per_device.get(d["device"], [0, 0])[0],
                           "changes_total": per_device.get(d["device"], [0, 0])[1]}
                          for d in sorted(self.state["devices"].values(), key=lambda d: d["joined"])],
            "tables": tables,
            "open_codes": sum(not c["used"] and c["expires"] >= now for c in self.state["codes"].values()),
        }

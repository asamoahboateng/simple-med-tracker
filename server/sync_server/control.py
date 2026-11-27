"""
control.py - Companies, join codes and computers, for every app on this server.

Each company of each app has its own database (apps.database_name), created only by
create_company (the admin key, in app.py). A join code belongs to one company, so joining puts a
computer in that company; its key then only opens that company's data (core_for). The company's
changes themselves are Core's job. See docs/superpowers/specs/2026-11-26-multi-tenant-sync-design.md.
"""

import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from sync_schema import BAD_CODE, REVOKED
from sync_server.apps import NOT_FOUND, check_names, database_name
from sync_server.core import Core, SyncError

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LIFETIME = timedelta(hours=24)
NOT_ALLOWED = "This computer is not allowed to sync with that company."
UNAVAILABLE = "The company's data is not available right now."
SWITCHED_OFF = "Sync is switched off for this company."
log = logging.getLogger("sync_server")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normal_code(code: str) -> str:
    """'abcd efgh' / 'ABCD-EFGH' -> 'ABCD-EFGH'."""
    letters = re.sub(r"[^A-Z0-9]", "", code.upper())
    return f"{letters[:4]}-{letters[4:]}"


class Control:
    def __init__(self, store, open_company: Callable[[str, str], Core],
                 create_database: Callable[[str, str], None]):
        """`open_company(app, company)` returns the company's Core and raises LookupError when its
        database is missing; `create_database(app, company)` makes it (and its tables) if missing."""
        self.store = store
        self.open_company = open_company
        self.create_database = create_database

    # --- companies ---------------------------------------------------------------

    def create_company(self, app: str, company: str, now: datetime) -> dict:
        """Create the company and its database if missing (safe to repeat); returns a join code."""
        database = database_name(app, company)
        with self.store.transaction():
            created = self.store.get_tenant(app, company) is None
        if created:
            self.create_database(app, company)       # outside the transaction: may take a moment
            with self.store.transaction():
                if self.store.get_tenant(app, company) is None:
                    self.store.add_tenant(app, company, database, now)
        return {"created": created, "code": self.make_code(app, company, now)}

    def set_disabled(self, app: str, company: str, disabled: bool) -> None:
        with self.store.transaction():
            if not self.store.set_disabled(app, company, disabled):
                raise SyncError(404, NOT_FOUND)

    def companies(self) -> list[dict]:
        with self.store.transaction():
            return self.store.tenants()

    def _tenant(self, app, company) -> dict:
        check_names(app, company)
        found = self.store.get_tenant(app, company)
        if found is None:
            raise SyncError(404, NOT_FOUND)
        return found

    # --- joining -----------------------------------------------------------------

    def make_code(self, app: str, company: str, now: datetime) -> str:
        code = normal_code("".join(secrets.choice(CODE_ALPHABET) for _ in range(8)))
        with self.store.transaction():
            self._tenant(app, company)
            self.store.add_code(_hash(code), app, company, now + CODE_LIFETIME)
        return code

    def join(self, code: str, computer: str, now: datetime) -> dict:
        computer = computer.strip()[:80] or "unnamed"
        with self.store.transaction():
            found = self.store.use_code(_hash(normal_code(code)), now)
            if found is None:
                raise SyncError(404, BAD_CODE)
            app, company = found
            if self.store.get_tenant(app, company)["disabled"]:
                raise SyncError(403, SWITCHED_OFF)
            empty = self._core(app, company).is_empty()
            device, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
            self.store.add_device(device, app, company, computer, _hash(token), now)
        return {"device": device, "token": token, "empty": empty, "app": app, "company": company}

    def core_for(self, token: str, app: str, company: str, now: datetime) -> Core:
        """The company's Core for a computer's key; refused unless the key is that company's."""
        return self.connect(token, app, company, now)[0]

    def connect(self, token: str, app: str, company: str, now: datetime) -> tuple[Core, str]:
        """core_for(), plus the computer's id (what Core records as who sent a change)."""
        with self.store.transaction():
            found = self.store.device_by_token(_hash(token))
            if found is None:
                raise SyncError(401, "This computer is not joined to sync.")
            if found["revoked"]:
                raise SyncError(403, REVOKED)
            if (found["app"], found["company"]) != (app, company):
                raise SyncError(403, NOT_ALLOWED)
            if self.store.get_tenant(app, company)["disabled"]:
                raise SyncError(403, SWITCHED_OFF)
            self.store.touch_device(found["device"], now)
        return self._core(app, company), found["device"]

    def _core(self, app, company) -> Core:
        try:
            return self.open_company(app, company)
        except LookupError:
            log.error("The database of %s/%s is missing", app, company)
            raise SyncError(503, UNAVAILABLE) from None

    # --- computers ---------------------------------------------------------------

    def computers(self, app: str, company: str) -> list[dict]:
        with self.store.transaction():
            self._tenant(app, company)
            return self.store.devices(app, company)

    def revoke(self, app: str, company: str, name: str) -> None:
        with self.store.transaction():
            self._tenant(app, company)
            if not self.store.revoke(app, company, name):
                raise SyncError(404, f"No computer called '{name}'.")

    # --- status page -------------------------------------------------------------

    def status(self, now: datetime) -> dict:
        """What /status shows for every company: counts and computer names, never row data."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        with self.store.transaction():
            tenants = self.store.tenants()
            details = [(t, self.store.devices(t["app"], t["company"]),
                        self.store.open_codes(t["app"], t["company"], now)) for t in tenants]
        companies = []
        for tenant, devices, open_codes in details:
            entry = {"app": tenant["app"], "company": tenant["company"], "disabled": tenant["disabled"],
                     "open_codes": open_codes, "error": None, "last_seq": 0, "last_change_at": None,
                     "changes_24h": 0, "tables": {}, "computers": []}
            try:
                stats = self._core(tenant["app"], tenant["company"]).stats(since)
            except SyncError as exc:
                entry["error"] = exc.message
            else:
                per_device = stats.pop("per_device")
                entry.update(stats)
                entry["computers"] = [
                    {"name": d["name"], "joined": d["joined"], "last_seen": d["last_seen"],
                     "revoked": d["revoked"], "changes_24h": per_device.get(d["device"], [0, 0])[0],
                     "changes_total": per_device.get(d["device"], [0, 0])[1]} for d in devices]
            companies.append(entry)
        return {"companies": companies}

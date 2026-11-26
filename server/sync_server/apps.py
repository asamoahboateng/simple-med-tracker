"""
apps.py - The apps this server syncs, and the database each company of an app gets.

Adding an app: give it a table list like sync_schema.TABLES and add it to APPS.
"""

import re

import sync_schema
from sync_server.core import SyncError

APPS = {"medtracker": sync_schema.TABLES}

APP_NAME = re.compile(r"[a-z][a-z0-9-]{1,19}")
COMPANY_NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
NOT_FOUND = "Not found."


def check_names(app: str, company: str) -> None:
    """SyncError(404) unless `app` is a known app and `company` a valid company name."""
    if (app not in APPS or not APP_NAME.fullmatch(app or "")
            or not COMPANY_NAME.fullmatch(company or "") or "--" in app + "|" + company):
        raise SyncError(404, NOT_FOUND)


def database_name(app: str, company: str) -> str:
    """'medtracker', 'kumasi-clinic' -> 'medtracker__kumasi_clinic'. Names have no underscores and
    no double dashes, so the double underscore keeps every app + company apart (max 62 chars)."""
    check_names(app, company)
    return f"{app.replace('-', '_')}__{company.replace('-', '_')}"

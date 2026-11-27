"""
Companies on real Postgres (sync_server/postgres.py): the test_control.py tests again, plus
creating twice, a half-finished create and a dropped database.

Skipped unless SYNC_TEST_DATABASE_URL points at a Postgres whose login may create databases
(see test_store_pg.py). Drops the medtracker__* databases it finds there.
"""

import os
from datetime import datetime

import pytest

from test_control import *          # noqa: F401,F403 - every control test runs again on Postgres
from test_control import NOW, joined, refused
from sync_server.control import UNAVAILABLE

DSN = os.environ.get("SYNC_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="SYNC_TEST_DATABASE_URL is not set")


@pytest.fixture
def control():
    import psycopg
    from sync_server.postgres import postgres_control
    found = postgres_control(DSN)
    for name in list(found.databases):
        del found.databases[name]
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("TRUNCATE tenants, join_codes, devices")
    return found


def test_create_after_half_create(control):
    import psycopg
    from psycopg import sql
    with psycopg.connect(DSN, autocommit=True) as conn:        # an earlier create stopped halfway
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier("medtracker__acme")))
    assert control.create_company("medtracker", "acme", NOW)["created"] is True
    pc = joined(control, "acme")
    assert control.core_for(pc["token"], "medtracker", "acme", NOW).is_empty()


def test_dropped_database_503_not_recreated(control):
    pc = joined(control, "acme")
    del control.databases["medtracker__acme"]
    refused(503, UNAVAILABLE)(lambda: control.core_for(pc["token"], "medtracker", "acme", NOW))
    assert "medtracker__acme" not in control.databases


def test_companies_keep_separate_databases(control):
    a, b = joined(control, "a-b"), joined(control, "ab")
    assert sorted(control.databases) == ["medtracker__a_b", "medtracker__ab"]
    from test_core import medicine
    control.core_for(a["token"], "medtracker", "a-b", NOW).push(a["device"], [medicine()])
    assert control.core_for(b["token"], "medtracker", "ab", datetime.now()).is_empty()

"""
The server's rules again, on real Postgres (sync_server/store_pg.py).

Skipped unless SYNC_TEST_DATABASE_URL points at a Postgres database whose data may be wiped:

    docker run -d --rm --name mt-sync-test -e POSTGRES_PASSWORD=t -p 55432:5432 postgres:16
    SYNC_TEST_DATABASE_URL=postgresql://postgres:t@127.0.0.1:55432/postgres .venv/bin/python -m pytest server/tests/test_store_pg.py
"""

import os

import pytest

from test_core import *          # noqa: F401,F403 - every rule test runs again on Postgres
from sync_server.core import Core

DSN = os.environ.get("SYNC_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="SYNC_TEST_DATABASE_URL is not set")


@pytest.fixture
def core():
    import psycopg
    from sync_server.store_pg import PostgresStore
    store = PostgresStore(DSN)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("TRUNCATE join_codes, devices, seen_changes, changes, rows, aliases")
    return Core(store)

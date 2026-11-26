"""
postgres.py - Wires Control to Postgres: the control database is DATABASE_URL, and each company
gets its own database on the same server, reached with the same login (which needs CREATEDB).
"""

import logging
from collections.abc import MutableMapping

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from sync_server.apps import APPS, database_name
from sync_server.control import Control
from sync_server.core import Core
from sync_server.store_pg import PostgresControlStore, PostgresStore

log = logging.getLogger("sync_server")


def company_dsn(dsn: str, database: str) -> str:
    """The control database's connection string, pointed at another database."""
    return make_conninfo(dsn, dbname=database)


class Databases(MutableMapping):
    """The company databases on this Postgres (name -> Core), as postgres_control sees them.
    Deleting one drops it (tests use this to simulate a lost database)."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.cores = {}

    def _names(self) -> list[str]:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            rows = conn.execute("SELECT datname FROM pg_database WHERE datname LIKE %s ORDER BY datname",
                                (r"%\_\_%",)).fetchall()
        return [r[0] for r in rows if r[0].split("__", 1)[0] in {a.replace("-", "_") for a in APPS}]

    def __contains__(self, name) -> bool:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is not None

    def __getitem__(self, name) -> Core:
        core = self.cores.get(name)
        if core is None or name not in self:
            raise KeyError(name)
        return core

    def __setitem__(self, name, core):
        self.cores[name] = core

    def __delitem__(self, name):
        self.cores.pop(name, None)
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))

    def __iter__(self):
        return iter(self._names())

    def __len__(self) -> int:
        return len(self._names())


def postgres_control(dsn: str) -> Control:
    """A Control on Postgres. `control.databases` is the Databases mapping."""
    databases = Databases(dsn)

    def create_database(app, company):
        """Make the company's database (reused if an earlier attempt made it) and its tables."""
        name = database_name(app, company)
        if name not in databases:
            with psycopg.connect(dsn, autocommit=True) as conn:
                try:
                    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                except psycopg.errors.DuplicateDatabase:
                    pass
            log.info("Created database %s", name)
        databases[name] = Core(PostgresStore(company_dsn(dsn, name)), APPS[app])

    def open_company(app, company):
        name = database_name(app, company)
        if name not in databases:            # never re-created here: a lost database must be noticed
            raise LookupError(name)
        if name not in databases.cores:      # first use since the server started
            databases[name] = Core(PostgresStore(company_dsn(dsn, name)), APPS[app])
        return databases.cores[name]

    control = Control(PostgresControlStore(dsn), open_company, create_database)
    control.databases = databases
    return control


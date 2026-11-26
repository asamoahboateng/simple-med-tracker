"""
admin.py - Commands for whoever runs the sync server (uses DATABASE_URL):

    python -m sync_server.admin make-code        a one-time join code for a computer (valid 24 hours)
    python -m sync_server.admin computers        the computers that joined
    python -m sync_server.admin revoke NAME      stop a computer from syncing (e.g. lost or stolen)

With Docker:  docker compose exec api python -m sync_server.admin make-code
"""

import argparse
import os
import sys
from datetime import datetime

from sync_server.core import Core, SyncError


def run(core: Core, argv: list[str], now: datetime | None = None) -> str:
    """Do one command and return what to print (raises SyncError on a refused command)."""
    parser = argparse.ArgumentParser(prog="python -m sync_server.admin")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("make-code", help="make a one-time join code (valid 24 hours)")
    commands.add_parser("computers", help="list the computers that joined")
    revoke = commands.add_parser("revoke", help="stop a computer from syncing")
    revoke.add_argument("name")
    args = parser.parse_args(argv)
    now = now or datetime.now()

    if args.command == "make-code":
        return (f"Join code: {core.make_code(now)}\n"
                f"Enter it in MedTracker under File > Sync setup... within 24 hours. It works once.")
    if args.command == "computers":
        found = core.computers()
        if not found:
            return "No computers have joined yet."
        return "\n".join(f"{c['name']:<30} joined {c['joined']:%Y-%m-%d %H:%M}   "
                         f"last seen {c['last_seen']:%Y-%m-%d %H:%M}"
                         + ("   REVOKED" if c["revoked"] else "") for c in found)
    core.revoke(args.name)
    return f"'{args.name}' can no longer sync."


def main() -> int:
    from sync_server.store_pg import PostgresStore
    try:
        print(run(Core(PostgresStore(os.environ["DATABASE_URL"])), sys.argv[1:]))
    except SyncError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

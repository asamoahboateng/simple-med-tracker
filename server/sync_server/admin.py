"""
admin.py - Commands for whoever runs the sync server (uses DATABASE_URL):

    python -m sync_server.admin create APP COMPANY           new company + its database, and a join code
    python -m sync_server.admin make-code APP COMPANY        another one-time join code (valid 24 hours)
    python -m sync_server.admin computers APP COMPANY        the company's computers
    python -m sync_server.admin revoke APP COMPANY NAME      stop a computer from syncing (lost, stolen)
    python -m sync_server.admin companies                    every company on this server

With Docker:  docker compose exec api python -m sync_server.admin create medtracker acme
"""

import argparse
import os
import sys
from datetime import datetime

from sync_server.apps import database_name
from sync_server.control import Control
from sync_server.core import SyncError

CODE_HINT = "Enter it in MedTracker under File > Sync setup... within 24 hours. It works once."


def run(control: Control, argv: list[str], now: datetime | None = None) -> str:
    """Do one command and return what to print (raises SyncError on a refused command)."""
    parser = argparse.ArgumentParser(prog="python -m sync_server.admin")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("create", "create a company and its database (safe to repeat)"),
                       ("make-code", "make a one-time join code (valid 24 hours)"),
                       ("computers", "list the company's computers"),
                       ("revoke", "stop a computer from syncing")):
        command = commands.add_parser(name, help=text)
        command.add_argument("app")
        command.add_argument("company")
        if name == "revoke":
            command.add_argument("name")
    commands.add_parser("companies", help="list every company")
    args = parser.parse_args(argv)
    now = now or datetime.now()

    if args.command == "companies":
        found = control.companies()
        if not found:
            return "No companies yet."
        return "\n".join(f"{c['app']}/{c['company']:<30} database {c['database']}   created "
                         f"{c['created']:%Y-%m-%d}" + ("   DISABLED" if c["disabled"] else "") for c in found)
    where = f"{args.app}/{args.company}"
    if args.command == "create":
        result = control.create_company(args.app, args.company, now)
        first = (f"Created {where} (database {database_name(args.app, args.company)})." if result["created"]
                 else f"{where} already exists.")
        return f"{first}\nJoin code: {result['code']}\n{CODE_HINT}"
    if args.command == "make-code":
        return f"Join code: {control.make_code(args.app, args.company, now)}\n{CODE_HINT}"
    if args.command == "computers":
        found = control.computers(args.app, args.company)
        if not found:
            return "No computers have joined yet."
        return "\n".join(f"{c['name']:<30} joined {c['joined']:%Y-%m-%d %H:%M}   "
                         f"last seen {c['last_seen']:%Y-%m-%d %H:%M}"
                         + ("   REVOKED" if c["revoked"] else "") for c in found)
    control.revoke(args.app, args.company, args.name)
    return f"'{args.name}' can no longer sync."


def main() -> int:
    from sync_server.postgres import postgres_control
    try:
        print(run(postgres_control(os.environ["DATABASE_URL"]), sys.argv[1:]))
    except SyncError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

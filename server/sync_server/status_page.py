"""
status_page.py - The HTML for GET /status: is the server up, and what have the computers been doing.

Shows counts and computer names per company only (from Control.status), never medicines,
patients or users.
"""

from datetime import datetime, timezone
from html import escape

from sync_schema import FORMAT

STYLE = """
:root { color-scheme: light dark; --ok: #1a7f37; --bad: #cf222e; --muted: #6e7781; --line: #d0d7de55; }
body { font: 15px/1.5 system-ui, sans-serif; max-width: 880px; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; } h2 { font-size: 1.05rem; margin: 2rem 0 .5rem; }
.muted { color: var(--muted); font-size: .9rem; }
.pill { display: inline-block; padding: .1rem .6rem; border-radius: 1rem; color: #fff; font-weight: 600; }
.ok { background: var(--ok); } .bad { background: var(--bad); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: .75rem; }
.tile { border: 1px solid var(--line); border-radius: .5rem; padding: .75rem; }
.tile b { display: block; font-size: 1.4rem; font-variant-numeric: tabular-nums; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid var(--line); }
th { font-size: .85rem; color: var(--muted); font-weight: 600; }
td.n, th.n { text-align: right; }
"""


def ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "never"
    seconds = int((now - when).total_seconds())
    if seconds < 60:
        return "just now"
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "min")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'s' if n > 1 and unit != 'min' else ''} ago"
    return "just now"


def _when(when: datetime | None, now: datetime) -> str:
    if when is None:
        return '<span class="muted">never</span>'
    return f'<span title="{when:%Y-%m-%d %H:%M:%S}">{ago(when, now)}</span>'


def _company(entry: dict, now: datetime, now_utc: datetime) -> str:
    """One company's section."""
    title = f'<h2>{escape(entry["app"])}/{escape(entry["company"])}'
    if entry["disabled"]:
        title += ' <span class="pill bad">switched off</span>'
    if entry["error"]:
        return f'{title} <span class="pill bad">{escape(entry["error"])}</span></h2>'
    tiles = "".join(f'<div class="tile"><span class="muted">{label}</span><b>{value}</b></div>' for label, value in (
        ("Last change", f'#{entry["last_seq"]}'),
        ("Last change received", _when(entry["last_change_at"], now_utc)),
        ("Changes, last 24 h", entry["changes_24h"]),
        ("Unused join codes", entry["open_codes"]),
    ))
    revoked, active = '<span class="pill bad">revoked</span>', '<span class="pill ok">active</span>'
    rows = "".join(
        f'<tr><td>{escape(c["name"])}</td><td>{revoked if c["revoked"] else active}</td>'
        f'<td>{_when(c["last_seen"], now)}</td><td class="n">{c["changes_24h"]}</td>'
        f'<td class="n">{c["changes_total"]}</td><td>{c["joined"]:%Y-%m-%d}</td></tr>'
        for c in entry["computers"])
    computers = (f'<table><tr><th>Computer</th><th>Status</th><th>Last seen</th><th class="n">Changes 24 h</th>'
                 f'<th class="n">Changes total</th><th>Joined</th></tr>{rows}</table>' if rows
                 else '<p class="muted">No computers have joined yet.</p>')
    tables = " · ".join(f'{escape(name)} {count}' for name, count in entry["tables"].items())
    return (f'{title}</h2><div class="tiles">{tiles}</div>{computers}'
            f'<p class="muted">Rows: {tables}</p>')


def render(status: dict | None, error: str | None = None) -> str:
    """The whole page. `status` is Control.status(); None with `error` when the database failed."""
    now, now_utc = datetime.now(), datetime.now(timezone.utc)
    head = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta http-equiv="refresh" content="30"><title>MedTracker sync status</title>'
            f'<style>{STYLE}</style></head><body>')
    stamp = f'<p class="muted">Server time {now:%Y-%m-%d %H:%M:%S} · format {FORMAT} · refreshes every 30 s</p>'
    if status is None:
        return (f'{head}<h1>MedTracker sync <span class="pill bad">Database not reachable</span></h1>'
                f'{stamp}<p>{escape(error or "")}</p></body></html>')
    companies = status["companies"]
    body = ("".join(_company(entry, now, now_utc) for entry in companies) if companies
            else '<p class="muted">No companies yet. Create one with the admin key.</p>')
    return (f'{head}<h1>MedTracker sync <span class="pill ok">Running</span></h1>{stamp}'
            f'<p class="muted">{len(companies)} {"company" if len(companies) == 1 else "companies"}</p>'
            f'{body}</body></html>')

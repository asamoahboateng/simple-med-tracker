# Sync server: setup and running

The sync server keeps every MedTracker computer in step. Each computer saves changes locally
first, sends them to this server, and fetches the other computers' changes. This guide is for
whoever runs the server. Design: `docs/superpowers/specs/2026-11-25-multi-computer-sync-design.md`.

| What | Where |
|---|---|
| Address the app uses | `https://sync.kalourmade.com` |
| Code | `server/` and `sync_schema.py` in this repository |
| Runs as | Docker Compose: `db` (Postgres 16) and `api` (Python, port 8000 inside) |

## 1. Install

On the server (Docker and the Compose plugin installed):

```sh
git clone <this repository> medtracker && cd medtracker
cp server/.env.example server/.env
openssl rand -hex 24          # put the result in server/.env as POSTGRES_PASSWORD
docker compose -f server/docker-compose.yml up -d --build
curl -s 127.0.0.1:8000/v1/health          # {"ok":true}
```

The API listens on `127.0.0.1` only (port `SYNC_PORT` in `server/.env`, default 8000), so it can
only be reached through your HTTPS proxy. `server/.env` holds the database password: it is not in
git; keep a copy somewhere safe.

## 2. HTTPS at sync.kalourmade.com

Point a DNS record for `sync.kalourmade.com` at the server and forward it to
`http://127.0.0.1:8000` in the same proxy that serves `s3.kalourmade.com`. For example:

**Caddy**

```
sync.kalourmade.com {
    reverse_proxy 127.0.0.1:8000
}
```

**nginx** (with a certificate from certbot)

```nginx
server {
    server_name sync.kalourmade.com;
    listen 443 ssl;
    client_max_body_size 25m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Check from any computer: `curl -s https://sync.kalourmade.com/v1/health` shows `{"ok":true}`.

## 3. Joining a computer

Each computer joins once, with its own one-time code:

```sh
docker compose -f server/docker-compose.yml exec api python -m sync_server.admin make-code
```

It prints a code like `V7Q3-XCAM`, valid for 24 hours and usable once. On the computer, the
superadmin opens **File → Sync setup...** in MedTracker and enters it.

- The **first** computer to join uploads its data; that becomes the shared data.
- Later computers choose **Use the shared data** (normal) or **Add this computer's data**
  (only when it recorded different things).

## 4. Computers: list and block

```sh
docker compose -f server/docker-compose.yml exec api python -m sync_server.admin computers
docker compose -f server/docker-compose.yml exec api python -m sync_server.admin revoke "FRONT-DESK-PC"
```

Revoke a computer that is lost, stolen or retired. It keeps its local data but can no longer
send or fetch changes; the other computers are not affected. To bring it back, join it again with
a new code. (Times are shown in the server's time zone, usually UTC.)

## 5. Backups of the shared data

The shared data lives in the `pgdata` Docker volume. Back it up nightly, e.g. with cron:

```sh
# /etc/cron.d/medtracker-sync-backup  (02:30 every night; keeps 30 days)
30 2 * * * root cd /path/to/medtracker && docker compose -f server/docker-compose.yml exec -T db pg_dump -U medtracker -Fc medtracker_sync > /var/backups/medtracker-sync-$(date +\%F).dump && find /var/backups -name 'medtracker-sync-*.dump' -mtime +30 -delete
```

Optionally copy each dump to MinIO with `mc cp`. To restore one (this replaces the shared data for
every computer; afterwards use **Reset from shared data** on each computer):

```sh
docker compose -f server/docker-compose.yml exec -T db pg_restore -U medtracker -d medtracker_sync --clean < medtracker-sync-2026-11-25.dump
```

## 6. Updating the server

```sh
git pull
docker compose -f server/docker-compose.yml up -d --build
```

The database tables are created or kept at every start; the data is untouched.

## 7. Developing and testing

```sh
.venv/bin/python -m pytest server/tests                 # rules and HTTP, in memory
docker run -d --rm --name mt-sync-test -e POSTGRES_PASSWORD=t -p 55432:5432 postgres:16
SYNC_TEST_DATABASE_URL=postgresql://postgres:t@127.0.0.1:55432/postgres \
  .venv/bin/python -m pytest server/tests/test_store_pg.py   # the same rules on Postgres
docker stop mt-sync-test
```

## How it decides (short version)

- Every change has its own id; a change sent twice is stored once.
- The server numbers changes; computers fetch "everything after number N".
- The same medicine (same name, ignoring case) or batch added on two computers becomes one.
- Two people registering the same username: the first keeps it; the second is told to register again.
- A medicine or batch still used by entries cannot be deleted; an entry recorded for one that
  another computer deleted brings it back.
- Changing an entry that another computer deleted is refused; the entry stays deleted.

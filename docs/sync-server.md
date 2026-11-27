# Sync server: setup and running

The sync server keeps every MedTracker computer in step. Each computer saves changes locally
first, sends them to this server, and fetches the other computers' changes. One server serves
many apps and many companies: **each company has its own database**. This guide is for whoever
runs the server. Design: `docs/superpowers/specs/2026-11-25-multi-computer-sync-design.md` and
`docs/superpowers/specs/2026-11-26-multi-tenant-sync-design.md`.

| What | Where |
|---|---|
| Address the app uses | `https://sync.kalourmade.com/v1/<app>/<company>`, e.g. `/v1/medtracker/acme` |
| Databases | the control database (`medtracker_sync`: companies, codes, computers) and one per company, e.g. `medtracker__acme` |
| Code | `server/` and `sync_schema.py` in this repository |
| Runs as | Docker Compose: `db` (Postgres 16) and `api` (Python, port 8000 inside) |

## 1. Install

On the server (Docker and the Compose plugin installed):

```sh
git clone <this repository> medtracker && cd medtracker
cp server/.env.example server/.env
openssl rand -hex 24          # put the result in server/.env as POSTGRES_PASSWORD
openssl rand -hex 32          # optional: ADMIN_KEY, to create companies over HTTPS (section 3)
docker compose -f server/docker-compose.yml up -d --build
curl -s 127.0.0.1:8000/v1/health          # {"ok":true}
```

The API listens on `127.0.0.1` only (port `SYNC_PORT` in `server/.env`, default 8000), so it can
only be reached through your HTTPS proxy. `server/.env` holds the database password: it is not in
git; keep a copy somewhere safe. The database login must be allowed to create databases (one per
company): the bundled Postgres's login is; on a shared Postgres, `server/db-init.sql` grants it.

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

**Status page.** Set `STATUS_PASSWORD` in `server/.env` and restart, then open
`https://sync.kalourmade.com/status` and sign in with any username and that password. It shows
whether the database answers and, for every company, the latest change and when it arrived,
changes in the last 24 hours, each computer (last seen, changes sent, active or revoked), row counts
per table and unused join codes; a company whose database is missing is marked. Counts and computer names only, never medicines, patients or users. It refreshes every
30 seconds. With `STATUS_PASSWORD` empty the page does not exist.

## 3. Companies and joining computers

Every company of every app has its own database. Create a company once; it is safe to repeat (an
existing company is left as it is, and you get a new join code):

```sh
docker compose -f server/docker-compose.yml exec api python -m sync_server.admin create medtracker acme
```

```
Created medtracker/acme (database medtracker__acme).
Join code: V7Q3-XCAM
```

Names: lowercase letters, digits and single dashes (`kumasi-clinic`); company names up to 40
characters. Each computer joins once, with its own one-time code (valid 24 hours):

```sh
docker compose -f server/docker-compose.yml exec api python -m sync_server.admin make-code medtracker acme
```

On the computer, the superadmin opens **File → Sync setup...** in MedTracker and enters the code;
the code says which company, so nobody types a company name there.

- The **first** computer of a company uploads its data; that becomes the company's shared data.
- Later computers choose **Use the shared data** (normal) or **Add this computer's data**
  (only when it recorded different things).

**For testing**, create a test company (`create medtracker test`) and join test copies of the app
with its codes. It is a separate database, so it never mixes with a real company.

**Over HTTPS** (e.g. for a sign-up page later), with `ADMIN_KEY` set in `server/.env`:

```sh
curl -X PUT  -H "Authorization: Bearer $ADMIN_KEY" https://sync.kalourmade.com/v1/admin/medtracker/acme
curl -X POST -H "Authorization: Bearer $ADMIN_KEY" https://sync.kalourmade.com/v1/admin/medtracker/acme/codes
curl         -H "Authorization: Bearer $ADMIN_KEY" https://sync.kalourmade.com/v1/admin/medtracker/acme/computers
curl -X POST -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
     -d '{"computer": "FRONT-DESK-PC"}' https://sync.kalourmade.com/v1/admin/medtracker/acme/revoke
```

Without `ADMIN_KEY` those addresses do not exist; the commands on the server always work. Apps
can never create a company themselves.

## 4. Computers and companies: list and block

```sh
docker compose -f server/docker-compose.yml exec api python -m sync_server.admin companies
docker compose -f server/docker-compose.yml exec api python -m sync_server.admin computers medtracker acme
docker compose -f server/docker-compose.yml exec api python -m sync_server.admin revoke medtracker acme "FRONT-DESK-PC"
```

Revoke a computer that is lost, stolen or retired. It keeps its local data but can no longer
send or fetch changes; the other computers are not affected. To bring it back, join it again with
a new code. A computer's key only works for its own company. (Times are shown in the server's
time zone, usually UTC.)

If a company's database goes missing, its computers get "The company's data is not available
right now." and the status page marks it. The server never re-creates it empty by itself: restore
it from a backup (section 5).

## 5. Backups of the shared data

The data lives in Postgres (the `pgdata` Docker volume with the bundled one). Back up **every**
database nightly, the control one and each company's, e.g. with `pg_dumpall` from cron:

```sh
# /etc/cron.d/medtracker-sync-backup  (02:30 every night; keeps 30 days)
30 2 * * * root cd /path/to/medtracker && docker compose -f server/docker-compose.yml exec -T db pg_dumpall -U medtracker | gzip > /var/backups/medtracker-sync-$(date +\%F).sql.gz && find /var/backups -name 'medtracker-sync-*.sql.gz' -mtime +30 -delete
```

One company on its own: `pg_dump -U medtracker -Fc medtracker__acme > acme.dump`.

Optionally copy each dump to MinIO with `mc cp`. To restore one company (this replaces its shared
data for all its computers; afterwards use **Reset from shared data** on each of them):

```sh
docker compose -f server/docker-compose.yml exec -T db createdb -U medtracker medtracker__acme   # if it is missing
docker compose -f server/docker-compose.yml exec -T db pg_restore -U medtracker -d medtracker__acme --clean < acme.dump
```

## 6. Updating the server

```sh
git pull
docker compose -f server/docker-compose.yml up -d --build
```

The control tables are created or kept at every start, and each company's when it is first used;
the data is untouched.

## 7. Developing and testing

```sh
.venv/bin/python -m pytest server/tests                 # rules and HTTP, in memory
docker run -d --rm --name mt-sync-test -e POSTGRES_PASSWORD=t -p 55432:5432 postgres:16
SYNC_TEST_DATABASE_URL=postgresql://postgres:t@127.0.0.1:55432/postgres \
  .venv/bin/python -m pytest server/tests   # the same tests again on Postgres (creates medtracker__* databases)
docker stop mt-sync-test
```

## How it decides (short version)

- Each company's data is in its own database; a computer's key only opens its own company.
- Only the admin (key or command) creates companies and their databases.
- Every change has its own id; a change sent twice is stored once.
- The server numbers changes; computers fetch "everything after number N".
- The same medicine (same name, ignoring case) or batch added on two computers becomes one.
- Two people registering the same username: the first keeps it; the second is told to register again.
- A medicine or batch still used by entries cannot be deleted; an entry recorded for one that
  another computer deleted brings it back.
- Changing an entry that another computer deleted is refused; the entry stays deleted.

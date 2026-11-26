# One sync server for many apps and companies — design

Date: 2026-11-26. Status: approved by the owner (option A: only the admin key creates databases).
Builds on: `2026-11-25-multi-computer-sync-design.md` (one company, one database).

## Intent

The owner wants MedTracker to become a service sold to groups and companies, and wants **one**
sync server for several apps (MedTracker now, others such as a mobile app later). Each company of
each app gets **its own database**, created when the company is set up. Testing uses its own
company on the same server instead of a separate server.

## Goals

- Requests name the app and company in the address: `/v1/<app>/<company>/...`.
- One Postgres database per app + company, e.g. `medtracker__acme`, created when the company is
  created; its tables are created then too.
- A company is created only with the server's **admin key** (owner's decision A), never by an app
  on its own. Creating an existing company is harmless.
- A computer's key works only for its own app + company. Naming another company gets nothing.
- Adding an app means adding its table list (like `sync_schema.TABLES`), not new server logic.
- A test company (e.g. `medtracker/test`) is the way to test; nothing extra to run.

## Non-goals (separate pieces of work)

- Sign-up, payment, or a web page for customers (a sign-up page can later call the admin API).
- A superadmin per company and cloud backups kept apart per company in the app (both needed
  before selling; their own design).
- Moving a company's data between servers.

## Anti-goals

- One company seeing, changing or even confirming the existence of another company's data.
- Anyone without the admin key creating databases.
- A company's database silently re-created empty when it has gone missing (data loss hidden).

## Design

### Names

- App: `[a-z][a-z0-9-]{1,19}`; company: `[a-z0-9][a-z0-9-]{1,39}` (lowercase letters, digits,
  dashes; no underscores). Database name: `<app>__<company>` with dashes turned into underscores,
  e.g. `medtracker__kumasi_clinic`. The double underscore can't come from a name, so two companies
  can never map to one database; the longest name is 62 characters (Postgres allows 63).
- Known apps are listed in the server code: `APPS = {"medtracker": sync_schema.TABLES}`. An
  unknown app is "not found".

### Where things live

- **Control database** (the one in `DATABASE_URL`, e.g. `medtracker_sync`, renamed in meaning to
  "control"): `tenants` (app, company, database name, created, disabled), `join_codes` and
  `devices` (each with app + company).
- **One database per company:** that company's `changes`, `seen_changes`, `rows`, `aliases`
  (today's tables, unchanged).
- The server connects to company databases on the same Postgres with the same login as the control
  database, changing only the database name. That login needs `CREATEDB` (granted in
  `server/db-init.sql`).

### Addresses

| Request | Who | What |
|---|---|---|
| `GET /v1/health` | anyone | `{"ok": true}` |
| `POST /v1/join` `{code, computer}` | anyone with a code | `{device, token, empty, app, company}`; the code says which company |
| `POST /v1/<app>/<company>/changes`, `GET …/changes`, `GET …/snapshot` | that company's computers | as today |
| `PUT /v1/admin/<app>/<company>` | admin key | create the company and its database if missing; returns `{created: bool, code}` (a first join code) |
| `POST /v1/admin/<app>/<company>/codes` | admin key | another join code |
| `GET /v1/admin/<app>/<company>/computers` | admin key | the company's computers |
| `POST /v1/admin/<app>/<company>/revoke` `{computer}` | admin key | block a computer |
| `GET /status` | status password | all companies, counts only (extends the existing page) |

- The admin key is `ADMIN_KEY` in the server's `.env`, sent as `Authorization: Bearer <key>`,
  compared in constant time. No key set → the admin addresses do not exist.
- Join stays one address: the code alone decides the company, so nobody types a company name on a
  computer. The app remembers `<server>/v1/<app>/<company>` from the join answer.
- A computer key used on another company's address → 403 "This computer is not allowed to sync
  with that company." (same answer whether that company exists or not).
- Unknown company on a data address → 404 "Not found." Company disabled → 403.
- Known company whose database cannot be opened → 503 "The company's data is not available right
  now." and an error in the log; it is never re-created automatically.

### Creating a company

`PUT /v1/admin/medtracker/acme` (or `python -m sync_server.admin create medtracker acme`):
1. If the company exists: return `created: false` and a fresh join code.
2. Otherwise: `CREATE DATABASE medtracker__acme` (if a database of that name already exists, it is
   reused — an earlier attempt may have stopped halfway), create its tables, then add the
   `tenants` row, then return `created: true` and a join code.

### The admin command

`python -m sync_server.admin` gains the app and company: `create APP COMPANY`,
`make-code APP COMPANY`, `computers APP COMPANY`, `revoke APP COMPANY NAME`, `companies`.

### Testing and the live service

The test company `medtracker/test` (or any name) lives on the same server, in its own database.
A test copy of the app joins with a `medtracker/test` code. Running the whole server on the Mac
(`server/docker-compose.yml`) stays available for development.

### What the earlier single-company setup becomes

Nothing is live yet, so there is no data to move. The tables that already exist in the control
database from the single-company version are left alone (and documented as unused).

### The app (for the app-side tasks)

- `config.SYNC_SERVER = "https://sync.kalourmade.com"`; the full address comes from the join answer
  and is stored on the computer (`sync_state.endpoint`).
- Developer override: `MEDTRACKER_SYNC_SERVER` and `MEDTRACKER_DATA_DIR` environment variables,
  so a test copy uses another server and another data folder.

## Left to the builder

- How company stores are cached and connections opened (a small cache per database is enough).
- Exact JSON of the admin answers beyond the fields above.
- Wording of messages, in the app's plain style.

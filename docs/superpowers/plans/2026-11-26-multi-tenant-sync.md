# Multi-company Sync Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One sync server serves many apps and companies, each company in its own Postgres database, created only with the admin key.

**Architecture:** A control database holds companies, join codes and computers. Each company's changes and rows live in their own database, served by today's `Core` rules unchanged. A `Control` class routes each request: the join code or the computer key decides the company, and a cache gives one store per company database.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, Postgres 16, pytest.

**Spec:** `docs/superpowers/specs/2026-11-26-multi-tenant-sync-design.md` (builds on `2026-11-25-multi-computer-sync-design.md`)

## Global Constraints

- App names `^[a-z][a-z0-9-]{1,19}$`; company names `^[a-z0-9][a-z0-9-]{1,39}$`; database `<app>__<company>` with `-` → `_`.
- `APPS = {"medtracker": sync_schema.TABLES}` in `server/sync_server/apps.py`.
- Admin key: env `ADMIN_KEY`, `Authorization: Bearer`, `secrets.compare_digest`; unset → admin addresses answer 404.
- Exact messages: `NOT_ALLOWED = "This computer is not allowed to sync with that company."`, `NOT_FOUND = "Not found."`, `UNAVAILABLE = "The company's data is not available right now."`.
- A missing company database is never re-created by a data request.
- Today's per-company rules (`Core.push/pull/snapshot`) do not change.
- Keep the status page (added by another session) working; it lists every company.
- Commits without `Co-Authored-By`.

## Review Focus

1. **A key from company A on company B's address** → 403 `NOT_ALLOWED`, and the same answer when B does not exist (test in Task 1).
2. **Create called twice, or after a half-finished create** (database exists, no tenants row) → one database, `created` false the second time, no error (Task 2, on Postgres).
3. **Company row exists but its database was dropped** → 503 `UNAVAILABLE`, nothing created (Task 2).
4. **Two companies with names that differ only in dashes vs. nothing** (`a-b`, `ab`) → two databases (`app__a_b`, `app__ab`) (Task 1).
5. **A join code for company A** puts the computer in A only; its pushes land in A's database and never in B's (Task 1 and Task 3).

---

### Task 1: Companies, codes and computers (control layer, in memory)

**Files:**
- Create: `server/sync_server/apps.py`, `server/sync_server/control.py`
- Modify: `server/sync_server/store_memory.py` (add `MemoryControlStore`), `server/sync_server/core.py` (move join codes and computers out of `Core` into `Control`; `Core` keeps push/pull/snapshot/status-counts for one company)
- Test: `server/tests/test_control.py`; adjust `server/tests/test_core.py`'s `device()` helper to push directly (Core no longer joins)

**Interfaces:**
- Produces:
  - `apps.APPS: dict[str, dict]`; `apps.database_name(app: str, company: str) -> str` (raises `SyncError(404, NOT_FOUND)` for an unknown app or a bad name).
  - `class Control(control_store, open_company: Callable[[str, str], Core], create_database: Callable[[str], None])`:
    - `create_company(app, company, now) -> dict` → `{"created": bool, "code": str}`.
    - `make_code(app, company, now) -> str`; `join(code, computer, now) -> dict` → `{"device", "token", "empty", "app", "company"}`.
    - `core_for(token, app, company, now) -> Core` (401 unknown key, 403 `REVOKED`, 403 `NOT_ALLOWED` wrong company, 403 disabled company; 503 `UNAVAILABLE` when `open_company` raises `LookupError`).
    - `computers(app, company) -> list[dict]`; `revoke(app, company, name) -> None`; `companies() -> list[dict]`.
  - `MemoryControlStore` with `transaction()`, tenants, codes (with app/company), devices (with app/company).
- Consumes: today's `Core`, `MemoryStore`, `normal_code`, hashing helpers.

- [ ] **Step 1: Write failing tests** in `server/tests/test_control.py` (a `Control` over `MemoryControlStore`, `open_company` returning a `Core(MemoryStore())` per database name from a dict, `create_database` adding to that dict):

```python
def test_database_names():  # ("medtracker","kumasi-clinic") -> "medtracker__kumasi_clinic"; "a-b" vs "ab" differ
@pytest.mark.parametrize("app,company", [("Med","x"), ("medtracker","A_B"), ("medtracker",""), ("nope","x"), ("medtracker","x"*41)])
def test_bad_names_not_found(app, company)
def test_create_company_once():  # created True then False; one database made; both return codes
def test_join_code_belongs_to_its_company():  # join -> app/company of the code; empty True
def test_key_only_works_for_its_company():  # core_for(token,"medtracker","b") -> 403 NOT_ALLOWED, same for "nope-co"
def test_pushes_land_in_own_company():  # A pushes a medicine; B's snapshot has none
def test_revoke_and_disabled():
def test_missing_database_503():  # open_company raises LookupError -> SyncError 503 UNAVAILABLE, create_database not called
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest server/tests/test_control.py` — Expected: FAIL (no `control`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/python -m pytest server/tests` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Sync server: companies, join codes and computers per company"`

### Task 2: Postgres — control database and one database per company

**Files:**
- Modify: `server/sync_server/store_pg.py` (`PostgresControlStore`, `PostgresStore` unchanged per company), `server/sync_server/schema.sql` → split into `control.sql` (tenants, join_codes, devices) and `company.sql` (changes, seen_changes, rows, aliases), `server/db-init.sql` (`ALTER ROLE … CREATEDB`)
- Create: `server/sync_server/postgres.py` — `create_database(dsn, name)` (autocommit `CREATE DATABASE`, ignore "already exists", then apply `company.sql`), `opener(dsn) -> Callable[[str, str], Core]` (cached `Core(PostgresStore(dsn with dbname))`; a missing database → `LookupError`)
- Test: `server/tests/test_control_pg.py` (skipped without `SYNC_TEST_DATABASE_URL`; the login must have CREATEDB; drops `medtracker__t_*` databases it made)

- [ ] **Step 1: Failing tests:** the Task 1 tests on Postgres, plus:

```python
def test_create_twice_and_after_half_create()   # database made by hand first -> create works, created True; again -> False
def test_dropped_database_503()                 # DROP DATABASE after create -> core_for -> 503, database not re-created
```

- [ ] **Step 2: Run** with the Postgres container (as in `docs/sync-server.md` §7) — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS; also `server/tests/test_store_pg.py` still passes.
- [ ] **Step 5: Commit** `git commit -m "Sync server: control database and one database per company"`

### Task 3: Addresses, admin API, admin command, status page, deploy files, docs

**Files:**
- Modify: `server/sync_server/app.py` (`create_app(control, status_password=None, admin_key=None)`; routes from the spec's table), `server/sync_server/admin.py` (`create`, `make-code`, `computers`, `revoke`, `companies`, each with APP COMPANY), `server/sync_server/status_page.py` (a section per company), `server/docker-compose.yml`, `server/docker-compose-traefik.yml`, `server/.env.example`, `server/.env.traefik.example` (`ADMIN_KEY`), `docs/sync-server.md`, `.github/workflows/deploy_sync_server.yml` (only if it reads env names)
- Test: `server/tests/test_app.py` (rewrite for the new addresses)

- [ ] **Step 1: Failing tests:**

```python
def test_admin_create_needs_key()                  # no/wrong key -> 401; no ADMIN_KEY configured -> 404
def test_admin_create_then_join_push_pull()        # PUT /v1/admin/medtracker/acme -> code; POST /v1/join -> company "acme";
                                                   # POST /v1/medtracker/acme/changes ok; GET /v1/medtracker/other/changes -> 403 NOT_ALLOWED
def test_unknown_app_404()
def test_status_page_lists_companies()
def test_admin_cli_create_and_make_code()
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest server/tests/test_app.py` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the whole suite; then the compose smoke test: `docker compose -f server/docker-compose.yml up -d --build`, `PUT /v1/admin/medtracker/test` with the key, join, push, pull over HTTP; `down -v`. Expected: all OK.
- [ ] **Step 5: Commit** `git commit -m "Sync server: per-company addresses and admin API"`

### Effect on the app plan (2026-11-25-multi-computer-sync.md)

When the app tasks run: Task 5's `sync_http` takes the stored company address (`sync_state.endpoint`, from the join answer's app/company) instead of `config.SYNC_ENDPOINT`; join posts to `<config.SYNC_SERVER>/v1/join`; Task 9 adds the `MEDTRACKER_SYNC_SERVER` and `MEDTRACKER_DATA_DIR` overrides.

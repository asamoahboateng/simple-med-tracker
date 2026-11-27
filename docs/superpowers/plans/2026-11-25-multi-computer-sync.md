# Multi-computer Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every MedTracker computer keeps its local SQLite database and stays in step with the others through a sync server at `https://sync.kalourmade.com`, working offline and catching up when the internet returns.

**Architecture:** SQLite triggers copy every change of a synced table into a local `outbox` in the same database transaction. A background thread sends the outbox to a FastAPI + Postgres server, which validates, numbers and stores each change, merges duplicate medicines/batches, and hands changes to the other computers by running number. Computers join once with a one-time join code; each holds its own token in the OS secure store.

**Tech Stack:** App: Python 3.12, PySide6, SQLite, `urllib`, `keyring`. Server: Python 3.12, FastAPI, uvicorn, psycopg 3, Postgres 16, Docker Compose. Tests: pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-multi-computer-sync-design.md`, with addresses per company from `docs/superpowers/specs/2026-11-26-multi-tenant-sync-design.md`

**Status (2026-11-27):** Tasks 3 and 4 (the server) are done and deployed, rebuilt for many apps and companies by `2026-11-26-multi-tenant-sync.md`. Still to build: Tasks 1, 2 and 5–9 (the app). Where this plan says `endpoint`, it now means the company address `<server>/v1/<app>/<company>` (see Task 5).

## Global Constraints

- Sync server `https://sync.kalourmade.com` in `config.SYNC_SERVER`; each computer syncs with its company address `<SYNC_SERVER>/v1/medtracker/<company>`, saved as `sync_state['endpoint']` from the join answer; HTTPS only, except `http://127.0.0.1`/`localhost` (tests), as in `s3client._url`.
- Data format sent with every request: header `X-MedTracker-Format: 1` (`sync_schema.FORMAT = 1`).
- Local schema version becomes `SCHEMA_VERSION = 9`.
- Only password and PIN **hashes** travel; never plain passwords. The token is never logged or shown.
- No network call on the GUI thread; saving locally never waits on the network.
- Background threads open their **own** SQLite connection to the database file (the GUI connection belongs to the GUI thread).
- Demo mode: no sync controller, no network.
- A computer that never joins behaves exactly as today (triggers record nothing, menus unchanged except **File → Sync setup…** for the superadmin).
- Messages in the app's plain style. Exact strings fixed by this plan:
  - `OFFLINE = "Cannot reach the sync server. Changes are saved on this computer and will be sent later."`
  - `REVOKED = "This computer is no longer allowed to sync. Ask the person who runs the sync server."`
  - `TOO_OLD = "Update MedTracker to keep syncing."`
  - `BAD_CODE = "That join code is not valid or has expired."`
- Indicator texts: `"● Up to date"`, `"↻ Syncing…"`, `"● Offline — {n} waiting"`, `"● Sync problem"`.
- Fetch every 60 s; retry sending every 30 s while it fails; push at most 500 changes per request; pull at most 1000 per request; flush on close for at most 3 s.
- Keyring service `"MedTracker sync"`, name `"token"`.
- Git commits: no `Co-Authored-By` lines (owner's rule).

## Review Focus

1. **Same data, same balances everywhere:** two computers holding the same rows must show identical `balance_after` for every entry even if their clocks differ — ordering is `date, entered_at, uid` on every computer (test in Task 5).
2. **Connection drops after the server stored a push but before the reply:** resending the same changes must not duplicate anything (server dedupes on `change_uid`; test in Task 3 and Task 5).
3. **MedTracker closed with unsent changes:** they stay in the outbox and are sent at the next start (test in Task 5).
4. **Editing an entry another computer deleted:** the edit is refused, the entry disappears locally, both audit rows survive (test in Task 5).
5. **A first upload of a large database (thousands of rows):** sent in 500-change requests in order, nothing lost, references always resolve (test in Task 5).

---

## File Structure

| File | Responsibility |
|---|---|
| `sync_schema.py` (new, repo root) | The synced tables: wire fields, keys, references. Shared by app and server. |
| `db.py` (modify) | Schema v9: `uid`/`made_on` columns, `outbox`, `sync_state`, `sync_flags`, triggers; small helpers. |
| `sync_local.py` (new) | No Qt, no network: read/clear the outbox, apply fetched changes, load a snapshot, seed the outbox, recompute balances. |
| `sync_http.py` (new) | No Qt: the HTTP calls to the server, error → message mapping. |
| `sync_engine.py` (new) | No Qt: one sync round (push, handle refusals, pull), joining, the token in keyring. |
| `logic.py` (modify) | Undo only this computer's entries; "Below zero" stock status. |
| `ui/sync_flow.py` (new) | Indicator button, timers, background thread, refresh/sign-out after changes, 24 h warning, flush on close. |
| `ui/sync_setup.py` (new) | Join dialog (code, first/shared/merge) and "Reset from shared data". |
| `ui/main_window.py`, `ui/about.py` (modify) | Menu items, indicator placement, hiding restore while joined, About lines. |
| `server/sync_server/core.py` | Server rules: validation, numbering, dedupe, merges, refusals, join codes, tokens. Storage-agnostic. |
| `server/sync_server/store_memory.py` | In-memory store (tests, app test fixture). |
| `server/sync_server/store_pg.py`, `server/sync_server/schema.sql` | Postgres store. |
| `server/sync_server/app.py` | FastAPI endpoints. |
| `server/sync_server/admin.py` | CLI: `make-code`, `computers`, `revoke NAME`. |
| `server/Dockerfile`, `server/docker-compose.yml`, `server/requirements.txt` | Running it. Build context is the repo root so `sync_schema.py` is copied in. |
| `docs/sync-server.md` (new) | Deploying at sync.kalourmade.com, join codes, backups, revoking. |
| `tests/…`, `server/tests/…` | Tests. `pytest.ini` gains `server/tests` and `pythonpath = . server`. |

### Wire format (used by every task)

A **change** is a dict:

```python
{"change_uid": "<32 hex>", "table": "medicines", "key": "<row uid, or unit name>",
 "op": "upsert" | "delete" | "merge",
 "data": {...wire fields...} | None,      # upsert only
 "into": "<key>" | None}                  # merge only: rows of `key` now belong to `into`
```

The server adds `"seq": int` and `"device": "<device id>" | None` (None = made by the server, e.g. a merge).

Wire fields per table (`sync_schema.TABLES`, in this dependency order):

| Table | key | Wire fields (besides the key) | References |
|---|---|---|---|
| `units` | `name` | — | — |
| `users` | `uid` | username, full_name, password_hash, pin_hash, can_delete_medicines, role, status, created_at, decided_by, decided_at | — |
| `medicines` | `uid` | name, unit, reorder_level, note, created_at | — |
| `batches` | `uid` | medicine_uid, batch_no, expiry_date, created_at | medicine_uid → medicines |
| `transactions` | `uid` | date, medicine_uid, batch_uid, type, quantity, patient_id, prescriber, entry_group, entered_at, entered_by, reason, made_on | medicine_uid → medicines, batch_uid → batches |
| `audit_log` | `uid` | changed_at, changed_by, action, reason, tx_id, tx_date, tx_type, medicine, unit, batch_no, old_quantity, new_quantity, patient_id, prescriber, entered_at, entered_by | — |

`balance_after` is never sent (each computer recalculates it). `tx_id` in `audit_log` is informational only.

---

### Task 1: Synced tables and schema version 9 (triggers fill the outbox)

**Files:**
- Create: `sync_schema.py`
- Modify: `db.py` (schema, `init_schema`, new helpers)
- Test: `tests/test_sync_schema.py`

**Interfaces:**
- Produces:
  - `sync_schema.FORMAT: int = 1`; `sync_schema.Table` (frozen dataclass: `name: str, key: str, fields: tuple[str, ...], refs: dict[str, tuple[str, str]]` mapping wire field → (table, local id column), e.g. `{"medicine_uid": ("medicines", "medicine_id")}`); `sync_schema.TABLES: dict[str, Table]` in the order above; `sync_schema.new_uid() -> str` (`uuid4().hex`).
  - `db.SCHEMA_VERSION = 9`. New columns: `uid TEXT UNIQUE` on users, medicines, batches, transactions, audit_log (filled for existing rows during migration with `lower(hex(randomblob(16)))`); `transactions.made_on TEXT NOT NULL DEFAULT ''`.
  - Tables: `outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, change_uid TEXT NOT NULL UNIQUE, table_name TEXT NOT NULL, row_key TEXT NOT NULL, op TEXT NOT NULL, data TEXT)` (data = JSON text or NULL); `sync_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)`; `sync_flags(id INTEGER PRIMARY KEY CHECK (id = 1), record INTEGER NOT NULL DEFAULT 0)` with its one row.
  - `db.set_recording(conn, on: bool) -> None`, `db.is_recording(conn) -> bool`, `db.sync_value(conn, key: str, default: str = "") -> str`, `db.set_sync_value(conn, key: str, value: str) -> None`.
  - Triggers, generated from `sync_schema.TABLES` by `db._sync_trigger_sql() -> str`. Per table exactly **one** AFTER INSERT trigger with no WHEN clause (SQLite does not guarantee the order of several triggers): its body (1) sets `uid` when NULL, (2) for `transactions` sets `made_on` to `sync_state['device_id']` when empty and recording is on, (3) `INSERT INTO outbox … SELECT … WHERE (SELECT record FROM sync_flags WHERE id = 1) = 1`. AFTER UPDATE OF <the table's wire-relevant local columns> (excludes `uid`, `made_on` and `balance_after`) and AFTER DELETE queue `upsert` / `delete` with `WHEN (SELECT record FROM sync_flags WHERE id = 1) = 1`. `data` is built with `json_object(...)`, references resolved by sub-select (`(SELECT uid FROM medicines WHERE id = NEW.medicine_id)`). `change_uid` is `lower(hex(randomblob(16)))`.

- [ ] **Step 1: Write the failing tests** in `tests/test_sync_schema.py`:

```python
def test_v8_database_upgrades_with_unique_uids(tmp_path): ...
    # build a v8 file (copy of the pre-change SCHEMA via sqlite3 + PRAGMA user_version=8, 2 medicines,
    # 1 batch, 2 transactions, 1 user), then db.connect(): user_version == 9,
    # every row in the 5 tables has a 32-char uid, all distinct; outbox empty
def test_new_rows_get_uid_when_not_recording(conn, add): # uid set, outbox empty
def test_recording_queues_insert_with_uid_references(conn, add):
    db.set_recording(conn, True); add()
    rows = outbox rows -> ops/tables == [("upsert","units"), ("upsert","medicines"), ("upsert","batches"), ("upsert","transactions")]
    # (units row only if the unit is new) ; transactions data has medicine_uid == the medicine's uid,
    # batch_uid == the batch's uid, no balance_after key, made_on == db.sync_value(conn,"device_id")
def test_balance_after_only_update_queues_nothing(conn, add): # UPDATE transactions SET balance_after=...
def test_edit_quantity_queues_one_upsert_and_one_audit(conn, add, give)
def test_delete_queues_delete_with_uid(conn, add): # logic.delete_entry -> ("delete","transactions",uid)
def test_rolled_back_save_leaves_no_outbox(conn, add): # dispense too much -> InsufficientStockError, outbox unchanged
def test_users_sync_hashes_only(conn): # auth.register(...) -> data has password_hash, no 'password'
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_sync_schema.py` — Expected: FAIL (`ModuleNotFoundError: sync_schema` / missing columns).
- [ ] **Step 3: Implement** `sync_schema.py` and the `db.py` changes above. Migration in `init_schema` adds the columns with `ALTER TABLE` (no default), fills uids with one `UPDATE … SET uid = lower(hex(randomblob(16))) WHERE uid IS NULL`, then `CREATE UNIQUE INDEX IF NOT EXISTS` on each uid; tables in `SCHEMA` get the columns for new databases. Triggers are `DROP TRIGGER IF EXISTS` + create on every `init_schema`, so they always match `sync_schema`.
- [ ] **Step 4: Run** the new tests, then the whole suite `.venv/bin/python -m pytest` — Expected: all pass (existing tests prove nothing else changed).
- [ ] **Step 5: Commit** `git add sync_schema.py db.py tests/test_sync_schema.py && git commit -m "Schema 9: row uids, outbox and triggers for sync"`

### Task 2: Applying changes on a computer (sync_local)

**Files:**
- Create: `sync_local.py`
- Test: `tests/test_sync_local.py`

**Interfaces:**
- Consumes: Task 1 (`TABLES`, outbox, `set_recording`, `sync_value`).
- Produces:
  - `pending_changes(conn, limit: int = 500) -> list[dict]` — wire changes in outbox order, each with extra `"_id": int`.
  - `mark_sent(conn, outbox_ids: list[int]) -> None`.
  - `@dataclass Applied: tables: set[str], medicine_ids: set[int], users_changed: bool`.
  - `apply_changes(conn, changes: list[dict], own_device: str) -> Applied` — one SQLite transaction with recording off (restored after, even on error); skips changes whose `device == own_device`; `upsert` = insert or update by key, translating `*_uid` refs to local ids; `delete` = delete by key (a missing row is fine); `merge` = for medicines: re-point batches (a batch whose `batch_no` already exists under `into` has its transactions moved to that batch and is deleted) and transactions to `into`, delete the old medicine, or if `into` is not here simply set the row's uid to `into`; for batches: move transactions to `into`, delete old. Saves `last_seq` = max `seq` seen. Recalculates balances of touched medicines.
  - `recompute_balances(conn, medicine_ids: set[int]) -> None` — `balance_after` running sum ordered by `date, entered_at, uid`.
  - `load_snapshot(conn, rows: dict[str, list[dict]], seq: int) -> None` — recording off; deletes all rows of the six tables and the outbox; inserts all rows (TABLES order); recomputes every balance; `last_seq = seq`.
  - `seed_outbox(conn) -> int` — queues an `upsert` for every existing row (TABLES order, transactions ordered by id), returns the count.
  - `is_joined(conn) -> bool` (`sync_value("joined") == "1"`), `device_id(conn) -> str`.

- [ ] **Step 1: Write the failing tests** (two databases `a`, `b` made with `db.connect`; a helper `ship(src, dst)` = `apply_changes(dst, [dict(c, seq=i+1, device="A") for i, c in enumerate(pending_changes(src))], own_device="B")`):

```python
def test_dispense_on_a_shows_on_b(): # add+give on A (recording on) -> ship -> b's log has the entry, stock 90
def test_two_dispenses_add_up(): # shared start; A gives 20, B gives 30, ship both ways -> both stock 50
def test_balances_identical_on_both(): # after the above, {uid: balance_after} equal on A and B
def test_own_changes_skipped(): # apply A's changes to A with own_device="A" -> no duplicate rows
def test_delete_and_edit_apply(): # delete_entry on A -> gone on B; edit_quantity on A -> B quantity updated
def test_merge_medicine_into_existing(): # B has "Amoxicillin"(u1) batch X, A-made "amoxicillin"(u2) batch X & Y arrive,
    # then {"op":"merge","table":"medicines","key":u2,"into":u1} -> one medicine, batch X holds both deliveries, Y moved
def test_applying_does_not_record(): # recording on in B; after apply, B's outbox empty
def test_apply_failure_restores_recording(): # bad change (unknown table) -> raises, record flag back to 1, nothing applied
def test_load_snapshot_replaces_everything_and_clears_outbox()
def test_seed_outbox_orders_references_first(): # medicines before batches before transactions
def test_last_seq_saved()
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_sync_local.py` — Expected: FAIL (`ModuleNotFoundError: sync_local`).
- [ ] **Step 3: Implement** `sync_local.py` with the interfaces above. Unknown table/op raises `ValueError` (the whole apply rolls back).
- [ ] **Step 4: Run** the tests and the whole suite — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Apply sync changes locally: upserts, deletes, merges, snapshots"`

### Task 3: Server rules (core + in-memory store)

**Files:**
- Create: `server/sync_server/__init__.py`, `server/sync_server/core.py`, `server/sync_server/store_memory.py`
- Modify: `pytest.ini` (`testpaths = tests server/tests`, `pythonpath = . server`)
- Test: `server/tests/test_core.py`

**Interfaces:**
- Consumes: `sync_schema.TABLES`, `FORMAT`, wire format.
- Produces:
  - `class SyncError(Exception)` with `.status: int` and `.message: str` (401 bad token, 403 revoked, 400 invalid change, 426 old format, 404 bad join code).
  - `class Core(store)`:
    - `make_code(now: datetime) -> str` — 8 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, shown as `XXXX-XXXX`, single use, valid 24 h, stored as SHA-256.
    - `join(code: str, computer: str, now) -> dict` → `{"device": <uuid hex>, "token": <secrets.token_urlsafe(32)>, "empty": bool}`; only the token's SHA-256 is stored; bad/used/expired code → `SyncError(404, BAD_CODE)`.
    - `device_for(token: str) -> str` — `SyncError(401)` unknown, `SyncError(403, REVOKED)` revoked; updates last seen.
    - `push(device: str, changes: list[dict]) -> dict` → `{"seq": int, "rejected": [{"change_uid", "table", "key", "reason", "current": data | None}]}`. All in one store transaction under one lock (one push at a time). Per change, in order: already-seen `change_uid` → skip; validate (known table, op, every wire field present with the right type, `type` in STOCK_IN/DISPENSED/REMOVED, `quantity > 0`, names/batch_no non-empty, references resolve after aliasing, `role`/`status` allowed values) → invalid = `SyncError(400)` for the whole push (a buggy client, not a conflict); rewrite references through aliases; then:
      - medicine upsert with a new uid whose name (casefold) exists under another uid → record alias, append a server `merge` change (`device=None`), do not store the duplicate;
      - batch upsert whose (medicine, batch_no casefold) exists under another uid → same, for batches;
      - user upsert with a new uid whose username exists → rejected (`current: None`, reason "Username taken");
      - upsert of a uid that was deleted → rejected (`current: None`);
      - medicine/batch delete while transactions still reference it → rejected (`current` = stored row);
      - otherwise store the row and append the change with the next seq.
    - `pull(after: int, limit: int = 1000) -> dict` → `{"changes": [...], "more": bool}`.
    - `snapshot() -> dict` → `{"rows": {table: [data incl. key field]}, "seq": int}`.
    - `computers() -> list[dict]` (name, joined, last_seen, revoked); `revoke(name: str) -> None`.
  - `MemoryStore()` implementing what `Core` needs (the store API is the builder's; keep it small and mirror it in Task 4's Postgres store).

- [ ] **Step 1: Write the failing tests** in `server/tests/test_core.py`:

```python
def test_join_code_single_use_and_expires()      # second use and 25 h later -> SyncError 404
def test_first_join_reports_empty_then_not()
def test_token_hash_only_stored()                # the plain token appears nowhere in the store
def test_push_numbers_changes_and_pull_returns_them_in_order()
def test_repeated_push_is_ignored()              # same change_uid twice -> stored once, seq unchanged
def test_invalid_change_refuses_whole_push()     # quantity 0 -> SyncError 400, nothing stored
def test_duplicate_medicine_name_becomes_merge() # -> pull has op "merge", key new uid, into existing uid
def test_reference_to_merged_medicine_is_rewritten()  # later batch with medicine_uid=alias stored with canonical uid
def test_duplicate_batch_becomes_merge()
def test_duplicate_username_rejected()
def test_delete_medicine_with_entries_rejected_with_current_row()
def test_edit_after_delete_rejected()
def test_revoked_device_refused()                # device_for -> SyncError 403
def test_snapshot_has_every_live_row_and_seq()
def test_pull_limit_and_more_flag()
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest server/tests/test_core.py` — Expected: FAIL (`ModuleNotFoundError: sync_server`).
- [ ] **Step 3: Implement** `core.py` and `store_memory.py`.
- [ ] **Step 4: Run** the tests and the whole suite — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Sync server rules: numbering, validation, merges, join codes"`

### Task 4: Server over HTTP, Postgres, Docker and the admin command

**Files:**
- Create: `server/sync_server/app.py`, `server/sync_server/store_pg.py`, `server/sync_server/schema.sql`, `server/sync_server/admin.py`, `server/Dockerfile`, `server/docker-compose.yml`, `server/requirements.txt`, `server/.env.example`, `docs/sync-server.md`
- Modify: `requirements-dev.txt` (add `fastapi`, `uvicorn`, `httpx` pinned to current releases — dev only, never bundled in the app), `.gitignore` (`server/.env`)
- Test: `server/tests/test_app.py`, `server/tests/test_store_pg.py`

**Interfaces:**
- Consumes: `Core`, `MemoryStore`, `SyncError`.
- Produces:
  - `create_app(core: Core) -> FastAPI`. Endpoints: `POST /v1/join` `{code, computer}`; `POST /v1/changes` `{changes}`; `GET /v1/changes?after=N&limit=M`; `GET /v1/snapshot`; `GET /v1/health` → `{"ok": true}`. All except join and health need `Authorization: Bearer <token>`. Every request except health needs `X-MedTracker-Format`; a value below `FORMAT` → 426 `TOO_OLD`. Errors are JSON `{"message": ...}` with the `SyncError` status. Request bodies over 20 MB → 413.
  - `PostgresStore(dsn: str)` with the same API as `MemoryStore`; `schema.sql` creates `devices`, `join_codes`, `changes (seq BIGSERIAL PRIMARY KEY, change_uid TEXT UNIQUE, …, data JSONB)`, `rows (table_name, row_key, data JSONB, deleted BOOLEAN, seq BIGINT, PRIMARY KEY (table_name, row_key))`, `aliases`. The push lock is `pg_advisory_xact_lock(4242)`. Schema applied at start (idempotent).
  - Module entry `sync_server.app:main` reads `DATABASE_URL` and serves on port 8000.
  - `python -m sync_server.admin make-code | computers | revoke NAME` using `DATABASE_URL`.
  - `docker-compose.yml`: services `db` (`postgres:16`, named volume, healthcheck) and `api` (built from `server/Dockerfile` with context `..`, `DATABASE_URL` from `server/.env`, port `127.0.0.1:8000:8000` so only the HTTPS proxy reaches it, `restart: unless-stopped`).

- [ ] **Step 1: Write the failing tests:** `test_app.py` uses `fastapi.testclient.TestClient(create_app(Core(MemoryStore())))`:

```python
def test_health()
def test_join_then_push_and_pull()
def test_missing_token_401_and_revoked_403_with_message()
def test_old_format_426_too_old()        # header "0" -> 426, json message == "Update MedTracker to keep syncing."
def test_invalid_change_400()
```

`test_store_pg.py` runs the Task 3 core tests' key cases against `PostgresStore`, skipped unless `SYNC_TEST_DATABASE_URL` is set: `pytestmark = pytest.mark.skipif(not os.environ.get("SYNC_TEST_DATABASE_URL"), reason=...)`.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest server/tests/test_app.py` — Expected: FAIL (no `app` module).
- [ ] **Step 3: Implement** the files above.
- [ ] **Step 4: Run** the app tests — Expected: PASS. Then against real Postgres:
  `docker run -d --rm --name mt-sync-test -e POSTGRES_PASSWORD=t -p 55432:5432 postgres:16`, then
  `SYNC_TEST_DATABASE_URL=postgresql://postgres:t@127.0.0.1:55432/postgres .venv/bin/python -m pytest server/tests/test_store_pg.py` — Expected: PASS; `docker stop mt-sync-test`.
- [ ] **Step 5: Smoke-test the compose stack:** `cp server/.env.example server/.env && docker compose -f server/docker-compose.yml up -d --build`, `curl -s 127.0.0.1:8000/v1/health` — Expected: `{"ok":true}`; `docker compose -f server/docker-compose.yml exec api python -m sync_server.admin make-code` prints a `XXXX-XXXX` code; `docker compose … down`.
- [ ] **Step 6: Write** `docs/sync-server.md`: copy `server/` + `sync_schema.py` to the server (or clone the repo), set `server/.env` (strong Postgres password), `docker compose up -d`, point `sync.kalourmade.com` at `127.0.0.1:8000` through the existing HTTPS proxy, making join codes, listing/revoking computers, nightly `pg_dump` (example cron line writing to a dated file, optionally uploaded with `mc` to MinIO), and updating the server (`git pull && docker compose up -d --build`).
- [ ] **Step 7: Commit** `git commit -m "Sync server: FastAPI, Postgres store, Docker Compose, admin command"`

### Task 5: Sync round on a computer (HTTP client + engine)

**Files:**
- Create: `sync_http.py`, `sync_engine.py`
- Modify: `config.py` (`SYNC_SERVER = "https://sync.kalourmade.com"`), `tests/conftest.py` (fixture `sync_server`)
- Test: `tests/test_sync_engine.py`

**Interfaces:**
- Consumes: Task 2 (`pending_changes`, `mark_sent`, `apply_changes`, `load_snapshot`, `seed_outbox`, `is_joined`, `device_id`), the server (`create_app(control, admin_key=...)`, `store_memory.memory_control()`).
- Produces:
  - `sync_http`: `class SyncHTTPError(Exception)` (`.message`, `.status` — 0 for network); messages `OFFLINE`, `REVOKED`, `TOO_OLD`, `BAD_CODE` (Global Constraints) for network / 401 or 403 / 426 / 404; other statuses → `"The sync server had a problem ({status}). Try again later."`. Functions: `join(server, code, computer) -> dict` (posts to `<server>/v1/join`; the answer has `device`, `token`, `empty`, `app`, `company`), `company_endpoint(server, app, company) -> str` (→ `<server>/v1/<app>/<company>`), `push(endpoint, token, changes) -> dict`, `pull(endpoint, token, after, limit=1000) -> dict`, `snapshot(endpoint, token) -> dict`. JSON over `urllib`, timeout 30 s, `User-Agent` like `s3client.USER_AGENT`, header `X-MedTracker-Format`.
  - `sync_engine`:
    - `load_token() -> str`, `save_token(token: str) -> None` (keyring `"MedTracker sync"`/`"token"`; errors → `""` / `SyncHTTPError`-free `RuntimeError` with message "This computer cannot store the sync key securely.").
    - `@dataclass SyncResult: sent: int = 0, received: int = 0, waiting: int = 0, applied: Applied | None = None, error: str = "", status: int = 0, refused_users: list[str] = field(default_factory=list)`.
    - `sync_once(conn, endpoint: str, token: str) -> SyncResult` — push pending in 500s (`mark_sent` after each success; refusals: apply each `current` with recording off, or delete the local row when `current` is None — a refused new user's pending account is removed and named in `refused_users` so the UI says "Username taken — register again"); then pull in 1000s until `more` is false and apply. Network/HTTP failure stops the round and returns `error` (and `status`), keeping what already succeeded. `waiting` = outbox count afterwards.
    - `join_computer(conn, server: str, code: str, computer: str, mode: str, joined: dict | None = None) -> None` — saves `sync_state['endpoint'] = company_endpoint(server, joined['app'], joined['company'])` and syncs with that address from then on; a 403 from it is shown as `REVOKED` — `mode` in `"first" | "shared" | "merge"`; calls `join` unless `joined` (an earlier `sync_http.join` result) is given, saves token, sets `device_id`, `joined=1`, recording on; `"first"`/`"merge"`: `seed_outbox` and push everything; then (all modes) `snapshot` → `load_snapshot`. Recording stays on afterwards. Making the local safety backup is the caller's job (UI).
  - Fixture `sync_server` in `tests/conftest.py`: runs `uvicorn` with `create_app(memory_control(), admin_key="test")` in a thread on a free `127.0.0.1` port, with company `medtracker/test` created; yields an object with `.server`, `.endpoint` (the company address), `.control`, `.stop()`/`.start()` (to simulate the internet going down), and `.code()` (a fresh join code).

- [ ] **Step 1: Write the failing tests** in `tests/test_sync_engine.py` (two databases joined to one `sync_server`; `a` joins `"first"`, `b` joins `"shared"`):

```python
def test_dispense_on_a_seen_on_b()               # spec's main promise
def test_offline_dispense_sent_when_back()       # server.stop(); give on a; sync_once -> error == OFFLINE, waiting == 1;
                                                 # server.start(); sync_once -> sent 1; b sees it
def test_outbox_survives_restart()               # give, close a's conn, reopen file, sync_once sends it   (Review Focus 3)
def test_lost_reply_resend_no_duplicate()        # push succeeds on server but mark_sent skipped (monkeypatch) -> next round: one row on b   (Review Focus 2)
def test_balances_identical_with_skewed_clocks() # entries with now= different clocks on a and b -> same balance_after per uid  (Review Focus 1)
def test_edit_of_deleted_entry()                 # a deletes, b edits same entry offline then syncs -> gone on b, both audit rows on both  (Review Focus 4)
def test_large_first_upload_in_batches()         # 1200 transactions on a before joining "first" -> b has all 1200   (Review Focus 5)
def test_same_medicine_added_offline_merges()    # both add "Amoxicillin" offline -> one medicine on both, stock is the sum
def test_join_shared_replaces_local_data()
def test_join_merge_adds_local_data()
def test_revoked_computer_message()              # core.revoke(name) -> error == REVOKED
def test_bad_join_code_message()                 # -> SyncHTTPError message BAD_CODE, nothing changed locally
def test_user_approved_on_a_can_sign_in_on_b()
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_sync_engine.py` — Expected: FAIL (`ModuleNotFoundError: sync_http`).
- [ ] **Step 3: Implement** `sync_http.py`, `sync_engine.py`, the config value and the fixture.
- [ ] **Step 4: Run** the tests and the whole suite — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Sync engine: push, pull, refusals and joining"`

### Task 6: Undo per computer and "Below zero" stock

**Files:**
- Modify: `db.py` (`last_entry_rows`), `logic.py` (`stock_status`), the stock/dashboard/search widgets that colour statuses (find them with `grep -rn "stock_status\|OUT_OF_STOCK" ui`)
- Test: `tests/test_undo.py`, `tests/test_stock.py`

**Interfaces:**
- Consumes: `transactions.made_on`, `db.sync_value(conn, "device_id")`.
- Produces: `db.last_entry_rows(conn)` considers only rows with `made_on IN ('', <this device_id>)` (unjoined computers: device_id is `""`, so behaviour is unchanged). `logic.stock_status(stock, reorder_level)` returns `"Below zero"` when `stock < 0` (constant `BELOW_ZERO`), shown in the same red as "Out of stock" and counted in the low-stock list.

- [ ] **Step 1: Write the failing tests:**

```python
def test_undo_skips_entries_from_other_computers(conn, add, give):
    # set device_id "A"; add (made_on "A"); insert a remote row via sync_local.apply_changes with made_on "B" and later entered_at
    # undo_last_entry removes the "A" entry, the "B" row stays
def test_below_zero_status():
    assert logic.stock_status(-5, 10) == "Below zero"
```

- [ ] **Step 2: Run** them — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them and the whole suite — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Undo only this computer's entries; show stock below zero"`

### Task 7: The sync indicator, timers and window wiring

**Files:**
- Create: `ui/sync_flow.py`
- Modify: `ui/main_window.py`, `ui/about.py`
- Test: `tests/test_sync_flow.py`

**Interfaces:**
- Consumes: `sync_engine.sync_once`, `load_token`, `sync_local.is_joined`, `pending_changes`, `sync_state['endpoint']`.
- Produces:
  - `ui.sync_flow.indicator_text(result: SyncResult | None, busy: bool) -> str` and `tooltip_text(last_success: float | None, now: float, error: str) -> str` (pure).
  - `class SyncController(QObject)` — `__init__(window, db_path: Path, conn, user)`; `.button` (QPushButton, `kind=link`, placed next to `☁ Back up`); `sync_now() -> None`; `notify_saved() -> None` (called from `window.data_changed`: starts a sync soon). One round at a time across window rebuilds (module-level `_busy`, `_active` weakref, relay signal — the `ui/cloud_backup_flow.py` pattern). Rounds run in a thread with **their own** `db.connect(db_path)`. QTimers: fetch every 60 000 ms; after a failed round, retry every 30 000 ms. After a round that applied changes: `window.data_changed()`; if `applied.users_changed`: `window.check_access()` (signs out a revoked/demoted user). Records `sync/last_success` in QSettings. `flush(timeout_s: float = 3.0) -> None` for close.
  - 24-hour warning (the spec's banner, shown in the indicator instead so nothing new is added above the pages): more than 24 h since `last_success` → indicator text `"● Not synced for {days} days"` in amber, with the last error in the tooltip.
  - `MainWindow`: `self.sync = SyncController(...)` only when not demo and `is_joined(conn)`; **File → Sync now** (Ctrl+Shift+S) when joined; **File → Sync setup…** (superadmin, not demo) always; when joined, **Restore from backup…** and **Restore from cloud backup…** are replaced by **Reset from shared data…** (superadmin). `closeEvent` calls `self.sync.flush()`.
  - `AboutDialog` / `system_details(...)` gains rows `Sync server` (company address or "Not joined"), `This computer` (device name), `Last sync`.

- [ ] **Step 1: Write the failing tests** (`qapp`, `isolated_settings`, `sync_server`, a joined database):

```python
@pytest.mark.parametrize(...)  # indicator_text: None/busy -> "↻ Syncing…"; error OFFLINE with waiting 3 -> "● Offline — 3 waiting";
                               # other error -> "● Sync problem"; ok -> "● Up to date"
def test_round_applies_and_refreshes_window()      # change made via second db -> sync_now -> window.data_changed called
def test_revoked_user_signed_out_after_sync()       # user revoked on other computer -> check_access called -> signed_out emitted
def test_one_round_at_a_time()                      # double sync_now -> one round (blocked engine, like cloud tests)
def test_not_joined_has_no_indicator_and_shows_setup_for_superadmin()
def test_joined_menu_replaces_restore_with_reset()
def test_demo_has_no_sync()
def test_about_shows_sync_rows()
def test_not_synced_for_days_text()
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_sync_flow.py` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests and the whole suite — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Sync indicator, background sync and menu wiring"`

### Task 8: Joining and "Reset from shared data" dialogs

**Files:**
- Create: `ui/sync_setup.py`
- Modify: `ui/main_window.py` (open the dialogs; rebuild the window after joining or resetting via the existing `restyle_requested` path so the sync controller starts)
- Test: `tests/test_sync_setup.py`

**Interfaces:**
- Consumes: `sync_engine.join_computer`, `sync_local.load_snapshot`, `sync_http.snapshot`, `db.backup_to`, `config.backups_dir()`.
- Produces:
  - `class SyncSetupDialog(QDialog)` — fields: join code (accepts with/without dash, any case), computer name (default `socket.gethostname()`); after the code is accepted by the server the dialog knows `empty`: when empty it says "This is the first computer: its data becomes the shared data." and uses mode `"first"`; otherwise two choices: **Use the shared data (recommended)** → `"shared"`, **Add this computer's data to the shared data** → `"merge"`, with the warning "Only choose this if this computer recorded different things. Entries copied from another computer will be counted twice." Before joining it saves `config.backups_dir() / f"before_sync_{stamp}.db"`. The work runs in a background thread with a busy cursor/message; errors are shown with `show_error` and nothing is marked joined.
    - Because `join` consumes the code, the dialog first calls `sync_http.join` itself (to learn `empty`), then passes that result as `joined=` to `join_computer`.
  - `reset_from_shared(window) -> bool` — confirm ("Replace this computer's data with the shared data? Changes not yet sent are sent first."), push pending first, safety backup `before_reset_{stamp}.db`, `snapshot` → `load_snapshot`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_first_computer_join_uploads_data()      # empty server -> mode first -> server snapshot has the medicines
def test_second_computer_shared_replaces()       # backup file before_sync_*.db exists; local data == shared
def test_second_computer_merge_adds()
def test_bad_code_shows_message_and_not_joined()
def test_code_format_normalised()                # "abcd efgh" / "ABCD-EFGH" both sent as "ABCD-EFGH"
def test_reset_from_shared_sends_pending_first()
```

- [ ] **Step 2: Run** them — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them and the whole suite — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Join a computer to sync, and reset from shared data"`

### Task 9: Docs, build and an end-to-end check against Docker

**Files:**
- Modify: `README.md` (Sync section: what it does, joining, the indicator, offline, below zero, reset, restore hidden while joined; files table: `sync_*.py`, `server/`), `medtracker.spec` (only if PyInstaller misses a module; `sync_*` are plain imports), `.github/workflows/build.yml` (run `server/tests` too; optional Postgres service with `SYNC_TEST_DATABASE_URL`)

- [ ] **Step 1:** Start the stack (`docker compose -f server/docker-compose.yml up -d --build`), make two codes, run the app twice against `http://127.0.0.1:8000` using two data folders (`MEDTRACKER_SYNC_SERVER` and `MEDTRACKER_DATA_DIR` env overrides read by `config` only when set — add with a test in `tests/test_sync_engine.py`; codes from `python -m sync_server.admin create medtracker test`), join first/shared, dispense on one, click **Sync now** on the other. Expected: the entry and the lower stock appear; indicator `● Up to date`. Stop the stack, dispense: indicator `● Offline — 1 waiting`; start it: sent within 30 s.
- [ ] **Step 2:** Update README and workflow; run the whole suite. Expected: PASS.
- [ ] **Step 3: Commit** `git commit -m "Sync: README, workflow and local end-to-end check"`

Releasing (version bump, tag) is not part of this plan; the owner asks for it separately, after the server is running at sync.kalourmade.com.

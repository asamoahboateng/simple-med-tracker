# Multi-computer sync — design

Date: 2026-11-25. Status: approved by the owner (join codes; server in this repo, Docker).

## Intent

MedTracker runs on more than one computer. Today each computer has its own SQLite database,
so a dispense on machine 1 is invisible on machine 2. The owner wants **one shared set of data**:
dispense on machine 1 and machine 2 shows the same log entry and the same lower stock.

The owner's rule, in their words: *each system pushes directly to the cloud; every update is
also made on the local database; if the internet goes down, local is used; when the internet
comes back, there's a sync.*

Success: on every computer the medicines, batches, log, stock, audit log, units and users are
the same, within about a minute when all are online, and every computer keeps working offline.

## Goals

- Every change is saved locally first (fast, works offline), then sent to a central server.
- Changes made elsewhere arrive on their own, without anyone pressing anything.
- Nothing entered on any computer is ever lost or counted twice.
- Users and permissions are the same everywhere (an account approved on one PC can sign in on all).
- Someone can see at a glance whether this computer is up to date.

## Non-goals

- Instant (sub-second) updates. Within about a minute is enough.
- Several separate pharmacies with separate data on one server (one shared data set only).
- A web or phone version, or reports on the server. The server only stores and passes changes.
- A screen for resolving conflicts by hand. Conflicts resolve by rules (below).

## Anti-goals (failure even if it "works")

- A dispense that disappears, or one that is counted twice.
- MedTracker freezing or refusing to dispense because the internet is slow or down.
- Two copies of the same medicine ("Amoxicillin" twice) after two PCs added it offline.
- A computer quietly drifting out of step with nobody noticing.

## Constraints (from the project as it is)

- Desktop app in Python 3.12 + PySide6; local SQLite, schema version 8 (`db.py`).
- All writes go through `logic.py` → `db.py`. Stock is never stored: it is the sum of
  `transactions` (STOCK_IN minus DISPENSED and REMOVED).
- Tables: `medicines` (name unique, case-insensitive), `batches` (unique per medicine +
  batch number), `transactions` (with a stored running `balance_after` and an `entry_group`
  shared by rows saved together), `units` (name is the key), `users` (username unique),
  `audit_log` (append-only copy of every edit/delete/undo).
- Rows are numbered 1, 2, 3… per computer (INTEGER AUTOINCREMENT), and the code passes these
  integer ids around everywhere.
- Log entries can be edited (quantity) and deleted, not only added. "Undo last entry" removes the
  highest-numbered entry group.
- The superadmin is not a database row (signs in with a code built into the app).
- The owner already runs MinIO at `s3.kalourmade.com` behind HTTPS; cloud backup and
  auto-update (GitHub Releases) already exist and stay.
- Demo mode never touches the network.

## Approaches considered

1. **Own sync server (chosen).** A small Python web service with Postgres, run in Docker on the
   owner's server. MedTracker records each change in a local outbox, sends it at once when
   online, and fetches other computers' changes by a running number. Full control, matches the
   existing Python code and tests, the server checks every change, each PC can be blocked
   separately. Costs: the most to build (server plus sync in the app) and one more service to run.
2. **PowerSync / ElectricSQL** (Postgres to SQLite sync products). Rejected: made for web and
   mobile apps; no Python desktop client.
3. **Turso / libSQL replicas** (SQLite in the cloud). Rejected: writes must reach the server, so
   offline work is not properly supported, which breaks the owner's "internet down → use local"
   rule.
4. **MedTracker writes straight to Postgres.** Rejected: the database password would ship inside
   the installer and nothing would check what is written.

The owner picked approach 1.

## Design

### Identity of records

Each synced table gets a `uid` column: a random UUID made on the computer that creates the row,
the same on every computer. The local integer `id` stays (all existing code keeps working);
changes sent between computers refer to rows, and to each other, only by `uid`. Natural keys
also count: a unit is identified by its name.

### What a change is

A change is one row's new state (or its deletion), plus: change uid, table, row uid, the
computer it came from, the user who made it, and when. Saving one dispense (possibly several
`transactions` rows in one `entry_group`) produces one bundle of changes that is applied
all-or-nothing, locally and on the server.

Every local write that `logic.py` already makes inside `with transaction(conn):` also writes
its changes into a local **outbox** table in the same SQLite transaction, so a change can never
be saved without being queued for sending, or the other way round.

### Sending and fetching

- **Send:** right after a local save, a background thread sends the outbox to the server
  (`POST /v1/changes`). The server stores each bundle once (repeating a bundle is harmless,
  matched by change uid), gives it the next running number, and answers. Sent items leave the
  outbox. If sending fails (offline, server down), they stay and are retried: every 30 seconds
  while failing, and immediately when a fetch succeeds.
- **Fetch:** every 60 seconds while MedTracker is open, when it starts, after it sends, and when
  someone clicks **Sync now**, it asks `GET /v1/changes?after=<last number seen>` and applies what
  comes back, in order, skipping its own changes.
- **Closing:** MedTracker tries to send the outbox before quitting (a few seconds at most);
  anything left is sent next time it opens.
- Network work never runs on the screen's thread; the app never waits on the network to save.

### Applying changes from other computers

- Inserts and updates are applied by `uid`; local integer ids are found or created locally.
- **Stock adds up.** A dispense is its own row, so 20 dispensed on machine 1 and 30 on machine 2
  give 50 less everywhere, in any order.
- **Running balance.** `balance_after` is recalculated for every medicine touched by the applied
  changes, ordered by date, then time entered, then uid, so the log reads correctly on every
  computer.
- **Same medicine added on two PCs offline.** The server owns the rule: when a new medicine's
  name already exists (ignoring case), the server answers that this uid is the existing medicine's
  uid. The sending computer then merges its copy into it (re-pointing its batches and entries)
  and the name is never duplicated. Batches merge the same way by medicine + batch number.
  Units merge by name.
- **Same row changed on two PCs.** The change the server numbered later wins for that row
  (for example two edits to one entry's quantity). A deletion beats an edit made at the same time.
  Every edit and delete is still in the audit log on all computers, so nothing is hidden.
- **Deleting a medicine** is only accepted by the server if it still has no entries anywhere. If
  another computer has added stock meanwhile, the server refuses, and the computer that deleted
  it gets the medicine back.
- **Negative stock.** Offline, two computers can both dispense the last boxes. After sync the
  stock may show below zero. That medicine is flagged (red on the stock page and in the low-stock
  list) until someone corrects it with an entry. Local checks still stop you dispensing more than
  this computer knows is in stock.
- **Undo last entry** undoes the last entry saved **on this computer** (not one that arrived
  from another computer). Editing or deleting any entry works as now and syncs like any change.

### Users and sign-in

- Accounts, roles, approval, revoking, PINs, password changes and the delete-medicines permission
  all sync. Only password and PIN hashes travel, never the passwords themselves.
- Sign-in uses the local copy, so it works offline. A revoke made on another computer takes
  effect here at the next fetch; if a revoked user is signed in, they are signed out then.
- The superadmin stays outside the database (built-in code), as now.
- Two people registering the same username on two PCs offline: the server keeps the first and
  refuses the second; the second computer marks that account "Username taken — register again".

### Joining a computer to sync

Sync is set up once per computer by the superadmin (**File → Sync setup…**), using a one-time
**join code** made on the server (see Security). Then:

- **The first computer** uploads all its data; that becomes the shared data.
- **Every later computer** chooses one of:
  - **Use the shared data (recommended):** this computer's data is backed up locally, then
    replaced with the shared data. Right for a new computer, or one restored from another's
    backup (merging those would count the same entries twice).
  - **Add this computer's data to the shared data:** everything on it is sent as new changes and
    merged by the rules above. Right only when the two computers really recorded different
    things. The screen says plainly that entries copied from another computer will be doubled.
- Before either, the usual local safety copy is made.

### Backups and restore while syncing

- Cloud backup (☁ Back up) and the backup before updates stay as they are.
- **Restore from backup** (local or cloud) on a syncing computer would undo other computers' work,
  so it is replaced by **Reset from shared data** (re-download everything). Restoring the shared
  data itself is a server task, done by whoever runs the server (documented, not in the app).
- The server's Postgres is backed up nightly (documented setup, e.g. a dump to MinIO).

### What the user sees

- Next to **☁ Back up** in the menu bar, a sync indicator:
  `● Up to date` · `↻ Syncing…` · `● Offline — 3 waiting` (amber) · `● Sync problem` (red, with
  the reason on hover and in the log). Hover shows the last successful sync time.
- **File → Sync now** (and clicking the indicator) syncs immediately.
- **Help → About** adds the sync server, this computer's name and the last sync time.
- When fetched changes arrive, open pages (stock, log, dashboard) refresh themselves; anything
  half-typed in a form is left alone.
- An amber banner if this computer has not synced for over 24 hours while it has had internet,
  so drifting is noticed.

### Security

- The server is only reachable over HTTPS (behind the same kind of proxy as MinIO), at
  `https://sync.kalourmade.com`, built into the app (`config.SYNC_ENDPOINT`).
- Each computer has its **own token**, issued when it joins with a one-time join code that the
  person running the server makes with a command on the server. Tokens are stored in the
  computer's secure store (Windows Credential Manager / macOS Keychain), as the MinIO passphrase
  was. A lost computer's token can be revoked on the server without affecting the others.
- No shared secret ships in the installer for sync.
- The server checks every change: known table and fields, types, references exist, quantities
  positive, names not empty, versions compatible. It refuses anything else and says why.
- Requests from a MedTracker too old for the server's data format are refused with "Update
  MedTracker to keep syncing"; the app keeps working locally and the outbox waits.

### The server

- Python 3.12 + FastAPI + Postgres 16, in this repository under `server/` with its own
  `Dockerfile` and `docker-compose.yml` (owner's decision). The owner deploys it on their server
  at `sync.kalourmade.com`; the HTTPS proxy in front of it is theirs, as for MinIO. It runs
  locally with `docker compose up` for development and tests (Docker is on the dev Mac).
- Stores: computers (name, token hash, joined, last seen, revoked), join codes (hash, expiry,
  used), the numbered change log (append-only), and the current state of every row, so a joining
  computer can download everything at once rather than replaying all history.
- Endpoints (all but join need a computer token): `POST /v1/join`, `POST /v1/changes`,
  `GET /v1/changes?after=N`, `GET /v1/snapshot` (everything, with the number it is current to),
  `GET /v1/health`.
- A small command for the owner: make a join code, list computers, revoke a computer.
- Setup and running instructions in `docs/sync-server.md`.

### App side, in short

- Schema version 9: `uid` columns (filled for existing rows), `outbox`, and `sync_state`
  (last number seen, this computer's id, joined or not).
- A sync module without Qt (like `cloud_backup.py`), and a thin Qt part for the indicator,
  timers and dialogs (like `ui/cloud_backup_flow.py`).
- Sync is off until the computer has joined; a computer that never joins behaves exactly as today.

### Rollout

1. Release the server and a MedTracker version with sync (off by default).
2. Join the main computer first (it uploads its data).
3. Join the others with "Use the shared data", unless their data is truly separate.

## Owner's decisions (2026-11-25)

- Approach 1, own sync server.
- Computers join with a one-time join code per computer (not a key built into the installer).
- The server and its Docker setup live in this repository (`server/`), deployed at
  `sync.kalourmade.com`.
- The other calls in this document (60-second fetch, later edit wins, undo is per computer,
  restore replaced by "Reset from shared data" while syncing, "Use the shared data" as the
  default when joining, 24-hour warning) were proposed and not objected to.

## Left to the builder

- Exact wire format, table layouts on the server, endpoint payloads, and the retry back-off.
- How the outbox is written (helper in `db.py` called from each write, or a wrapper around
  `transaction`), as long as change and outbox are in the same SQLite transaction.
- How the server is tested (real Postgres in Docker, or similar) and how its migrations run.
- Wording of messages, following the app's plain-language style.
- How pages refresh when changes arrive.

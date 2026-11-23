# MinIO Cloud Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "☁ Back up" button in the menu bar (next to A− 100% A+) uploads an encrypted copy of the MedTracker database to the Kalourmade MinIO server, and an administrator can restore any of those backups from inside the app.

**Architecture:** Two pure-Python modules (no Qt), tested like `updater.py`: `s3client.py` talks to MinIO over the S3 API with hand-signed (AWS Signature V4) `urllib` requests; `cloud_backup.py` compresses + encrypts, names, uploads, lists and downloads backups. The MinIO keys are written into a generated, git-ignored `cloud_keys.py` at build time (from GitHub Actions secrets, or `.env` locally). `ui/cloud_backup_flow.py` runs uploads in a background thread (same pattern as `ui/update_flow.py`); `ui/cloud_settings.py` holds the setup and restore dialogs.

**Tech Stack:** Python 3.10+, PySide6, `urllib` + `hmac`/`hashlib` (S3 signing), `cryptography` (AES-GCM), `keyring` (Windows Credential Manager), pytest.

**Spec:** agreed in conversation on 2026-11-23: backups only when the button is pressed (no schedule); button in the menu bar next to the text-size buttons, plus a File menu item; keys built into the installer; backups encrypted with a passphrase; each backup named only by PC name and timestamp; restore lists every backup and the admin picks one.

## Global Constraints

- S3 API endpoint: `https://s3.kalourmade.com` (`https://minio.kalourmade.com/...` is the web console, not the API). Bucket: `medtracker-inventory`. Region `us-east-1`. Path-style URLs: `{endpoint}/{bucket}/{key}`. Both live in `config.py` as `CLOUD_ENDPOINT`, `CLOUD_BUCKET`.
- HTTPS only; `http://` refused except for `127.0.0.1`/`localhost` (tests).
- Keys: `.env` (git-ignored, already holds `accesskey=` and `secretkey=`) locally; GitHub secrets `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` in CI. `scripts/make_cloud_keys.py` writes `cloud_keys.py` (`ACCESS_KEY = "..."`, `SECRET_KEY = "..."`), git-ignored. Never print, log or show the keys.
- One key does upload, list and download. Its MinIO policy allows only `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` on `medtracker-inventory` — no delete — because it ships inside every installer.
- Object key: `{computer}/medtracker_{YYYY-MM-DD_HHMMSS}.db.gz.enc` — PC name and timestamp only, no location. `computer` is `socket.gethostname()` as a slug: lowercase `[a-z0-9-]`, max 40 chars, empty → `unnamed`. Timestamp is the PC's local time.
- File format: `b"MTCB1"` + 16-byte salt + 12-byte nonce + AES-256-GCM ciphertext of `gzip(db bytes)`; key = `hashlib.scrypt(passphrase, salt=salt, n=2**14, r=8, p=1, dklen=32)`.
- Last success time in `QSettings("MedTracker", "MedTracker")` key `cloud_backup/last_success`. Passphrase only in `keyring` service `"MedTracker cloud backup"`, name `"passphrase"`. Passphrase minimum 8 characters.
- Backing up: any signed-in user (like File > Backup database). Setup and restore: `user.is_admin` only. Demo mode (`--demo`): button and menu items hidden.
- Network timeout 30 s per request. The upload runs in a background thread; the window stays usable.
- Button texts: `☁ Back up` (idle), `☁ Backing up…` (disabled while running). Tooltip: `Back up to the cloud (Ctrl+Shift+B) · Last: today 09:05` / `· Last: 21 Nov 09:05` / `· Never backed up`.
- Messages: success `"Backup uploaded to the cloud."`; not set up, non-admin `"Cloud backup is not set up on this computer. Ask an administrator."`; build without keys `"Cloud backup is not available in this version of MedTracker."`; network/server errors show the `S3Error` text.
- Python 3.10 syntax only.

## Review Focus

1. **Wrong passphrase on restore** → "The backup passphrase is not correct." and the live database is untouched (tests in Task 2 and Task 6).
2. **Offline / server down / 403 / bucket missing** → a clear message, the button becomes usable again, `last_success` unchanged (tests in Task 1 and Task 5).
3. **Window rebuilt mid-upload** (colour theme, text size and sign-out all rebuild `MainWindow`) → the result must not touch deleted widgets and a second upload must not start; the busy flag lives at module level like `update_flow._available` (test in Task 5).
4. **Button pressed twice quickly** → only one upload (test in Task 5).
5. **Odd computer names** (spaces, non-ASCII, empty hostname) → still a valid key (test in Task 3).

---

### Task 1: S3 client (`s3client.py`)

**Files:**
- Create: `s3client.py`
- Test: `tests/test_s3client.py`, `tests/conftest.py` (add the `fake_s3` fixture)

**Interfaces:**
- Produces:
  - `class S3Error(Exception)` — message safe to show.
  - `@dataclass S3Config(endpoint: str, bucket: str, access_key: str, secret_key: str, region: str = "us-east-1")`
  - `@dataclass ObjectInfo(key: str, size: int, modified: datetime)`
  - `sign(method: str, url: str, headers: dict[str, str], payload_hash: str, cfg: S3Config, when: datetime) -> dict[str, str]` — returns `headers` plus `x-amz-date`, `x-amz-content-sha256`, `Authorization`.
  - `put_object(cfg, key: str, data: bytes, timeout: float = 30) -> None`
  - `get_object(cfg, key: str, timeout: float = 30) -> bytes`
  - `list_objects(cfg, prefix: str, timeout: float = 30) -> list[ObjectInfo]` — ListObjectsV2, follows `NextContinuationToken`.
  - Fixture `fake_s3` (in `tests/conftest.py`): a `http.server` on 127.0.0.1 storing PUT bodies in `fake_s3.store: dict[str, bytes]`, serving GET and ListObjectsV2 (pages of 1000), with `fake_s3.cfg: S3Config` and `fake_s3.fail_with: tuple[int, str] | None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_sign_matches_aws_get_object_example():
    # AWS SigV4 docs, "Example: GET Object"
    cfg = S3Config("https://s3.amazonaws.com", "examplebucket",
                   "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    h = sign("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"},
             hashlib.sha256(b"").hexdigest(), cfg, datetime(2013, 5, 24, tzinfo=timezone.utc))
    assert h["Authorization"].endswith(
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in h["Authorization"]

def test_put_get_list_round_trip(fake_s3):
    put_object(fake_s3.cfg, "pc/a.enc", b"one")
    put_object(fake_s3.cfg, "pc/b.enc", b"two")
    assert get_object(fake_s3.cfg, "pc/b.enc") == b"two"
    assert [o.key for o in list_objects(fake_s3.cfg, "pc/")] == ["pc/a.enc", "pc/b.enc"]

def test_list_follows_continuation_token(fake_s3):
    for i in range(1001): fake_s3.store[f"s/{i:04}"] = b""
    assert len(list_objects(fake_s3.cfg, "s/")) == 1001

@pytest.mark.parametrize("status,code,message", [
    (403, "AccessDenied", "The backup server refused access. Check the MedTracker version or ask for support."),
    (404, "NoSuchBucket", "The bucket 'medtracker-inventory' does not exist."),
    (500, "InternalError", "The backup server had a problem (InternalError). Try again later."),
])
def test_server_errors_become_safe_messages(fake_s3, status, code, message):
    fake_s3.fail_with = (status, code)
    with pytest.raises(S3Error) as err: put_object(fake_s3.cfg, "x", b"")
    assert str(err.value) == message and fake_s3.cfg.secret_key not in str(err.value)

def test_unreachable_server():
    with pytest.raises(S3Error, match="Cannot reach the backup server. Check the internet connection."):
        put_object(S3Config("https://127.0.0.1:9", "b", "k", "s"), "x", b"", timeout=2)

def test_http_refused_except_localhost():
    with pytest.raises(S3Error, match="must start with https://"):
        put_object(S3Config("http://s3.kalourmade.com", "b", "k", "s"), "x", b"")
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_s3client.py -v` — Expected: FAIL, `ModuleNotFoundError: s3client`.
- [ ] **Step 3: Implement `s3client.py`** — SigV4 per AWS docs: canonical request (URI-encode each path segment, sorted query, lower-case sorted signed headers incl. `host`), scope `{yyyymmdd}/{region}/s3/aws4_request`. `urllib.request` with `User-Agent` like `updater.USER_AGENT`; error XML `<Code>` via `xml.etree.ElementTree`; list XML namespace `http://s3.amazonaws.com/doc/2006-03-01/`.
- [ ] **Step 4: Run** the same command — Expected: all PASS.
- [ ] **Step 5: Commit** `git add s3client.py tests/test_s3client.py tests/conftest.py && git commit -m "Cloud backup: S3 client for MinIO (signed urllib requests)"`

---

### Task 2: Encrypting backups (`cloud_backup.py`, part 1)

**Files:**
- Create: `cloud_backup.py`
- Modify: `requirements.txt` (add pinned `cryptography`, a release at least two weeks old, with a one-line comment like the others)
- Test: `tests/test_cloud_backup.py`

**Interfaces:**
- Produces: `class CloudBackupError(Exception)`; `MAGIC = b"MTCB1"`; `pack(plain: bytes, passphrase: str) -> bytes`; `unpack(blob: bytes, passphrase: str) -> bytes`.

- [ ] **Step 1: Write the failing tests**

```python
def test_pack_round_trip_smaller_and_unreadable(conn, add, tmp_path):
    add(); db.backup_to(conn, tmp_path / "s.db"); plain = (tmp_path / "s.db").read_bytes()
    blob = pack(plain, "correct horse")
    assert blob.startswith(b"MTCB1") and len(blob) < len(plain) and b"Paracetamol" not in blob
    assert unpack(blob, "correct horse") == plain

def test_wrong_passphrase():
    with pytest.raises(CloudBackupError, match="The backup passphrase is not correct."):
        unpack(pack(b"x" * 100, "right"), "wrong")

def test_not_a_backup_file():
    with pytest.raises(CloudBackupError, match="not a MedTracker cloud backup"):
        unpack(b"SQLite format 3\x00...", "p")

def test_same_input_packs_differently():
    assert pack(b"abc", "p") != pack(b"abc", "p")
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_cloud_backup.py -v` — Expected: FAIL, `ModuleNotFoundError`.
- [ ] **Step 3: Install and implement** — `.venv/bin/pip install -r requirements.txt`; `pack`/`unpack` per the file format (`gzip`, `os.urandom`, `cryptography.hazmat.primitives.ciphers.aead.AESGCM`; `InvalidTag` → wrong passphrase).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Cloud backup: compress and encrypt backups"` (with `requirements.txt`).

---

### Task 3: Keys, naming, upload, list, download (`cloud_backup.py`, part 2)

**Files:**
- Modify: `cloud_backup.py`; `config.py` (add `CLOUD_ENDPOINT`, `CLOUD_BUCKET`); `requirements.txt` (add pinned `keyring`); `.gitignore` (add `cloud_keys.py`)
- Create: `scripts/make_cloud_keys.py`
- Test: `tests/test_cloud_backup.py`

**Interfaces:**
- Consumes: Task 1 `S3Config`, `put_object`, `get_object`, `list_objects`, `ObjectInfo`, `S3Error`; Task 2 `pack`, `unpack`.
- Produces:
  - `scripts/make_cloud_keys.py [--env PATH] [--out PATH]` — reads `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` from the environment, else `accesskey`/`secretkey` from `.env` (`#` comments and blank lines ignored); writes `cloud_keys.py`; prints only `cloud_keys.py written` or `No MinIO keys found - cloud backup will be unavailable` (exit 0 either way, so builds without keys still work).
  - `cloud_config() -> S3Config | None` — from `cloud_keys` if importable, else `None`.
  - `slug(text: str) -> str`; `object_key(computer: str, when: datetime) -> str`
  - `upload_backup(cfg: S3Config, snapshot: Path, passphrase: str, computer: str, when: datetime) -> str` — packs the snapshot file, PUTs it, returns the key.
  - `list_backups(cfg: S3Config) -> list[ObjectInfo]` — every PC's backups, only `.db.gz.enc`, newest first by the timestamp in the name.
  - `download_backup(cfg: S3Config, key: str, passphrase: str, dest: Path) -> None` — writes the plain `.db`.
  - `KEYRING_SERVICE = "MedTracker cloud backup"`; `load_passphrase() -> str` (`""` if none); `save_passphrase(value: str) -> None` — any `keyring.errors.KeyringError` → `CloudBackupError("This computer cannot store the passphrase securely.")`.

- [ ] **Step 1: Write the failing tests** (an in-memory keyring backend via `keyring.set_keyring(...)` in a fixture)

```python
@pytest.mark.parametrize("raw,expected", [("Front Desk", "front-desk"), ("PHARM-PC_01", "pharm-pc-01"),
                                          ("Kɔfi’s PC", "k-fi-s-pc"), ("", "unnamed"), ("x" * 60, "x" * 40)])
def test_slug(raw, expected): assert slug(raw) == expected

def test_object_key():
    assert object_key("PC 1", datetime(2026, 11, 23, 9, 5, 7)) == "pc-1/medtracker_2026-11-23_090507.db.gz.enc"

def test_upload_list_download_round_trip(fake_s3, conn, add, tmp_path):
    add(); db.backup_to(conn, tmp_path / "s.db")
    key = upload_backup(fake_s3.cfg, tmp_path / "s.db", "passphrase1", "PC1", datetime(2026, 11, 23, 9, 5))
    assert list_backups(fake_s3.cfg)[0].key == key
    download_backup(fake_s3.cfg, key, "passphrase1", tmp_path / "back.db")
    assert db.is_valid_backup(tmp_path / "back.db")

def test_list_backups_all_pcs_newest_first_backups_only(fake_s3): ...
    # store pc1/…_2026-11-01…enc, pc2/…_2026-11-20…enc, pc1/…_2026-11-10…enc, notes.txt
    # → three keys: 2026-11-20 (pc2), 2026-11-10 (pc1), 2026-11-01 (pc1)

def test_make_cloud_keys_from_env_file(tmp_path):
    (tmp_path / ".env").write_text("#minio\naccesskey=AK\nsecretkey=SK\n")
    run([sys.executable, "scripts/make_cloud_keys.py", "--env", tmp_path / ".env", "--out", tmp_path / "k.py"])
    assert 'ACCESS_KEY = "AK"' in (tmp_path / "k.py").read_text()

def test_make_cloud_keys_never_prints_keys(tmp_path): ...   # stdout has no "AK"/"SK"

def test_no_keys_means_no_config(monkeypatch):
    monkeypatch.setitem(sys.modules, "cloud_keys", None); assert cloud_config() is None

def test_passphrase_in_keyring(memory_keyring):
    save_passphrase("passphrase1"); assert load_passphrase() == "passphrase1"
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_cloud_backup.py -v` — Expected: new tests FAIL.
- [ ] **Step 3: Implement** the functions, the script and the `config.py` / `.gitignore` additions; run `.venv/bin/python scripts/make_cloud_keys.py` once to create the local `cloud_keys.py` from `.env`.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` and `git status --short` — Expected: all PASS; `cloud_keys.py` and `.env` not listed.
- [ ] **Step 5: Commit** `git commit -m "Cloud backup: keys from the build, upload, list and download"`

---

### Task 4: Keys in the release build

**Files:**
- Modify: `build.sh`, `build.bat`, `build-linux.sh` (run `scripts/make_cloud_keys.py` before PyInstaller), `.github/workflows/build.yml` (same step, with `env: MINIO_ACCESS_KEY: ${{ secrets.MINIO_ACCESS_KEY }}`, `MINIO_SECRET_KEY: ${{ secrets.MINIO_SECRET_KEY }}`), `medtracker.spec` (`hiddenimports=["cloud_keys", "keyring.backends.Windows", "keyring.backends.macOS"]`)

- [ ] **Step 1: Run** `./build.sh` — Expected: `cloud_keys.py written`, build succeeds, tests pass.
- [ ] **Step 2: Check** the built app finds the keys: `dist/MedTracker…` → (after Task 5) the ☁ Back up button is enabled; without `cloud_keys.py` it shows the "not available in this version" message.
- [ ] **Step 3: Note for the user** (not done by the agent): add `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` as repository secrets on GitHub (Settings → Secrets and variables → Actions), copied from `.env`.
- [ ] **Step 4: Commit** `git commit -m "Cloud backup: build the MinIO keys into releases"`

---

### Task 5: The ☁ Back up button and setup dialog

**Files:**
- Create: `ui/cloud_backup_flow.py`, `ui/cloud_settings.py`
- Modify: `ui/main_window.py` — `_zoom_buttons` (~line 368): add the `☁ Back up` link button before A−; `_build_menu` (~line 428): `Back up to cloud` (Ctrl+Shift+B) for everyone and, for admins, `Cloud backup setup...`; all hidden when `self.demo`.
- Test: `tests/test_cloud_backup_flow.py`

**Interfaces:**
- Consumes: Task 3 `cloud_config`, `upload_backup`, `slug`, `load_passphrase`, `save_passphrase`; `db.backup_to`; `config.backups_dir`.
- Produces:
  - `last_success() -> float | None`
  - `tooltip_text(last: float | None, now: float) -> str` — texts from Global Constraints.
  - `class CloudBackupController(QObject)`: `__init__(window, conn, user, demo: bool)`, `button: QPushButton`, `back_up() -> None`, signal `finished(str)` (error text, or `""` on success).
  - `class CloudSetupDialog(QDialog)`: `__init__(parent)` — passphrase + confirm (password echo), hint "Write this passphrase down and keep it safe. Without it the cloud backups cannot be restored." Blank passphrase on reopen keeps the stored one.
- `back_up()` flow: no keys → message; no passphrase → admins get `CloudSetupDialog`, others the "Ask an administrator" message; module-level `_busy` true → return; snapshot with `db.backup_to` on the GUI thread into a temp file under `backups_dir()`; `upload_backup` in a `threading.Thread`; temp file deleted in `finally`; result back through a module-level `QObject` signal; controllers disconnect on `window.destroyed`.

- [ ] **Step 1: Write the failing tests** (`QT_QPA_PLATFORM=offscreen`; `cloud_config` monkeypatched to `fake_s3.cfg`)

```python
@pytest.mark.parametrize("last,text", [
    (None, "Back up to the cloud (Ctrl+Shift+B) · Never backed up"),
    (NOW - 3600, "Back up to the cloud (Ctrl+Shift+B) · Last: today 08:00"),     # NOW = 2026-11-23 09:00 local
    (NOW - 2 * 86400, "Back up to the cloud (Ctrl+Shift+B) · Last: 21 Nov 09:00"),
])
def test_tooltip_text(last, text): ...

def test_back_up_uploads_and_records_success(fake_s3, conn, ...)       # one key in fake_s3.store, last_success set, temp file gone
def test_failure_reports_and_keeps_last_success(fake_s3, conn, ...)    # fail_with=(500, ...) → finished emits message, last_success unchanged, button enabled
def test_double_press_uploads_once(fake_s3, conn, ...)
def test_window_closed_during_upload_does_not_crash(fake_s3, conn, ...)
def test_not_set_up_non_admin_gets_message(...)                         # no dialog, exact message
def test_no_keys_message(...)
def test_demo_mode_has_no_button(...)
def test_setup_requires_matching_passphrase_of_8_chars(...)            # "Passphrases do not match." / "Use at least 8 characters for the passphrase."
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_cloud_backup_flow.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement**, using `make_button`, `show_error`, `show_info`, `dialog_header` from `ui/widgets.py`.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Try it for real:** `.venv/bin/python main.py` → set a passphrase → ☁ Back up → success message; the object appears in the MinIO console under `medtracker-inventory/<this-pc-name>/`.
- [ ] **Step 6: Commit** `git commit -m "Cloud backup: Back up button in the menu bar"`

---

### Task 6: Restore from cloud

**Files:**
- Modify: `ui/cloud_settings.py` (add `CloudRestoreDialog`); `ui/main_window.py` (split `restore_database` (~line 505) into the file picker and `restore_file(path: str) -> None` keeping every existing check, the safety copy and the sign-out; admin-only `Restore from cloud backup...` menu item, hidden in demo mode)
- Test: `tests/test_cloud_settings.py`

**Interfaces:**
- Consumes: Task 3 `cloud_config`, `list_backups`, `download_backup`, `load_passphrase`.
- Produces: `class CloudRestoreDialog(QDialog)`: `__init__(parent)` — lists every backup from every PC, newest first, as `23 Nov 2026 09:05 · front-desk-pc · 1.2 MB`, with this PC's own backups marked "(this PC)"; a **Restore** button (disabled until a row is chosen) and the existing "ALL current data will be REPLACED" confirmation (loaded in a background thread), passphrase pre-filled from keyring and editable (for restoring on a new PC); `chosen_file() -> Path | None` (decrypted temp `.db`) after `exec()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_restore_dialog_lists_newest_first(fake_s3, ...)
def test_wrong_passphrase_shows_error_and_returns_nothing(fake_s3, conn, ...)  # chosen_file() is None, live db unchanged
def test_chosen_backup_restores_through_existing_checks(fake_s3, conn, ...)    # restore_file(path) → data replaced, safety copy exists
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**; delete the temp file after `restore_file` returns.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Cloud backup: restore from the cloud"`

---

### Task 7: Server setup guide and version

**Files:**
- Create: `docs/minio-setup.md`
- Modify: `config.py` (`APP_VERSION = "1.4.0"`), `README.md` (short "Cloud backup" section linking the guide)

- [ ] **Step 1: Write `docs/minio-setup.md`** with copy-paste `mc` commands:
  - `mc alias set kalour https://s3.kalourmade.com <ADMIN_KEY> <ADMIN_SECRET>`
  - `mc version enable kalour/medtracker-inventory` (a backup overwritten by mistake can be recovered)
  - The app key's policy: `s3:PutObject`, `s3:GetObject` on `arn:aws:s3:::medtracker-inventory/*` and `s3:ListBucket` on `arn:aws:s3:::medtracker-inventory` — nothing else (no delete, no other buckets), because the key is inside every installer.
  - Optional clean-up: `mc ilm rule add kalour/medtracker-inventory --expire-days 365`.
  - The API is `s3.kalourmade.com`; the console is `minio.kalourmade.com`.
  - Adding `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` GitHub secrets; if a key leaks, create a new one, update `.env` and the secrets, release a new version.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q` and `./build.sh` — Expected: PASS, build succeeds.
- [ ] **Step 3: Commit** `git commit -m "MedTracker 1.4.0: cloud backup to MinIO"`

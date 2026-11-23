# MedTracker

A desktop app for tracking medicine stock and dispensing in a small pharmacy or clinic.
It runs on Windows, macOS and Linux, works fully offline, and keeps its data in one
local SQLite database file. Backups can also be uploaded to the cloud (MinIO).

- **Dashboard**: summary figures; what needs attention (out of stock, expiring, expired); an expiry shelf showing every batch by the month it expires; running low, stock health and this month's dispensing
- **Add Stock** / **Record Dispensed** / **Remove Stock**: data-entry dialogs. Dispensing takes stock from the batch that expires first (FEFO) automatically.
- **Search** (Ctrl+F): find a medicine by name or note and see its details, batches and full log
- **Audit Log**: who edited, deleted or undid which entry, when, and why
- **Dispensing Log**: every entry (stock in, dispensed, removed), with filters, undo, and Excel/CSV export
- **Stock & Batches**: current stock per medicine and per batch, colour-coded
- **Reports**: a month or any date range (quick picks for the last 7, 30 or 90 days), compared with the period before; a day-by-day calendar, top 10 medicines, pace, busiest weekdays and hours, prescriber share, days of stock left and a ranked table, with Excel and PDF export
- **File menu**: back up and restore the database (on this computer or in the cloud), open the data folder, change password, sign out
- **Cloud backup**: the **☁ Back up** button in the menu bar uploads a copy of the data; administrators can restore any cloud backup. Every update backs up to the cloud first.
- **Sign-in and users**: people register and wait for approval; administrators approve or
  revoke access, and every entry records who made it
- **View menu**: colour themes, text size (80%–160%) and search; the whole app can be used from the keyboard
- **Help menu**: updates (Windows installs update themselves) and **About MedTracker** with the version and system details

---

## 1. How it is built

| File / folder | What it does |
|---|---|
| `main.py` | Starts the app. Handles `--demo`, sets up the error log and the global error handler. |
| `config.py` | App name, version, the 90-day expiry warning, the data folder, the cloud backup server and `resource_path()`. |
| `db.py` | Creates the SQLite tables and holds all database reads and writes. |
| `logic.py` | Business rules: validation, FEFO allocation, undo, dashboard and report calculations. It has no UI code, so it can be tested. |
| `exports.py` | Excel/CSV export and the HTML used for the PDF report. |
| `demo_data.py` | Sample data for the separate demo database. |
| `cloud_backup.py`, `s3client.py` | Cloud backup without Qt: compress backups, and upload, list and download them over the S3 API (signed requests, Python's own `urllib`). |
| `ui/` | One module per page (`dashboard.py`, `search.py`, `log.py`, `audit.py`, `stock.py`, `report.py`, `users.py`) and per dialog (`add_stock.py`, `dispense.py`, `remove_stock.py`, `medicine.py` for New/Edit Medicine, `edit_entry.py`, `edit_batch.py`, `units.py`, `login.py`, `about.py`), plus `main_window.py` (sidebar and menus), `cloud_backup_flow.py` and `cloud_settings.py` (the ☁ Back up button, setup and restore), `theme.py` (colours, text size and the app-wide stylesheet), `responsive.py` (grids and layouts that adapt to the window size), the shared table model with status badges (`models.py`), the dashboard's panels and drawn charts (`dashboard_widgets.py`), line icons (`icons.py`), the report chart widgets (`report_widgets.py`) and shared cards/buttons (`widgets.py`). The app font, Atkinson Hyperlegible Next, is bundled in `resources/fonts` under the SIL Open Font License (`OFL.txt`). |
| `resources/` | App icons (`.ico` Windows, `.icns` macOS, `.png` Linux/window) and small SVG arrows used by the theme. |
| `tests/` | pytest tests. |
| `medtracker.spec` | PyInstaller build recipe. |
| `setup.bat` / `setup.sh` | One-step setup: create `.venv` and install everything. |
| `build.bat` / `build.sh` | One-step build: run the tests, build the app and package it (program folder, plus an installer if Inno Setup is installed, on Windows; `.app`, `.dmg` and `.zip` on macOS). |
| `updater.py`, `ui/update_bar.py`, `ui/update_flow.py` | Update checking, downloading and installing (see **Updates** below). |
| `installer/medtracker.iss` | Inno Setup script that builds the Windows installer. |
| `scripts/make_manifest.py` | Writes `latest.json`, the file installed copies read to find updates. |
| `scripts/make_cloud_keys.py` | Before a build: writes the MinIO keys from `.env` (or GitHub secrets) into `cloud_keys.py`, which is never committed. |
| `scripts/check_cloud_keys.py` | Run first by the release workflow: stops a release whose MinIO keys are missing or rejected. |
| `docs/minio-setup.md` | Setting up the MinIO server and the keys for cloud backup. |
| `build-linux.sh` / `build-all.sh` | From a Mac: build the Linux version with Docker / build everything this Mac can build. |
| `run.bat` / `run.sh` | Start the app with the `.venv` Python. No activation needed. |
| `.github/workflows/build.yml` | Builds on GitHub when you push a version tag (Windows; add macOS/Linux via the tag message). |

**Stock is never stored as a number you can edit.** MedTracker works it out every time
from the log: *stock received − stock dispensed − stock removed*. It does the same for each batch.
When a dispensing entry is split across several batches, the rows are saved together
in one database transaction, and **Undo last entry** removes them together.

### Where your data is kept

The database is never stored next to the program. It goes in your personal data folder:

| System | Folder |
|---|---|
| Windows | `%APPDATA%\MedTracker` (for example `C:\Users\you\AppData\Roaming\MedTracker`) |
| macOS | `~/Library/Application Support/MedTracker` |
| Linux | `~/.local/share/MedTracker` |

The folder contains:
- `medtracker.db`: your real data
- `medtracker_demo.db`: demo data, used only with `--demo`
- `medtracker.log`: the error log
- `backups/`: the default location for backups, including the automatic `before-update-…` and
  `before_restore_…` copies

To open this folder from the app, use **File → Open data folder**. **Help → About MedTracker**
shows the database's exact location.

Each new version may upgrade the database format the first time it opens it (automatically,
keeping all data). An older MedTracker then refuses to open it, and backups made by the newer
version, rather than risk damaging them.

---

## 2. Setup, step by step

### a) Install Python and create the virtual environment

1. Install **Python 3.10 or newer** (3.12 is recommended):
   - **Windows**: download it from <https://www.python.org/downloads/>. On the first
     installer screen, **tick "Add python.exe to PATH"**.
   - **macOS**: download it from <https://www.python.org/downloads/>, or run `brew install python@3.12`.
   - **Linux (Ubuntu/Debian)**: `sudo apt install python3 python3-venv python3-pip`.
     The Qt window also needs `sudo apt install libxcb-cursor0`.
2. Open a terminal **in the project folder** (the folder that contains `main.py`):
   - Windows: open the folder in File Explorer, click the address bar, type `powershell` and press Enter.
   - macOS: right-click the folder in Finder, then choose **Services → New Terminal at Folder**.
   - Linux: right-click inside the folder, then choose **Open in Terminal**.
3. Create the virtual environment. You can do this the easy way or by hand.

   **Easy way:** one script creates `.venv`, upgrades pip and installs everything.
   - Windows: double-click **`setup.bat`**
   - macOS / Linux: run `./setup.sh`

   **By hand:**
   ```
   python -m venv .venv          (Windows)
   python3 -m venv .venv         (macOS / Linux)
   ```

4. **Activate** the virtual environment. Do this every time you open a new terminal to work on the project.

   | Terminal | Command |
   |---|---|
   | Windows PowerShell | `.venv\Scripts\Activate.ps1` |
   | Windows Command Prompt | `.venv\Scripts\activate.bat` |
   | macOS / Linux | `source .venv/bin/activate` |

   PowerShell may say *"running scripts is disabled on this system"*. If it does, run this once
   and then try again:
   ```
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

5. **Check that the venv is active.** The terminal prompt should now start with `(.venv)`.
   You can confirm it with:
   ```
   python -c "import sys; print(sys.prefix)"
   ```
   The printed path must end in your project folder followed by `.venv`.
   If it shows a system path such as `C:\Python312` or `/usr`, the venv is **not** active.

> Never run `pip install` without the venv active. That would install packages into your
> system Python, which this project deliberately avoids.

### b) Install the packages (with the venv active)

```
pip install -r requirements.txt -r requirements-dev.txt
```
- `requirements.txt` lists what the app needs, pinned to exact versions: PySide6 (the window),
  openpyxl (Excel export), platformdirs (the data folder), cryptography and keyring (to open
  cloud backups made by 1.4.x, which were encrypted with a passphrase saved on that computer).
- `requirements-dev.txt` lists the build and test tools: PyInstaller and pytest.

If you ran `setup.bat` or `setup.sh`, this step is already done.

**Cloud backup keys (optional):** to build or run a copy that can back up to the cloud, put the
MinIO keys in a file called `.env` in the project folder:
```
accesskey=...
secretkey=...
```
`.env` is never committed. The build scripts turn it into `cloud_keys.py` (also never committed);
when running from source, run `python scripts/make_cloud_keys.py` once. Without keys everything
else works, and cloud backup says it is not available. See [docs/minio-setup.md](docs/minio-setup.md).

### c) Run the app from source

With the venv active:
```
python main.py            # your real data
python main.py --demo     # separate demo database with sample data
```
You can also skip activation and double-click **`run.bat`** on Windows, or run
`./run.sh` on macOS/Linux. Both use `.venv`'s Python directly, and both accept `--demo`
(for example `run.bat --demo`).

**Demo mode** uses its own `medtracker_demo.db` file. It fills that file with about 100 days of
sample data the first time. It never touches your real database, and the window title
shows `[DEMO]`. To start the demo again from scratch, delete `medtracker_demo.db` from the data folder.

### d) Run the tests

With the venv active, run:
```
pytest
```
The tests cover stock calculation, FEFO allocation across several batches, blocking of expired
batches, blocking of over-dispensing, undo, edits and the audit log, reports, exports, sign-in and
permissions, updates, deleting medicines, and backup/restore (on this computer and in the cloud,
against a small fake storage server). Each test uses its own temporary database, settings and
password store, so your data, settings and the real cloud server are never touched.

### e) Build the standalone program with PyInstaller

PyInstaller **cannot cross-compile**: it builds for the system it runs on. Build the
Windows version on Windows, the Mac version on a Mac, and the Linux version on Linux.
To get all of them at once, use the GitHub workflow in step f.

**Building everything from a Mac:**

| Target | Command on your Mac | Needs |
|---|---|---|
| macOS (your Mac's chip) | `./build.sh` | nothing extra |
| Linux x86_64 | `./build-linux.sh` (builds inside an Ubuntu 22.04 container) | [Docker Desktop](https://www.docker.com/products/docker-desktop/) running |
| Linux ARM64 | `./build-linux.sh arm64` | Docker Desktop |
| All of the above | `./build-all.sh` | Docker Desktop for the Linux part |
| **Windows .exe** and **Intel Mac** | push a version tag to GitHub (step f) | a free GitHub account |

A Windows `.exe` can't be built reliably on a Mac, so GitHub builds it on a real Windows
machine for you, for free.

**Easiest: one-click build scripts.** They run the tests first, build the app, and then package it for sharing:

| System | Run | You get (in the `dist` folder) |
|---|---|---|
| Windows | double-click **`build.bat`** | the `MedTracker\` folder (with `MedTracker.exe` inside) and, if [Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed, `MedTracker-Setup-<version>.exe` |
| macOS | `./build.sh` | `MedTracker.app`, `MedTracker-<version>-macOS-arm64.dmg` (drag-to-Applications installer) and a `.zip` |
| Linux | `./build.sh` | `MedTracker/` folder and `MedTracker-<version>-Linux.zip` |

The version number comes from `APP_VERSION` in `config.py`. That's the only place to change it.
The build scripts also build in the cloud backup keys from `.env`, if it exists.

**By hand:** activate the venv, then run this from the project folder (same command on every system):
```
pyinstaller medtracker.spec --noconfirm --clean
```

| System | Output | How to run it |
|---|---|---|
| Windows | `dist\MedTracker\MedTracker.exe` | A folder. Keep the whole folder together. The installer (built with Inno Setup from this folder) is what you give to users. |
| macOS | `dist/MedTracker.app` | Drag it to Applications. |
| Linux | `dist/MedTracker/` (folder) | Run `dist/MedTracker/MedTracker`. Keep the whole folder together. |

The build uses only what is installed in `.venv`, so it contains just the project's dependencies.
It opens without a console window. The `build/` folder is temporary and can be deleted.

**macOS:** the app is not signed or notarized with a paid Apple Developer account. So the first
time you open a downloaded copy, macOS says *"Apple could not verify 'MedTracker' is free of malware…"*.
To allow it (once per copy):
1. Try to open MedTracker once, then click **Done**.
2. Open **System Settings → Privacy & Security**, scroll down to **Security**, click **Open Anyway**,
   and confirm with your password or Touch ID.

Or run this once in Terminal (it also fixes an *"app is damaged"* message):
```
xattr -dr com.apple.quarantine /Applications/MedTracker.app
```
(On macOS 14 and older, **right-click MedTracker.app → Open → Open** also works.) To remove the
warning for everyone, the app must be signed and notarized, which requires a paid Apple Developer
Program membership (US$99 a year).
A Mac build runs on the same kind of processor it was built on: Apple Silicon or Intel.

**Windows:** SmartScreen may warn about an unknown publisher. Click **More info → Run anyway**.

**Linux:** the target computer needs the usual desktop libraries. If the app fails to start,
install them with `sudo apt install libxcb-cursor0 libegl1`.

### f) Build Windows, macOS and Linux automatically with GitHub Actions

GitHub builds on real Windows, Mac (Apple Silicon **and** Intel) and Linux machines, so you
get every version from your Mac without owning the other computers. It's free for public
repositories, and private repositories get free monthly build minutes.

> **Keep the repository public** while installed copies update from its Releases: they download
> `latest.json` and the installer without signing in to GitHub, which stops working for a
> private repository. To make the code private, first move the releases somewhere public (for
> example a separate public releases-only repository), release a version that looks there, and
> wait until every PC has it.

**One-time setup:**
1. Create a free account at <https://github.com> if you don't have one.
2. On GitHub, click **+ → New repository**. Name it `medtracker`, choose **Public** (see the note
   above), and **don't** tick "Add a README" (this project already has one). Click **Create repository**.
3. In Terminal, in the project folder (the project is already a git repository with its first
   commit), connect it and upload. Replace `YOUR-USERNAME` with your GitHub user name:
   ```
   git remote add origin https://github.com/YOUR-USERNAME/medtracker.git
   git push -u origin main
   ```
   When git asks for a password, use a GitHub **personal access token**, not your GitHub
   password. To create one: GitHub → Settings → Developer settings → Personal access tokens.
   Give it the "repo" and "workflow" permissions.
4. For cloud backup, add the MinIO keys as repository secrets (**Settings → Secrets and variables
   → Actions → New repository secret**): `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`, with the
   values from `.env`.

**Every time you want new builds:**
1. Change `APP_VERSION` in `config.py` if needed (for example to `1.0.1`), then commit your changes:
   ```
   git add -A
   git commit -m "Version 1.0.1"
   git push
   ```
2. Tag the version and push the tag. **This starts the builds.** Only Windows is built by
   default. To also build macOS and/or Linux, say so in the tag message:
   ```
   git tag v1.0.1                                  # Windows only
   git tag -a v1.0.1 -m "include mac"              # Windows + macOS
   git tag -a v1.0.1 -m "include mac linux"        # Windows + macOS + Linux ("include all" also works)
   git push origin v1.0.1
   ```
   The same words in the tagged commit's message work too.
3. Open your repository on GitHub and click the **Actions** tab to watch the progress. It takes about 10–15 minutes.
   First the MinIO keys are checked: a release stops there, with the reason, if they are missing
   or MinIO rejects them. Then each machine runs the tests and builds.
4. When it finishes, go to **Releases** (on the right of the repository's main page). Download
   (only the platforms you built are there):
   - `MedTracker-Setup-<version>.exe` for Windows 10/11 (the installer; installed copies update themselves),
     `MedTracker-Windows-portable.zip` (no installer, no auto-update) and `latest.json` (read by the updater)
   - `MedTracker-macOS-AppleSilicon.dmg` / `.zip` for Macs with an M1 or newer chip
   - `MedTracker-macOS-Intel.dmg` / `.zip` for Intel Macs
   - `MedTracker-Linux-x86_64.zip` for Linux

You can also start the workflow by hand from the Actions tab (**Run workflow**), with
checkboxes to also build macOS and Linux. A manual run attaches the builds to the workflow run
instead of creating a release.

When you release a new version, update `APP_VERSION` in `config.py`, then push a new tag such as `v1.0.1`.

---

## Updates

### For users (Windows)

MedTracker checks for a newer version in the background about 10 seconds after it opens, at most
once a day. If one is found, a bar appears at the top of the window:
**MedTracker 1.2.0 is available.**

- **What's new**: shows what changed.
- **Install now**: MedTracker backs up your data, closes, installs the new version and reopens.
- **Install when I close**: downloads the update now and installs it when you next close MedTracker.
- **Later**: hides the bar until the next check.

Before every update your data is copied to the `backups` folder (**File → Open data folder**) as
`before-update-<old version>-<date>_<time>.db`. Updating never deletes or changes your data, and an
older MedTracker refuses to open data saved by a newer one rather than damaging it.
When cloud backup is set up on the computer, that copy is also uploaded to the cloud first. If the
upload fails after you clicked **Install now**, MedTracker asks whether to install anyway; when
installing on close, the failure is only written to the log and the update goes ahead.

**Help menu**
- **Check for updates...** checks right now and tells you the result.
- **Install update from file...** is for a PC without internet: on another computer download
  `latest.json` and `MedTracker-Setup-<version>.exe` from the Releases page, put both in the same
  folder (for example on a USB stick), then choose `latest.json`. MedTracker checks the installer
  is intact before using it.
- **Check for updates automatically** turns the background check on or off (on by default).

If MedTracker runs from source, or on a Mac or Linux, it tells you a new version exists and the
**Download** button opens the Releases page instead of installing.

### For the maintainer

1. Set `APP_VERSION` in `config.py`, commit, then tag it with the same number and push the tag:
   `git tag -a v1.5.0 -m "What changed (shown as the release notes)"` and `git push origin v1.5.0`.
   The workflow refuses to publish if the tag and `APP_VERSION` differ, or if the MinIO keys
   (repository secrets) are missing or don't work.
2. GitHub builds the Windows folder, packs it with Inno Setup into `MedTracker-Setup-1.2.0.exe`, writes
   `latest.json` (version, download link, SHA-256, size, release notes) and attaches the installer,
   `latest.json` and `MedTracker-Windows-portable.zip` to the Release.
3. Installed copies find the update through
   `https://github.com/asamoahboateng/simple-med-tracker/releases/latest/download/latest.json`.
   GitHub's "latest" ignores **pre-releases** and drafts, so to test the whole thing first, publish
   a pre-release: it can be installed with **Install update from file...**, and normal users do not
   see it. Only make it a normal release when you're happy.
4. The first move to 1.2.0 must be done by hand once on each PC (versions before 1.2.0 are a single
   `.exe` that cannot update itself, and `latest.json` says `min_version` 1.2.0): run the installer.
   It installs for the current user only, to `%LOCALAPPDATA%\Programs\MedTracker`, with no
   administrator rights, and keeps the data in `%APPDATA%\MedTracker`. After that, updates are automatic.
   The old single `.exe` can be deleted.
5. The installer is not code-signed, so Windows SmartScreen may warn the first time. Downloads are
   checked against the SHA-256 in `latest.json` and may only come from GitHub hosts.

---

## 3. Using MedTracker

### Signing in and user accounts

- **Signing in**: MedTracker opens on a sign-in window. New staff click **Create an account**
  (full name, username, password of at least 8 characters, and optionally a 6-digit sign-in
  code). They can sign in once an administrator approves the account, with either their
  password or their code. **File → Set sign-in code** sets, changes or removes the code later.
- **Superadmin**: click **Use the superadmin code** on the sign-in window and enter the
  6-digit code.
  The superadmin can approve, revoke and restore anyone, make a user a **user admin** (or back
  to a regular user), allow someone to delete medicines, and set a new password for anyone who
  has forgotten theirs. The code is
  stored only as a salted hash, so it can't be read from the source code or the program; keep
  it somewhere safe.
- **User admins** can approve, revoke, restore and reset passwords for regular users, but not
  for other administrators. Only administrators see the **Users** page, **File → Restore
  from backup**, and **File → Restore from cloud backup...**
  (a restore also replaces the user accounts).
- **Users page**: new accounts show as *Awaiting approval*, and the sidebar shows how many are
  waiting, e.g. **Users (2)**. Select an account and use **Approve**, **Revoke access** or
  **Set new password**. The superadmin also has **Allow deleting medicines** / **Stop deleting
  medicines**; the **Can delete medicines** column shows who has it. **Remove sign-in code** clears a user's 6-digit code if someone else may
  know it; they can still sign in with their password. Revoking takes effect at once: a revoked user who is still signed in
  is signed out the next time they do anything.
- **Entered by**: every stock or dispensing entry records who made it, shown in the
  Dispensing Log and its exports. Entries made before sign-in existed show *Before sign-in*.
- Passwords and codes are stored as salted PBKDF2 hashes. A 6-digit code has only a million
  possibilities: in the app, five wrong attempts in a row pause sign-in for 30 seconds, but
  someone who copies the program or the database could try every code. Use a password for
  anything sensitive and keep the program and data folder on trusted computers. Sign-in protects the app, not the data file
  itself: anyone who can open the data folder can copy the database, so keep the computer's own
  user account protected too.

### Everyday tasks

- **New medicine**: use the **➕ New medicine** button on the Stock & Batches page, or
  **Entries → New Medicine** (Ctrl+M). Enter the name, unit and reorder level, and optionally a note (for example
  storage instructions). The medicine
  starts with no stock, so it shows as OUT OF STOCK until you add stock.
- **Units**: **Entries → Units…**, the **Units** button on Stock & Batches, or **Manage units**
  next to any Unit drop-down. Add units such as strips, rolls or "boxes of 100" and they appear
  in every Unit drop-down. A unit typed straight into a drop-down is added to the list too.
  A unit that any medicine uses can't be removed; the list shows how many medicines use each.
- **Add Stock**: pick a medicine or type a new name. For a new medicine, you'll also be asked
  for its unit and reorder level. The batch number and expiry date are required. If the
  batch already exists, its original expiry date is kept. Stock that is already expired
  needs confirmation.
- **Record Dispensed**: the available stock appears as soon as you choose a medicine.
  Leave the batch on *Automatic (earliest expiry first)*, or choose a specific batch.
  Expired batches and quantities larger than the available stock are blocked. After saving,
  the app shows which batches were used and warns you if stock is now **LOW**.
- **Dispensing Log → Undo last entry**: shows the most recent entry and deletes it after you confirm.
- **Dispensing Log → correct a quantity**: double-click any entry (stock in or dispensed), or select
  it and click **Edit entry**. A window shows the entry and how the stock will change as you type
  the correct quantity; stock and **Balance After** are recalculated when you save.
- **Delete an entry**: select it on the Dispensing Log (or in a medicine's log on Search) and click
  **Delete entry**. Type `DELETE` to confirm. Stock is recalculated; deleting stock that was
  later dispensed is blocked until those dispensing entries are corrected or deleted.
- **Audit Log**: every quantity correction, delete and undo is recorded automatically with who
  did it, when, the optional **Reason** typed in the pop-up, and a full copy of the entry (so
  deleted entries can still be read). The audit log can be filtered and exported, but not changed. A change that would make a batch go below zero is blocked.
- **Remove Stock** (Ctrl+R, or **Remove stock** in the sidebar): for expired, recalled, damaged or
  lost stock. Choose the medicine and a reason. The batch is optional: pick one from the list
  (expired batches are included and marked) and its whole remaining quantity is filled in, or leave
  it on *Automatic*, which takes from the earliest expiry first. Removals show as **REMOVED** in the
  log with their reason, count against stock, and are not counted as dispensing in reports.
- **Stock & Batches**: double-click a medicine (or select it and press Enter) to open **Edit
  Medicine**, where you change its name, unit, reorder level and note together. Double-click a batch to open **Edit Batch** (also on the Search page), where you can
  correct its number, expiry and the quantity received. The quantity received can only be changed
  there when the batch came in one delivery; otherwise correct each delivery in the log.
  Other values are calculated and can't be edited.
- **Delete a medicine**: double-click it on Stock & Batches and click **Delete medicine**, then
  confirm. Only a medicine with no stock and nothing in the log can be deleted (e.g. one added by
  mistake); for any other the button is greyed out, so no history is ever lost.
  You're asked to confirm first, and it can't be undone. Only the
  superadmin, and anyone the superadmin allows (**Users → Allow deleting medicines**), sees the
  button.
- **Colours**: **View → Colour theme** switches between Bottle green, Navy, Ocean blue, Teal,
  Plum and Charcoal. The change applies at once and is remembered on that computer. Red, amber
  and green keep their meaning (expired, expiring, OK) in every theme. The theme colours the whole
  window: background, table headers, buttons, scrollbars and menus, not just the sidebar.
- **Text size**: **View → Text size**, Ctrl+= / Ctrl+- / Ctrl+0, or the **A− 100% A+** buttons at
  the right of the menu bar (80% to 160%, remembered on that computer).
- **Keyboard**: Tab moves between controls (a focused control is outlined), Enter acts like a
  double-click in tables, and Esc goes back. On Search, Alt+S/M/L/B jump to the search box,
  medicines, log and batches; on Stock & Batches, Alt+S/M/B.
- **Help → About MedTracker...**: the version, computer name, operating system, who is signed in,
  where the database is and when the last cloud backup was made. **Copy details** puts all of it
  on the clipboard to send to whoever supports you.
- **Backups**: **File → Backup database** saves a copy with the date in its file name.
  **File → Restore from backup** replaces the current data, but first saves a safety copy of
  your current data in the `backups` folder.
- **Cloud backup**: the **☁ Back up** button in the menu bar (or **File → Back up to cloud**,
  Ctrl+Shift+B) uploads a compressed copy to the MinIO server as
  `<computer name>/medtracker_<date>_<time>.db.gz`. No setup or passphrase is needed, so anyone
  can press it. The backups are not encrypted: keep the bucket private and the keys secret. Nothing is overwritten: every backup is
  kept. The upload runs in the background; hover over the button to see when the last one was made.
  - **Restore (administrators):** **File → Restore from cloud backup...** lists every computer's
    backups, newest first (this computer's are marked), and restores the one you pick after the
    usual confirmation and safety copy. No passphrase is asked for. Older encrypted backups
    (`.db.gz.enc`, made by 1.4.x) restore only on a computer that saved their passphrase.
  - **Before updates:** each update's `before-update-…` copy is also uploaded first (see **Updates**).
  - Server setup and keys: [docs/minio-setup.md](docs/minio-setup.md).

If something unexpected happens, a message box explains it, and the full details are written
to `medtracker.log` in the data folder. Send that file to whoever supports you.

## 4. Validation rules (summary)

- Quantities must be whole numbers greater than 0.
- Medicine names and batch numbers ignore upper/lower case and extra spaces at the start or end.
  They are displayed as first entered. Batch numbers keep leading zeros, so `00123` stays `00123`.
- Dates cannot be in the future.
- A batch can be dispensed up to and including its expiry date.
- The dashboard flags batches as expired, or as expiring within 90 days. This only applies
  to batches that still have stock.

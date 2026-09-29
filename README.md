# MedTracker

A desktop app for tracking medicine stock and dispensing in a small pharmacy or clinic.
It runs on Windows, macOS and Linux, works fully offline, and keeps its data in one
local SQLite database file.

- **Dashboard**: summary cards, charts and alerts for low stock and expiring batches
- **Add Stock** / **Record Dispensed**: data-entry dialogs. Dispensing takes stock from the batch that expires first (FEFO) automatically.
- **Dispensing Log**: every entry, with filters, undo, and Excel/CSV export
- **Stock & Batches**: current stock per medicine and per batch, colour-coded
- **Monthly Report**: totals, rankings, busiest days and prescribers, with Excel and PDF export
- **File menu**: back up and restore the database, open the data folder

---

## 1. How it is built

| File / folder | What it does |
|---|---|
| `main.py` | Starts the app. Handles `--demo`, sets up the error log and the global error handler. |
| `config.py` | App name, version, the 90-day expiry warning, the data folder and `resource_path()`. |
| `db.py` | Creates the SQLite tables and holds all database reads and writes. |
| `logic.py` | Business rules: validation, FEFO allocation, undo, dashboard and report calculations. It has no UI code, so it can be tested. |
| `exports.py` | Excel/CSV export and the HTML used for the PDF report. |
| `demo_data.py` | Sample data for the separate demo database. |
| `ui/` | One module per page (`dashboard.py`, `add_stock.py`, `dispense.py`, `log.py`, `stock.py`, `report.py`), plus `main_window.py` (sidebar and menus), `medicine.py` (New Medicine dialog), `theme.py` (colours and the app-wide stylesheet), `responsive.py` (grids and layouts that adapt to the window size), the shared table model with status badges (`models.py`), the chart widgets (`charts.py`) and shared cards/buttons (`widgets.py`). |
| `resources/` | App icons (`.ico` Windows, `.icns` macOS, `.png` Linux/window) and small SVG arrows used by the theme. |
| `tests/` | pytest tests. |
| `medtracker.spec` | PyInstaller build recipe. |
| `setup.bat` / `setup.sh` | One-step setup: create `.venv` and install everything. |
| `build.bat` / `build.sh` | One-step build: run the tests, build the app and package it (`.exe` on Windows; `.app`, `.dmg` and `.zip` on macOS). |
| `build-linux.sh` / `build-all.sh` | From a Mac: build the Linux version with Docker / build everything this Mac can build. |
| `run.bat` / `run.sh` | Start the app with the `.venv` Python. No activation needed. |
| `.github/workflows/build.yml` | Builds all three versions on GitHub when you push a version tag. |

**Stock is never stored as a number you can edit.** MedTracker works it out every time
from the log: *stock received − stock dispensed*. It does the same for each batch.
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
- `backups/`: the default location for backups

To open this folder from the app, use **File → Open data folder**.

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
- `requirements.txt` lists what the app needs, pinned to exact versions.
- `requirements-dev.txt` lists the build and test tools: PyInstaller and pytest.

If you ran `setup.bat` or `setup.sh`, this step is already done.

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
batches, blocking of over-dispensing, undo, monthly report totals, and backup/restore.
Each test uses its own temporary database, so your data is never touched.

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
| Windows | double-click **`build.bat`** | `MedTracker.exe` and `MedTracker-<version>-Windows.exe` |
| macOS | `./build.sh` | `MedTracker.app`, `MedTracker-<version>-macOS-arm64.dmg` (drag-to-Applications installer) and a `.zip` |
| Linux | `./build.sh` | `MedTracker/` folder and `MedTracker-<version>-Linux.zip` |

The version number comes from `APP_VERSION` in `config.py`. That's the only place to change it.

**By hand:** activate the venv, then run this from the project folder (same command on every system):
```
pyinstaller medtracker.spec --noconfirm --clean
```

| System | Output | How to run it |
|---|---|---|
| Windows | `dist\MedTracker.exe` | A single file. Double-click it, or copy it anywhere. |
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

**One-time setup:**
1. Create a free account at <https://github.com> if you don't have one.
2. On GitHub, click **+ → New repository**. Name it `medtracker`, choose **Private**, and
   **don't** tick "Add a README" (this project already has one). Click **Create repository**.
3. In Terminal, in the project folder (the project is already a git repository with its first
   commit), connect it and upload. Replace `YOUR-USERNAME` with your GitHub user name:
   ```
   git remote add origin https://github.com/YOUR-USERNAME/medtracker.git
   git push -u origin main
   ```
   When git asks for a password, use a GitHub **personal access token**, not your GitHub
   password. To create one: GitHub → Settings → Developer settings → Personal access tokens.
   Give it the "repo" and "workflow" permissions.

**Every time you want new builds:**
1. Change `APP_VERSION` in `config.py` if needed (for example to `1.0.1`), then commit your changes:
   ```
   git add -A
   git commit -m "Version 1.0.1"
   git push
   ```
2. Tag the version and push the tag. **This starts the builds:**
   ```
   git tag v1.0.1
   git push origin v1.0.1
   ```
3. Open your repository on GitHub and click the **Actions** tab to watch the progress. It takes about 10–15 minutes.
   Each machine runs the tests first, then builds.
4. When it finishes, go to **Releases** (on the right of the repository's main page). Download:
   - `MedTracker-Windows.exe` for Windows 10/11
   - `MedTracker-macOS-AppleSilicon.dmg` / `.zip` for Macs with an M1 or newer chip
   - `MedTracker-macOS-Intel.dmg` / `.zip` for Intel Macs
   - `MedTracker-Linux-x86_64.zip` for Linux

You can also start the workflow by hand from the Actions tab (**Run workflow**). A manual run
attaches the builds to the workflow run instead of creating a release.

When you release a new version, update `APP_VERSION` in `config.py`, then push a new tag such as `v1.0.1`.

---

## 3. Using MedTracker

- **New medicine**: use the **➕ New medicine** button on the Stock & Batches page, or
  **Entries → New Medicine** (Ctrl+M). Enter the name, unit and reorder level. The medicine
  starts with no stock, so it shows as OUT OF STOCK until you add stock.
- **Add Stock**: pick a medicine or type a new name. For a new medicine, you'll also be asked
  for its unit and reorder level. The batch number and expiry date are required. If the
  batch already exists, its original expiry date is kept. Stock that is already expired
  needs confirmation.
- **Record Dispensed**: the available stock appears as soon as you choose a medicine.
  Leave the batch on *Automatic (earliest expiry first)*, or choose a specific batch.
  Expired batches and quantities larger than the available stock are blocked. After saving,
  the app shows which batches were used and warns you if stock is now **LOW**.
- **Dispensing Log → Undo last entry**: shows the most recent entry and deletes it after you confirm.
- **Stock & Batches**: double-click **Unit** or **Reorder level** to change them.
  Other values are calculated and can't be edited.
- **Backups**: **File → Backup database** saves a copy with the date in its file name.
  **File → Restore from backup** replaces the current data, but first saves a safety copy of
  your current data in the `backups` folder.

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

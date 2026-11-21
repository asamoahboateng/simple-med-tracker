"""
config.py - Application-wide constants and file locations.

All user data (the database, backups and log files) lives in the per-user data
folder chosen by platformdirs, NEVER next to the program itself:

    Windows : %APPDATA%\\MedTracker
    macOS   : ~/Library/Application Support/MedTracker
    Linux   : ~/.local/share/MedTracker
"""

import sys
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "MedTracker"
APP_VERSION = "1.3.0"
APP_DESCRIPTION = "Medicine inventory and dispensing tracker for small pharmacies and clinics."

# Batches expiring within this many days are flagged as "Expiring soon".
EXPIRY_WARNING_DAYS = 90

# Database file names (the demo database is kept separate from real data).
DB_FILENAME = "medtracker.db"
DEMO_DB_FILENAME = "medtracker_demo.db"
LOG_FILENAME = "medtracker.log"

# --- Updates ---------------------------------------------------------------
# The newest non-pre-release GitHub Release carries latest.json (see scripts/make_manifest.py).
UPDATE_MANIFEST_URL = ("https://github.com/asamoahboateng/simple-med-tracker"
                       "/releases/latest/download/latest.json")
UPDATE_CHECK_HOURS = 24                 # how often the automatic check may run
# Installers may only be downloaded from these hosts (GitHub redirects downloads to the
# githubusercontent ones).
UPDATE_ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com",
                        "release-assets.githubusercontent.com")
RELEASES_PAGE_URL = "https://github.com/asamoahboateng/simple-med-tracker/releases"

# Suggested units shown in the "unit" drop-down (users may type their own).
COMMON_UNITS = [
    "tablets", "capsules", "bottles", "sachets", "vials", "ampoules",
    "tubes", "inhalers", "packs", "ml", "pieces",
]


def data_dir() -> Path:
    """Return the per-user data folder, creating it on first use."""
    path = Path(user_data_dir(APP_NAME, appauthor=False, roaming=True))
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    """Default folder offered when making a backup."""
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def updates_dir() -> Path:
    """Folder where downloaded installers are kept (local, never roamed or backed up)."""
    path = Path(user_data_dir(APP_NAME, appauthor=False, roaming=False)) / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path(demo: bool = False) -> Path:
    """Full path of the SQLite database file (real or demo)."""
    return data_dir() / (DEMO_DB_FILENAME if demo else DB_FILENAME)


def log_path() -> Path:
    """Full path of the error log file."""
    return data_dir() / LOG_FILENAME


def resource_path(relative: str) -> Path:
    """
    Locate a bundled read-only resource (e.g. an icon).

    - Running from source: relative to the project folder.
    - Running as a PyInstaller bundle: relative to the unpacked bundle folder,
      which PyInstaller exposes as sys._MEIPASS.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = Path(sys.argv[0]).resolve().parent if getattr(sys, "frozen", False) \
            else Path(__file__).resolve().parent
    return Path(base) / relative

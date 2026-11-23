"""
ui/cloud_backup_flow.py - The ☁ Back up button: copy the database, then encrypt and upload
it in a background thread (cloud_backup.py does the work), like ui/update_flow.py.
"""

import logging
import socket
import threading
import time
import weakref
from datetime import datetime

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QPushButton

import config
import db
from cloud_backup import CloudBackupError, cloud_config, load_passphrase, upload_backup
from s3client import S3Error
from ui.cloud_settings import CloudSetupDialog
from ui.widgets import show_error, show_info

log = logging.getLogger("medtracker")

NOT_AVAILABLE = "Cloud backup is not available in this version of MedTracker."
NOT_SET_UP = "Cloud backup is not set up on this computer. Ask an administrator."
UPLOADED = "Backup uploaded to the cloud."
IDLE_TEXT, BUSY_TEXT = "☁ Back up", "☁ Backing up…"

# Kept for the whole run: changing colours or text size rebuilds the window, and an upload
# that is still running must neither be started twice nor report to a deleted window.
_busy = False
_relay_object = None
_active = None                     # weakref to the newest window's controller: only it reports


def _settings() -> QSettings:
    return QSettings("MedTracker", "MedTracker")


def last_success() -> float | None:
    value = _settings().value("cloud_backup/last_success")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def tooltip_text(last: float | None, now: float) -> str:
    text = "Back up to the cloud (Ctrl+Shift+B) · "
    if last is None:
        return text + "Never backed up"
    when, today = datetime.fromtimestamp(last), datetime.fromtimestamp(now)
    if when.date() == today.date():
        return text + f"Last: today {when:%H:%M}"
    return text + f"Last: {when.day} {when:%b %H:%M}"


class _Relay(QObject):
    """Carries the background thread's result to the GUI thread."""
    done = Signal(str)                # error message, or "" when the upload worked


def _finished(message: str) -> None:
    global _busy
    _busy = False
    if message:
        log.warning("Cloud backup failed: %s", message)
    else:
        _settings().setValue("cloud_backup/last_success", time.time())


def _relay() -> _Relay:
    global _relay_object
    if _relay_object is None:
        _relay_object = _Relay()
        _relay_object.done.connect(_finished)        # first, so controllers see the new state
    return _relay_object


def _upload(snapshot, passphrase: str) -> None:
    """Runs in a background thread."""
    message = ""
    try:
        upload_backup(cloud_config(), snapshot, passphrase, socket.gethostname(), datetime.now())
    except (S3Error, CloudBackupError) as exc:
        message = str(exc)
    except Exception:                                  # never leave the button stuck
        log.exception("Cloud backup failed")
        message = "The backup could not be uploaded. See the log file for details."
    finally:
        snapshot.unlink(missing_ok=True)
    _relay().done.emit(message)


class CloudBackupController(QObject):
    """Owns the ☁ Back up button of one main window."""

    def __init__(self, window, conn, user):
        global _active
        super().__init__(window)           # deleted with its window
        self.conn = conn
        self.user = user
        self.button = QPushButton(IDLE_TEXT, window)
        self.button.setProperty("kind", "link")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.back_up)
        _relay().done.connect(self._on_done)
        _active = weakref.ref(self)
        self.refresh()

    @property
    def window(self):
        return self.parent()               # not stored, so the window can be freed when replaced

    def refresh(self) -> None:
        self.button.setText(BUSY_TEXT if _busy else IDLE_TEXT)
        self.button.setEnabled(not _busy)
        self.button.setToolTip(tooltip_text(last_success(), time.time()))

    def back_up(self) -> None:
        global _busy
        if _busy:
            return
        if cloud_config() is None:
            show_error(self.window, NOT_AVAILABLE, title="Cloud backup")
            return
        passphrase = load_passphrase()
        if not passphrase:
            if not self.user.is_admin:
                show_error(self.window, NOT_SET_UP, title="Cloud backup")
                return
            if not CloudSetupDialog(self.window).exec():
                return
            passphrase = load_passphrase()
        snapshot = config.backups_dir() / f"cloud_upload_{datetime.now():%Y-%m-%d_%H%M%S}.db"
        try:
            db.backup_to(self.conn, snapshot)      # on this thread: the connection belongs to it
        except Exception:
            log.exception("Could not copy the database for a cloud backup")
            snapshot.unlink(missing_ok=True)
            show_error(self.window, "The database could not be copied for the backup.",
                       title="Cloud backup failed")
            return
        _busy = True
        self.refresh()
        threading.Thread(target=_upload, args=(snapshot, passphrase), daemon=True).start()

    def _on_done(self, message: str) -> None:
        self.refresh()
        if _active is None or _active() is not self:
            return                         # an older, replaced window: no message from it
        if message:
            show_error(self.window, message, title="Cloud backup failed")
        else:
            show_info(self.window, UPLOADED, title="Cloud backup")

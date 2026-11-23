"""
ui/update_flow.py - Checking for updates and installing them (everything the update bar and
the Help menu do). The network work is done by updater.py in background threads.
"""

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QSettings, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QProgressDialog

import config
import db
import updater
from ui.cloud_backup_flow import upload_now
from ui.update_bar import UpdateBar
from ui.widgets import ask_yes_no, show_error, show_info

log = logging.getLogger("medtracker")

AUTO_CHECK_DELAY_MS = 10_000      # wait a little after the window opens

# Kept for the whole run, so signing out or changing colours (which rebuild the window)
# doesn't forget a found update or an installer waiting for the app to close.
_available = None                  # Manifest of a newer version found by a check
_pending = None                    # (Manifest, installer path) to run when the app closes


# --- remembered on this computer (same place as the colour theme) -------------------
def _settings() -> QSettings:
    return QSettings("MedTracker", "MedTracker")


def auto_check_enabled() -> bool:
    return str(_settings().value("updates/auto_check", "true")).lower() != "false"


def set_auto_check(on: bool) -> None:
    _settings().setValue("updates/auto_check", "true" if on else "false")


def last_check_time() -> float:
    try:
        return float(_settings().value("updates/last_check", 0))
    except (TypeError, ValueError):
        return 0.0


def save_last_check(when: float | None = None) -> None:
    _settings().setValue("updates/last_check", datetime.now().timestamp() if when is None else when)


def check_is_due(now: float | None = None) -> bool:
    now = datetime.now().timestamp() if now is None else now
    return now - last_check_time() >= config.UPDATE_CHECK_HOURS * 3600


# --- background workers ------------------------------------------------------------
class _CheckWorker(QObject):
    """Runs the check in a thread; the result is stored, then `finished` is emitted."""
    finished = Signal()

    def __init__(self, interactive: bool = False):
        super().__init__()
        self.interactive = interactive
        self.manifest = None
        self.error = ""

    def start(self, current_version: str) -> None:
        threading.Thread(target=self._run, args=(current_version,), daemon=True).start()

    def _run(self, current_version: str) -> None:
        try:
            self.manifest = updater.check_for_update(current_version)
        except updater.UpdateError as exc:
            self.error = str(exc)
        except Exception as exc:       # never let a thread die silently
            log.exception("Update check crashed")
            self.error = str(exc)
        self.finished.emit()


class _DownloadWorker(QObject):
    """Downloads in a thread; `percent` reports progress, then `finished` after path/error is set."""
    percent = Signal(int)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.cancel = threading.Event()
        self.path = None
        self.error = ""

    def start(self, manifest) -> None:
        threading.Thread(target=self._run, args=(manifest,), daemon=True).start()

    def _run(self, manifest) -> None:
        try:
            self.path = updater.download(
                manifest, updater.updates_dir(), cancelled=self.cancel.is_set,
                progress=lambda done, total: self.percent.emit(int(done * 100 / max(total, 1))))
        except updater.UpdateError as exc:
            self.error = str(exc)
        except Exception as exc:
            log.exception("Update download crashed")
            self.error = str(exc)
        self.finished.emit()


class UpdateController(QObject):
    """Owns the update bar and the update menu actions of one main window."""

    def __init__(self, window, current_version: str = config.APP_VERSION):
        super().__init__(window)
        self.window = window
        self.current_version = current_version
        self.manifest = None
        self._workers = []         # keep running workers alive
        self.bar = UpdateBar()
        self.bar.whats_new.connect(self.show_whats_new)
        self.bar.install_now.connect(self.install_now)
        self.bar.install_on_close.connect(self.install_on_close)
        self.bar.download_page.connect(self.open_download_page)
        if _available is not None and updater.is_newer(_available.version, current_version):
            self.manifest = _available
            self.bar.show_update(_available, current_version)

    # --- starting up ------------------------------------------------------------
    def start_auto_check(self) -> None:
        QTimer.singleShot(AUTO_CHECK_DELAY_MS, self._auto_check)

    def _auto_check(self) -> None:
        if auto_check_enabled() and check_is_due():
            self._start_check(interactive=False)

    def announce_if_updated(self) -> None:
        """Tell the user once when this run is a newer version than the last one."""
        settings = _settings()
        last = str(settings.value("updates/last_run_version", ""))
        settings.setValue("updates/last_run_version", config.APP_VERSION)
        if last and last != config.APP_VERSION:
            for old in config.updates_dir().glob("*"):      # the installer is no longer needed
                try:
                    old.unlink()
                except OSError:
                    pass
            QTimer.singleShot(500, lambda: show_info(
                self.window, f"MedTracker was updated to version {config.APP_VERSION}.",
                title="Updated"))

    # --- checking ---------------------------------------------------------------
    def check_now(self) -> None:
        """Help > Check for updates: always checks, and always says what it found."""
        if self.window.check_access():
            self.window.statusBar().showMessage("Checking for updates...", 5000)
            self._start_check(interactive=True)

    def _start_check(self, interactive: bool) -> None:
        worker = _CheckWorker(interactive)
        self._workers.append(worker)
        # a bound method of a QObject, so the result is handled on the window's thread
        worker.finished.connect(self._check_finished, Qt.QueuedConnection)
        worker.start(self.current_version)

    @Slot()
    def _check_finished(self) -> None:
        global _available
        worker = self.sender()
        self._workers.remove(worker)
        if worker.error:
            log.info("Update check failed: %s", worker.error)     # automatic checks stay silent
            if worker.interactive:
                show_error(self.window, worker.error, title="Cannot check for updates")
            return
        manifest = worker.manifest
        save_last_check()
        _available = manifest
        if manifest is None:
            self.bar.hide()
            if worker.interactive:
                show_info(self.window, f"You have the latest version ({self.current_version}).",
                          title="No updates")
            return
        self.manifest = manifest
        self.bar.show_update(manifest, self.current_version)
        log.info("Update available: %s", manifest.version)

    # --- bar buttons ------------------------------------------------------------
    def show_whats_new(self) -> None:
        if self.manifest is not None:
            show_info(self.window, self.manifest.notes or "No release notes were provided.",
                      title=f"What's new in {self.manifest.version}")

    def open_download_page(self) -> None:
        QDesktopServices.openUrl(QUrl(config.RELEASES_PAGE_URL))

    def _confirm(self, manifest) -> bool:
        return ask_yes_no(
            self.window,
            f"MedTracker will back up your data, close, install {manifest.version} and reopen.\n\n"
            f"Continue?", title="Install update", yes_text="Install", no_text="Cancel")

    def install_now(self) -> None:
        manifest = self.manifest
        if manifest is None or not self.window.check_access() or not self._confirm(manifest):
            return
        installer = self._download(manifest)
        if installer is not None:
            self._backup_and_install(installer, interactive=True)

    def install_on_close(self) -> None:
        global _pending
        manifest = self.manifest
        if manifest is None or not self.window.check_access():
            return
        installer = self._download(manifest)
        if installer is None:
            return
        _pending = (manifest, installer)
        self.bar.hide()
        self.window.statusBar().showMessage(
            f"MedTracker {manifest.version} will be installed when you close the program.", 20000)
        show_info(self.window, f"MedTracker {manifest.version} is downloaded. It will be "
                  f"installed (after a backup of your data) when you close MedTracker.",
                  title="Update ready")

    def install_from_file(self) -> None:
        """Help > Install update from file: latest.json plus the installer, e.g. from a USB stick."""
        if not self.window.check_access():
            return
        path, _ = QFileDialog.getOpenFileName(
            self.window, "Choose latest.json", "", "Update information (latest.json *.json)")
        if not path:
            return
        try:
            manifest, installer = updater.manifest_from_folder(path)
        except updater.UpdateError as exc:
            show_error(self.window, str(exc), title="Cannot install update")
            return
        if not updater.is_newer(manifest.version, self.current_version):
            show_info(self.window, f"That update ({manifest.version}) is not newer than the "
                      f"version you have ({self.current_version}).", title="No update needed")
            return
        if updater.needs_manual_install(manifest, self.current_version) \
                or not updater.can_self_install():
            show_error(self.window, f"MedTracker {manifest.version} has to be installed by "
                       f"running the installer yourself:\n{installer}", title="Install by hand")
            return
        if self._confirm(manifest):
            self._backup_and_install(installer, interactive=True)

    # --- the work ---------------------------------------------------------------
    def _download(self, manifest):
        """Download and verify with a progress window; the installer path, or None."""
        worker = _DownloadWorker()
        progress = QProgressDialog(f"Downloading MedTracker {manifest.version}...", "Cancel",
                                   0, 100, self.window)
        progress.setWindowTitle("Downloading update")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        loop = QEventLoop()
        worker.percent.connect(progress.setValue, Qt.QueuedConnection)
        worker.finished.connect(loop.quit, Qt.QueuedConnection)
        progress.canceled.connect(worker.cancel.set)
        progress.setValue(0)
        progress.show()
        worker.start(manifest)
        loop.exec()
        progress.close()
        if worker.path is not None:
            return worker.path
        message = worker.error
        if message != "Download cancelled.":
            show_error(self.window, f"{message}\n\nNothing was installed.",
                       title="Update failed")
        return None

    def _backup_and_install(self, installer, quit_after: bool = True,
                            interactive: bool = False) -> bool:
        """
        Back up the data (here and, when this build has the keys, to the cloud), start the installer, and
        (normally) close MedTracker. `interactive`: someone clicked Install, so a failed cloud
        backup asks whether to go on; otherwise (installing on close) it is only logged.
        """
        try:
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            backup = config.backups_dir() / f"before-update-{self.current_version}-{stamp}.db"
            db.backup_to(self.window.conn, backup)
            if not self._cloud_backup(backup, interactive):
                return False
            updater.run_installer(installer)
        except (updater.UpdateError, OSError, sqlite3.Error) as exc:
            log.exception("Update install failed")
            show_error(self.window, f"{exc}\n\nNothing was installed. MedTracker keeps running "
                       f"as before.", title="Update failed")
            return False
        log.info("Installer started: %s", installer)
        if quit_after:
            self._clear_pending()
            self.window.close()          # closes the database and quits
        return True

    def _cloud_backup(self, backup, interactive: bool) -> bool:
        """Upload the pre-update backup. False when the user chose not to install after all."""
        if getattr(self.window, "demo", False):
            return True
        self.window.statusBar().showMessage("Backing up to the cloud before the update...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            error = upload_now(backup)
        finally:
            QApplication.restoreOverrideCursor()
            self.window.statusBar().clearMessage()
        if error and interactive:
            return ask_yes_no(
                self.window, f"Cloud backup failed: {error}\n\nYour data was still backed up on "
                f"this computer.\n\nInstall the update anyway?", title="Cloud backup failed",
                yes_text="Install", no_text="Cancel")
        return True

    def _clear_pending(self) -> None:
        global _pending
        _pending = None

    def run_pending_install(self) -> None:
        """Called when the window closes: install a downloaded update, if one is waiting."""
        if _pending is None:
            return
        _manifest, installer = _pending
        self._clear_pending()
        self._backup_and_install(installer, quit_after=False)

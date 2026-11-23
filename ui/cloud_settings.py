"""ui/cloud_settings.py - Restoring from a cloud backup."""

import shutil
import socket
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout,
)

from cloud_backup import CloudBackupError, cloud_config, download_backup, list_backups, slug
from s3client import S3Error
from ui import theme
from ui.widgets import dialog_header, make_button, show_error


def _row_text(key: str, size: int, this_pc: str) -> str:
    """'23 Nov 2026 09:05 · front-desk-pc · 1.2 MB' for pc/medtracker_2026-11-23_090500.db.gz"""
    computer, _, name = key.rpartition("/")
    try:
        when = datetime.strptime(name[len("medtracker_"):][:17], "%Y-%m-%d_%H%M%S")
        shown = f"{when.day} {when:%b %Y %H:%M}"
    except ValueError:
        shown = name
    if computer == this_pc:
        computer += " (this PC)"
    amount = f"{size / 1_000_000:.1f} MB" if size >= 100_000 else f"{max(1, round(size / 1000))} KB"
    return f"{shown} · {computer} · {amount}"


class _ListRelay(QObject):
    """Carries the background listing back to the GUI thread."""
    done = Signal(object, str)        # list of ObjectInfo, error message


class CloudRestoreDialog(QDialog):
    """Pick one of the backups on the server; after exec(), chosen_file() is the downloaded copy."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restore from cloud backup")
        self.setMinimumSize(560, 460)
        self._chosen = None
        self._temp_dir = None

        self.backups = QListWidget()
        self.backups.currentRowChanged.connect(lambda row: self.restore_button.setEnabled(row >= 0))
        self.backups.itemDoubleClicked.connect(lambda _item: self.restore_selected())
        self.status = QLabel("Loading the list of backups…")
        self.status.setWordWrap(True)

        self.restore_button = make_button("Restore", "primary")
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self.restore_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.addButton(self.restore_button, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(dialog_header("Restore from cloud backup",
                                       "Newest first, from every computer", "☁", theme.PRIMARY))
        layout.addWidget(self.status)
        layout.addWidget(self.backups, 1)
        layout.addWidget(buttons)

        self._relay = _ListRelay()          # no parent: may outlive the dialog until the thread ends
        self._relay.done.connect(self._show_list)
        cfg, relay = cloud_config(), self._relay

        def load():
            try:
                relay.done.emit(list_backups(cfg), "")
            except S3Error as exc:
                relay.done.emit([], str(exc))
        threading.Thread(target=load, daemon=True).start()

    def _show_list(self, found, error: str) -> None:
        this_pc = slug(socket.gethostname())
        for info in found:
            item = QListWidgetItem(_row_text(info.key, info.size, this_pc))
            item.setData(Qt.UserRole, info.key)
            self.backups.addItem(item)
        if error:
            self.status.setText(error)
        elif not found:
            self.status.setText("There are no cloud backups yet.")
        else:
            self.status.setText("Choose the backup to restore. All current data on this computer "
                                "will be replaced by it.")
        self.backups.setCurrentRow(-1)

    def restore_selected(self) -> None:
        item = self.backups.currentItem()
        if item is None:
            return
        self._temp_dir = self._temp_dir or Path(tempfile.mkdtemp(prefix="medtracker_restore_"))
        dest = self._temp_dir / "cloud_backup.db"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            download_backup(cloud_config(), item.data(Qt.UserRole), dest)
        except (S3Error, CloudBackupError) as exc:
            QApplication.restoreOverrideCursor()
            show_error(self, str(exc), title="Cannot restore")
            return
        QApplication.restoreOverrideCursor()
        self._chosen = dest
        self.chosen_label = item.text()
        self.accept()

    def chosen_file(self) -> Path | None:
        return self._chosen

    def remove_download(self) -> None:
        """Delete the downloaded copy (call after restoring)."""
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)

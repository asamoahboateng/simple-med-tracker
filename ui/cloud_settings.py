"""ui/cloud_settings.py - Setting up cloud backup (the passphrase) and restoring from it."""

import shutil
import socket
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QVBoxLayout,
)

from cloud_backup import (
    CloudBackupError, cloud_config, download_backup, list_backups, load_passphrase, save_passphrase,
    slug,
)
from s3client import S3Error
from ui import theme
from ui.widgets import dialog_header, make_button, show_error, style_dialog_buttons

MIN_PASSPHRASE = 8


class CloudSetupDialog(QDialog):
    """Choose the passphrase that encrypts this computer's cloud backups."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cloud backup setup")
        self.setMinimumWidth(480)
        self.has_passphrase = bool(load_passphrase())
        self.passphrase = QLineEdit()
        self.confirm = QLineEdit()
        for edit in (self.passphrase, self.confirm):
            edit.setEchoMode(QLineEdit.Password)
        self.passphrase.setPlaceholderText(
            "Leave empty to keep the current one" if self.has_passphrase
            else f"At least {MIN_PASSPHRASE} characters")

        form = QFormLayout()
        form.addRow("Passphrase:", self.passphrase)
        form.addRow("Confirm:", self.confirm)
        hint = QLabel("Write this passphrase down and keep it safe. Without it the cloud "
                      "backups cannot be restored."
                      + (" Backups made before a change still need the old passphrase."
                         if self.has_passphrase else ""))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.AMBER_TEXT}; font-weight: 700;")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        style_dialog_buttons(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(dialog_header("Cloud backup", "Backups are encrypted with this passphrase "
                                       "before they leave the computer", "☁", theme.PRIMARY))
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def save(self) -> str:
        """Store the passphrase. Returns an error message, or "" when saved (or kept)."""
        first, second = self.passphrase.text(), self.confirm.text()
        if self.has_passphrase and not first and not second:
            return ""
        if first != second:
            return "Passphrases do not match."
        if len(first) < MIN_PASSPHRASE:
            return f"Use at least {MIN_PASSPHRASE} characters for the passphrase."
        try:
            save_passphrase(first)
        except CloudBackupError as exc:
            return str(exc)
        return ""

    def accept(self):
        error = self.save()
        if error:
            show_error(self, error)
            return
        super().accept()


def _row_text(key: str, size: int, this_pc: str) -> str:
    """'23 Nov 2026 09:05 · front-desk-pc · 1.2 MB' for pc/medtracker_2026-11-23_090500.db.gz.enc"""
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
    """Pick one of the backups on the server; after exec(), chosen_file() is the decrypted copy."""

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
        self.passphrase = QLineEdit(load_passphrase())
        self.passphrase.setEchoMode(QLineEdit.Password)
        form = QFormLayout()
        form.addRow("Passphrase:", self.passphrase)

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
        layout.addLayout(form)
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
            download_backup(cloud_config(), item.data(Qt.UserRole), self.passphrase.text(), dest)
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

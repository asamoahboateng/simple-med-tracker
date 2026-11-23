"""ui/cloud_settings.py - Setting up cloud backup (the passphrase) and restoring from it."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from cloud_backup import CloudBackupError, load_passphrase, save_passphrase
from ui import theme
from ui.widgets import dialog_header, show_error, style_dialog_buttons

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

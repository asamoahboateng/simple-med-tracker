"""ui/about.py - Help > About MedTracker: the version and details about this computer."""

import platform
import socket
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout,
)

import auth
import config
from ui import theme
from ui.widgets import dialog_header, make_button


def _operating_system() -> str:
    if platform.system() == "Darwin":
        name = f"macOS {platform.mac_ver()[0]}"
    else:
        name = f"{platform.system()} {platform.release()}"
    return f"{name} ({platform.machine()})"


def system_details(user: auth.User, db_path: Path, demo: bool,
                   last_backup: float | None) -> list[tuple[str, str]]:
    """(label, value) pairs shown in the About window and copied for support."""
    if last_backup is None:
        backed_up = "Never"
    else:
        when = datetime.fromtimestamp(last_backup)
        backed_up = f"{when.day} {when:%b %Y %H:%M}"
    details = [
        ("Version", config.APP_VERSION),
        ("Computer", socket.gethostname()),
        ("Operating system", _operating_system()),
        ("Signed in as", f"{user.display_name} ({user.role_name})"),
        ("Database", str(db_path)),
        ("Last cloud backup", backed_up),
    ]
    if demo:
        details.append(("Mode", "Demo (sample data)"))
    return details


class AboutDialog(QDialog):
    def __init__(self, user: auth.User, db_path: Path, demo: bool, last_backup: float | None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {config.APP_NAME}")
        self.setMinimumWidth(520)
        self.details = system_details(user, db_path, demo, last_backup)

        form = QFormLayout()
        for label, value in self.details:
            text = QLabel(value)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if label == "Version":
                text.setStyleSheet(f"font-weight: 700; color: {theme.TEXT};")
            form.addRow(f"{label}:", text)

        copy = make_button("Copy details")
        copy.clicked.connect(self.copy_details)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.addButton(copy, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(dialog_header(f"{config.APP_NAME} {config.APP_VERSION}",
                                       config.APP_DESCRIPTION, "✚", theme.PRIMARY))
        layout.addLayout(form)
        layout.addWidget(buttons)

    def copy_details(self) -> None:
        """Put the details on the clipboard, e.g. to send to whoever supports MedTracker."""
        QApplication.clipboard().setText(
            "\n".join(f"{label}: {value}" for label, value in self.details))

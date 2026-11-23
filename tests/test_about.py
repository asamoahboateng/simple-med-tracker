"""Help > About MedTracker: version and system details."""

import platform
import socket
from datetime import datetime

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

import auth
import config
from ui.about import AboutDialog, system_details

ADMIN = auth.User(None, "superadmin", "Superadmin", auth.SUPERADMIN)


def test_details_include_version_and_system(tmp_path):
    details = dict(system_details(ADMIN, tmp_path / "medtracker.db", demo=False, last_backup=None))
    assert details["Version"] == config.APP_VERSION
    assert details["Computer"] == socket.gethostname()
    system = {"Darwin": "macOS"}.get(platform.system(), platform.system())
    assert details["Operating system"].startswith(system)
    assert details["Signed in as"] == "Superadmin (Superadmin)"
    assert details["Database"] == str(tmp_path / "medtracker.db")
    assert details["Last cloud backup"] == "Never"
    assert "Mode" not in details


def test_details_show_demo_and_last_backup(tmp_path):
    details = dict(system_details(ADMIN, tmp_path / "demo.db", demo=True, last_backup=1795424700.0))
    assert details["Mode"] == "Demo (sample data)"
    when = datetime.fromtimestamp(1795424700.0)
    assert details["Last cloud backup"] == f"{when.day} {when:%b %Y %H:%M}"


def test_copy_details_puts_text_on_clipboard(qapp, tmp_path):
    dialog = AboutDialog(ADMIN, tmp_path / "medtracker.db", demo=False, last_backup=None)
    dialog.copy_details()
    text = QApplication.clipboard().text()
    assert f"Version: {config.APP_VERSION}" in text and f"Computer: {socket.gethostname()}" in text


def test_about_stays_in_help_menu(qapp, conn, tmp_path, isolated_settings):
    from ui.main_window import MainWindow
    window = MainWindow(conn, tmp_path / "x.db", ADMIN)
    help_menu = [a.menu() for a in window.menuBar().actions() if a.text() == "&Help"][0]
    about = [a for a in help_menu.actions() if a.text() == "About MedTracker..."][0]
    assert about.menuRole() == QAction.NoRole        # macOS would move it out of Help otherwise
    window.signing_out = True
    window.close()

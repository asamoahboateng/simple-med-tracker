"""Restoring from a cloud backup: the list of backups, the passphrase and the restore itself."""

import socket
import time
from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication, QDialog

import auth
import cloud_backup
import db
from cloud_backup import slug, upload_backup
from ui import cloud_settings
from ui.cloud_settings import CloudRestoreDialog

ADMIN = auth.User(None, "superadmin", "Superadmin", auth.SUPERADMIN)


@pytest.fixture
def env(qapp, tmp_path, monkeypatch, memory_keyring, fake_s3):
    monkeypatch.setattr(cloud_settings, "cloud_config", lambda: fake_s3.cfg)
    messages = []
    monkeypatch.setattr(cloud_settings, "show_error", lambda parent, text, title="": messages.append(text))
    fake_s3.messages = messages
    return fake_s3


def wait_until(condition, timeout=10):
    end = time.time() + timeout
    while not condition():
        QApplication.processEvents()
        assert time.time() < end, "timed out"
        time.sleep(0.01)


def upload(env, conn, tmp_path, computer, when, passphrase="passphrase1"):
    db.backup_to(conn, tmp_path / "snap.db")
    return upload_backup(env.cfg, tmp_path / "snap.db", passphrase, computer, when)


def test_restore_dialog_lists_newest_first(env, conn, tmp_path):
    upload(env, conn, tmp_path, "front-desk-pc", datetime(2026, 11, 20, 8, 40))
    upload(env, conn, tmp_path, socket.gethostname(), datetime(2026, 11, 23, 9, 5))
    dialog = CloudRestoreDialog()
    wait_until(lambda: dialog.backups.count() == 2)
    first, second = dialog.backups.item(0).text(), dialog.backups.item(1).text()
    assert first.startswith(f"23 Nov 2026 09:05 · {slug(socket.gethostname())} (this PC) · ")
    assert second.startswith("20 Nov 2026 08:40 · front-desk-pc · ")
    assert not dialog.restore_button.isEnabled()
    dialog.backups.setCurrentRow(1)
    assert dialog.restore_button.isEnabled()


def test_passphrase_prefilled_from_keyring(env):
    cloud_backup.save_passphrase("passphrase1")
    assert CloudRestoreDialog().passphrase.text() == "passphrase1"


def test_wrong_passphrase_shows_error_and_returns_nothing(env, conn, tmp_path):
    upload(env, conn, tmp_path, "pc1", datetime(2026, 11, 23, 9, 5))
    dialog = CloudRestoreDialog()
    wait_until(lambda: dialog.backups.count() == 1)
    dialog.backups.setCurrentRow(0)
    dialog.passphrase.setText("wrong-pass")
    dialog.restore_selected()
    assert env.messages == ["The backup passphrase is not correct."]
    assert dialog.chosen_file() is None
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_server_error_while_listing_is_shown(env):
    env.fail_with = (500, "InternalError")
    dialog = CloudRestoreDialog()
    wait_until(lambda: dialog.status.text().startswith("The backup server had a problem"))
    assert dialog.backups.count() == 0


def test_chosen_backup_restores_through_existing_checks(env, conn, add, tmp_path, monkeypatch):
    from ui import main_window
    from ui.main_window import MainWindow

    add(name="Amoxicillin")
    upload(env, conn, tmp_path, "pc1", datetime(2026, 11, 23, 9, 5))
    add(name="Ibuprofen", batch="B002")                # added after the backup: gone after restore
    dialog = CloudRestoreDialog()
    wait_until(lambda: dialog.backups.count() == 1)
    dialog.backups.setCurrentRow(0)
    dialog.passphrase.setText("passphrase1")
    dialog.restore_selected()
    path = dialog.chosen_file()
    assert db.is_valid_backup(path)

    backups = tmp_path / "backups"
    monkeypatch.setattr(main_window.config, "backups_dir", lambda: backups)
    monkeypatch.setattr(main_window, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(main_window, "show_info", lambda *a, **k: None)
    window = MainWindow(conn, tmp_path / "live.db", ADMIN)
    window.restore_file(path, "the cloud backup")
    names = [m["name"] for m in db.list_medicines(conn)]
    assert "Amoxicillin" in names and "Ibuprofen" not in names
    assert list(backups.glob("before_restore_*.db"))
    window.signing_out = True
    window.close()


def test_admin_menu_has_cloud_restore(env, conn, tmp_path):
    from ui.main_window import MainWindow
    window = MainWindow(conn, tmp_path / "x.db", ADMIN)
    texts = [a.text() for a in window.menuBar().actions()[0].menu().actions()]
    assert "Restore from cloud backup..." in texts
    window.signing_out = True
    window.close()

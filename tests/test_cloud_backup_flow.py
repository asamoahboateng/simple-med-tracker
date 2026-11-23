"""The ☁ Back up button: uploading in the background, messages and the setup dialog."""

import threading
import time
from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication, QWidget

import auth
import db
import cloud_backup
from ui import cloud_backup_flow as flow
from ui.cloud_settings import CloudSetupDialog

ADMIN = auth.User(None, "superadmin", "Superadmin", auth.SUPERADMIN)
CLERK = auth.User(2, "clerk", "Clerk", auth.USER)
NOW = datetime(2026, 11, 23, 9, 0).timestamp()


@pytest.fixture
def env(qapp, tmp_path, monkeypatch, memory_keyring, fake_s3, isolated_settings):
    """Isolated settings, keyring and server; message boxes recorded instead of shown."""
    monkeypatch.setattr(flow, "cloud_config", lambda: fake_s3.cfg)
    monkeypatch.setattr(flow.config, "backups_dir", lambda: tmp_path)
    messages = []
    monkeypatch.setattr(flow, "show_info", lambda parent, text, title="": messages.append(("info", text)))
    monkeypatch.setattr(flow, "show_error", lambda parent, text, title="": messages.append(("error", text)))
    monkeypatch.setattr(flow, "_busy", False)
    monkeypatch.setattr(flow, "_active", None)
    fake_s3.messages = messages
    fake_s3.tmp = tmp_path
    return fake_s3


def wait_until(condition, timeout=10):
    end = time.time() + timeout
    while not condition():
        QApplication.processEvents()
        assert time.time() < end, "timed out"
        time.sleep(0.01)


def controller(conn, user=ADMIN):
    window = QWidget()
    return window, flow.CloudBackupController(window, conn, user)


@pytest.mark.parametrize("last,text", [
    (None, "Back up to the cloud (Ctrl+Shift+B) · Never backed up"),
    (NOW - 3600, "Back up to the cloud (Ctrl+Shift+B) · Last: today 08:00"),
    (NOW - 2 * 86400, "Back up to the cloud (Ctrl+Shift+B) · Last: 21 Nov 09:00"),
])
def test_tooltip_text(last, text):
    assert flow.tooltip_text(last, NOW) == text


def test_back_up_uploads_and_records_success(env, conn, add):
    add()
    cloud_backup.save_passphrase("passphrase1")
    window, ctl = controller(conn)
    ctl.back_up()
    wait_until(lambda: env.messages)
    assert env.messages == [("info", "Backup uploaded to the cloud.")]
    assert len(env.store) == 1
    assert flow.last_success() is not None
    assert not list(env.tmp.glob("cloud_upload_*.db"))           # the temporary copy is gone
    assert ctl.button.isEnabled() and ctl.button.text() == "☁ Back up"


def test_failure_reports_and_keeps_last_success(env, conn):
    cloud_backup.save_passphrase("passphrase1")
    env.fail_with = (500, "InternalError")
    window, ctl = controller(conn)
    ctl.back_up()
    wait_until(lambda: env.messages)
    assert env.messages == [("error", "The backup server had a problem (InternalError). Try again later.")]
    assert flow.last_success() is None
    assert ctl.button.isEnabled()
    assert not list(env.tmp.glob("cloud_upload_*.db"))


def _blocked_upload(monkeypatch):
    release, calls = threading.Event(), []

    def slow_upload(*args):
        calls.append(args)
        release.wait(5)
        return "pc/medtracker_x.db.gz.enc"
    monkeypatch.setattr(flow, "upload_backup", slow_upload)
    return release, calls


def test_double_press_uploads_once(env, conn, monkeypatch):
    cloud_backup.save_passphrase("passphrase1")
    release, calls = _blocked_upload(monkeypatch)
    window, ctl = controller(conn)
    ctl.back_up()
    assert ctl.button.text() == "☁ Backing up…" and not ctl.button.isEnabled()
    ctl.back_up()
    release.set()
    wait_until(lambda: not flow._busy)
    assert len(calls) == 1


def test_window_closed_during_upload_does_not_crash(env, conn, monkeypatch):
    cloud_backup.save_passphrase("passphrase1")
    release, calls = _blocked_upload(monkeypatch)
    window, ctl = controller(conn)
    ctl.back_up()
    window.deleteLater()
    QApplication.processEvents()
    new_window, new_ctl = controller(conn)            # e.g. the colour theme rebuilt the window
    assert not new_ctl.button.isEnabled()             # still uploading: no second upload
    release.set()
    wait_until(lambda: not flow._busy)
    QApplication.processEvents()
    assert new_ctl.button.isEnabled()
    assert flow.last_success() is not None
    assert env.messages == [("info", "Backup uploaded to the cloud.")]   # once, from the new window


def test_replaced_window_that_still_exists_stays_quiet(env, conn, add):
    cloud_backup.save_passphrase("passphrase1")
    old_window, old_ctl = controller(conn)           # not deleted yet (still referenced)
    new_window, new_ctl = controller(conn)
    old_ctl.back_up()
    wait_until(lambda: env.messages)
    QApplication.processEvents()
    assert env.messages == [("info", "Backup uploaded to the cloud.")]


def test_not_set_up_non_admin_gets_message(env, conn):
    window, ctl = controller(conn, CLERK)
    ctl.back_up()
    assert env.messages == [("error", "Cloud backup is not set up on this computer. Ask an administrator.")]
    assert not env.requests


def test_no_keys_message(env, conn, monkeypatch):
    monkeypatch.setattr(flow, "cloud_config", lambda: None)
    window, ctl = controller(conn)
    ctl.back_up()
    assert env.messages == [("error", "Cloud backup is not available in this version of MedTracker.")]


@pytest.mark.parametrize("first,second,error", [
    ("passphrase1", "passphrase2", "Passphrases do not match."),
    ("short", "short", "Use at least 8 characters for the passphrase."),
    ("", "", "Use at least 8 characters for the passphrase."),
])
def test_setup_rejects_bad_passphrase(env, first, second, error):
    dialog = CloudSetupDialog()
    dialog.passphrase.setText(first)
    dialog.confirm.setText(second)
    assert dialog.save() == error
    assert cloud_backup.load_passphrase() == ""


def test_setup_saves_passphrase_and_blank_keeps_it(env):
    dialog = CloudSetupDialog()
    dialog.passphrase.setText("passphrase1")
    dialog.confirm.setText("passphrase1")
    assert dialog.save() == ""
    assert cloud_backup.load_passphrase() == "passphrase1"
    again = CloudSetupDialog()                        # reopened: leaving it blank keeps it
    assert again.save() == ""
    assert cloud_backup.load_passphrase() == "passphrase1"


def test_main_window_button_and_menu(env, conn, tmp_path):
    from ui.main_window import MainWindow
    window = MainWindow(conn, tmp_path / "x.db", ADMIN)
    texts = [a.text() for a in window.menuBar().actions()[0].menu().actions()]
    assert "Back up to cloud" in texts and "Cloud backup setup..." in texts
    assert window.cloud.button.text() == "☁ Back up"
    window.signing_out = True
    window.close()


def test_demo_mode_has_no_button(env, conn, tmp_path):
    from ui.main_window import MainWindow
    window = MainWindow(conn, tmp_path / "x.db", ADMIN, demo=True)
    texts = [a.text() for a in window.menuBar().actions()[0].menu().actions()]
    assert "Back up to cloud" not in texts and "Cloud backup setup..." not in texts
    assert window.cloud is None
    window.signing_out = True
    window.close()


# --- before an update ------------------------------------------------------------

def test_upload_now_uploads_and_records(env, conn, tmp_path):
    cloud_backup.save_passphrase("passphrase1")
    db.backup_to(conn, tmp_path / "before-update.db")
    assert flow.upload_now(tmp_path / "before-update.db") == ""
    assert len(env.store) == 1
    assert flow.last_success() is not None
    assert (tmp_path / "before-update.db").exists()      # the local backup is kept


def test_upload_now_skips_when_not_set_up(env, conn, tmp_path, monkeypatch):
    db.backup_to(conn, tmp_path / "b.db")
    assert flow.upload_now(tmp_path / "b.db") is None     # no passphrase
    cloud_backup.save_passphrase("passphrase1")
    monkeypatch.setattr(flow, "cloud_config", lambda: None)
    assert flow.upload_now(tmp_path / "b.db") is None     # no keys
    assert not env.requests


def test_upload_now_reports_failure(env, conn, tmp_path):
    cloud_backup.save_passphrase("passphrase1")
    env.fail_with = (500, "InternalError")
    db.backup_to(conn, tmp_path / "b.db")
    assert flow.upload_now(tmp_path / "b.db") == \
        "The backup server had a problem (InternalError). Try again later."
    assert flow.last_success() is None


def _update_window(env, conn, tmp_path, monkeypatch, demo=False):
    from ui import update_flow
    from ui.main_window import MainWindow
    started = []
    monkeypatch.setattr(update_flow.updater, "run_installer",
                        lambda installer: started.append(len(env.store)))
    monkeypatch.setattr(update_flow.config, "backups_dir", lambda: tmp_path)
    window = MainWindow(conn, tmp_path / "x.db", ADMIN, demo=demo)
    return window, started


def test_update_uploads_to_cloud_before_installing(env, conn, tmp_path, monkeypatch):
    cloud_backup.save_passphrase("passphrase1")
    window, started = _update_window(env, conn, tmp_path, monkeypatch)
    assert window.updates._backup_and_install(tmp_path / "setup.exe", quit_after=False)
    assert started == [1]                                 # the upload happened first
    window.signing_out = True
    window.close()


def test_update_asks_when_cloud_backup_fails(env, conn, tmp_path, monkeypatch):
    from ui import update_flow
    cloud_backup.save_passphrase("passphrase1")
    env.fail_with = (500, "InternalError")
    asked = []
    monkeypatch.setattr(update_flow, "ask_yes_no", lambda parent, text, **k: asked.append(text) or False)
    window, started = _update_window(env, conn, tmp_path, monkeypatch)
    assert not window.updates._backup_and_install(tmp_path / "setup.exe", quit_after=False,
                                                  interactive=True)
    assert "Cloud backup failed" in asked[0] and "Install the update anyway?" in asked[0]
    assert started == []                                  # answered No: nothing installed
    window.signing_out = True
    window.close()


def test_update_on_close_installs_even_if_cloud_fails(env, conn, tmp_path, monkeypatch):
    cloud_backup.save_passphrase("passphrase1")
    env.fail_with = (500, "InternalError")
    window, started = _update_window(env, conn, tmp_path, monkeypatch)
    assert window.updates._backup_and_install(tmp_path / "setup.exe", quit_after=False)
    assert started == [0]
    window.signing_out = True
    window.close()


def test_update_without_cloud_setup_installs_as_before(env, conn, tmp_path, monkeypatch):
    window, started = _update_window(env, conn, tmp_path, monkeypatch)
    assert window.updates._backup_and_install(tmp_path / "setup.exe", quit_after=False)
    assert started == [0] and not env.requests
    window.signing_out = True
    window.close()


def test_demo_update_never_uploads(env, conn, tmp_path, monkeypatch):
    cloud_backup.save_passphrase("passphrase1")
    window, started = _update_window(env, conn, tmp_path, monkeypatch, demo=True)
    assert window.updates._backup_and_install(tmp_path / "setup.exe", quit_after=False)
    assert started == [0] and not env.requests
    window.signing_out = True
    window.close()

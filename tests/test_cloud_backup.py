"""Cloud backup: encrypting, naming, uploading and downloading backups (cloud_backup.py)."""

import pytest

import db
from cloud_backup import CloudBackupError, pack, unpack


def test_pack_round_trip_smaller_and_unreadable(conn, add, tmp_path):
    add()
    db.backup_to(conn, tmp_path / "s.db")
    plain = (tmp_path / "s.db").read_bytes()
    blob = pack(plain, "correct horse")
    assert blob.startswith(b"MTCB1")
    assert len(blob) < len(plain)
    assert b"Paracetamol" not in blob
    assert unpack(blob, "correct horse") == plain


def test_wrong_passphrase():
    with pytest.raises(CloudBackupError, match="The backup passphrase is not correct."):
        unpack(pack(b"x" * 100, "right"), "wrong")


def test_not_a_backup_file():
    with pytest.raises(CloudBackupError, match="not a MedTracker cloud backup"):
        unpack(b"SQLite format 3\x00" + b"\x00" * 100, "p")


def test_same_input_packs_differently():
    assert pack(b"abc", "p") != pack(b"abc", "p")


# --- naming, upload, list, download ----------------------------------------------

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import keyring
from keyring.backend import KeyringBackend

import cloud_backup
from cloud_backup import (
    cloud_config, download_backup, list_backups, load_passphrase, object_key, save_passphrase, slug,
    upload_backup,
)

ROOT = Path(__file__).resolve().parent.parent


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


@pytest.fixture
def memory_keyring():
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield
    keyring.set_keyring(previous)


@pytest.mark.parametrize("raw,expected", [
    ("Front Desk", "front-desk"), ("PHARM-PC_01", "pharm-pc-01"), ("Kɔfi’s PC", "k-fi-s-pc"),
    ("", "unnamed"), ("---", "unnamed"), ("x" * 60, "x" * 40)])
def test_slug(raw, expected):
    assert slug(raw) == expected


def test_object_key():
    assert object_key("PC 1", datetime(2026, 11, 23, 9, 5, 7)) == "pc-1/medtracker_2026-11-23_090507.db.gz.enc"


def test_upload_list_download_round_trip(fake_s3, conn, add, tmp_path):
    add()
    db.backup_to(conn, tmp_path / "s.db")
    key = upload_backup(fake_s3.cfg, tmp_path / "s.db", "passphrase1", "PC1", datetime(2026, 11, 23, 9, 5))
    assert key == "pc1/medtracker_2026-11-23_090500.db.gz.enc"
    assert list_backups(fake_s3.cfg)[0].key == key
    download_backup(fake_s3.cfg, key, "passphrase1", tmp_path / "back.db")
    assert db.is_valid_backup(tmp_path / "back.db")


def test_list_backups_all_pcs_newest_first_backups_only(fake_s3):
    for key in ("pc1/medtracker_2026-11-01_090000.db.gz.enc", "pc2/medtracker_2026-11-20_090000.db.gz.enc",
                "pc1/medtracker_2026-11-10_090000.db.gz.enc", "notes.txt"):
        fake_s3.store[key] = b"x"
    assert [o.key for o in list_backups(fake_s3.cfg)] == [
        "pc2/medtracker_2026-11-20_090000.db.gz.enc", "pc1/medtracker_2026-11-10_090000.db.gz.enc",
        "pc1/medtracker_2026-11-01_090000.db.gz.enc"]


def test_download_with_wrong_passphrase_writes_nothing(fake_s3, conn, tmp_path):
    db.backup_to(conn, tmp_path / "s.db")
    key = upload_backup(fake_s3.cfg, tmp_path / "s.db", "passphrase1", "PC1", datetime(2026, 11, 23))
    with pytest.raises(CloudBackupError, match="passphrase is not correct"):
        download_backup(fake_s3.cfg, key, "wrong-pass", tmp_path / "back.db")
    assert not (tmp_path / "back.db").exists()


def _make_keys(tmp_path, env_text, extra_env=None):
    (tmp_path / ".env").write_text(env_text)
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("MINIO_")}
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "make_cloud_keys.py"),
                           "--env", str(tmp_path / ".env"), "--out", str(tmp_path / "k.py")],
                          capture_output=True, text=True, env=env, check=True)


def test_make_cloud_keys_from_env_file(tmp_path):
    result = _make_keys(tmp_path, "#minio\naccesskey=AKEY123\nsecretkey=SKEY456\n")
    text = (tmp_path / "k.py").read_text()
    assert 'ACCESS_KEY = "AKEY123"' in text and 'SECRET_KEY = "SKEY456"' in text
    assert "AKEY123" not in result.stdout + result.stderr
    assert "SKEY456" not in result.stdout + result.stderr


def test_make_cloud_keys_prefers_environment(tmp_path):
    _make_keys(tmp_path, "accesskey=FILE\nsecretkey=FILE\n",
               {"MINIO_ACCESS_KEY": "ENVA", "MINIO_SECRET_KEY": "ENVS"})
    assert 'ACCESS_KEY = "ENVA"' in (tmp_path / "k.py").read_text()


def test_make_cloud_keys_without_keys_still_succeeds(tmp_path):
    result = _make_keys(tmp_path, "# nothing here\n")
    assert "No MinIO keys found" in result.stdout
    assert not (tmp_path / "k.py").exists()


def test_no_keys_means_no_config(monkeypatch):
    monkeypatch.setitem(sys.modules, "cloud_keys", None)
    assert cloud_config() is None


def test_keys_give_config(monkeypatch):
    fake = type(sys)("cloud_keys")
    fake.ACCESS_KEY, fake.SECRET_KEY = "a", "s"
    monkeypatch.setitem(sys.modules, "cloud_keys", fake)
    cfg = cloud_config()
    assert (cfg.endpoint, cfg.bucket, cfg.access_key) == ("https://s3.kalourmade.com", "medtracker-inventory", "a")


def test_passphrase_in_keyring(memory_keyring):
    assert load_passphrase() == ""
    save_passphrase("passphrase1")
    assert load_passphrase() == "passphrase1"
    assert cloud_backup.KEYRING_SERVICE == "MedTracker cloud backup"

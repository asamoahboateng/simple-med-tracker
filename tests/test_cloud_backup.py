"""Cloud backup: compressing, naming, uploading and downloading backups (cloud_backup.py)."""

import gzip
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import db
from cloud_backup import OLD_BACKUP, CloudBackupError, pack, unpack


def seal_old(plain: bytes, passphrase: str) -> bytes:
    """A backup as MedTracker 1.4.x made it: encrypted with the passphrase."""
    import hashlib
    salt, nonce = os.urandom(16), os.urandom(12)
    key = hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return b"MTCB1" + salt + nonce + AESGCM(key).encrypt(nonce, gzip.compress(plain), b"MTCB1")


def test_pack_round_trip_compressed_without_passphrase(conn, add, tmp_path):
    add()
    db.backup_to(conn, tmp_path / "s.db")
    plain = (tmp_path / "s.db").read_bytes()
    blob = pack(plain)
    assert len(blob) < len(plain)
    assert gzip.decompress(blob) == plain                # an ordinary .gz file
    assert unpack(blob) == plain


def test_old_encrypted_backup_opens_with_saved_passphrase():
    assert unpack(seal_old(b"x" * 100, "right"), "right") == b"x" * 100


@pytest.mark.parametrize("passphrase", ["", "wrong"])
def test_old_encrypted_backup_without_its_passphrase(passphrase):
    with pytest.raises(CloudBackupError) as err:
        unpack(seal_old(b"x" * 100, "right"), passphrase)
    assert str(err.value) == OLD_BACKUP


def test_not_a_backup_file():
    with pytest.raises(CloudBackupError, match="not a MedTracker cloud backup"):
        unpack(b"SQLite format 3\x00" + b"\x00" * 100)


# --- naming, upload, list, download ----------------------------------------------

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cloud_backup
from cloud_backup import (
    cloud_config, download_backup, list_backups, object_key, slug, upload_backup,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("raw,expected", [
    ("Front Desk", "front-desk"), ("PHARM-PC_01", "pharm-pc-01"), ("Kɔfi’s PC", "k-fi-s-pc"),
    ("", "unnamed"), ("---", "unnamed"), ("x" * 60, "x" * 40)])
def test_slug(raw, expected):
    assert slug(raw) == expected


def test_object_key():
    assert object_key("PC 1", datetime(2026, 11, 23, 9, 5, 7)) == "pc-1/medtracker_2026-11-23_090507.db.gz"


def test_upload_list_download_round_trip(fake_s3, conn, add, tmp_path):
    add()
    db.backup_to(conn, tmp_path / "s.db")
    key = upload_backup(fake_s3.cfg, tmp_path / "s.db", "PC1", datetime(2026, 11, 23, 9, 5))
    assert key == "pc1/medtracker_2026-11-23_090500.db.gz"
    assert list_backups(fake_s3.cfg)[0].key == key
    download_backup(fake_s3.cfg, key, tmp_path / "back.db")
    assert db.is_valid_backup(tmp_path / "back.db")


def test_list_backups_all_pcs_newest_first_backups_only(fake_s3):
    for key in ("pc1/medtracker_2026-11-01_090000.db.gz.enc", "pc2/medtracker_2026-11-20_090000.db.gz",
                "pc1/medtracker_2026-11-10_090000.db.gz", "notes.txt", "pc1/x.gz"):
        fake_s3.store[key] = b"x"
    assert [o.key for o in list_backups(fake_s3.cfg)] == [
        "pc2/medtracker_2026-11-20_090000.db.gz", "pc1/medtracker_2026-11-10_090000.db.gz",
        "pc1/medtracker_2026-11-01_090000.db.gz.enc"]     # older encrypted backups are still listed


def test_download_old_backup_uses_saved_passphrase(fake_s3, conn, add, tmp_path, memory_keyring):
    import keyring
    add()
    db.backup_to(conn, tmp_path / "s.db")
    key = "pc1/medtracker_2026-11-01_090000.db.gz.enc"
    fake_s3.store[key] = seal_old((tmp_path / "s.db").read_bytes(), "passphrase1")
    keyring.set_password("MedTracker cloud backup", "passphrase", "passphrase1")
    download_backup(fake_s3.cfg, key, tmp_path / "back.db")
    assert db.is_valid_backup(tmp_path / "back.db")


def test_download_old_backup_elsewhere_writes_nothing(fake_s3, tmp_path, memory_keyring):
    key = "pc1/medtracker_2026-11-01_090000.db.gz.enc"
    fake_s3.store[key] = seal_old(b"x" * 100, "passphrase1")
    with pytest.raises(CloudBackupError) as err:
        download_backup(fake_s3.cfg, key, tmp_path / "back.db")
    assert str(err.value) == OLD_BACKUP
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

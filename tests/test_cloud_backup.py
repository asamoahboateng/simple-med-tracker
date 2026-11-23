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

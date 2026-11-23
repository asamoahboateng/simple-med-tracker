"""
cloud_backup.py - Backing the database up to the MinIO server and getting it back.

Pure Python (no Qt) so it can be tested like updater.py. A backup is the database file
compressed with gzip (<pc name>/medtracker_<date>_<time>.db.gz), so no passphrase is needed
to back up or restore. The bucket's keys, built into MedTracker, are what protect it.

MedTracker 1.4.x encrypted its backups with a passphrase (.db.gz.enc: b"MTCB1" + 16-byte
salt + 12-byte nonce + AES-256-GCM(gzip(database)), key from scrypt). Those still restore on
a computer that saved that passphrase.
"""

import gzip
import hashlib
import importlib
import re
from datetime import datetime
from pathlib import Path

import keyring
import keyring.errors
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config
from s3client import ObjectInfo, S3Config, get_object, list_objects, put_object

SUFFIX = ".db.gz"
OLD_SUFFIX = ".db.gz.enc"
MAGIC = b"MTCB1"
SALT_SIZE = 16
NONCE_SIZE = 12
GZIP_MAGIC = b"\x1f\x8b"
KEYRING_SERVICE = "MedTracker cloud backup"
OLD_BACKUP = ("This backup was made by an older MedTracker that used a passphrase. "
              "Restore it on the computer that made it, or choose a newer backup.")


class CloudBackupError(Exception):
    """Something went wrong with a cloud backup; the message is safe to show to the user."""


def pack(plain: bytes) -> bytes:
    """Compress a database file's bytes."""
    return gzip.compress(plain)


def _open_old(blob: bytes, passphrase: str) -> bytes:
    header = len(MAGIC) + SALT_SIZE + NONCE_SIZE
    if not passphrase or len(blob) <= header:
        raise CloudBackupError(OLD_BACKUP)
    salt = blob[len(MAGIC):len(MAGIC) + SALT_SIZE]
    nonce = blob[len(MAGIC) + SALT_SIZE:header]
    key = hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    try:
        return gzip.decompress(AESGCM(key).decrypt(nonce, blob[header:], MAGIC))
    except InvalidTag:
        raise CloudBackupError(OLD_BACKUP) from None


def unpack(blob: bytes, passphrase: str = "") -> bytes:
    """The database bytes inside a backup (`passphrase` only matters for 1.4.x backups)."""
    if blob.startswith(MAGIC):
        return _open_old(blob, passphrase)
    if blob.startswith(GZIP_MAGIC):
        try:
            return gzip.decompress(blob)
        except (OSError, EOFError):
            pass
    raise CloudBackupError("This file is not a MedTracker cloud backup.")


# --------------------------------------------------------------------------
# Server and names
# --------------------------------------------------------------------------

def cloud_config() -> S3Config | None:
    """The MinIO connection, or None if this build has no keys (cloud_keys.py)."""
    try:
        keys = importlib.import_module("cloud_keys")
    except ImportError:
        return None
    if keys is None or not getattr(keys, "ACCESS_KEY", "") or not getattr(keys, "SECRET_KEY", ""):
        return None
    return S3Config(config.CLOUD_ENDPOINT, config.CLOUD_BUCKET, keys.ACCESS_KEY, keys.SECRET_KEY)


def slug(text: str) -> str:
    """A computer name made safe for a file path: lowercase letters, digits and dashes."""
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return value or "unnamed"


def object_key(computer: str, when: datetime) -> str:
    """Where a backup goes on the server: <pc name>/medtracker_<date>_<time>.db.gz"""
    return f"{slug(computer)}/medtracker_{when:%Y-%m-%d_%H%M%S}{SUFFIX}"


def upload_backup(cfg: S3Config, snapshot: Path, computer: str, when: datetime) -> str:
    """Compress the database copy at `snapshot`, upload it and return its name on the server."""
    key = object_key(computer, when)
    put_object(cfg, key, pack(Path(snapshot).read_bytes()))
    return key


def list_backups(cfg: S3Config) -> list[ObjectInfo]:
    """Every PC's backups (1.4.x ones too), newest first (by the date and time in the name)."""
    found = [o for o in list_objects(cfg, "") if o.key.endswith((SUFFIX, OLD_SUFFIX))
             and o.key.rsplit("/", 1)[-1].startswith("medtracker_")]
    return sorted(found, key=lambda o: o.key.rsplit("/", 1)[-1], reverse=True)


def download_backup(cfg: S3Config, key: str, dest: Path) -> None:
    """Download a backup and unpack it into the database file `dest`."""
    blob = get_object(cfg, key)
    plain = unpack(blob, load_passphrase() if blob.startswith(MAGIC) else "")
    Path(dest).write_bytes(plain)


# --------------------------------------------------------------------------
# The passphrase MedTracker 1.4.x saved (Windows Credential Manager / macOS Keychain)
# --------------------------------------------------------------------------

def load_passphrase() -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, "passphrase") or ""
    except keyring.errors.KeyringError:
        return ""

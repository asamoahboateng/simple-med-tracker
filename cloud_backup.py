"""
cloud_backup.py - Backing the database up to the MinIO server and getting it back.

Pure Python (no Qt) so it can be tested like updater.py. Before a backup leaves the
computer it is compressed and encrypted with the pharmacy's passphrase, so the server
(and anyone holding the keys built into MedTracker) cannot read it.

File format: b"MTCB1" + 16-byte salt + 12-byte nonce + AES-256-GCM(gzip(database)).
The key comes from the passphrase with scrypt.
"""

import gzip
import hashlib
import importlib
import os
import re
from datetime import datetime
from pathlib import Path

import keyring
import keyring.errors
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config
from s3client import ObjectInfo, S3Config, get_object, list_objects, put_object

MAGIC = b"MTCB1"
SALT_SIZE = 16
NONCE_SIZE = 12
SUFFIX = ".db.gz.enc"
KEYRING_SERVICE = "MedTracker cloud backup"


class CloudBackupError(Exception):
    """Something went wrong with a cloud backup; the message is safe to show to the user."""


def _key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def pack(plain: bytes, passphrase: str) -> bytes:
    """Compress and encrypt a database file's bytes."""
    salt, nonce = os.urandom(SALT_SIZE), os.urandom(NONCE_SIZE)
    sealed = AESGCM(_key(passphrase, salt)).encrypt(nonce, gzip.compress(plain), MAGIC)
    return MAGIC + salt + nonce + sealed


def unpack(blob: bytes, passphrase: str) -> bytes:
    """The database bytes inside a packed backup."""
    header = len(MAGIC) + SALT_SIZE + NONCE_SIZE
    if not blob.startswith(MAGIC) or len(blob) <= header:
        raise CloudBackupError("This file is not a MedTracker cloud backup.")
    salt = blob[len(MAGIC):len(MAGIC) + SALT_SIZE]
    nonce = blob[len(MAGIC) + SALT_SIZE:header]
    try:
        return gzip.decompress(AESGCM(_key(passphrase, salt)).decrypt(nonce, blob[header:], MAGIC))
    except InvalidTag:
        raise CloudBackupError("The backup passphrase is not correct.") from None


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
    """Where a backup goes on the server: <pc name>/medtracker_<date>_<time>.db.gz.enc"""
    return f"{slug(computer)}/medtracker_{when:%Y-%m-%d_%H%M%S}{SUFFIX}"


def upload_backup(cfg: S3Config, snapshot: Path, passphrase: str, computer: str,
                  when: datetime) -> str:
    """Encrypt the database copy at `snapshot`, upload it and return its name on the server."""
    key = object_key(computer, when)
    put_object(cfg, key, pack(Path(snapshot).read_bytes(), passphrase))
    return key


def list_backups(cfg: S3Config) -> list[ObjectInfo]:
    """Every PC's backups, newest first (by the date and time in the name)."""
    found = [o for o in list_objects(cfg, "") if o.key.endswith(SUFFIX)]
    return sorted(found, key=lambda o: o.key.rsplit("/", 1)[-1], reverse=True)


def download_backup(cfg: S3Config, key: str, passphrase: str, dest: Path) -> None:
    """Download and decrypt a backup into the database file `dest`."""
    plain = unpack(get_object(cfg, key), passphrase)
    Path(dest).write_bytes(plain)


# --------------------------------------------------------------------------
# The passphrase (kept in Windows Credential Manager / macOS Keychain)
# --------------------------------------------------------------------------

def load_passphrase() -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, "passphrase") or ""
    except keyring.errors.KeyringError:
        return ""


def save_passphrase(value: str) -> None:
    try:
        keyring.set_password(KEYRING_SERVICE, "passphrase", value)
    except keyring.errors.KeyringError:
        raise CloudBackupError("This computer cannot store the passphrase securely.") from None

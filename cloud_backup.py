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
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"MTCB1"
SALT_SIZE = 16
NONCE_SIZE = 12


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

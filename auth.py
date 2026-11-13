"""
auth.py - Sign-in, registration and user approval rules (no UI code).

Who can do what
---------------
* superadmin - signs in with the superadmin code (not stored in the database).
               Approves, revokes and restores anyone, makes users user admins,
               and sets new passwords.
* useradmin  - an approved user promoted by the superadmin. Approves, revokes,
               restores and sets passwords for regular users, not for admins.
* user       - registers, waits for approval, then uses the app.

Users sign in with their password or, if they set one, a 6-digit code. Passwords,
codes and the superadmin code are kept only as salted PBKDF2-SHA256 hashes. A
6-digit code has only a million possibilities, so the hash slows guessing down but
can't stop someone who has copied the program or the database; in the app, the
pause after repeated wrong attempts is what protects it.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime

import db

SUPERADMIN = "superadmin"
USERADMIN = "useradmin"
USER = "user"
ROLE_NAMES = {SUPERADMIN: "Superadmin", USERADMIN: "User admin", USER: "User"}

PENDING, ACTIVE, REVOKED = "pending", "active", "revoked"
STATUS_NAMES = {PENDING: "Awaiting approval", ACTIVE: "Active", REVOKED: "Revoked"}

ITERATIONS = 600_000
MIN_PASSWORD = 8
PIN_LENGTH = 6
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")

# Hash of the superadmin code (PBKDF2-SHA256, ITERATIONS rounds).
_CODE_SALT = "042551367df871658be6df25effe8360"
_CODE_HASH = "f76d32ccd46f6b9dbbf308448e2d14ebd7f450b05967921c638fa3c9568dbb10"


class AuthError(ValueError):
    """A message that can be shown to the user as-is."""


@dataclass(frozen=True)
class User:
    id: int | None            # None for the superadmin (not a database row)
    username: str
    full_name: str
    role: str

    @property
    def display_name(self) -> str:
        """The name recorded as 'Entered by' on entries."""
        return self.full_name

    @property
    def is_admin(self) -> bool:
        return self.role in (SUPERADMIN, USERADMIN)

    @property
    def role_name(self) -> str:
        return ROLE_NAMES[self.role]


SUPERADMIN_USER = User(None, SUPERADMIN, "Superadmin", SUPERADMIN)


# --------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------

def _pbkdf2(secret: str, salt_hex: str, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), bytes.fromhex(salt_hex),
                               iterations).hex()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${_pbkdf2(password, salt, ITERATIONS)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _scheme, iterations, salt, expected = stored.split("$")
        return hmac.compare_digest(_pbkdf2(password, salt, int(iterations)), expected)
    except (ValueError, TypeError):
        return False


def is_superadmin_code(code: str) -> bool:
    return hmac.compare_digest(_pbkdf2((code or "").strip(), _CODE_SALT), _CODE_HASH)


# --------------------------------------------------------------------------
# Sign-in and registration
# --------------------------------------------------------------------------

def _to_user(row) -> User:
    return User(row["id"], row["username"], row["full_name"], row["role"])


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def validate_password(password: str, confirm: str | None = None) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if confirm is not None and password != confirm:
        raise AuthError("The two passwords don't match.")


def is_pin(text: str) -> bool:
    return len(text) == PIN_LENGTH and text.isdigit()


def validate_pin(pin: str, confirm: str | None = None) -> None:
    if not is_pin(pin or ""):
        raise AuthError(f"The sign-in code must be exactly {PIN_LENGTH} digits.")
    if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
        raise AuthError("That code is too easy to guess. Avoid repeated or consecutive digits.")
    if confirm is not None and pin != confirm:
        raise AuthError("The two codes don't match.")


def register(conn, username: str, full_name: str, password: str, confirm: str,
             pin: str = "", pin_confirm: str = "") -> int:
    """Create an account that waits for approval. The 6-digit code is optional."""
    username, full_name = (username or "").strip(), " ".join((full_name or "").split())
    if not full_name:
        raise AuthError("Enter your full name.")
    if not USERNAME_RE.match(username):
        raise AuthError("Choose a username of 3 to 32 letters, numbers, dots, dashes or "
                        "underscores, with no spaces.")
    if username.casefold() == SUPERADMIN:
        raise AuthError("That username is reserved. Choose another.")
    validate_password(password, confirm)
    if pin or pin_confirm:
        validate_pin(pin, pin_confirm)
    with db.transaction(conn):
        if db.find_user(conn, username) is not None:
            raise AuthError(f"The username '{username}' is already taken.")
        return db.create_user(conn, username, full_name, hash_password(password),
                              hash_password(pin) if pin else "")


def sign_in(conn, username: str, secret: str) -> User:
    """Sign in with the password, or with the 6-digit code if the user has set one."""
    row = db.find_user(conn, (username or "").strip())
    secret = secret or ""
    if row is None:
        ok = False
    elif is_pin(secret) and row["pin_hash"]:
        ok = verify_password(secret, row["pin_hash"])
    else:
        ok = verify_password(secret, row["password_hash"])
    if not ok:
        raise AuthError("Wrong username, password or code.")
    if row["status"] == PENDING:
        raise AuthError("Your account is waiting for approval by an administrator.")
    if row["status"] == REVOKED:
        raise AuthError("Your access has been revoked. Ask an administrator if you need it back.")
    return _to_user(row)


def sign_in_with_code(code: str) -> User:
    if not is_superadmin_code(code):
        raise AuthError("That code is not correct.")
    return SUPERADMIN_USER


def still_allowed(conn, user: User) -> bool:
    """False once a signed-in user has been revoked (or deleted by a restore)."""
    if user.role == SUPERADMIN:
        return True
    row = db.get_user(conn, user.id)
    return row is not None and row["status"] == ACTIVE


def refreshed(conn, user: User) -> User:
    """The signed-in user with their current role (it may have been changed meanwhile)."""
    if user.role == SUPERADMIN:
        return user
    row = db.get_user(conn, user.id)
    return _to_user(row) if row is not None else user


# --------------------------------------------------------------------------
# Managing users
# --------------------------------------------------------------------------

def can_manage(actor: User, target) -> bool:
    """Whether `actor` may approve, revoke or reset the password of the `target` row."""
    if actor.role == SUPERADMIN:
        return True
    if actor.role == USERADMIN:
        return target["role"] == USER and target["id"] != actor.id
    return False


def _target(conn, actor: User, user_id: int):
    row = db.get_user(conn, user_id)
    if row is None:
        raise AuthError("That account no longer exists.")
    if not can_manage(actor, row):
        raise AuthError("Only the superadmin can change administrator accounts.")
    return row


def approve(conn, actor: User, user_id: int) -> None:
    """Approve a pending account, or give a revoked account its access back."""
    _target(conn, actor, user_id)
    db.set_user_status(conn, user_id, ACTIVE, actor.display_name, _now())


def revoke(conn, actor: User, user_id: int) -> None:
    row = _target(conn, actor, user_id)
    if row["id"] == actor.id:
        raise AuthError("You can't revoke your own access.")
    db.set_user_status(conn, user_id, REVOKED, actor.display_name, _now())


def set_role(conn, actor: User, user_id: int, role: str) -> None:
    if actor.role != SUPERADMIN:
        raise AuthError("Only the superadmin can change roles.")
    if role not in (USER, USERADMIN):
        raise AuthError("Unknown role.")
    _target(conn, actor, user_id)
    db.set_user_role(conn, user_id, role)


def set_password(conn, actor: User, user_id: int, password: str, confirm: str) -> None:
    """An administrator sets a new password, e.g. when a user has forgotten theirs."""
    _target(conn, actor, user_id)
    validate_password(password, confirm)
    db.set_user_password(conn, user_id, hash_password(password))


def set_own_pin(conn, user: User, current_password: str, pin: str, confirm: str) -> None:
    """Set or change your own 6-digit code; an empty code removes it."""
    if user.role == SUPERADMIN:
        raise AuthError("The superadmin signs in with the superadmin code.")
    row = db.get_user(conn, user.id)
    if row is None or not verify_password(current_password, row["password_hash"]):
        raise AuthError("Your password is not correct.")
    if not pin and not confirm:
        db.set_user_pin(conn, user.id, "")
        return
    validate_pin(pin, confirm)
    db.set_user_pin(conn, user.id, hash_password(pin))


def remove_pin(conn, actor: User, user_id: int) -> None:
    """An administrator removes a user's code (e.g. if someone else may know it)."""
    _target(conn, actor, user_id)
    db.set_user_pin(conn, user_id, "")


def change_own_password(conn, user: User, current: str, password: str, confirm: str) -> None:
    if user.role == SUPERADMIN:
        raise AuthError("The superadmin signs in with the code and has no password.")
    row = db.get_user(conn, user.id)
    if row is None or not verify_password(current, row["password_hash"]):
        raise AuthError("Your current password is not correct.")
    validate_password(password, confirm)
    db.set_user_password(conn, user.id, hash_password(password))


def user_rows(conn) -> list[dict]:
    """Rows for the Users page."""
    return [{
        "id": r["id"], "full_name": r["full_name"], "username": r["username"],
        "role": r["role"], "role_name": ROLE_NAMES[r["role"]],
        "status": r["status"], "status_name": STATUS_NAMES[r["status"]],
        "has_pin": bool(r["pin_hash"]), "pin_text": "Set" if r["pin_hash"] else "None",
        "created_at": r["created_at"], "decided_by": r["decided_by"],
        "decided_at": r["decided_at"],
    } for r in db.list_users(conn)]

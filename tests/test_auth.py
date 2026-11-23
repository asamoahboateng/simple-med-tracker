"""Sign-in, registration, approval and the 'Entered by' audit trail."""

import sqlite3

import pytest

import auth
import db
import logic
from tests.conftest import TODAY


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    """Real hashing uses 600,000 rounds; tests only need the behaviour."""
    monkeypatch.setattr(auth, "ITERATIONS", 1000)


def make_user(conn, username="ama", name="Ama Mensah", password="secret-pass", approve=True,
              role=auth.USER):
    user_id = auth.register(conn, username, name, password, password)
    if role != auth.USER:
        auth.set_role(conn, auth.SUPERADMIN_USER, user_id, role)
    if approve:
        auth.approve(conn, auth.SUPERADMIN_USER, user_id)
    return user_id


def test_password_is_stored_hashed_and_verifies(conn):
    make_user(conn)
    stored = db.find_user(conn, "ama")["password_hash"]
    assert "secret-pass" not in stored and stored.startswith("pbkdf2_sha256$1000$")
    assert auth.verify_password("secret-pass", stored)
    assert not auth.verify_password("wrong-pass", stored)


def test_superadmin_code(monkeypatch):
    # The real code is only stored as a hash; test the check with a stand-in code.
    salt = "00" * 16
    monkeypatch.setattr(auth, "_CODE_SALT", salt)
    monkeypatch.setattr(auth, "_CODE_HASH", auth._pbkdf2("Test-Code-99", salt))
    assert auth.sign_in_with_code(" Test-Code-99 ").role == auth.SUPERADMIN
    for wrong in ("test-code-99", "Test-Code-98", "", None):
        with pytest.raises(auth.AuthError):
            auth.sign_in_with_code(wrong)


def test_new_account_waits_for_approval(conn):
    make_user(conn, approve=False)
    with pytest.raises(auth.AuthError, match="waiting for approval"):
        auth.sign_in(conn, "ama", "secret-pass")
    auth.approve(conn, auth.SUPERADMIN_USER, db.find_user(conn, "ama")["id"])
    user = auth.sign_in(conn, "AMA", "secret-pass")          # usernames ignore case
    assert (user.full_name, user.role) == ("Ama Mensah", auth.USER)


def test_wrong_password_and_unknown_user_give_the_same_message(conn):
    make_user(conn)
    for username, password in (("ama", "nope-nope"), ("nobody", "secret-pass")):
        with pytest.raises(auth.AuthError, match="Wrong username, password or code"):
            auth.sign_in(conn, username, password)


@pytest.mark.parametrize("username, name, password, confirm, message", [
    ("ama", "", "secret-pass", "secret-pass", "full name"),
    ("a b", "Ama", "secret-pass", "secret-pass", "username"),
    ("superadmin", "Ama", "secret-pass", "secret-pass", "reserved"),
    ("ama", "Ama", "short", "short", "at least"),
    ("ama", "Ama", "secret-pass", "secret-pasz", "don't match"),
])
def test_registration_is_validated(conn, username, name, password, confirm, message):
    with pytest.raises(auth.AuthError, match=message):
        auth.register(conn, username, name, password, confirm)


def test_usernames_are_unique_ignoring_case(conn):
    make_user(conn)
    with pytest.raises(auth.AuthError, match="already taken"):
        auth.register(conn, "AMA", "Someone Else", "secret-pass", "secret-pass")


def test_revoked_user_cannot_sign_in(conn):
    user_id = make_user(conn)
    user = auth.sign_in(conn, "ama", "secret-pass")
    auth.revoke(conn, auth.SUPERADMIN_USER, user_id)
    assert not auth.still_allowed(conn, user)
    with pytest.raises(auth.AuthError, match="revoked"):
        auth.sign_in(conn, "ama", "secret-pass")
    auth.approve(conn, auth.SUPERADMIN_USER, user_id)       # access restored
    assert auth.sign_in(conn, "ama", "secret-pass").id == user_id


def test_user_admin_manages_users_but_not_admins(conn):
    admin_id = make_user(conn, "kofi", "Kofi Asante", role=auth.USERADMIN)
    other_admin_id = make_user(conn, "efua", "Efua Owusu", role=auth.USERADMIN)
    user_id = make_user(conn, approve=False)
    admin = auth.sign_in(conn, "kofi", "secret-pass")

    auth.approve(conn, admin, user_id)
    assert db.get_user(conn, user_id)["decided_by"] == "Kofi Asante"
    auth.revoke(conn, admin, user_id)
    for action in (lambda: auth.revoke(conn, admin, other_admin_id),
                   lambda: auth.revoke(conn, admin, admin_id),
                   lambda: auth.set_role(conn, admin, user_id, auth.USERADMIN)):
        with pytest.raises(auth.AuthError):
            action()


def test_regular_user_cannot_manage_anyone(conn):
    make_user(conn)
    other = make_user(conn, "yaw", "Yaw Boateng", approve=False)
    user = auth.sign_in(conn, "ama", "secret-pass")
    with pytest.raises(auth.AuthError):
        auth.approve(conn, user, other)


def test_passwords_can_be_reset_and_changed(conn):
    user_id = make_user(conn)
    auth.set_password(conn, auth.SUPERADMIN_USER, user_id, "new-secret-1", "new-secret-1")
    user = auth.sign_in(conn, "ama", "new-secret-1")
    with pytest.raises(auth.AuthError, match="current password"):
        auth.change_own_password(conn, user, "wrong", "new-secret-2", "new-secret-2")
    auth.change_own_password(conn, user, "new-secret-1", "new-secret-2", "new-secret-2")
    assert auth.sign_in(conn, "ama", "new-secret-2")


def test_entries_record_who_entered_them(conn):
    logic.add_stock(conn, "2026-06-01", "Paracetamol", 50, "B1", "2027-01-31", unit="tablets",
                    today=TODAY, entered_by="Ama Mensah")
    logic.dispense(conn, "2026-06-02", "Paracetamol", 5, today=TODAY, entered_by="Kofi Asante")
    assert [r["entered_by"] for r in logic.log_rows(conn)] == ["Kofi Asante", "Ama Mensah"]


def test_old_database_is_upgraded(tmp_path):
    """A version 1 database (no users, no 'Entered by') opens and is labelled."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(db.SCHEMA.split("CREATE TABLE IF NOT EXISTS users")[0]
                      .replace(",\n    entered_by    TEXT    NOT NULL DEFAULT ''", ""))
    old.execute("INSERT INTO medicines (name, unit) VALUES ('Paracetamol', 'tablets')")
    old.execute("INSERT INTO batches (medicine_id, batch_no, expiry_date) VALUES (1, 'B1', '2027-01-31')")
    old.execute("""INSERT INTO transactions (date, medicine_id, batch_id, type, quantity,
                   balance_after, entry_group, entered_at)
                   VALUES ('2026-06-01', 1, 1, 'STOCK_IN', 10, 10, 'g', '2026-06-01 09:00:00')""")
    old.commit()
    old.close()

    conn = db.connect(path)
    assert [r["entered_by"] for r in logic.log_rows(conn)] == [db.PRE_LOGIN_ENTERED_BY]
    assert db.list_users(conn) == []
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_sign_in_with_a_six_digit_code(conn):
    user_id = auth.register(conn, "ama", "Ama Mensah", "secret-pass", "secret-pass",
                            pin="482913", pin_confirm="482913")
    auth.approve(conn, auth.SUPERADMIN_USER, user_id)
    stored = db.get_user(conn, user_id)["pin_hash"]
    assert "482913" not in stored and auth.verify_password("482913", stored)
    assert auth.sign_in(conn, "ama", "482913").id == user_id        # the code
    assert auth.sign_in(conn, "ama", "secret-pass").id == user_id   # or the password
    with pytest.raises(auth.AuthError, match="Wrong username, password or code"):
        auth.sign_in(conn, "ama", "482914")


def test_code_only_works_once_set(conn):
    user_id = make_user(conn)                                        # no code
    with pytest.raises(auth.AuthError):
        auth.sign_in(conn, "ama", "482913")
    user = auth.sign_in(conn, "ama", "secret-pass")
    with pytest.raises(auth.AuthError, match="password is not correct"):
        auth.set_own_pin(conn, user, "wrong", "482913", "482913")
    auth.set_own_pin(conn, user, "secret-pass", "482913", "482913")
    assert auth.sign_in(conn, "ama", "482913").id == user_id
    auth.remove_pin(conn, auth.SUPERADMIN_USER, user_id)
    with pytest.raises(auth.AuthError):
        auth.sign_in(conn, "ama", "482913")


@pytest.mark.parametrize("pin, confirm, message", [
    ("12345", "12345", "exactly 6 digits"),
    ("12a456", "12a456", "exactly 6 digits"),
    ("111111", "111111", "too easy"),
    ("123456", "123456", "too easy"),
    ("654321", "654321", "too easy"),
    ("482913", "482914", "don't match"),
])
def test_codes_are_validated(conn, pin, confirm, message):
    with pytest.raises(auth.AuthError, match=message):
        auth.register(conn, "ama", "Ama Mensah", "secret-pass", "secret-pass", pin, confirm)


def test_version_2_database_gains_the_code_column(tmp_path):
    path = tmp_path / "v2.db"
    old = sqlite3.connect(path)
    old.executescript(db.SCHEMA.replace(
        "    pin_hash      TEXT    NOT NULL DEFAULT '',   -- optional 6-digit sign-in code\n", ""))
    old.execute("INSERT INTO users (username, full_name, password_hash, status) "
                "VALUES ('ama', 'Ama Mensah', 'x', 'active')")
    old.commit()
    old.close()
    conn = db.connect(path)
    assert db.find_user(conn, "ama")["pin_hash"] == ""


# --- permission to delete medicines ------------------------------------------------

def test_only_superadmin_may_delete_medicines_by_default(conn):
    make_user(conn)
    clerk = auth.sign_in(conn, "ama", "secret-pass")
    admin_id = make_user(conn, "kofi", "Kofi Asante", role=auth.USERADMIN)
    admin = auth.User(admin_id, "kofi", "Kofi Asante", auth.USERADMIN)
    assert auth.can_delete_medicines(conn, auth.SUPERADMIN_USER)
    assert not auth.can_delete_medicines(conn, clerk)
    assert not auth.can_delete_medicines(conn, admin)          # user admins need it too


def test_superadmin_gives_and_takes_the_permission(conn):
    user_id = make_user(conn)
    clerk = auth.sign_in(conn, "ama", "secret-pass")
    auth.set_delete_permission(conn, auth.SUPERADMIN_USER, user_id, True)
    assert auth.can_delete_medicines(conn, clerk)
    assert [r["delete_text"] for r in auth.user_rows(conn)] == ["Yes"]
    auth.set_delete_permission(conn, auth.SUPERADMIN_USER, user_id, False)
    assert not auth.can_delete_medicines(conn, clerk)            # takes effect at once
    assert [r["delete_text"] for r in auth.user_rows(conn)] == ["No"]


def test_only_superadmin_can_give_the_permission(conn):
    admin_id = make_user(conn, "kofi", "Kofi Asante", role=auth.USERADMIN)
    user_id = make_user(conn)
    admin = auth.User(admin_id, "kofi", "Kofi Asante", auth.USERADMIN)
    with pytest.raises(auth.AuthError, match="Only the superadmin can allow deleting medicines."):
        auth.set_delete_permission(conn, admin, user_id, True)
    assert not db.get_user(conn, user_id)["can_delete_medicines"]


def test_revoked_user_cannot_delete(conn):
    user_id = make_user(conn)
    clerk = auth.sign_in(conn, "ama", "secret-pass")
    auth.set_delete_permission(conn, auth.SUPERADMIN_USER, user_id, True)
    auth.revoke(conn, auth.SUPERADMIN_USER, user_id)
    assert not auth.can_delete_medicines(conn, clerk)


def test_version_7_database_gets_the_permission_column(tmp_path):
    path = tmp_path / "v7.db"
    conn = db.connect(path)
    make_user(conn)
    conn.execute("ALTER TABLE users DROP COLUMN can_delete_medicines")
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()
    conn = db.connect(path)
    assert db.get_user(conn, 1)["can_delete_medicines"] == 0
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 8


def test_users_page_toggles_the_permission(qapp, conn):
    from ui.users import UsersPage
    user_id = make_user(conn)
    page = UsersPage(conn, auth.SUPERADMIN_USER)
    page.refresh()
    page.view.selectRow(0)
    assert not page.delete_btn.isHidden() and page.delete_btn.isEnabled()
    assert page.delete_btn.text() == "Allow deleting medicines"
    page.toggle_delete_permission()
    assert db.get_user(conn, user_id)["can_delete_medicines"] == 1
    page.view.selectRow(0)
    assert page.delete_btn.text() == "Stop deleting medicines"
    page.toggle_delete_permission()
    assert db.get_user(conn, user_id)["can_delete_medicines"] == 0


def test_users_page_hides_the_button_from_user_admins(qapp, conn):
    from ui.users import UsersPage
    admin_id = make_user(conn, "kofi", "Kofi Asante", role=auth.USERADMIN)
    page = UsersPage(conn, auth.User(admin_id, "kofi", "Kofi Asante", auth.USERADMIN))
    assert page.delete_btn.isHidden()

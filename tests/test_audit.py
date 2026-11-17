"""Edits, deletes and undos are recorded in the audit log."""

import sqlite3
from datetime import datetime

import db
import logic

NOW = datetime(2026, 6, 15, 14, 30, 0)


def _rows(conn):
    return sorted(logic.log_rows(conn), key=lambda r: r["id"])


def test_edit_is_recorded(conn, add, give):
    add(qty=300)
    give(qty=100, patient="P9", prescriber="Dr B")
    tx = _rows(conn)[1]
    logic.edit_quantity(conn, tx["id"], 150, changed_by="Ama Mensah", reason="Typo", now=NOW)

    [audit] = logic.audit_rows(conn)
    assert audit["action"] == logic.AUDIT_EDITED
    assert (audit["changed_by"], audit["changed_at"], audit["reason"]) == (
        "Ama Mensah", "2026-06-15 14:30:00", "Typo")
    assert (audit["tx_id"], audit["medicine"], audit["batch_no"], audit["tx_type"]) == (
        tx["id"], "Paracetamol", "B001", logic.DISPENSED)
    assert (audit["old_quantity"], audit["new_quantity"], audit["change"]) == (100, 150, "100 → 150")
    assert (audit["patient_id"], audit["prescriber"]) == ("P9", "Dr B")


def test_unchanged_edit_is_not_recorded(conn, add):
    add(qty=10)
    logic.edit_quantity(conn, _rows(conn)[0]["id"], 10, changed_by="Ama")
    assert logic.audit_rows(conn) == []


def test_delete_keeps_a_copy_of_the_entry(conn, add, give):
    add(qty=300)
    give(qty=100)
    tx = _rows(conn)[1]
    logic.delete_entry(conn, tx["id"], changed_by="Kofi", reason="Entered twice", now=NOW)
    assert db.get_transaction(conn, tx["id"]) is None

    [audit] = logic.audit_rows(conn)
    assert audit["action"] == logic.AUDIT_DELETED
    assert (audit["old_quantity"], audit["new_quantity"]) == (100, None)
    assert audit["change"] == "100 → removed"
    assert (audit["entered_at"], audit["tx_date"]) == (tx["entered_at"], tx["date"])


def test_undo_records_every_row(conn, add, give):
    add(qty=10, batch="A", expiry="2026-09-30")
    add(qty=10, batch="B", expiry="2027-09-30")
    give(qty=15)  # split over two rows
    logic.undo_last_entry(conn, changed_by="Ama")
    audits = logic.audit_rows(conn)
    assert [a["action"] for a in audits] == [logic.AUDIT_UNDONE] * 2
    assert sorted(a["batch_no"] for a in audits) == ["A", "B"]


def test_blocked_change_is_not_recorded(conn, add, give):
    add(qty=100)
    give(qty=10)
    try:
        logic.delete_entry(conn, _rows(conn)[0]["id"], changed_by="Ama")
    except logic.ValidationError:
        pass
    assert logic.audit_rows(conn) == []


def test_old_database_gets_audit_log(tmp_path):
    path = tmp_path / "v5.db"
    old = sqlite3.connect(path)
    old.executescript(db.SCHEMA.split("CREATE TABLE IF NOT EXISTS audit_log")[0])
    old.close()
    conn = db.connect(path)
    assert logic.audit_rows(conn) == []
    conn.close()

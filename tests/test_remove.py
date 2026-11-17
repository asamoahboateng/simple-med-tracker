"""Removing stock (expired, recalled...) and editing a batch in one go."""

import sqlite3

import pytest

import db
import logic
from tests.conftest import TODAY


def _stock(conn, name="Paracetamol"):
    return db.medicine_stock(conn, db.find_medicine(conn, name)["id"])


def _rows(conn):
    return sorted(logic.log_rows(conn), key=lambda r: r["id"])


def remove(conn, qty, reason="Expired", batch=None, on="2026-06-12", name="Paracetamol"):
    return logic.remove_stock(conn, on, name, qty, reason, batch_no=batch, today=TODAY,
                              entered_by="Ama")


# --- remove stock ---------------------------------------------------------

def test_remove_from_chosen_batch(conn, add):
    add(qty=100, batch="A")
    add(qty=50, batch="B", expiry="2027-06-30")
    result = remove(conn, 30, reason="Recalled", batch="b")
    assert result.remaining_stock == 120 == _stock(conn)
    row = _rows(conn)[-1]
    assert (row["type"], row["quantity"], row["batch_no"], row["reason"], row["balance_after"]) == (
        logic.REMOVED, 30, "B", "Recalled", 120)
    assert row["entered_by"] == "Ama"


def test_remove_automatic_takes_expired_batches_first(conn, add):
    add(qty=10, batch="OLD", expiry="2026-06-05", on="2026-05-01")   # expired before 06-12
    add(qty=10, batch="NEW", expiry="2027-06-30")
    result = remove(conn, 15)
    assert [(a.batch_no, a.quantity) for a in result.allocations] == [("OLD", 10), ("NEW", 5)]
    assert _stock(conn) == 5


def test_expired_batches_are_offered_for_removal(conn, add):
    add(qty=10, batch="OLD", expiry="2026-06-05", on="2026-05-01")
    add(qty=10, batch="NEW", expiry="2027-06-30")
    assert [b.batch_no for b in logic.batches_with_stock(conn, "paracetamol")] == ["OLD", "NEW"]
    assert [b.batch_no for b in logic.dispensable_batches(conn, "paracetamol", "2026-06-12")] == ["NEW"]


def test_remove_checks(conn, add):
    add(qty=10, batch="A")
    with pytest.raises(logic.InsufficientStockError, match="only has 10"):
        remove(conn, 11, batch="A")
    with pytest.raises(logic.InsufficientStockError, match="only 10 in stock"):
        remove(conn, 11)
    with pytest.raises(logic.ValidationError, match="Reason is required"):
        remove(conn, 1, reason="  ")
    with pytest.raises(logic.ValidationError, match="not found"):
        remove(conn, 1, batch="ZZZ")
    assert _stock(conn) == 10


def test_removed_stock_counts_in_every_total(conn, add, give):
    add(qty=100, batch="A")
    give(qty=10)
    remove(conn, 5, batch="A")
    med = logic.medicine_rows(conn)[0]
    assert (med["received"], med["dispensed"], med["removed"], med["stock"]) == (100, 10, 5, 85)
    batch = logic.batch_rows(conn)[0]
    assert (batch["removed"], batch["remaining"]) == (5, 85)
    # Removals are not dispensing: the report only counts dispensed stock.
    assert logic.monthly_report(conn, 2026, 6, today=TODAY).total_dispensed == 10


def test_removal_can_be_edited_deleted_and_undone(conn, add):
    add(qty=100, batch="A")
    remove(conn, 10, batch="A")
    tx_id = _rows(conn)[-1]["id"]
    logic.edit_quantity(conn, tx_id, 25, changed_by="Ama")
    assert _stock(conn) == 75
    with pytest.raises(logic.InsufficientStockError, match="at most 100"):
        logic.edit_quantity(conn, tx_id, 101)
    logic.delete_entry(conn, tx_id, changed_by="Ama")
    assert _stock(conn) == 100
    remove(conn, 10, batch="A")
    logic.undo_last_entry(conn)
    assert _stock(conn) == 100


def test_cannot_shrink_delivery_below_what_was_removed(conn, add):
    add(qty=100, batch="A")
    remove(conn, 80, batch="A")
    with pytest.raises(logic.InsufficientStockError, match="dispensed or removed"):
        logic.edit_quantity(conn, _rows(conn)[0]["id"], 70)


def test_version_6_database_is_upgraded(tmp_path):
    """A database whose transactions table only allowed STOCK_IN and DISPENSED."""
    path = tmp_path / "v6.db"
    old = sqlite3.connect(path)
    old.executescript(
        db.SCHEMA.replace(", 'REMOVED'", "")
                 .replace(",\n    reason        TEXT    NOT NULL DEFAULT ''     -- why stock was REMOVED", ""))
    old.execute("INSERT INTO medicines (name, unit) VALUES ('Paracetamol', 'tablets')")
    old.execute("INSERT INTO batches (medicine_id, batch_no, expiry_date) VALUES (1, 'A', '2027-01-31')")
    old.execute("""INSERT INTO transactions (id, date, medicine_id, batch_id, type, quantity,
                   balance_after, entry_group, entered_at, entered_by)
                   VALUES (7, '2026-06-01', 1, 1, 'STOCK_IN', 40, 40, 'g', '2026-06-01 09:00:00', 'Ama')""")
    old.commit()
    old.close()

    conn = db.connect(path)
    [row] = logic.log_rows(conn)
    assert (row["id"], row["quantity"], row["entered_by"], row["reason"]) == (7, 40, "Ama", "")
    remove(conn, 5, batch="A")                                  # the new type is accepted
    assert _stock(conn) == 35
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_tx_medicine", "idx_tx_batch", "idx_tx_date", "idx_tx_group"} <= indexes
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


# --- edit batch -----------------------------------------------------------

def test_edit_batch_number_expiry_and_received(conn, add, give):
    add(qty=100, batch="A")
    give(qty=10)
    batch_id = logic.batch_rows(conn)[0]["id"]
    logic.edit_batch(conn, batch_id, "A-2", "2027-05-31", received=120, changed_by="Ama",
                     reason="Delivery note says 120")
    batch = logic.batch_rows(conn)[0]
    assert (batch["batch_no"], batch["expiry"], batch["received"], batch["remaining"]) == (
        "A-2", "2027-05-31", 120, 110)
    [audit] = logic.audit_rows(conn)
    assert (audit["action"], audit["old_quantity"], audit["new_quantity"]) == (
        logic.AUDIT_EDITED, 100, 120)


def test_edit_batch_is_all_or_nothing(conn, add, give):
    add(qty=100, batch="A")
    add(qty=50, batch="B", expiry="2027-06-30")
    give(qty=90, batch="A")
    batch_a = next(b for b in logic.batch_rows(conn) if b["batch_no"] == "A")
    with pytest.raises(logic.InsufficientStockError):
        logic.edit_batch(conn, batch_a["id"], "A-NEW", "2027-02-28", received=80)
    with pytest.raises(logic.ValidationError, match="already exists"):
        logic.edit_batch(conn, batch_a["id"], "b", "2027-02-28", received=95)
    batch_a = next(b for b in logic.batch_rows(conn) if b["id"] == batch_a["id"])
    assert (batch_a["batch_no"], batch_a["expiry"], batch_a["received"]) == ("A", "2027-01-31", 100)
    assert logic.audit_rows(conn) == []


def test_received_needs_a_single_delivery(conn, add):
    add(qty=100, batch="A")
    add(qty=20, batch="A")
    batch = logic.batch_rows(conn)[0]
    assert batch["deliveries"] == 2
    with pytest.raises(logic.ValidationError, match="2 deliveries"):
        logic.edit_batch(conn, batch["id"], "A", batch["expiry"], received=150)
    logic.edit_batch(conn, batch["id"], "A", "2027-03-31")    # number/expiry still editable
    assert logic.batch_rows(conn)[0]["expiry"] == "2027-03-31"

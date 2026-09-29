"""Undo removes the most recent entry (all rows of a split dispensing)."""

import pytest

import db
import logic


def test_undo_last_dispensing_restores_stock(conn, add, give):
    add(qty=10, batch="A", expiry="2026-09-30")
    add(qty=10, batch="B", expiry="2027-09-30")
    give(qty=15)  # split: 10 from A + 5 from B
    med_id = db.find_medicine(conn, "Paracetamol")["id"]
    assert db.medicine_stock(conn, med_id) == 5

    last = logic.last_entry(conn)
    assert len(last) == 2 and {r["type"] for r in last} == {logic.DISPENSED}

    removed = logic.undo_last_entry(conn, expected_group=last[0]["entry_group"])
    assert len(removed) == 2
    assert db.medicine_stock(conn, med_id) == 20
    assert len(logic.log_rows(conn)) == 2


def test_undo_stock_in_removes_orphan_batch(conn, add):
    add(qty=10, batch="A")
    add(qty=10, batch="NEW-BATCH", expiry="2027-03-01")
    logic.undo_last_entry(conn)
    assert [b["batch_no"] for b in logic.batch_rows(conn)] == ["A"]


def test_undo_with_nothing_to_undo(conn):
    with pytest.raises(logic.ValidationError, match="nothing"):
        logic.undo_last_entry(conn)


def test_undo_refuses_if_latest_entry_changed(conn, add):
    add(qty=10)
    seen = logic.last_entry(conn)[0]["entry_group"]
    add(qty=5)
    with pytest.raises(logic.ValidationError, match="changed"):
        logic.undo_last_entry(conn, expected_group=seen)

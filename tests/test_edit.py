"""Editing the quantity of a logged entry recalculates stock and later balances."""

import pytest

import db
import logic


def _rows(conn):
    """Log rows oldest first."""
    return sorted(logic.log_rows(conn), key=lambda r: r["id"])


def _stock(conn, name="Paracetamol"):
    return db.medicine_stock(conn, db.find_medicine(conn, name)["id"])


def test_edit_dispensed_quantity_lowers_stock(conn, add, give):
    add(qty=400)
    give(qty=100)
    give(qty=50)
    assert _stock(conn) == 250
    first_dispense = _rows(conn)[1]

    new_stock = logic.edit_quantity(conn, first_dispense["id"], 150)

    assert new_stock == 200
    assert _stock(conn) == 200
    assert [r["balance_after"] for r in _rows(conn)] == [400, 250, 200]
    assert _rows(conn)[1]["quantity"] == 150


def test_edit_stock_in_quantity(conn, add, give):
    add(qty=300)
    give(qty=100)
    logic.edit_quantity(conn, _rows(conn)[0]["id"], 250)
    assert _stock(conn) == 150
    assert [r["balance_after"] for r in _rows(conn)] == [250, 150]


def test_edit_leaves_other_medicines_alone(conn, add, give):
    add(qty=100)
    add(name="Ibuprofen", qty=60, batch="I1")
    give(qty=10)
    logic.edit_quantity(conn, _rows(conn)[0]["id"], 80)
    ibuprofen = [r for r in _rows(conn) if r["medicine"] == "Ibuprofen"]
    assert ibuprofen[0]["balance_after"] == 60
    assert _stock(conn, "Ibuprofen") == 60


def test_dispensed_cannot_exceed_batch_stock(conn, add, give):
    add(qty=100)
    give(qty=30)
    give(qty=50)
    with pytest.raises(logic.InsufficientStockError, match="at most 50"):
        logic.edit_quantity(conn, _rows(conn)[1]["id"], 51)
    assert _stock(conn) == 20


def test_stock_in_cannot_drop_below_what_was_dispensed(conn, add, give):
    add(qty=100)
    give(qty=70)
    with pytest.raises(logic.InsufficientStockError, match="at least 70"):
        logic.edit_quantity(conn, _rows(conn)[0]["id"], 60)
    logic.edit_quantity(conn, _rows(conn)[0]["id"], 70)
    assert _stock(conn) == 0


def test_check_uses_the_balance_at_every_point(conn, add, give):
    # Batch goes 100 -> 10 -> 60. Final stock is 60, but the low point after
    # the first dispensing is 10, so that entry can only grow by 10.
    add(qty=100)
    give(qty=90)
    add(qty=50)
    with pytest.raises(logic.InsufficientStockError, match="at most 100"):
        logic.edit_quantity(conn, _rows(conn)[1]["id"], 101)


def test_edit_rejects_bad_quantity_and_missing_entry(conn, add):
    add(qty=10)
    tx_id = _rows(conn)[0]["id"]
    with pytest.raises(logic.ValidationError, match="greater than 0"):
        logic.edit_quantity(conn, tx_id, 0)
    with pytest.raises(logic.ValidationError, match="no longer exists"):
        logic.edit_quantity(conn, tx_id + 99, 5)


def test_editing_a_split_dispensing_row_only_changes_that_row(conn, add, give):
    add(qty=10, batch="A", expiry="2026-09-30")
    add(qty=10, batch="B", expiry="2027-09-30")
    give(qty=15)  # 10 from A + 5 from B
    row_b = next(r for r in _rows(conn) if r["type"] == logic.DISPENSED and r["batch_no"] == "B")
    logic.edit_quantity(conn, row_b["id"], 8)
    assert _stock(conn) == 2
    assert _rows(conn)[-1]["balance_after"] == 2


def test_delete_dispensed_entry_restores_stock(conn, add, give):
    add(qty=300)
    give(qty=100)
    give(qty=20)
    new_stock = logic.delete_entry(conn, _rows(conn)[1]["id"])
    assert new_stock == 280 == _stock(conn)
    assert [(r["quantity"], r["balance_after"]) for r in _rows(conn)] == [(300, 300), (20, 280)]


def test_delete_stock_in_removes_empty_batch(conn, add):
    add(qty=100, batch="A")
    add(qty=40, batch="B", expiry="2027-03-01")
    logic.delete_entry(conn, _rows(conn)[0]["id"])
    assert _stock(conn) == 40
    assert _rows(conn)[0]["balance_after"] == 40
    assert [b["batch_no"] for b in logic.batch_rows(conn)] == ["B"]


def test_cannot_delete_stock_that_was_dispensed(conn, add, give):
    add(qty=100)
    give(qty=10)
    with pytest.raises(logic.InsufficientStockError, match="already been dispensed"):
        logic.delete_entry(conn, _rows(conn)[0]["id"])
    assert _stock(conn) == 90


def test_delete_missing_entry(conn):
    with pytest.raises(logic.ValidationError, match="no longer exists"):
        logic.delete_entry(conn, 12345)

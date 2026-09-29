"""FEFO allocation, expired-batch blocking and over-dispensing protection."""

from datetime import date

import pytest

import db
import logic


def test_fefo_splits_across_batches_earliest_expiry_first(conn, add, give):
    add(qty=10, batch="LATE", expiry="2027-12-31")
    add(qty=5, batch="SOON", expiry="2026-08-31")
    add(qty=8, batch="MIDDLE", expiry="2027-03-31")

    result = give(qty=20)

    assert [(a.batch_no, a.quantity) for a in result.allocations] == [
        ("SOON", 5), ("MIDDLE", 8), ("LATE", 7)]
    assert result.remaining_stock == 3

    # One transaction row per batch, all in the same entry group.
    dispensed = [r for r in logic.log_rows(conn) if r["type"] == logic.DISPENSED]
    assert len(dispensed) == 3
    assert len({r["entry_group"] for r in dispensed}) == 1
    assert sorted(r["balance_after"] for r in dispensed) == [3, 10, 18]


def test_fefo_skips_expired_batches(conn, add, give):
    add(qty=50, batch="OLD", expiry="2026-06-05", on="2026-05-01")
    add(qty=10, batch="NEW", expiry="2027-01-01")

    result = give(qty=4, on="2026-06-10")
    assert [(a.batch_no, a.quantity) for a in result.allocations] == [("NEW", 4)]


def test_batch_can_be_used_on_its_expiry_day(add, give):
    add(qty=10, batch="EXP", expiry="2026-06-10", on="2026-05-01")
    result = give(qty=2, batch="EXP", on="2026-06-10")
    assert result.allocations[0].batch_no == "EXP"


def test_chosen_expired_batch_is_blocked(conn, add, give):
    add(qty=10, batch="OLD", expiry="2026-06-05", on="2026-05-01")
    with pytest.raises(logic.ExpiredBatchError):
        give(qty=1, batch="old", on="2026-06-10")
    assert [r["type"] for r in logic.log_rows(conn)] == [logic.STOCK_IN]


def test_over_dispensing_is_blocked_automatic(conn, add, give):
    add(qty=10, batch="A")
    add(qty=5, batch="B", expiry="2027-05-01")
    with pytest.raises(logic.InsufficientStockError):
        give(qty=16)
    # Nothing saved: stock untouched.
    assert db.medicine_stock(conn, db.find_medicine(conn, "Paracetamol")["id"]) == 15


def test_over_dispensing_is_blocked_for_chosen_batch(add, give):
    add(qty=10, batch="A")
    add(qty=50, batch="B", expiry="2027-05-01")
    with pytest.raises(logic.InsufficientStockError):
        give(qty=11, batch="A")


def test_expired_stock_does_not_count_as_available(add, give):
    add(qty=100, batch="OLD", expiry="2026-06-01", on="2026-05-01")
    add(qty=5, batch="NEW", expiry="2027-01-01")
    with pytest.raises(logic.InsufficientStockError, match="only 5"):
        give(qty=6, on="2026-06-10")


def test_unknown_medicine_is_rejected(give):
    with pytest.raises(logic.ValidationError, match="not in the list"):
        give(name="Unknown")


def test_allocate_fefo_pure_function():
    batches = [
        logic.BatchStock(1, "A", date(2027, 1, 1), 3),
        logic.BatchStock(2, "B", date(2026, 7, 1), 3),
        logic.BatchStock(3, "C", date(2026, 1, 1), 99),   # expired
        logic.BatchStock(4, "D", date(2026, 6, 1), 0),    # empty
    ]
    allocs = logic.allocate_fefo(batches, 5, date(2026, 6, 15))
    assert [(a.batch_no, a.quantity) for a in allocs] == [("B", 3), ("A", 2)]

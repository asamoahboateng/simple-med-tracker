"""Stock is always calculated from transactions: received minus dispensed."""

import pytest

import db
import logic
from tests.conftest import TODAY


def test_stock_is_received_minus_dispensed(conn, add, give):
    add(qty=100, batch="B001")
    add(qty=50, batch="B002", expiry="2027-06-30")
    give(qty=30)
    give(qty=5)

    med = db.find_medicine(conn, "Paracetamol")
    assert db.medicine_stock(conn, med["id"]) == 115

    row = logic.medicine_rows(conn)[0]
    assert (row["received"], row["dispensed"], row["stock"]) == (150, 35, 115)
    assert row["status"] == logic.STATUS_OK


def test_batch_remaining_is_calculated_per_batch(conn, add, give):
    add(qty=10, batch="B001", expiry="2026-12-31")
    add(qty=20, batch="B002", expiry="2027-12-31")
    give(qty=4)  # FEFO takes from B001 (expires first)

    remaining = {b["batch_no"]: b["remaining"] for b in logic.batch_rows(conn, TODAY)}
    assert remaining == {"B001": 6, "B002": 20}


def test_balance_after_is_recorded(conn, add, give):
    assert add(qty=40).new_stock == 40
    assert give(qty=15).remaining_stock == 25
    balances = [r["balance_after"] for r in reversed(logic.log_rows(conn))]
    assert balances == [40, 25]


def test_names_and_batches_match_case_insensitively(conn, add):
    add(name="  Amoxicillin ", batch="0012")
    result = add(name="AMOXICILLIN", batch="0012", qty=5)
    assert result.medicine_name == "Amoxicillin"   # original spelling kept
    assert result.batch_no == "0012"               # leading zeros kept
    assert result.created_medicine is False
    assert result.created_batch is False
    assert len(db.list_medicines(conn)) == 1
    assert result.new_stock == 105


def test_existing_batch_keeps_original_expiry(conn, add):
    add(batch="B001", expiry="2027-01-31")
    check = logic.check_add_stock(conn, "2026-06-02", "paracetamol", "b001", "2028-01-01")
    assert check.expiry_conflict and check.existing_expiry.isoformat() == "2027-01-31"
    result = add(batch="b001", expiry="2028-01-01")
    assert result.kept_original_expiry
    assert result.expiry.isoformat() == "2027-01-31"


def test_check_flags_already_expired_stock(conn):
    check = logic.check_add_stock(conn, "2026-06-01", "New Med", "X1", "2026-06-01")
    assert check.already_expired and not check.medicine_exists


def test_low_and_out_of_stock_status(conn, add, give):
    add(qty=25, reorder=20)
    assert give(qty=5).low_stock  # 20 left == reorder level -> LOW
    assert logic.medicine_rows(conn)[0]["status"] == logic.STATUS_LOW
    give(qty=20)
    assert logic.medicine_rows(conn)[0]["status"] == logic.STATUS_OUT


@pytest.mark.parametrize("bad", [0, -3, 2.5, "abc", "", None, True])
def test_quantity_must_be_positive_whole_number(bad):
    with pytest.raises(logic.ValidationError):
        logic.validate_quantity(bad)


def test_future_dates_are_blocked(add, give):
    add()
    with pytest.raises(logic.ValidationError, match="future"):
        give(on="2026-06-16")


def test_new_medicine_requires_unit(conn):
    with pytest.raises(logic.ValidationError, match="Unit"):
        logic.add_stock(conn, "2026-06-01", "Mystery", 10, "B1", "2027-01-01",
                        unit="  ", today=TODAY)
    assert db.list_medicines(conn) == []  # nothing half-saved


def test_create_medicine_without_stock(conn, add):
    logic.create_medicine(conn, "  Zinc 20mg ", "tablets", 30)
    row = next(r for r in logic.medicine_rows(conn) if r["name"] == "Zinc 20mg")
    assert (row["stock"], row["reorder_level"], row["status"]) == (0, 30, logic.STATUS_OUT)
    with pytest.raises(logic.ValidationError, match="already exists"):
        logic.create_medicine(conn, "zinc 20MG", "tablets", 5)
    # Adding stock later uses the existing medicine.
    assert add(name="ZINC 20mg", qty=50).created_medicine is False

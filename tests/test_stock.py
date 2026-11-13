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


def test_rename_medicine_keeps_history(conn, add, give):
    add(name="Paracetmol", qty=50)
    give(name="Paracetmol", qty=5)
    med = db.find_medicine(conn, "Paracetmol")
    logic.rename_medicine(conn, med["id"], "  Paracetamol 500mg ")
    assert db.get_medicine(conn, med["id"])["name"] == "Paracetamol 500mg"
    assert db.medicine_stock(conn, med["id"]) == 45
    assert {r["medicine"] for r in logic.log_rows(conn)} == {"Paracetamol 500mg"}


def test_rename_medicine_allows_case_change_but_not_duplicates(conn, add):
    add(name="Ibuprofen")
    add(name="Amoxicillin")
    med = db.find_medicine(conn, "Ibuprofen")
    logic.rename_medicine(conn, med["id"], "IBUPROFEN")
    assert db.get_medicine(conn, med["id"])["name"] == "IBUPROFEN"
    with pytest.raises(logic.ValidationError, match="already exists"):
        logic.rename_medicine(conn, med["id"], "amoxicillin")
    with pytest.raises(logic.ValidationError):
        logic.rename_medicine(conn, med["id"], "   ")


def test_update_batch_number_and_expiry(conn, add, give):
    add(qty=30, batch="OPENING", expiry="2099-12-31")
    give(qty=10)
    med = db.find_medicine(conn, "Paracetamol")
    batch = db.find_batch(conn, med["id"], "OPENING")
    logic.update_batch(conn, batch["id"], batch_no="BX-77", expiry_date="2027-03-31")
    row = logic.batch_rows(conn, TODAY)[0]
    assert (row["batch_no"], row["expiry"], row["remaining"]) == ("BX-77", "2027-03-31", 20)


def test_update_batch_rejects_duplicate_number_and_bad_date(conn, add):
    add(batch="B001")
    add(batch="B002", expiry="2027-06-30")
    med = db.find_medicine(conn, "Paracetamol")
    b2 = db.find_batch(conn, med["id"], "B002")
    with pytest.raises(logic.ValidationError, match="already exists"):
        logic.update_batch(conn, b2["id"], batch_no="b001")
    with pytest.raises(logic.ValidationError):
        logic.update_batch(conn, b2["id"], expiry_date="31/06/2027")
    with pytest.raises(logic.ValidationError):
        logic.update_batch(conn, b2["id"], batch_no="")
    logic.update_batch(conn, b2["id"], batch_no="b002")  # case change of itself is fine
    assert db.get_batch(conn, b2["id"])["batch_no"] == "b002"


def test_unit_list_starts_with_common_units_and_grows(conn, add):
    from config import COMMON_UNITS
    assert set(COMMON_UNITS) <= set(logic.unit_names(conn))
    assert logic.add_unit(conn, "  strips ") == "strips"
    with pytest.raises(logic.ValidationError, match="already in the list"):
        logic.add_unit(conn, "STRIPS")
    with pytest.raises(logic.ValidationError):
        logic.add_unit(conn, "   ")
    # Typing a new unit when creating a medicine adds it to the list too.
    logic.create_medicine(conn, "Gauze roll", "rolls", 5)
    add(name="Test kit", unit="kits")
    assert {"strips", "rolls", "kits"} <= set(logic.unit_names(conn))


def test_a_unit_in_use_cannot_be_removed(conn, add):
    add(name="Paracetamol", unit="tablets")
    with pytest.raises(logic.ValidationError, match="1 medicine uses it"):
        logic.remove_unit(conn, "TABLETS")                   # ignoring case
    assert "tablets" in logic.unit_names(conn)
    logic.remove_unit(conn, "vials")                         # unused: removed
    assert "vials" not in logic.unit_names(conn)
    med = db.find_medicine(conn, "Paracetamol")
    logic.update_medicine_settings(conn, med["id"], unit="strips")
    logic.remove_unit(conn, "tablets")                       # no longer used
    assert "tablets" not in logic.unit_names(conn)


def test_existing_database_gets_its_units_listed(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(db.SCHEMA.split("CREATE TABLE IF NOT EXISTS units")[0])
    old.execute("INSERT INTO medicines (name, unit) VALUES ('Swabs', 'boxes of 100')")
    old.commit()
    old.close()
    conn = db.connect(path)
    assert "boxes of 100" in logic.unit_names(conn)
